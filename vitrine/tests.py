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


class IdentiteYelenovaTests(TestCase):
    """Nom, slogan, description et logo de la plateforme (Yelenova), distincts de l'identité de chaque école."""

    SLOGAN = "La lumière du savoir"

    def _ecoles(self, nombre):
        from etablissement.models import Etablissement
        return [Etablissement.objects.create(nom=f"École Test {i}") for i in range(nombre)]

    def test_constantes_d_identite(self):
        from django.conf import settings
        self.assertEqual(settings.NOM_PLATEFORME, "Yelenova")
        self.assertEqual(settings.NOM_COMMERCIAL, "YELENOVA")
        self.assertEqual(settings.SLOGAN_PLATEFORME, self.SLOGAN)
        self.assertIn("pilotage des établissements scolaires", settings.POSITIONNEMENT_PLATEFORME)
        self.assertIn("espaces adaptés à leurs responsabilités", settings.DESCRIPTION_PLATEFORME)

    def test_accueil_sans_ecole_affiche_yelenova(self):
        reponse = self.client.get(reverse("vitrine:accueil"))
        self.assertContains(reponse, "YELENOVA")
        self.assertContains(reponse, "logo-yelenova")

    def test_accueil_plusieurs_ecoles_affiche_slogan_description_et_logo(self):
        self._ecoles(2)
        reponse = self.client.get(reverse("vitrine:accueil"))
        self.assertContains(reponse, "YELENOVA")
        self.assertContains(reponse, self.SLOGAN)
        self.assertContains(reponse, "centralise les opérations")
        self.assertContains(reponse, "logo-yelenova")
        self.assertContains(reponse, "pilotage des établissements scolaires")  # pied de page et description de la page
        self.assertNotContains(reponse, "L'éducation du Mali")

    def test_accueil_une_seule_ecole_garde_son_identite_dans_le_menu(self):
        ecole = self._ecoles(1)[0]
        reponse = self.client.get(reverse("vitrine:accueil"))
        self.assertContains(reponse, ecole.nom)
        self.assertContains(reponse, self.SLOGAN)

    def test_connexion_sans_ecole_choisie_affiche_yelenova(self):
        self._ecoles(2)
        reponse = self.client.get(reverse("comptes:connexion"))
        self.assertContains(reponse, "YELENOVA")
        self.assertContains(reponse, self.SLOGAN)
        self.assertContains(reponse, "logo-yelenova")

    def test_connexion_avec_une_ecole_choisie_affiche_l_ecole(self):
        ecoles = self._ecoles(2)
        self.client.get(reverse("vitrine:choisir_etablissement", args=[ecoles[0].slug]))
        reponse = self.client.get(reverse("comptes:connexion"))
        self.assertContains(reponse, ecoles[0].nom)
        self.assertNotContains(reponse, "logo-yelenova")

    def test_manifeste_de_l_application_installable(self):
        import json
        reponse = self.client.get(reverse("manifeste_pwa"))
        manifeste = json.loads(reponse.content)
        self.assertEqual(manifeste["name"], "Yelenova")
        self.assertEqual(manifeste["short_name"], "Yelenova")
        tailles = {icone["sizes"] for icone in manifeste["icons"]}
        self.assertTrue({"192x192", "512x512"} <= tailles)

    def test_page_proprietaire_affiche_yelenova_dans_la_barre_laterale(self):
        proprietaire = Utilisateur(
            email="proprio-yelenova@example.com", prenom="Test", nom="Proprio", role=Role.DEVELOPPEUR,
            is_superuser=True, is_staff=True, statut=StatutCompte.ACTIF, is_active=True,
        )
        proprietaire.set_unusable_password()
        proprietaire.save()
        self.client.force_login(proprietaire)
        reponse = self.client.get(reverse("espace_plateforme:liste_etablissements"))
        self.assertContains(reponse, "YELENOVA")
        self.assertContains(reponse, "logo-yelenova")

    def test_proprietaire_voit_yelenova_meme_avec_une_seule_ecole(self):
        """Avec une seule école, les visiteurs la voient par défaut - pas le propriétaire de la plateforme."""
        ecole = self._ecoles(1)[0]
        proprietaire = Utilisateur(
            email="proprio-une-ecole@example.com", prenom="Test", nom="Proprio", role=Role.DEVELOPPEUR,
            is_superuser=True, is_staff=True, statut=StatutCompte.ACTIF, is_active=True,
        )
        proprietaire.set_unusable_password()
        proprietaire.save()
        self.client.force_login(proprietaire)
        reponse = self.client.get(reverse("espace_plateforme:liste_etablissements"))
        self.assertContains(reponse, "YELENOVA")
        self.assertContains(reponse, "logo-yelenova")
        self.assertNotContains(reponse, f'<div class="marque-nom">{ecole.nom}</div>')

    def test_double_authentification_porte_le_nom_yelenova(self):
        utilisateur = Utilisateur(email="2fa-yelenova@example.com", prenom="T", nom="U", role=Role.ENSEIGNANT)
        uri = utilisateur.uri_provisionnement_2fa(Utilisateur.generer_secret_2fa())
        self.assertIn("issuer=Yelenova", uri)

    def test_page_administration_porte_le_nom_yelenova(self):
        from django.contrib import admin
        self.assertIn("Yelenova", admin.site.site_header)

    def test_gabarits_annuaire_et_aucun_etablissement_se_rendent(self):
        from django.template.loader import render_to_string
        for gabarit in ("vitrine/annuaire.html", "vitrine/aucun_etablissement.html"):
            with self.subTest(gabarit=gabarit):
                html = render_to_string(gabarit, {
                    "nom_plateforme": "Yelenova", "nom_commercial": "YELENOVA", "etablissements": [],
                })
                self.assertIn("logo-yelenova", html)

    def test_images_de_l_identite_visuelle_presentes_et_aux_bonnes_tailles(self):
        from pathlib import Path
        from django.conf import settings
        from PIL import Image
        racine = Path(settings.BASE_DIR) / "static" / "img"
        attendu = {
            "icons/icone-192.png": (192, 192), "icons/icone-512.png": (512, 512),
            "icons/icone-maskable-512.png": (512, 512), "icons/icone-apple-touch.png": (180, 180),
            "favicon-32.png": (32, 32),
        }
        for fichier, taille in attendu.items():
            with self.subTest(fichier=fichier):
                self.assertEqual(Image.open(racine / fichier).size, taille)
        self.assertTrue((racine / "favicon.ico").exists())
        # Le logo est un dessin en dégradés sur fond blanc (ses blancs, pages du livre et reflets, disparaîtraient avec un fond transparent) :
        # le fond doit être d'un blanc pur, sans liseré grisâtre, et le dessin lui-même doit bien être là.
        for fichier in ("logo-yelenova.png", "logo-yelenova-embleme.png"):
            with self.subTest(fichier=fichier):
                logo = Image.open(racine / fichier).convert("RGB")
                for coin in ((0, 0), (logo.width - 1, 0), (0, logo.height - 1), (logo.width - 1, logo.height - 1)):
                    self.assertEqual(logo.getpixel(coin), (255, 255, 255))
                histogramme = logo.convert("L").histogram()
                self.assertGreater(sum(histogramme[:200]), 0.1 * logo.width * logo.height)  # le dessin est bien là : plus d'un dixième de l'image n'est pas clair
        self.assertGreater(Image.open(racine / "logo-yelenova.png").height, Image.open(racine / "logo-yelenova-embleme.png").height)  # le logo complet porte aussi le nom

    def test_plus_aucune_reference_a_l_ancien_favicon(self):
        from pathlib import Path
        from django.conf import settings
        trouves = [
            str(chemin) for chemin in (Path(settings.BASE_DIR) / "templates").rglob("*.html")
            if "favicon.svg" in chemin.read_text(encoding="utf-8")
        ]
        self.assertEqual(trouves, [])
