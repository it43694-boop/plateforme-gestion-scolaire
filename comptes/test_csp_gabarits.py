"""
La politique de sécurité du site (Content-Security-Policy : style-src 'self') bloque les attributs style="" en ligne.
Un bloc « caché » par style="display:none" s'affichait donc toujours dans le navigateur (bandeau hors connexion vide,
bloc « mois couverts » du paiement...). Les gabarits servis au navigateur n'en contiennent plus ; seuls les PDF
(xhtml2pdf) et les emails, rendus par d'autres moteurs, gardent des styles en ligne.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

GABARITS = Path(settings.BASE_DIR) / "templates"
STYLE_EN_LIGNE = re.compile(r"""\bstyle\s*=\s*["']""", re.IGNORECASE)


class GabaritsSansStyleEnLigneTests(SimpleTestCase):
    def test_aucun_style_en_ligne_dans_les_pages_du_navigateur(self):
        fautifs = []
        for chemin in sorted(GABARITS.rglob("*.html")):
            relatif = chemin.relative_to(GABARITS).as_posix()
            if relatif.startswith("emails/") or chemin.name.endswith("_pdf.html"):
                continue
            for numero, ligne in enumerate(chemin.read_text(encoding="utf-8").splitlines(), start=1):
                if STYLE_EN_LIGNE.search(ligne):
                    fautifs.append(f"{relatif}:{numero}")
        self.assertEqual(fautifs, [], "style=\"\" bloqué par la CSP : utilisez une classe CSS ou l'attribut hidden")

    def test_le_script_affiche_les_blocs_caches_par_l_attribut_hidden(self):
        """app.js doit lever `hidden` (et pas seulement display) pour réafficher le tableau de saisie."""
        script = (Path(settings.BASE_DIR) / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("tableau.hidden = false", script)
        self.assertIn("videMsg.hidden = true", script)
