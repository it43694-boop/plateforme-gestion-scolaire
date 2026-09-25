from django.test import TestCase
from django.urls import reverse

from comptes.models import Utilisateur
from comptes.roles import Role, StatutCompte


class AccueilTests(TestCase):
    def test_accueil_accessible_sans_connexion(self):
        reponse = self.client.get(reverse("vitrine:accueil"))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Se connecter")

    def test_utilisateur_connecte_redirige_vers_tableau_de_bord(self):
        utilisateur = Utilisateur(
            email="vitrine@example.com", prenom="Test", nom="Utilisateur", role=Role.ENSEIGNANT,
            statut=StatutCompte.ACTIF, is_active=True,
        )
        utilisateur.set_password("MotDePasse#2026")
        utilisateur.full_clean(exclude=["password"])
        utilisateur.save()
        self.client.force_login(utilisateur)
        reponse = self.client.get(reverse("vitrine:accueil"))
        self.assertRedirects(reponse, reverse("comptes:redirection_tableau_de_bord"))
