import datetime

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from comptes.models import Notification, Utilisateur
from comptes.roles import Role, StatutCompte
from communication.models import Annonce, Message, Portee
from scolarite.models import Affectation, AnneeScolaire, Classe, Cycle, Inscription


def creer_utilisateur_actif(email, role, **kwargs):
    utilisateur = Utilisateur(email=email, prenom="Test", nom="Utilisateur", role=role, **kwargs)
    utilisateur.set_password("MotDePasse#2026")
    utilisateur.statut = StatutCompte.ACTIF
    utilisateur.is_active = True
    utilisateur.full_clean(exclude=["password"])
    utilisateur.save()
    return utilisateur


def creer_contexte_classe():
    annee = AnneeScolaire.objects.create(
        libelle="2026-2027", date_debut=datetime.date(2026, 10, 1),
        date_fin=datetime.date(2027, 7, 31), est_active=True,
    )
    classe = Classe.objects.create(nom="6ème année B", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=annee)
    return annee, classe


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PubierAnnonceTests(TestCase):
    def setUp(self):
        self.annee, self.classe = creer_contexte_classe()
        self.enseignant = creer_utilisateur_actif("prof-com@example.com", Role.ENSEIGNANT)
        self.direction = creer_utilisateur_actif("direction-com@example.com", Role.FONDATEUR)
        self.eleve = creer_utilisateur_actif("eleve-com@example.com", Role.ELEVE)
        Inscription.objects.create(eleve=self.eleve, classe=self.classe)
        self.parent = creer_utilisateur_actif("parent-com@example.com", Role.PARENT, telephone="70300001", profession="X")
        self.eleve.parents_lies.add(self.parent)

    def test_enseignant_ne_peut_pas_publier_a_toute_lecole(self):
        annonce = Annonce(
            titre="Test", contenu="Contenu", portee=Portee.TOUTE_ECOLE, auteur=self.enseignant,
        )
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            annonce.full_clean()

    def test_enseignant_peut_publier_pour_sa_classe(self):
        self.client.force_login(self.enseignant)
        reponse = self.client.post(reverse("communication:publier_annonce"), {
            "titre": "Sortie pédagogique", "contenu": "RDV lundi 8h",
            "portee": Portee.MA_CLASSE, "classe_ciblee": self.classe.id,
        })
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(Annonce.objects.count(), 1)

    def test_direction_peut_publier_a_toute_lecole(self):
        self.client.force_login(self.direction)
        reponse = self.client.post(reverse("communication:publier_annonce"), {
            "titre": "Rentrée", "contenu": "La rentrée aura lieu le 1er octobre.",
            "portee": Portee.TOUTE_ECOLE,
        })
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(Annonce.objects.get().portee, Portee.TOUTE_ECOLE)

    def test_notification_email_envoyee_aux_eleves_et_parents_de_la_classe(self):
        self.client.force_login(self.enseignant)
        self.client.post(reverse("communication:publier_annonce"), {
            "titre": "Devoir", "contenu": "Devoir de maths pour vendredi",
            "portee": Portee.MA_CLASSE, "classe_ciblee": self.classe.id,
        })
        destinataires = mail.outbox[0].to
        self.assertIn(self.eleve.email, destinataires)
        self.assertIn(self.parent.email, destinataires)

    def test_eleve_ne_voit_pas_une_annonce_dune_autre_classe(self):
        autre_classe = Classe.objects.create(nom="6ème année C", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        Annonce.objects.create(
            titre="Autre classe", contenu="...", portee=Portee.MA_CLASSE,
            classe_ciblee=autre_classe, auteur=self.direction,
        )
        self.client.force_login(self.eleve)
        reponse = self.client.get(reverse("communication:liste_annonces"))
        self.assertNotContains(reponse, "Autre classe")


class MessagerieTests(TestCase):
    def setUp(self):
        self.annee, self.classe = creer_contexte_classe()
        self.enseignant = creer_utilisateur_actif("prof-msg@example.com", Role.ENSEIGNANT)
        Affectation.objects.create(enseignant=self.enseignant, classe=self.classe, matiere="Mathématiques")
        self.autre_enseignant = creer_utilisateur_actif("autre-prof-msg@example.com", Role.ENSEIGNANT)
        self.eleve = creer_utilisateur_actif("eleve-msg@example.com", Role.ELEVE)
        Inscription.objects.create(eleve=self.eleve, classe=self.classe)
        self.parent = creer_utilisateur_actif("parent-msg@example.com", Role.PARENT, telephone="70400001", profession="X")
        self.eleve.parents_lies.add(self.parent)
        self.parent_etranger = creer_utilisateur_actif(
            "parent-etranger-msg@example.com", Role.PARENT, telephone="70400002", profession="X",
        )

    def test_parent_peut_ecrire_a_lenseignant_de_son_enfant(self):
        self.client.force_login(self.parent)
        reponse = self.client.post(
            reverse("communication:conversation", args=[self.eleve.id, self.enseignant.id]),
            {"contenu": "Bonjour, comment progresse mon enfant ?"},
        )
        self.assertEqual(reponse.status_code, 302)
        message = Message.objects.get()
        self.assertEqual(message.expediteur, self.parent)
        self.assertEqual(message.destinataire, self.enseignant)
        self.assertEqual(message.eleve, self.eleve)
        self.assertTrue(Notification.objects.filter(destinataire=self.enseignant).exists())

    def test_enseignant_peut_repondre_au_parent(self):
        Message.objects.create(
            eleve=self.eleve, expediteur=self.parent, destinataire=self.enseignant, contenu="Bonjour",
        )
        self.client.force_login(self.enseignant)
        reponse = self.client.post(
            reverse("communication:conversation", args=[self.eleve.id, self.parent.id]),
            {"contenu": "Bonjour, tout va bien."},
        )
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(Message.objects.filter(expediteur=self.enseignant).count(), 1)

    def test_parent_ne_peut_pas_ecrire_a_un_enseignant_qui_nenseigne_pas_a_son_enfant(self):
        self.client.force_login(self.parent)
        reponse = self.client.post(
            reverse("communication:conversation", args=[self.eleve.id, self.autre_enseignant.id]),
            {"contenu": "Bonjour"},
        )
        self.assertEqual(reponse.status_code, 403)
        self.assertEqual(Message.objects.count(), 0)

    def test_parent_ne_peut_pas_ecrire_au_sujet_dun_enfant_qui_nest_pas_le_sien(self):
        self.client.force_login(self.parent_etranger)
        reponse = self.client.post(
            reverse("communication:conversation", args=[self.eleve.id, self.enseignant.id]),
            {"contenu": "Bonjour"},
        )
        self.assertEqual(reponse.status_code, 403)

    def test_message_marque_lu_a_la_lecture_de_la_conversation(self):
        message = Message.objects.create(
            eleve=self.eleve, expediteur=self.parent, destinataire=self.enseignant, contenu="Bonjour",
        )
        self.client.force_login(self.enseignant)
        self.client.get(reverse("communication:conversation", args=[self.eleve.id, self.parent.id]))
        message.refresh_from_db()
        self.assertIsNotNone(message.lu_le)
