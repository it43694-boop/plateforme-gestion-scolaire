"""Un mot de passe refusé doit toujours s'expliquer : chaque règle non respectée est écrite sous le champ, en français comme en arabe."""
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from comptes.langues import NOM_COOKIE_LANGUE
from comptes.models import Utilisateur
from comptes.outils_test_arabe import restes_hors_textes_saisis
from comptes.roles import Role
from comptes.tests import creer_utilisateur_actif
from etablissement.models import Etablissement

SAISIS = {"Français", "Aicha", "Traore", "aicha.traore@exemple.test", "Test", "Utilisateur"}  # le bouton de langue s'écrit dans la langue vers laquelle il bascule ; ce que la personne a tapé reste tel quel


def donnees(mot_de_passe, confirmation=None, **autres):
    base = {
        "prenom": "Aicha", "nom": "Traore", "email": "aicha.traore@exemple.test", "telephone": "70123456", "profession": "Enseignante",
        "role": Role.PARENT.value, "mot_de_passe": mot_de_passe, "confirmation_mot_de_passe": mot_de_passe if confirmation is None else confirmation,
    }
    base.update(autres)
    return base


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class MotDePasseRefuseALInscriptionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        Etablissement.objects.create(nom="École des mots de passe")
        self.adresse = reverse("comptes:inscription")

    def refuse(self, mot_de_passe, *attendus, confirmation=None, **autres):
        """Le compte n'est pas créé, la page revient avec le formulaire et chaque explication attendue est écrite dessus."""
        reponse = self.client.post(self.adresse, donnees(mot_de_passe, confirmation, **autres))
        self.assertEqual(reponse.status_code, 200, mot_de_passe)
        self.assertFalse(Utilisateur.objects.filter(email="aicha.traore@exemple.test").exists(), mot_de_passe)
        for attendu in attendus:
            self.assertContains(reponse, attendu, msg_prefix=mot_de_passe)
        return reponse

    def test_trop_court(self):
        self.refuse("Ab#1", "trop court")

    def test_sans_majuscule(self):
        self.refuse("motdepasse#2026", "au moins une lettre majuscule")

    def test_sans_chiffre(self):
        self.refuse("MotDePasse#abcd", "au moins un chiffre")

    def test_sans_caractere_special(self):
        self.refuse("MotDePasse2026", "au moins un caractère spécial")

    def test_uniquement_des_chiffres(self):
        self.refuse("1234567890", "entièrement numérique")

    def test_mot_de_passe_trop_courant(self):
        self.refuse("password", "trop courant")

    def test_trop_semblable_au_nom_ou_a_l_email(self):
        self.refuse("Aicha.Traore@Exemple.Test1", "trop semblable")  # l'email avec un chiffre en plus
        self.refuse("Mahamadou#1", "trop semblable", prenom="Mahamadou", nom="Coulibaly")  # le prénom avec un chiffre et un signe

    def test_tout_ce_qui_manque_est_dit_en_une_fois(self):
        self.refuse("abc", "trop court", "au moins une lettre majuscule", "au moins un chiffre", "au moins un caractère spécial")

    def test_les_deux_saisies_different(self):
        self.refuse("MotDePasse#2026", "Les deux mots de passe ne correspondent pas", confirmation="MotDePasse#2027")

    def test_les_regles_sont_ecrites_avant_la_saisie(self):
        page = self.client.get(self.adresse)
        for regle in ("10 caractères", "majuscule", "chiffre", "caractère spécial"):
            self.assertContains(page, regle)

    def test_un_bon_mot_de_passe_cree_le_compte(self):
        reponse = self.client.post(self.adresse, donnees("Mali-Soleil#2026"))
        self.assertEqual(reponse.status_code, 302)
        self.assertTrue(Utilisateur.objects.filter(email="aicha.traore@exemple.test").exists())

    def test_le_message_ne_reprend_pas_le_mot_de_passe_tape(self):
        reponse = self.refuse("secretmalien", "au moins une lettre majuscule")
        self.assertNotContains(reponse, "secretmalien")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class MotDePasseRefuseEnArabeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        Etablissement.objects.create(nom="École des mots de passe")
        self.client = Client()
        self.client.cookies[NOM_COOKIE_LANGUE] = "ar"

    def test_la_page_et_chaque_refus_sont_en_arabe_pur(self):
        adresse = reverse("comptes:inscription")
        pages = [self.client.get(adresse)]
        for mot_de_passe in ("Ab#1", "motdepasse#2026", "MotDePasse#abcd", "MotDePasse2026", "1234567890", "password", "Aicha.Traore@Exemple.Test1", "abc"):
            pages.append(self.client.post(adresse, donnees(mot_de_passe)))
        for page in pages:
            with self.subTest(page=page.request["REQUEST_METHOD"]):
                self.assertEqual(page.status_code, 200)
                self.assertEqual(restes_hors_textes_saisis(page.content.decode(), SAISIS), [])


class MotDePasseRefuseAilleursTests(TestCase):
    """Le changement de mot de passe, la réinitialisation et la création d'un premier administrateur expliquent eux aussi le refus."""

    def test_changer_son_mot_de_passe(self):
        compte = creer_utilisateur_actif("changer-mdp@exemple.test", Role.ENSEIGNANT)
        self.client.force_login(compte)
        reponse = self.client.post(reverse("comptes:changer_mot_de_passe"), {
            "old_password": "MotDePasse#2026", "new_password1": "abc", "new_password2": "abc",
        })
        self.assertEqual(reponse.status_code, 200)
        for attendu in ("trop court", "au moins une lettre majuscule", "au moins un chiffre", "au moins un caractère spécial"):
            self.assertContains(reponse, attendu)

    def test_reinitialiser_son_mot_de_passe(self):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        compte = creer_utilisateur_actif("reinit-mdp@exemple.test", Role.ENSEIGNANT)
        adresse = reverse("comptes:reinitialiser_mot_de_passe", args=[urlsafe_base64_encode(force_bytes(compte.pk)), default_token_generator.make_token(compte)])
        suite = self.client.get(adresse, follow=True)  # Django range le jeton dans la session puis redirige
        reponse = self.client.post(suite.request["PATH_INFO"], {"new_password1": "abc", "new_password2": "abc"})
        self.assertEqual(reponse.status_code, 200)
        for attendu in ("trop court", "au moins une lettre majuscule", "au moins un chiffre", "au moins un caractère spécial"):
            self.assertContains(reponse, attendu)

    def test_creer_le_premier_administrateur_d_une_ecole(self):
        from espace_plateforme.forms import CreerEtablissementForm

        formulaire = CreerEtablissementForm({
            "nom": "École du premier administrateur", "prenom_developpeur": "Awa", "nom_developpeur": "Keita", "email_developpeur": "premier@exemple.test",
            "mot_de_passe_developpeur": "abc",
        })
        self.assertFalse(formulaire.is_valid())
        erreurs = " ".join(formulaire.errors["mot_de_passe_developpeur"])
        for attendu in ("trop court", "au moins une lettre majuscule", "au moins un chiffre", "au moins un caractère spécial"):
            self.assertIn(attendu, erreurs)

    def test_le_nom_et_l_email_comptent_aussi_au_changement(self):
        compte = creer_utilisateur_actif("karim.sanogo@exemple.test", Role.ENSEIGNANT)
        compte.prenom, compte.nom = "Mahamadou", "Sanogo"
        compte.save()
        self.client.force_login(compte)
        reponse = self.client.post(reverse("comptes:changer_mot_de_passe"), {
            "old_password": "MotDePasse#2026", "new_password1": "Mahamadou#1", "new_password2": "Mahamadou#1",
        })
        self.assertContains(reponse, "trop semblable")
