"""
Préparation des fichiers du site comme sur Render (`collectstatic` avec le stockage « manifeste » de WhiteNoise).

Ce stockage est strict : si une feuille de style ou un script annonce un fichier absent (par exemple un `sourceMappingURL` vers un fichier
`.map` oublié, ou un `url(...)` vers une police), la construction du déploiement s'arrête et la nouvelle version n'est jamais mise en ligne.
Les tests ordinaires ne le voient pas parce qu'ils utilisent le stockage simple : ce test refait la vraie construction.
"""
import json
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

STOCKAGE_PRODUCTION = {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"}


class ConstructionDesFichiersStatiquesTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dossier = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.dossier.cleanup)
        with override_settings(STORAGES={**settings.STORAGES, "staticfiles": STOCKAGE_PRODUCTION}, STATIC_ROOT=cls.dossier.name):
            call_command("collectstatic", interactive=False, verbosity=0)  # échoue si un fichier annoncé manque
        manifeste = Path(cls.dossier.name) / "staticfiles.json"
        cls.fichiers = json.loads(manifeste.read_text(encoding="utf-8"))["paths"]

    def test_la_construction_de_production_reussit_et_ecrit_le_manifeste(self):
        self.assertGreater(len(self.fichiers), 50)

    def test_les_fichiers_de_l_arabe_et_de_l_interface_sont_empreints(self):
        for nom in (
            "css/toumai.css", "css/toumai-rtl.css", "css/bootstrap.min.css", "css/bootstrap.rtl.min.css",
            "fonts/cairo-variable-arabic.woff2", "js/app.js", "js/sw.js",
        ):
            with self.subTest(fichier=nom):
                self.assertIn(nom, self.fichiers)
                self.assertNotEqual(self.fichiers[nom], nom)  # le nom final porte l'empreinte du contenu

    def test_les_polices_appelees_par_la_feuille_arabe_suivent_l_empreinte(self):
        feuille = (Path(self.dossier.name) / self.fichiers["css/toumai-rtl.css"]).read_text(encoding="utf-8")
        self.assertIn(self.fichiers["fonts/cairo-variable-arabic.woff2"].split("/")[-1], feuille)
