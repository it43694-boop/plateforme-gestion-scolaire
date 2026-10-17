"""Courriels envoyés à quelqu'un dont la langue est l'arabe : sujet et texte en arabe, mise en page de droite à gauche ; le français ne change pas."""
from django.core import mail
from django.test import TestCase, override_settings

from comptes.arabisation import invalider
from comptes.langue import langue_du_compte, texte_en_langue
from comptes.mail import envoyer_email
from comptes.models import Utilisateur
from comptes.roles import Role
from statistiques.test_education import EducationBase, creer_compte

CONTENU = (
    "Bonjour Awa,\n\nVotre code de vérification est : 123456\nIl est valable 10 minutes.\n\n"
    "Si vous n'êtes pas à l'origine de cette demande, ignorez cet email."
)


class TexteEnLangueTests(EducationBase):
    def setUp(self):
        Utilisateur.objects.filter(pk=self.e5.pk).update(prenom="Awa", nom="Traore", prenom_ar="عوا", nom_ar="تراوري")
        invalider(self.ecole.pk)

    def test_chaque_ligne_est_traduite_et_les_sauts_de_ligne_sont_gardes(self):
        texte = texte_en_langue(CONTENU, "ar", self.ecole.pk)
        lignes = texte.split("\n")
        self.assertEqual(len(lignes), len(CONTENU.split("\n")))
        self.assertEqual(lignes[0], "مرحبًا عوا،")
        self.assertEqual(lignes[2], "رمز التحقق الخاص بك هو : ١٢٣٤٥٦")
        self.assertEqual(lignes[3], "صلاحيته ١٠ دقائق.")

    def test_le_francais_ne_change_pas(self):
        self.assertEqual(texte_en_langue(CONTENU, "fr", self.ecole.pk), CONTENU)

    def test_un_lien_garde_ses_chiffres_latins(self):
        texte = texte_en_langue("Cliquez sur ce lien pour choisir un nouveau mot de passe :\nhttp://localhost/reinitialiser/Mjc/abc-123/", "ar")
        self.assertIn("http://localhost/reinitialiser/Mjc/abc-123/", texte)

    def test_la_langue_d_un_compte(self):
        self.assertEqual(langue_du_compte(self.e5), "fr")
        Utilisateur.objects.filter(pk=self.e5.pk).update(langue="ar")
        self.e5.refresh_from_db()
        self.assertEqual(langue_du_compte(self.e5), "ar")
        self.assertEqual(langue_du_compte(None, "ar"), "ar")
        self.assertEqual(langue_du_compte(None), "fr")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", EMAIL_ASYNC=False)
class EnvoiEnArabeTests(EducationBase):
    def test_un_courriel_en_arabe_est_traduit_et_de_droite_a_gauche(self):
        envoyer_email(
            sujet=f"{self.ecole.nom} - Vérification de votre email", contenu=CONTENU, expediteur="no-reply@test.test",
            destinataires=["awa@test.test"], langue="ar", etablissement_id=self.ecole.pk,
        )
        message = mail.outbox[0]
        self.assertIn("التحقق من بريدك الإلكتروني", message.subject)
        self.assertIn("رمز التحقق الخاص بك هو", message.body)
        html = message.alternatives[0][0]
        self.assertIn('dir="rtl"', html)
        self.assertIn("text-align: right", html)
        self.assertIn("يُرسل هذا البريد الإلكتروني تلقائيًا", html)

    def test_un_courriel_en_francais_ne_change_pas(self):
        envoyer_email(
            sujet="École - Vérification de votre email", contenu=CONTENU, expediteur="no-reply@test.test", destinataires=["awa@test.test"],
        )
        message = mail.outbox[0]
        self.assertEqual(message.body, CONTENU)
        html = message.alternatives[0][0]
        self.assertIn('dir="ltr"', html)
        self.assertIn("Cet email est envoyé automatiquement", html)
