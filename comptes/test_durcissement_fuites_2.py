"""
Second audit de fuites (octobre 2026) : un test par défaut trouvé.

1. Double authentification : les codes faux verrouillent le compte, et un mot de passe volé ne remet pas le compteur à zéro.
2. Changer l'email ou le mot de passe : pas d'essais illimités du mot de passe actuel.
3. Lien de réinitialisation du mot de passe : un jour.
4. Notifications de messages : l'extrait du message est effacé avec le message.
5. Sauvegardes : jamais dans le dossier du projet (le dépôt de code est public).
"""
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

import pyotp
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from comptes.entretien import purger_messages_anciens
from comptes.models import Notification
from comptes.roles import Role
from espace_plateforme.tests import creer_utilisateur_actif
from statistiques.test_education import EducationBase

MOT_DE_PASSE = "MotDePasse#2026"


class DoubleAuthentificationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.compte = creer_utilisateur_actif("verrou2fa@example.com", Role.DEVELOPPEUR)
        self.secret = self.compte.generer_secret_2fa()
        self.compte.totp_secret = self.secret
        self.compte.deux_facteurs_actif = True
        self.compte.save(update_fields=["totp_secret", "deux_facteurs_actif"])

    def mot_de_passe(self, mot_de_passe=MOT_DE_PASSE):
        cache.clear()  # la limite par adresse IP n'est pas ce que ces tests vérifient
        return self.client.post(reverse("comptes:connexion"), {"email": self.compte.email, "mot_de_passe": mot_de_passe})

    def code(self, code):
        cache.clear()
        return self.client.post(reverse("comptes:verifier_2fa"), {"code": code})

    def echecs(self):
        self.compte.refresh_from_db()
        return self.compte.tentatives_connexion_echouees

    @override_settings(NB_TENTATIVES_CONNEXION_AVANT_VERROUILLAGE=3)
    def test_trois_codes_faux_verrouillent_le_compte(self):
        self.mot_de_passe()
        for _ in range(3):
            reponse = self.code("000000")
        self.compte.refresh_from_db()
        self.assertTrue(self.compte.verrouille())
        self.assertRedirects(reponse, reverse("comptes:connexion"), fetch_redirect_response=False)
        # Même le BON code ne passe plus : la session en attente a été retirée et le compte est verrouillé.
        reponse = self.code(pyotp.TOTP(self.secret).now())
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertRedirects(reponse, reverse("comptes:connexion"), fetch_redirect_response=False)

    @override_settings(NB_TENTATIVES_CONNEXION_AVANT_VERROUILLAGE=3)
    def test_un_compte_verrouille_refuse_aussi_le_mot_de_passe(self):
        self.mot_de_passe()
        for _ in range(3):
            self.code("000000")
        reponse = self.mot_de_passe()
        self.assertNotIn("utilisateur_en_attente_2fa_id", self.client.session)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(reponse, "verrouillé")

    @override_settings(NB_TENTATIVES_CONNEXION_AVANT_VERROUILLAGE=3)
    def test_se_reconnecter_avec_le_mot_de_passe_ne_remet_pas_les_echecs_a_zero(self):
        """Le contournement visé : deux codes ratés, nouveau mot de passe, deux codes ratés... sans fin."""
        self.mot_de_passe()
        self.code("000000")
        self.code("000000")
        self.assertEqual(self.echecs(), 2)
        self.mot_de_passe()  # le mot de passe volé sert à recommencer
        self.assertEqual(self.echecs(), 2)  # inchangé : il ne reste qu'un essai
        self.code("000000")
        self.compte.refresh_from_db()
        self.assertTrue(self.compte.verrouille())

    def test_le_bon_code_remet_les_echecs_a_zero(self):
        self.mot_de_passe()
        self.code("000000")
        self.code("000000")
        self.assertEqual(self.echecs(), 2)
        reponse = self.code(pyotp.TOTP(self.secret).now())
        self.assertEqual(reponse.status_code, 302)
        self.assertTrue(self.client.session.get("_auth_user_id"))
        self.assertEqual(self.echecs(), 0)

    def test_un_code_de_secours_remet_aussi_les_echecs_a_zero(self):
        codes = self.compte.generer_codes_secours_2fa()
        self.mot_de_passe()
        self.code("000000")
        self.assertEqual(self.echecs(), 1)
        self.code(codes[0])
        self.assertTrue(self.client.session.get("_auth_user_id"))
        self.assertEqual(self.echecs(), 0)

    def test_sans_double_authentification_la_connexion_remet_les_echecs_a_zero_comme_avant(self):
        autre = creer_utilisateur_actif("sans2fa@example.com", Role.SECRETAIRE)
        autre.tentatives_connexion_echouees = 2
        autre.save(update_fields=["tentatives_connexion_echouees"])
        cache.clear()
        self.client.post(reverse("comptes:connexion"), {"email": autre.email, "mot_de_passe": MOT_DE_PASSE})
        autre.refresh_from_db()
        self.assertEqual(autre.tentatives_connexion_echouees, 0)

    @override_settings(NB_TENTATIVES_CONNEXION_AVANT_VERROUILLAGE=3)
    def test_le_verrouillage_prend_fin(self):
        self.mot_de_passe()
        for _ in range(3):
            self.code("000000")
        self.compte.verrouille_jusqu_a = timezone.now() - timedelta(minutes=1)
        self.compte.save(update_fields=["verrouille_jusqu_a"])
        self.mot_de_passe()
        reponse = self.code(pyotp.TOTP(self.secret).now())
        self.assertEqual(reponse.status_code, 302)
        self.assertTrue(self.client.session.get("_auth_user_id"))


class ChangementsDeCompteLimitesTests(TestCase):
    def setUp(self):
        cache.clear()
        # La limite compte par fenêtre fixe d'une minute : si les requêtes (lentes, mot de passe haché) chevauchaient un
        # changement de minute, le compteur repartirait à zéro et le test serait instable. On fige l'horloge de la limite.
        horloge = mock.patch("django_ratelimit.core.time.time", return_value=1_800_000_030.0)
        horloge.start()
        self.addCleanup(horloge.stop)
        self.compte = creer_utilisateur_actif("limite@example.com", Role.SECRETAIRE)
        self.client.force_login(self.compte)

    def test_changer_le_mot_de_passe_apres_cinq_essais_faux(self):
        url = reverse("comptes:changer_mot_de_passe")
        donnees = {"old_password": "faux", "new_password1": "Nouveau-Mot-2026!", "new_password2": "Nouveau-Mot-2026!"}
        for _ in range(5):
            self.assertNotContains(self.client.post(url, donnees), "Trop de tentatives")
        # Le sixième est bloqué, même avec le BON mot de passe actuel.
        donnees["old_password"] = MOT_DE_PASSE
        reponse = self.client.post(url, donnees)
        self.assertContains(reponse, "Trop de tentatives")
        self.compte.refresh_from_db()
        self.assertTrue(self.compte.check_password(MOT_DE_PASSE))

    def test_changer_l_email_apres_cinq_essais_faux(self):
        url = reverse("comptes:changer_email")
        for _ in range(5):
            self.client.post(url, {"nouvel_email": "nouveau@example.com", "mot_de_passe": "faux"})
        reponse = self.client.post(url, {"nouvel_email": "nouveau@example.com", "mot_de_passe": MOT_DE_PASSE})
        self.assertContains(reponse, "Trop de tentatives")
        self.compte.refresh_from_db()
        self.assertEqual(self.compte.email, "limite@example.com")

    def test_la_limite_est_par_utilisateur(self):
        url = reverse("comptes:changer_email")
        for _ in range(6):
            self.client.post(url, {"nouvel_email": "x@example.com", "mot_de_passe": "faux"})
        autre = creer_utilisateur_actif("autre-limite@example.com", Role.SECRETAIRE)
        self.client.force_login(autre)
        reponse = self.client.post(url, {"nouvel_email": "autre-nouveau@example.com", "mot_de_passe": MOT_DE_PASSE})
        self.assertEqual(reponse.status_code, 302)
        autre.refresh_from_db()
        self.assertEqual(autre.email, "autre-nouveau@example.com")

    def test_un_usage_normal_n_est_pas_gene(self):
        reponse = self.client.post(reverse("comptes:changer_mot_de_passe"), {
            "old_password": MOT_DE_PASSE, "new_password1": "Nouveau-Mot-2026!", "new_password2": "Nouveau-Mot-2026!",
        })
        self.assertEqual(reponse.status_code, 302)


class LienDeReinitialisationTests(TestCase):
    def test_le_lien_expire_au_bout_d_un_jour(self):
        self.assertEqual(settings.PASSWORD_RESET_TIMEOUT, 24 * 3600)
        compte = creer_utilisateur_actif("reset@example.com", Role.SECRETAIRE)
        jeton = default_token_generator.make_token(compte)
        maintenant = default_token_generator._now()
        with mock.patch.object(type(default_token_generator), "_now", return_value=maintenant + timedelta(hours=23)):
            self.assertTrue(default_token_generator.check_token(compte, jeton))
        with mock.patch.object(type(default_token_generator), "_now", return_value=maintenant + timedelta(hours=25)):
            self.assertFalse(default_token_generator.check_token(compte, jeton))


@override_settings(DUREE_CONSERVATION_MESSAGES_JOURS=30)
class NotificationsDeMessagesTests(EducationBase):
    def notification(self, url, age_jours, message="Bonjour, je voulais vous parler de Awa"):
        notification = Notification.objects.create(
            destinataire=self.t1, etablissement=self.ecole, titre="Nouveau message de X", message=message, url=url,
        )
        Notification.objects.filter(pk=notification.pk).update(cree_le=timezone.now() - timedelta(days=age_jours))
        return notification

    def test_l_extrait_du_message_part_avec_le_message(self):
        conversation = reverse("communication:conversation", args=[self.e1.pk, self.parent.pk])
        ancienne = self.notification(conversation, 40)
        recente = self.notification(conversation, 5)
        resultat = purger_messages_anciens()
        self.assertEqual(resultat["notifications_de_messages"], 1)
        self.assertFalse(Notification.objects.filter(pk=ancienne.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=recente.pk).exists())

    def test_les_autres_notifications_anciennes_sont_conservees(self):
        autre = self.notification(reverse("communication:liste_annonces"), 90, message="Réunion des parents")
        purger_messages_anciens()
        self.assertTrue(Notification.objects.filter(pk=autre.pk).exists())

    def test_la_simulation_ne_supprime_rien(self):
        ancienne = self.notification(reverse("communication:conversation", args=[self.e1.pk, self.parent.pk]), 40)
        self.assertEqual(purger_messages_anciens(simulation=True)["notifications_de_messages"], 1)
        self.assertTrue(Notification.objects.filter(pk=ancienne.pk).exists())

    def test_une_duree_a_zero_ne_supprime_rien(self):
        ancienne = self.notification(reverse("communication:conversation", args=[self.e1.pk, self.parent.pk]), 400)
        with override_settings(DUREE_CONSERVATION_MESSAGES_JOURS=0):
            self.assertEqual(purger_messages_anciens()["notifications_de_messages"], 0)
        self.assertTrue(Notification.objects.filter(pk=ancienne.pk).exists())


class SauvegardesHorsDuProjetTests(SimpleTestCase):
    def lancer(self, destination):
        with mock.patch("comptes.management.commands.sauvegarder_donnees.Command._sauvegarder_base_de_donnees"), mock.patch(
            "comptes.management.commands.sauvegarder_donnees.Command._sauvegarder_medias",
        ):
            call_command("sauvegarder_donnees", destination=str(destination))

    def test_refusee_dans_le_dossier_du_projet(self):
        projet = Path(settings.BASE_DIR)
        for destination in (projet, projet / "sauvegardes", projet / "a" / "b", projet / ".." / projet.name / "sauvegardes"):
            with self.subTest(destination=str(destination)):
                with self.assertRaises(CommandError) as erreur:
                    self.lancer(destination)
                self.assertIn("en dehors du projet", str(erreur.exception))
        self.assertFalse((projet / "sauvegardes").exists())  # rien n'a été créé

    def test_acceptee_en_dehors_du_projet(self):
        with tempfile.TemporaryDirectory() as dossier:
            self.lancer(dossier)
            self.assertEqual(len(list(Path(dossier).glob("sauvegarde_*"))), 1)

    def test_le_depot_ignore_les_sauvegardes(self):
        gitignore = (Path(settings.BASE_DIR) / ".gitignore").read_text(encoding="utf-8")
        for motif in ("sauvegarde_*/", "sauvegardes/", "backups/", "*.dump", "*.sqlite3", ".env"):
            self.assertIn(motif, gitignore)


class ConnexionDeLAdministrationTests(TestCase):
    """L'administration Django n'a pas son propre formulaire : un mot de passe seul ne donne jamais accès à toutes les données."""

    def setUp(self):
        cache.clear()
        self.proprietaire = creer_utilisateur_actif("owner-admin@example.com", Role.DEVELOPPEUR, is_superuser=True)

    def test_la_page_de_connexion_de_l_admin_renvoie_vers_celle_de_l_application(self):
        reponse = self.client.get("/admin/login/")
        self.assertRedirects(reponse, reverse("comptes:connexion"), fetch_redirect_response=False)  # plus d'erreur 500

    def test_un_mot_de_passe_poste_a_l_admin_ne_connecte_pas(self):
        reponse = self.client.post("/admin/login/", {"username": self.proprietaire.email, "password": MOT_DE_PASSE})
        self.assertRedirects(reponse, reverse("comptes:connexion"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.get("/admin/").status_code, 302)

    def test_l_administration_exige_la_connexion_de_l_application(self):
        reponse = self.client.get("/admin/", follow=True)
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.redirect_chain[-1][0], reverse("comptes:connexion"))

    def test_le_proprietaire_connecte_par_l_application_entre_toujours(self):
        self.client.force_login(self.proprietaire)
        self.assertEqual(self.client.get("/admin/").status_code, 200)

    def test_un_compte_ordinaire_n_entre_pas(self):
        compte = creer_utilisateur_actif("ordinaire-admin@example.com", Role.SECRETAIRE)
        self.client.force_login(compte)
        reponse = self.client.get("/admin/")
        self.assertEqual(reponse.status_code, 302)
