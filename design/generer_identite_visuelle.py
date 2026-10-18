"""
Génère toutes les images de l'identité Yelenova à partir du logo source (design/logo-yelenova.png) :
logo complet, emblème seul, favicon, icônes de l'application installable (PWA) et icône iPhone.

À relancer si le logo change :
    python design/generer_identite_visuelle.py

Le logo source est un dessin en dégradés (livre vert et or, soleil, carte du Mali) posé sur un fond presque blanc. Ce fond est blanchi
(les pixels très clairs deviennent tout à fait blancs, avec une transition douce) mais n'est pas rendu transparent : les blancs du dessin
lui-même (pages du livre, reflets) disparaîtraient avec lui. L'interface pose donc le logo sur une pastille blanche (voir toumai.css).

Les zones ci-dessous (en pixels du logo source) séparent l'emblème (soleil et livre) du nom et du slogan.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

RACINE = Path(__file__).resolve().parent.parent
SOURCE = RACINE / "design" / "logo-yelenova.png"
IMG = RACINE / "static" / "img"

ZONE_LOGO_COMPLET = (40, 110, 1210, 1070)  # emblème, nom YELENOVA et slogan (sans le filet décoratif du bas)
ZONE_EMBLEME = (118, 112, 1138, 818)  # le soleil et le livre seuls
BLANC = (255, 255, 255)


def fond_blanchi(image: Image.Image) -> Image.Image:
    """Les pixels très clairs (le fond) deviennent blancs ; une rampe de 225 à 245 évite tout liseré."""
    pixels = np.asarray(image.convert("RGB"), dtype=np.float64)
    clarte = pixels.min(axis=2)
    poids = np.clip((clarte - 225.0) / 20.0, 0.0, 1.0)[..., None]
    return Image.fromarray((pixels * (1.0 - poids) + 255.0 * poids).round().astype(np.uint8), "RGB")


def a_la_largeur(image: Image.Image, largeur: int) -> Image.Image:
    return image.resize((largeur, round(image.height * largeur / image.width)), Image.LANCZOS)


def sur_toile(image: Image.Image, cote: int, fraction_largeur: float) -> Image.Image:
    """Image centrée sur une toile carrée blanche ; elle occupe `fraction_largeur` de la largeur (ou de la hauteur si elle est plus haute)."""
    toile = Image.new("RGB", (cote, cote), BLANC)
    largeur = max(1, round(cote * fraction_largeur))
    hauteur = max(1, round(image.height * largeur / image.width))
    if hauteur > cote * fraction_largeur:
        hauteur = max(1, round(cote * fraction_largeur))
        largeur = max(1, round(image.width * hauteur / image.height))
    toile.paste(image.resize((largeur, hauteur), Image.LANCZOS), ((cote - largeur) // 2, (cote - hauteur) // 2))
    return toile


def main(sortie: Path = IMG):
    icones = sortie / "icons"
    icones.mkdir(parents=True, exist_ok=True)
    source = fond_blanchi(Image.open(SOURCE))
    complet = source.crop(ZONE_LOGO_COMPLET)
    embleme = source.crop(ZONE_EMBLEME)

    # Interface : le logo complet (connexion, accueil) et l'emblème seul (barre latérale, pages légales, annuaire).
    a_la_largeur(complet, 720).save(sortie / "logo-yelenova.png", optimize=True)
    a_la_largeur(embleme, 480).save(sortie / "logo-yelenova-embleme.png", optimize=True)

    # Application installable : l'emblème sur fond blanc ; l'icône « maskable » reste dans la zone visible quand le téléphone la découpe en
    # rond (zone de sécurité de 80 % : la demi-diagonale de l'emblème doit tenir dans un cercle de 40 % du côté).
    sur_toile(embleme, 512, 0.92).save(icones / "icone-512.png", optimize=True)
    sur_toile(embleme, 192, 0.92).save(icones / "icone-192.png", optimize=True)
    sur_toile(embleme, 512, 0.62).save(icones / "icone-maskable-512.png", optimize=True)
    sur_toile(embleme, 180, 0.94).save(icones / "icone-apple-touch.png", optimize=True)

    # Onglet du navigateur.
    sur_toile(embleme, 32, 0.98).save(sortie / "favicon-32.png", optimize=True)
    sur_toile(embleme, 256, 0.98).save(sortie / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])

    print("Images générées dans", sortie)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else IMG)
