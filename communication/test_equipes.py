"""Tests de cloisonnement des discussions d'équipe pédagogique."""
import datetime

from django.test import TestCase
from django.urls import reverse

from comptes.models import JournalAudit, Notification, Utilisateur
from comptes.roles import Role, StatutCompte
from communication.equipes import fils_proposes_pour, obtenir_ou_creer_fil
from communication.models import FilEquipe, MessageEquipe, PorteeEquipe
from etablissement.models import Etablissement
from permissions_matrix.models import PermissionMatrix
from scolarite.models import Affectation, AnneeScolaire, Classe, Cycle


class EquipesPedagogiquesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ecole = Etablissement.objects.create(nom="École équipes A")
        cls.ecole_b = Etablissement.objects.create(nom="École équipes B")
        PermissionMatrix.seed_pour(cls.ecole)
        PermissionMatrix.seed_pour(cls.ecole_b)
        cls.annee = AnneeScolaire.objects.create(
            etablissement=cls.ecole, libelle="2026-2027", date_debut=datetime.date(2026, 10, 1),
            date_fin=datetime.date(2027, 7, 31), est_active=True,
        )
        cls.annee_b = AnneeScolaire.objects.create(
            etablissement=cls.ecole_b, libelle="2026-2027", date_debut=datetime.date(2026, 10, 1),
            date_fin=datetime.date(2027, 7, 31), est_active=True,
        )
        cls.classe_a = Classe.objects.create(
            nom="10A", cycle=Cycle.LYCEE, niveau="annee_10", annee_scolaire=cls.annee,
        )
        cls.classe_b = Classe.objects.create(
            nom="10B", cycle=Cycle.LYCEE, niveau="annee_10", annee_scolaire=cls.annee,
        )
        cls.classe_autre = Classe.objects.create(
            nom="10A", cycle=Cycle.LYCEE, niveau="annee_10", annee_scolaire=cls.annee_b,
        )
        cls.prof_a = cls.creer_compte("prof-a@example.test", Role.ENSEIGNANT, cls.ecole)
        cls.prof_b = cls.creer_compte("prof-b@example.test", Role.ENSEIGNANT, cls.ecole)
        cls.prof_autre_ecole = cls.creer_compte("prof-c@example.test", Role.ENSEIGNANT, cls.ecole_b)
        cls.parent = cls.creer_compte("parent@example.test", Role.PARENT, cls.ecole, telephone="70100001")
        cls.directeur = cls.creer_compte("direction@example.test", Role.DIRECTEUR_LYCEE, cls.ecole)
        Affectation.objects.create(enseignant=cls.prof_a, classe=cls.classe_a, matiere="Maths")
        Affectation.objects.create(enseignant=cls.prof_b, classe=cls.classe_b, matiere=" maths  ")
        Affectation.objects.create(enseignant=cls.prof_autre_ecole, classe=cls.classe_autre, matiere="Maths")

    @staticmethod
    def creer_compte(email, role, etablissement, **extra):
        compte = Utilisateur(
            email=email, prenom="Test", nom=email.split("@")[0], role=role, etablissement=etablissement,
            statut=StatutCompte.ACTIF, is_active=True, email_verifie=True, **extra,
        )
        compte.set_unusable_password()
        compte.save()
        return compte

    def fil_matiere(self, professeur):
        proposition = next(
            proposition for proposition in fils_proposes_pour(professeur)
            if proposition["portee"] == PorteeEquipe.MATIERE_NIVEAU
        )
        return obtenir_ou_creer_fil(professeur, proposition)

    def test_sections_paralleles_partagent_un_fil_de_matiere_normalisee(self):
        fil_a = self.fil_matiere(self.prof_a)
        fil_b = self.fil_matiere(self.prof_b)
        self.assertEqual(fil_a.pk, fil_b.pk)
        self.assertEqual(set(fil_a.messages.all()), set())

    def test_autre_ecole_et_parent_ne_peuvent_pas_lire_ou_ecrire(self):
        fil = self.fil_matiere(self.prof_a)
        self.client.force_login(self.prof_autre_ecole)
        self.assertEqual(self.client.get(reverse("communication:fil_equipe", args=[fil.pk])).status_code, 404)
        self.client.force_login(self.parent)
        url = reverse("communication:fil_equipe", args=[fil.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {"contenu": "intrusion"}).status_code, 403)
        self.assertEqual(MessageEquipe.objects.count(), 0)

    def test_message_notifie_seulement_les_enseignants_membres_sans_auditer_le_contenu(self):
        fil = self.fil_matiere(self.prof_a)
        contenu = "Contenu pédagogique privé"
        self.client.force_login(self.prof_a)
        response = self.client.post(reverse("communication:fil_equipe", args=[fil.pk]), {"contenu": contenu})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(set(Notification.objects.values_list("destinataire_id", flat=True)), {self.prof_b.pk})
        notification = Notification.objects.get(destinataire=self.prof_b)
        self.assertNotIn(contenu, notification.message)
        self.assertNotIn(contenu, notification.titre)
        audit = JournalAudit.objects.get(action="message_equipe")
        self.assertNotIn(contenu, f"{audit.cible} {audit.details}")

    def test_direction_peut_superviser_son_cycle_et_les_annonces_lient_au_fil(self):
        fil = self.fil_matiere(self.prof_a)
        self.client.force_login(self.directeur)
        self.assertEqual(self.client.get(reverse("communication:fil_equipe", args=[fil.pk])).status_code, 200)
        response = self.client.get(reverse("communication:liste_annonces"))
        self.assertContains(response, reverse("communication:liste_equipes"))

    def test_enseignant_sans_affectation_n_obtient_aucun_fil(self):
        sans_affectation = self.creer_compte("sans-affectation@example.test", Role.ENSEIGNANT, self.ecole)
        self.assertEqual(fils_proposes_pour(sans_affectation), [])
        self.client.force_login(sans_affectation)
        self.assertContains(self.client.get(reverse("communication:liste_equipes")), "Aucune équipe")

    def test_creation_concurrente_representee_par_get_or_create_est_idempotente(self):
        proposition = next(
            proposition for proposition in fils_proposes_pour(self.prof_a)
            if proposition["portee"] == PorteeEquipe.NIVEAU
        )
        premier = obtenir_ou_creer_fil(self.prof_a, proposition)
        second = obtenir_ou_creer_fil(self.prof_b, proposition)
        self.assertEqual(premier.pk, second.pk)
        self.assertEqual(FilEquipe.objects.filter(cle=premier.cle).count(), 1)

    # --- page des équipes : pas de requêtes par fil (une direction voit un fil par classe) ---

    def _ajouter_classes(self, nombre, debut=0):
        for i in range(debut, debut + nombre):
            classe = Classe.objects.create(
                nom=f"11-{i}", cycle=Cycle.LYCEE, niveau="annee_11", annee_scolaire=self.annee,
            )
            Affectation.objects.create(enseignant=self.prof_a, classe=classe, matiere=f"Matière {i}")

    def _requetes_de_la_page(self, utilisateur):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.client.force_login(utilisateur)
        with CaptureQueriesContext(connection) as requetes:
            reponse = self.client.get(reverse("communication:liste_equipes"))
        self.assertEqual(reponse.status_code, 200)
        return len(requetes), reponse

    def test_nombre_de_requetes_independant_du_nombre_de_fils(self):
        self._ajouter_classes(2)
        self._requetes_de_la_page(self.directeur)  # première visite : crée les fils
        peu = self._requetes_de_la_page(self.directeur)[0]
        self._ajouter_classes(25, debut=2)
        self._requetes_de_la_page(self.directeur)  # crée les fils ajoutés
        beaucoup = self._requetes_de_la_page(self.directeur)[0]
        self.assertLessEqual(beaucoup, peu + 2)  # avant : environ 3 requêtes de plus par fil

    def test_deuxieme_visite_ne_cree_rien(self):
        self._ajouter_classes(3)
        self._requetes_de_la_page(self.prof_a)
        avant = FilEquipe.objects.count()
        self._requetes_de_la_page(self.prof_a)
        self.assertEqual(FilEquipe.objects.count(), avant)

    def test_compte_sans_equipe_ne_cree_aucun_fil(self):
        sans_affectation = self.creer_compte("vide@example.test", Role.ENSEIGNANT, self.ecole)
        self._requetes_de_la_page(sans_affectation)
        self.assertEqual(FilEquipe.objects.count(), 0)

    def test_dernier_message_et_nombre_affiches_par_fil(self):
        fil = self.fil_matiere(self.prof_a)
        MessageEquipe.objects.create(fil=fil, auteur=self.prof_a, contenu="Premier message")
        MessageEquipe.objects.create(fil=fil, auteur=self.prof_b, contenu="Dernier message du fil")
        _, reponse = self._requetes_de_la_page(self.prof_a)
        self.assertContains(reponse, "Dernier message du fil")
        self.assertNotContains(reponse, "Premier message")

    def test_la_page_ne_montre_pas_les_fils_d_une_autre_ecole(self):
        _, reponse = self._requetes_de_la_page(self.prof_autre_ecole)
        self.assertNotContains(reponse, "École équipes A")
        self.assertEqual(
            set(FilEquipe.objects.values_list("etablissement__nom", flat=True)), {"École équipes B"},
        )

    def test_ordre_des_classes_conserve(self):
        _, reponse = self._requetes_de_la_page(self.directeur)
        contenu = reponse.content.decode()
        self.assertLess(contenu.index("Classe 10A"), contenu.index("Classe 10B"))
