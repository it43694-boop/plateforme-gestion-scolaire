"""
Génère toutes les images de l'identité Nexora à partir du logo source (design/logo-nexora.png) :
logo à fond transparent, favicon, icônes de l'application installable (PWA) et icône iPhone.

À relancer si le logo change :
    python design/generer_identite_visuelle.py

Le logo source est un aplat sur fond blanc (deux couleurs : bleu marine et turquoise). Le fond
blanc est retiré en calculant, pour chaque pixel, la couleur d'origine et son opacité : les bords
restent nets et propres sur n'importe quel fond, clair ou sombre (pas de liseré blanc).
"""
from pathlib import Path

import numpy as np
from PIL import Image

RACINE = Path(__file__).resolve().parent.parent
SOURCE = RACINE / "design" / "logo-nexora.png"
IMG = RACINE / "static" / "img"
ICONES = IMG / "icons"

BLANC = np.array([255.0, 255.0, 255.0])


def logo_transparent() -> Image.Image:
    """Logo recadré, fond blanc remplacé par de la transparence."""
    pixels = np.asarray(Image.open(SOURCE).convert("RGB"), dtype=np.float64)

    # Les deux couleurs pleines du logo : les plus fréquentes parmi les pixels bien colorés.
    colores = pixels[(255 - pixels.min(axis=2)) > 120]
    # Le vert distingue les deux couleurs : faible dans le bleu marine, élevé dans le turquoise.
    est_turquoise = colores[:, 1] > 110
    marine = np.median(colores[~est_turquoise], axis=0)
    turquoise = np.median(colores[est_turquoise], axis=0)
    print("Couleurs détectées - marine :", marine.round(), "turquoise :", turquoise.round())

    sortie_rgb = np.zeros_like(pixels)
    sortie_alpha = np.zeros(pixels.shape[:2])
    meilleure_erreur = np.full(pixels.shape[:2], np.inf)
    for couleur in (marine, turquoise):
        # pixel = a * couleur + (1 - a) * blanc  ->  a estimé par moindres carrés sur les 3 canaux
        direction = couleur - BLANC
        a = np.clip(((pixels - BLANC) * direction).sum(axis=2) / (direction * direction).sum(), 0.0, 1.0)
        reconstruit = BLANC + a[..., None] * direction
        erreur = ((pixels - reconstruit) ** 2).sum(axis=2)
        mieux = erreur < meilleure_erreur
        meilleure_erreur = np.where(mieux, erreur, meilleure_erreur)
        sortie_alpha = np.where(mieux, a, sortie_alpha)
        sortie_rgb[mieux] = couleur

    # Les pixels quasi blancs deviennent totalement transparents (supprime le bruit de fond).
    sortie_alpha[sortie_alpha < 0.03] = 0.0
    rgba = np.dstack([sortie_rgb, sortie_alpha * 255.0]).round().astype(np.uint8)
    image = Image.fromarray(rgba, "RGBA")
    return image.crop(image.getchannel("A").getbbox())


def sur_toile(logo: Image.Image, cote: int, fraction_hauteur: float, fond=None) -> Image.Image:
    """Logo centré sur une toile carrée ; fond=None -> transparent."""
    toile = Image.new("RGBA", (cote, cote), fond or (0, 0, 0, 0))
    hauteur = max(1, round(cote * fraction_hauteur))
    largeur = max(1, round(logo.width * hauteur / logo.height))
    if largeur > cote:  # logo plus large que la toile : on limite par la largeur
        largeur = round(cote * fraction_hauteur)
        hauteur = round(logo.height * largeur / logo.width)
    redimensionne = logo.resize((largeur, hauteur), Image.LANCZOS)
    toile.alpha_composite(redimensionne, ((cote - largeur) // 2, (cote - hauteur) // 2))
    return toile


def main():
    ICONES.mkdir(parents=True, exist_ok=True)
    logo = logo_transparent()
    blanc = (255, 255, 255, 255)

    # Logo de l'interface (barre latérale, connexion, accueil) : transparent, haute définition.
    hauteur = 320
    logo.resize((round(logo.width * hauteur / logo.height), hauteur), Image.LANCZOS).save(
        IMG / "logo-nexora.png", optimize=True,
    )

    # Application installable : fond blanc plein, le logo reste dans la zone visible même quand
    # le téléphone découpe l'icône en rond (« maskable » : zone de sécurité de 80 %).
    sur_toile(logo, 512, 0.74, blanc).convert("RGB").save(ICONES / "icone-512.png", optimize=True)
    sur_toile(logo, 192, 0.74, blanc).convert("RGB").save(ICONES / "icone-192.png", optimize=True)
    sur_toile(logo, 512, 0.56, blanc).convert("RGB").save(ICONES / "icone-maskable-512.png", optimize=True)
    sur_toile(logo, 180, 0.78, blanc).convert("RGB").save(ICONES / "icone-apple-touch.png", optimize=True)

    # Onglet du navigateur : fond transparent, logo au maximum de la place.
    sur_toile(logo, 32, 0.96).save(IMG / "favicon-32.png", optimize=True)
    sur_toile(logo, 256, 0.96).save(IMG / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])

    print("Images générées dans", IMG)


if __name__ == "__main__":
    main()
