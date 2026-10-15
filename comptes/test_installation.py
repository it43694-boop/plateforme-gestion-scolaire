"""
Bouton « Installer l'application » : présent dans l'application, sur la connexion et sur l'accueil public, caché tant que le
navigateur n'a pas dit qu'il sait installer (le script `static/js/app.js` le montre), avec une aide pour iPhone et iPad.
Le manifeste suit la langue choisie.
"""
import json
import re
from pathlib import Path

from django.conf import settings
from django.test import Client, TestCase
from django.urls import reverse

from comptes.langues import NOM_COOKIE_LANGUE
from comptes.roles import Role
from statistiques.test_education import EducationBase, creer_compte

BOUTON = re.compile(r'<button type="button" class="bouton-installer" data-installer hidden>')


class BoutonInstallerTests(EducationBase):
    def pages(self):
        compte = creer_compte(Role.FONDATEUR, "installer@test.test", self.ecole)
        connecte = Client()
        connecte.force_login(compte)
        return {
            "application": connecte.get("/comptes/tableau-de-bord/"),
            "connexion": Client().get(reverse("comptes:connexion")),
            "accueil": Client().get(reverse("vitrine:accueil")),
        }

    def test_le_bouton_est_cache_au_depart_et_present_une_seule_fois_par_page(self):
        for nom, page in self.pages().items():
            with self.subTest(page=nom):
                html = page.content.decode()
                self.assertEqual(len(BOUTON.findall(html)), 1)
                self.assertEqual(html.count('id="installer-aide"'), 1)
                self.assertIn("Installer l'application", html)

    def test_l_aide_pour_iphone_explique_les_trois_gestes(self):
        html = self.pages()["connexion"].content.decode()
        for geste in ("Partager", "Sur l'écran d'accueil", "Ajouter"):
            self.assertIn(geste, html)

    def test_en_arabe_le_bouton_et_l_aide_sont_traduits(self):
        client = Client()
        client.cookies[NOM_COOKIE_LANGUE] = "ar"
        html = client.get(reverse("comptes:connexion")).content.decode()
        self.assertIn("تثبيت التطبيق", html)
        self.assertIn("إضافة إلى الشاشة الرئيسية", html)
        self.assertNotIn("Installer l'application", html)
        self.assertNotIn("Touchez", html)

    def test_le_script_montre_le_bouton_seulement_si_l_installation_est_possible(self):
        script = (Path(settings.BASE_DIR) / "static" / "js" / "app.js").read_text(encoding="utf-8")
        for morceau in ("beforeinstallprompt", "appinstalled", "display-mode: standalone", "navigator.standalone", "[data-installer]"):
            self.assertIn(morceau, script)

    def test_la_regle_hidden_l_emporte_sur_l_affichage_du_bouton(self):
        feuille = (Path(settings.BASE_DIR) / "static" / "css" / "toumai.css").read_text(encoding="utf-8")
        self.assertIn(".bouton-installer[hidden] { display: none; }", feuille)


class ManifesteTests(TestCase):
    def manifeste(self, langue=None):
        client = Client()
        if langue:
            client.cookies[NOM_COOKIE_LANGUE] = langue
        reponse = client.get(reverse("manifeste_pwa"))
        self.assertEqual(reponse["Content-Type"], "application/manifest+json")
        return json.loads(reponse.content)

    def test_le_manifeste_rend_l_application_installable(self):
        manifeste = self.manifeste()
        self.assertEqual(manifeste["display"], "standalone")
        self.assertEqual(manifeste["id"], "/")
        self.assertEqual(manifeste["start_url"], "/")
        self.assertTrue(any(i.get("purpose") == "maskable" for i in manifeste["icons"]))

    def test_le_manifeste_suit_la_langue(self):
        self.assertEqual((self.manifeste()["lang"], self.manifeste()["dir"]), ("fr", "ltr"))
        self.assertEqual((self.manifeste("ar")["lang"], self.manifeste("ar")["dir"]), ("ar", "rtl"))

    def test_le_service_worker_est_servi_a_la_racine(self):
        reponse = Client().get("/sw.js")
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("javascript", reponse["Content-Type"])
