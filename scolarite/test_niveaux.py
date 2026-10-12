import datetime

from django.test import TestCase
from django.urls import reverse

from comptes.models import Utilisateur
from comptes.roles import Role, StatutCompte
from etablissement.models import Etablissement
from permissions_matrix.models import PermissionMatrix
from scolarite.models import AnneeScolaire, Classe, Cycle, Niveau


class NiveauxClassesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ecole = Etablissement.objects.create(nom="École niveaux A")
        cls.ecole_b = Etablissement.objects.create(nom="École niveaux B")
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
        cls.classe_1 = Classe.objects.create(nom="10A", cycle=Cycle.LYCEE, annee_scolaire=cls.annee)
        cls.classe_2 = Classe.objects.create(nom="10B", cycle=Cycle.LYCEE, annee_scolaire=cls.annee)
        cls.autre_ecole_classe = Classe.objects.create(
            nom="10A", cycle=Cycle.LYCEE, annee_scolaire=cls.annee_b,
        )
        cls.directeur = cls.creer_compte("directeur@example.test", Role.DEVELOPPEUR, cls.ecole)
        cls.directeur_lycee = cls.creer_compte("dir-lycee@example.test", Role.DIRECTEUR_LYCEE, cls.ecole)
        cls.enseignant = cls.creer_compte("enseignant@example.test", Role.ENSEIGNANT, cls.ecole)

    @staticmethod
    def creer_compte(email, role, etablissement):
        compte = Utilisateur(
            email=email, prenom="Test", nom="Utilisateur", role=role, etablissement=etablissement,
            statut=StatutCompte.ACTIF, is_active=True, email_verifie=True,
        )
        compte.set_unusable_password()
        compte.save()
        return compte

    def test_niveaux_facultatifs_et_coherence_par_cycle(self):
        self.assertEqual(self.classe_1.niveau, "")
        self.classe_1.niveau = Niveau.ANNEE_10
        self.classe_1.full_clean()
        self.classe_1.niveau = Niveau.ANNEE_3
        with self.assertRaisesMessage(Exception, "Ce niveau ne correspond pas au cycle"):
            self.classe_1.full_clean()

    def test_direction_peut_definir_les_niveaux_de_son_cycle_uniquement(self):
        self.client.force_login(self.directeur_lycee)
        response = self.client.post(reverse("scolarite:definir_niveaux"), {
            f"niveau_{self.classe_1.pk}": Niveau.ANNEE_10,
            f"niveau_{self.classe_2.pk}": Niveau.ANNEE_11,
            f"niveau_{self.autre_ecole_classe.pk}": Niveau.ANNEE_12,
        })
        self.assertEqual(response.status_code, 302)
        self.classe_1.refresh_from_db()
        self.classe_2.refresh_from_db()
        self.autre_ecole_classe.refresh_from_db()
        self.assertEqual(self.classe_1.niveau, Niveau.ANNEE_10)
        self.assertEqual(self.classe_2.niveau, Niveau.ANNEE_11)
        self.assertEqual(self.autre_ecole_classe.niveau, "")

    def test_niveau_invalide_ignore_et_page_interdite_a_un_enseignant(self):
        self.client.force_login(self.directeur)
        response = self.client.post(reverse("scolarite:definir_niveaux"), {
            f"niveau_{self.classe_1.pk}": Niveau.ANNEE_3,
        })
        self.assertEqual(response.status_code, 302)
        self.classe_1.refresh_from_db()
        self.assertEqual(self.classe_1.niveau, "")

        self.client.force_login(self.enseignant)
        response = self.client.get(reverse("scolarite:definir_niveaux"))
        self.assertEqual(response.status_code, 403)
