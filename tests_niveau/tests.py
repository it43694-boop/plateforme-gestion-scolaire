import datetime

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from comptes.models import Utilisateur
from comptes.roles import Role, StatutCompte
from scolarite.models import AnneeScolaire, Classe, Cycle
from tests_niveau.models import Candidat, Decision, candidats_visibles_pour, decider_candidat


def creer_utilisateur_actif(email, role, **kwargs):
    utilisateur = Utilisateur(email=email, prenom="Test", nom="Utilisateur", role=role, **kwargs)
    utilisateur.set_password("MotDePasse#2026")
    utilisateur.statut = StatutCompte.ACTIF
    utilisateur.is_active = True
    utilisateur.full_clean(exclude=["password"])
    utilisateur.save()
    return utilisateur


def creer_contexte():
    annee = AnneeScolaire.objects.create(
        libelle="2026-2027", date_debut=datetime.date(2026, 10, 1),
        date_fin=datetime.date(2027, 7, 31), est_active=True,
    )
    classe_1er = Classe.objects.create(nom="1ère année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=annee)
    classe_2eme = Classe.objects.create(nom="7ème année A", cycle=Cycle.DEUXIEME_CYCLE, annee_scolaire=annee)
    return annee, classe_1er, classe_2eme


class CandidatModelTests(TestCase):
    def setUp(self):
        self.annee, self.classe_1er, self.classe_2eme = creer_contexte()
        self.secretaire = creer_utilisateur_actif("secretaire-test@example.com", Role.SECRETAIRE)

    def test_note_hors_intervalle_refusee(self):
        candidat = Candidat(
            prenom="Awa", nom="Coulibaly", classe_visee=self.classe_1er,
            note_test=25, cree_par=self.secretaire,
        )
        with self.assertRaises(ValidationError):
            candidat.full_clean()

    def test_decider_candidat_admis(self):
        candidat = Candidat.objects.create(prenom="Awa", nom="Coulibaly", classe_visee=self.classe_1er, cree_par=self.secretaire)
        decider_candidat(candidat=candidat, decision=Decision.ADMIS, acteur=self.secretaire)
        candidat.refresh_from_db()
        self.assertEqual(candidat.decision, Decision.ADMIS)
        self.assertEqual(candidat.decide_par, self.secretaire)
        self.assertIsNotNone(candidat.decide_le)

    def test_decision_invalide_refusee(self):
        candidat = Candidat.objects.create(prenom="Awa", nom="Coulibaly", classe_visee=self.classe_1er, cree_par=self.secretaire)
        with self.assertRaises(ValidationError):
            decider_candidat(candidat=candidat, decision=Decision.EN_ATTENTE, acteur=self.secretaire)

    def test_cloisonnement_par_cycle(self):
        Candidat.objects.create(prenom="Awa", nom="Coulibaly", classe_visee=self.classe_1er, cree_par=self.secretaire)
        Candidat.objects.create(prenom="Ibrahim", nom="Traore", classe_visee=self.classe_2eme, cree_par=self.secretaire)
        directeur_1er = creer_utilisateur_actif("dir1-test@example.com", Role.DIRECTEUR_1ER_CYCLE)
        visibles = candidats_visibles_pour(directeur_1er)
        self.assertEqual(visibles.count(), 1)
        self.assertEqual(visibles.first().classe_visee, self.classe_1er)


class VueCandidatsTests(TestCase):
    def setUp(self):
        self.annee, self.classe_1er, self.classe_2eme = creer_contexte()
        self.secretaire = creer_utilisateur_actif("secretaire-vue-test@example.com", Role.SECRETAIRE)

    def test_secretaire_peut_ajouter_un_candidat(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.post(reverse("tests_niveau:ajouter_candidat"), {
            "prenom": "Mariam", "nom": "Diallo", "classe_visee": self.classe_1er.id,
            "date_test": "2026-11-15", "telephone_contact": "", "note_test": "",
        })
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(Candidat.objects.filter(nom="Diallo").count(), 1)

    def test_enseignant_sans_acces_est_bloque(self):
        enseignant = creer_utilisateur_actif("prof-test@example.com", Role.ENSEIGNANT)
        self.client.force_login(enseignant)
        reponse = self.client.get(reverse("tests_niveau:liste_candidats"))
        self.assertEqual(reponse.status_code, 403)

    def test_decision_via_vue_http(self):
        candidat = Candidat.objects.create(prenom="Awa", nom="Coulibaly", classe_visee=self.classe_1er, cree_par=self.secretaire)
        self.client.force_login(self.secretaire)
        reponse = self.client.post(reverse("tests_niveau:decider_candidat", args=[candidat.id, "admis"]))
        self.assertEqual(reponse.status_code, 302)
        candidat.refresh_from_db()
        self.assertEqual(candidat.decision, Decision.ADMIS)

    def test_directeur_ne_peut_pas_decider_hors_de_son_cycle(self):
        candidat = Candidat.objects.create(prenom="Ibrahim", nom="Traore", classe_visee=self.classe_2eme, cree_par=self.secretaire)
        directeur_1er = creer_utilisateur_actif("dir1-vue-test@example.com", Role.DIRECTEUR_1ER_CYCLE)
        self.client.force_login(directeur_1er)
        reponse = self.client.post(reverse("tests_niveau:decider_candidat", args=[candidat.id, "admis"]))
        self.assertEqual(reponse.status_code, 404)
