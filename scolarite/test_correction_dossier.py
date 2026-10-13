"""
Corriger le dossier d'un élève (nom, naissance, parents sans compte) et utiliser les numéros des parents « en attente »
pour le bouton WhatsApp et les messages aux familles.

Jeu de données de EducationBase : école A (e1..e9, classes 6A/6B/9A/TSE/CAP-E), école B vide.
"""
import datetime

from django.test import TestCase
from django.urls import reverse

from comptes.models import JournalAudit, Utilisateur
from comptes.roles import Role
from communication.diffusion import preparer_messages
from scolarite.models import EcheancierFrais, ParentEnAttente
from statistiques.test_education import EducationBase, creer_compte


def donnees_formulaire(eleve, parents=(), **changements):
    """Le POST complet du formulaire : les valeurs actuelles de l'élève, modifiées par `changements`."""
    donnees = {
        "prenom": eleve.prenom, "nom": eleve.nom, "sexe": eleve.sexe or "F",
        "date_naissance": eleve.date_naissance.isoformat() if eleve.date_naissance else "",
        "lieu_naissance": eleve.lieu_naissance, "numero_acte_naissance": eleve.numero_acte_naissance,
        "handicap": eleve.handicap, "statut_deplacement": eleve.statut_deplacement,
        "parents-TOTAL_FORMS": str(len(parents) + 1), "parents-INITIAL_FORMS": str(len(parents)),
        "parents-MIN_NUM_FORMS": "0", "parents-MAX_NUM_FORMS": "2",
    }
    for rang, attente in enumerate(parents):
        donnees.update({
            f"parents-{rang}-id": str(attente.pk), f"parents-{rang}-email": attente.email,
            f"parents-{rang}-prenom": attente.prenom, f"parents-{rang}-nom": attente.nom,
            f"parents-{rang}-telephone": attente.telephone,
        })
    donnees.update(changements)
    return donnees


class CorrectionBase(EducationBase):
    def url(self, eleve=None):
        return reverse("scolarite:corriger_dossier_eleve", args=[(eleve or self.e1).matricule])


class AccesCorrectionTests(CorrectionBase):
    def test_l_administration_peut_ouvrir_la_page(self):
        for compte in (self.fondateur, self.secretaire, self.dir_1er):
            self.client.force_login(compte)
            with self.subTest(role=compte.role):
                self.assertEqual(self.client.get(self.url()).status_code, 200)

    def test_les_autres_roles_sont_refuses(self):
        for compte in (self.comptable, self.censeur, self.t1, self.parent, self.e1):
            self.client.force_login(compte)
            with self.subTest(role=compte.role):
                self.assertEqual(self.client.get(self.url()).status_code, 403)
                self.assertEqual(self.client.post(self.url(), donnees_formulaire(self.e1, nom="Pirate")).status_code, 403)
        self.e1.refresh_from_db()
        self.assertNotEqual(self.e1.nom, "Pirate")

    def test_un_directeur_de_cycle_ne_corrige_que_son_cycle(self):
        self.client.force_login(self.dir_1er)
        self.assertEqual(self.client.get(self.url(self.e5)).status_code, 403)  # e5 est en 9A (2ème cycle)

    def test_un_eleve_d_une_autre_ecole_est_introuvable(self):
        self.client.force_login(self.fondateur_b)
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.assertEqual(self.client.post(self.url(), donnees_formulaire(self.e1, nom="Pirate")).status_code, 404)

    def test_visiteur_anonyme_redirige(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url()).status_code, 302)

    def test_le_bouton_n_est_propose_qu_a_ceux_qui_peuvent_corriger(self):
        dossier = reverse("scolarite:dossier_eleve", args=[self.e1.matricule])
        self.client.force_login(self.secretaire)
        self.assertContains(self.client.get(dossier), self.url())
        for compte in (self.parent, self.e1):
            self.client.force_login(compte)
            self.assertNotContains(self.client.get(dossier), self.url())


class CorrectionDesRenseignementsTests(CorrectionBase):
    def test_correction_du_nom_de_la_naissance_et_du_sexe(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.post(self.url(), donnees_formulaire(
            self.e1, prenom="Awa", nom="Traoré", sexe="M", date_naissance="2014-06-02", lieu_naissance="Kayes",
        ))
        self.assertRedirects(reponse, reverse("scolarite:dossier_eleve", args=[self.e1.matricule]))
        self.e1.refresh_from_db()
        self.assertEqual((self.e1.prenom, self.e1.nom, self.e1.sexe), ("Awa", "Traoré", "M"))
        self.assertEqual(self.e1.date_naissance, datetime.date(2014, 6, 2))
        self.assertEqual(self.e1.lieu_naissance, "Kayes")

    def test_le_matricule_et_l_email_ne_changent_pas(self):
        matricule, email = self.e1.matricule, self.e1.email
        self.client.force_login(self.secretaire)
        self.client.post(self.url(), donnees_formulaire(self.e1, nom="Autre", matricule="HACK", email="hack@x.test"))
        self.e1.refresh_from_db()
        self.assertEqual((self.e1.matricule, self.e1.email), (matricule, email))

    def test_le_journal_note_les_champs_modifies_sans_les_valeurs(self):
        self.client.force_login(self.secretaire)
        self.client.post(self.url(), donnees_formulaire(self.e1, nom="Zorglub", lieu_naissance="Tombouctou"))
        entree = JournalAudit.objects.get(action="correction_dossier_eleve")
        self.assertEqual(entree.cible, self.e1.matricule)
        self.assertEqual(entree.details, {"champs": ["nom", "lieu_naissance"], "parents_en_attente": False})
        texte = f"{entree.cible} {entree.details}"
        self.assertNotIn("Zorglub", texte)
        self.assertNotIn("Tombouctou", texte)

    def test_sans_changement_rien_n_est_ecrit_au_journal(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.post(self.url(), donnees_formulaire(self.e1), follow=True)
        self.assertContains(reponse, "Aucune modification")
        self.assertFalse(JournalAudit.objects.filter(action="correction_dossier_eleve").exists())

    def test_date_de_naissance_dans_le_futur_refusee(self):
        self.client.force_login(self.secretaire)
        futur = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
        reponse = self.client.post(self.url(), donnees_formulaire(self.e1, date_naissance=futur, nom="Nouveau"))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "ne peut pas être dans le futur")
        self.e1.refresh_from_db()
        self.assertNotEqual(self.e1.nom, "Nouveau")  # rien n'est enregistré à moitié

    def test_nom_et_sexe_obligatoires(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.post(self.url(), donnees_formulaire(self.e1, nom="", sexe="X"))
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(reponse.context["formulaire"].errors.keys() >= {"nom", "sexe"})

    def test_effacer_la_date_de_naissance(self):
        self.client.force_login(self.secretaire)
        self.client.post(self.url(), donnees_formulaire(self.e1, date_naissance=""))
        self.e1.refresh_from_db()
        self.assertIsNone(self.e1.date_naissance)


class CorrectionDesParentsEnAttenteTests(CorrectionBase):
    def setUp(self):
        self.attente = ParentEnAttente.objects.create(
            eleve=self.e2, email="premier@attente.test", prenom="Premier", nom="Parent", telephone="70555001",
        )
        self.client.force_login(self.secretaire)

    def lignes_attente(self):
        return list(ParentEnAttente.objects.filter(eleve=self.e2).order_by("pk"))

    def test_corriger_le_telephone_d_un_parent_en_attente(self):
        donnees = donnees_formulaire(self.e2, parents=[self.attente])
        donnees["parents-0-telephone"] = "76 00 11 22"
        self.client.post(self.url(self.e2), donnees)
        self.attente.refresh_from_db()
        self.assertEqual(self.attente.telephone, "76 00 11 22")
        entree = JournalAudit.objects.get(action="correction_dossier_eleve")
        self.assertEqual(entree.details, {"champs": [], "parents_en_attente": True})
        self.assertNotIn("76 00", f"{entree.details}")

    def test_ajouter_un_parent(self):
        donnees = donnees_formulaire(self.e2, parents=[self.attente])
        donnees.update({
            "parents-1-email": "Second@Attente.test", "parents-1-prenom": "Second", "parents-1-nom": "Parent",
            "parents-1-telephone": "70555002",
        })
        self.client.post(self.url(self.e2), donnees)
        self.assertEqual([a.email for a in self.lignes_attente()], ["premier@attente.test", "Second@Attente.test"])

    def test_retirer_un_parent(self):
        donnees = donnees_formulaire(self.e2, parents=[self.attente])
        donnees["parents-0-DELETE"] = "on"
        self.client.post(self.url(self.e2), donnees)
        self.assertEqual(self.lignes_attente(), [])

    def test_deux_parents_avec_le_meme_email_refuses(self):
        donnees = donnees_formulaire(self.e2, parents=[self.attente])
        donnees.update({"parents-1-email": "PREMIER@attente.test", "parents-1-telephone": "70555002"})
        reponse = self.client.post(self.url(self.e2), donnees)
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "même email")
        self.assertEqual(len(self.lignes_attente()), 1)

    def test_email_d_un_compte_qui_n_est_pas_un_parent_refuse(self):
        donnees = donnees_formulaire(self.e2, parents=[self.attente])
        donnees["parents-0-email"] = self.t1.email
        reponse = self.client.post(self.url(self.e2), donnees)
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "pas le rôle")
        self.attente.refresh_from_db()
        self.assertEqual(self.attente.email, "premier@attente.test")

    def test_email_d_un_parent_qui_a_deja_un_compte_le_relie_tout_de_suite(self):
        parent = creer_compte(Role.PARENT, "existant@attente.test", self.ecole, telephone="70123456")
        donnees = donnees_formulaire(self.e2, parents=[self.attente])
        donnees["parents-0-email"] = "existant@attente.test"
        self.client.post(self.url(self.e2), donnees)
        self.assertEqual(self.lignes_attente(), [])
        self.assertTrue(self.e2.parents_lies.filter(pk=parent.pk).exists())

    def test_pas_de_ligne_vide_quand_l_eleve_a_deja_deux_parents(self):
        self.attente.delete()
        for numero in (1, 2):
            self.e2.parents_lies.add(creer_compte(Role.PARENT, f"lie{numero}@attente.test", self.ecole))
        reponse = self.client.get(self.url(self.e2))
        self.assertEqual(len(reponse.context["parents"].forms), 0)
        self.assertContains(reponse, "déjà deux parents liés")

    def test_un_seul_parent_lie_laisse_une_place(self):
        self.attente.delete()
        self.e2.parents_lies.add(creer_compte(Role.PARENT, "lie@attente.test", self.ecole))
        reponse = self.client.get(self.url(self.e2))
        self.assertEqual(len(reponse.context["parents"].forms), 1)


class NumerosEnAttenteUtilisesTests(CorrectionBase):
    """Le numéro donné à l'inscription par un parent sans compte sert au bouton WhatsApp et aux messages."""

    def setUp(self):
        # e4 (6B) n'a ni parent lié ni numéro propre ; e1 a un parent lié avec numéro (70999001).
        ParentEnAttente.objects.create(eleve=self.e4, email="p@attente.test", prenom="Premier", nom="Parent", telephone="70555001")
        ParentEnAttente.objects.create(eleve=self.e4, email="q@attente.test", prenom="Second", nom="Parent", telephone="70555002")
        ParentEnAttente.objects.create(eleve=self.e1, email="r@attente.test", telephone="77000001")
        ParentEnAttente.objects.create(eleve=self.e2, email="sans-numero@attente.test")
        EcheancierFrais.objects.create(classe=self.c6a, montant_inscription=10000, montant_periode=5000, nombre_versements=3)
        EcheancierFrais.objects.create(classe=self.c6b, montant_inscription=10000, montant_periode=5000, nombre_versements=3)

    def test_le_bouton_whatsapp_utilise_le_numero_d_un_parent_en_attente(self):
        self.client.force_login(self.comptable)
        reponse = self.client.get(reverse("finances:suivi_paiements"))
        par_eleve = {ligne["inscription"].eleve.pk: ligne for ligne in reponse.context["lignes"]}
        self.assertEqual(par_eleve[self.e4.pk]["telephone_whatsapp"], "70555001")
        self.assertContains(reponse, "https://wa.me/22370555001")

    def test_un_parent_avec_compte_passe_avant_un_parent_en_attente(self):
        self.client.force_login(self.comptable)
        reponse = self.client.get(reverse("finances:suivi_paiements"))
        par_eleve = {ligne["inscription"].eleve.pk: ligne for ligne in reponse.context["lignes"]}
        self.assertEqual(par_eleve[self.e1.pk]["telephone_whatsapp"], "70999001")

    def test_pas_de_bouton_si_aucun_numero_nulle_part(self):
        self.client.force_login(self.comptable)
        reponse = self.client.get(reverse("finances:suivi_paiements"))
        par_eleve = {ligne["inscription"].eleve.pk: ligne for ligne in reponse.context["lignes"]}
        self.assertIsNone(par_eleve[self.e2.pk]["telephone_whatsapp"])

    def test_messages_aux_familles_listent_les_deux_parents_en_attente(self):
        resultat = preparer_messages(
            type_="convocation", classes=[self.c6b], modele="Bonjour {eleve}", ecole="École A", date=datetime.date(2026, 11, 10),
        )
        self.assertEqual(resultat["sans_numero"], [])
        self.assertEqual(
            [(ligne["famille"], ligne["telephone"]) for ligne in resultat["lignes"]],
            [("Premier Parent", "70555001"), ("Second Parent", "70555002")],
        )

    def test_un_parent_en_attente_sans_numero_ne_compte_pas(self):
        resultat = preparer_messages(
            type_="annonce", classes=[self.c6a], modele="Bonjour", ecole="École A",
        )
        self.assertIn(f"{self.e2.nom_complet} ({self.c6a.nom})", resultat["sans_numero"])

    def test_le_numero_d_un_parent_en_attente_qui_double_un_parent_lie_n_est_pas_repete(self):
        ParentEnAttente.objects.create(eleve=self.e1, email="s@attente.test", telephone="70999001")  # même numéro que le parent lié
        resultat = preparer_messages(
            type_="convocation", classes=[self.c6a], modele="Bonjour", ecole="École A", date=datetime.date(2026, 11, 10),
        )
        numeros_e1 = [ligne["telephone"] for ligne in resultat["lignes"] if self.e1.nom_complet in ligne["eleves"]]
        self.assertEqual(sorted(numeros_e1), ["70999001", "77000001"])
