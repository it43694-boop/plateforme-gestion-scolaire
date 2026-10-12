from django.test import TestCase
from django.urls import reverse

from comptes.models import Notification, Utilisateur
from comptes.roles import Role, StatutCompte
from etablissement.models import Etablissement


class NotificationsCloisonneesParEtablissementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ecole_a = Etablissement.objects.create(nom="École notifications A")
        cls.ecole_b = Etablissement.objects.create(nom="École notifications B")
        cls.utilisateur = Utilisateur(
            email="enseignant-notifications@example.test", prenom="Test", nom="Enseignant",
            role=Role.ENSEIGNANT, etablissement=cls.ecole_b, statut=StatutCompte.ACTIF,
            is_active=True, email_verifie=True,
        )
        cls.utilisateur.set_unusable_password()
        cls.utilisateur.save()

    def creer_notification(self, etablissement, message):
        return Notification.objects.create(
            destinataire=self.utilisateur, etablissement=etablissement,
            titre=f"Notification {message}", message=message,
        )

    def test_liste_ne_montre_pas_les_notifications_d_une_ancienne_ecole(self):
        privee = self.creer_notification(self.ecole_a, "CONTENU_ECOLE_A_SECRET")
        visible = self.creer_notification(self.ecole_b, "Notification actuelle")
        personnelle = self.creer_notification(None, "Notification personnelle")

        self.client.force_login(self.utilisateur)
        response = self.client.get(reverse("comptes:liste_notifications"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, privee.message)
        self.assertContains(response, visible.message)
        self.assertContains(response, personnelle.message)

    def test_marquer_tout_ne_modifie_pas_les_notifications_d_une_autre_ecole(self):
        ancienne = self.creer_notification(self.ecole_a, "Ancienne")
        actuelle = self.creer_notification(self.ecole_b, "Actuelle")
        personnelle = self.creer_notification(None, "Personnelle")
        self.client.force_login(self.utilisateur)

        response = self.client.post(reverse("comptes:marquer_notifications_lues"))

        self.assertEqual(response.status_code, 302)
        ancienne.refresh_from_db()
        actuelle.refresh_from_db()
        personnelle.refresh_from_db()
        self.assertIsNone(ancienne.lue_le)
        self.assertIsNotNone(actuelle.lue_le)
        self.assertIsNotNone(personnelle.lue_le)

    def test_un_identifiant_ne_permet_pas_de_marquer_lue_une_notification_d_une_autre_ecole(self):
        ancienne = self.creer_notification(self.ecole_a, "Ancienne")
        self.client.force_login(self.utilisateur)

        response = self.client.post(reverse("comptes:marquer_notification_lue", args=[ancienne.pk]))

        self.assertEqual(response.status_code, 404)
        ancienne.refresh_from_db()
        self.assertIsNone(ancienne.lue_le)
