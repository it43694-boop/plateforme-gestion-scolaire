"""
Fabrication des PDF (reçus, bulletins, attestations, emplois du temps, bulletins de paie, factures).

En arabe, le même document est écrit en arabe : textes du catalogue, noms de l'école, des élèves, des classes, chiffres arabes, de droite à
gauche, avec une police arabe (Amiri, licence SIL OFL : static/fonts/pdf).

Ce que xhtml2pdf ne fait pas tout seul, et que ce module ajoute :
- il retourne les parenthèses mal : on les inverse dans le HTML avant de lui donner la page ;
- il remet un paragraphe dans l'ordre visuel AVANT de couper les lignes : sur plusieurs lignes, la première ligne porte alors la FIN de la phrase.
  On le règle en gardant l'ordre logique jusqu'à la coupure des lignes, puis en remettant chaque ligne dans l'ordre de lecture (voir
  `_installer_ordre_logique`).
"""
import logging
import re
from pathlib import Path

from django.conf import settings
from xhtml2pdf import pisa

from comptes.arabisation import Localisateur, finaliser_arabe, index_pour, localisateur_pour
from comptes.traduction import JETONS, catalogue_pour, traduire_html

logger = logging.getLogger(__name__)
DOSSIER_POLICES = Path(settings.BASE_DIR) / "static" / "fonts" / "pdf"
PARENTHESES = str.maketrans("()[]{}«»", ")(][}{»«")

CSS_ARABE = """
@font-face {{ font-family: Amiri; src: url("{regulier}"); }}
@font-face {{ font-family: Amiri; font-weight: bold; src: url("{gras}"); }}
@font-face {{ font-family: Amiri; font-style: italic; src: url("{regulier}"); }}
@font-face {{ font-family: Amiri; font-weight: bold; font-style: italic; src: url("{gras}"); }}
body, p, div, span, td, th, h1, h2, h3, h4, strong, b, em, i, li, a, small, label {{ font-family: Amiri; }}
body {{ font-size: 13px; direction: rtl; text-align: right; }}
td, th, p, li {{ text-align: right; }}
td.numerique, th.numerique, .numerique {{ text-align: left; }}
"""
BALISE_HTML = re.compile(r"<html\b[^>]*>", re.IGNORECASE)
FIN_DE_STYLE_OU_TETE = re.compile(r"</head>", re.IGNORECASE)
TAILLE_DE_POLICE = re.compile(r"font-size:\s*([\d.]+)(px|pt)", re.IGNORECASE)
AGRANDISSEMENT = 1.18  # la police arabe paraît plus petite que la police latine à taille égale


def _texte_arabe(html: str, localisateur) -> str:
    """Le HTML d'un document dont les textes sont traduits et les parenthèses retournées (hors balises, scripts et styles)."""
    html = traduire_html(html, catalogue_pour("ar"), localisateur=localisateur, chiffres=finaliser_arabe)
    html = html.replace("<bdi>", "").replace("</bdi>", "").replace("⁨", "").replace("⁩", "")
    morceaux = JETONS.split(html)
    for indice in range(0, len(morceaux), 2):  # les indices pairs sont des textes ; les impairs, des balises, scripts, styles, commentaires
        morceaux[indice] = morceaux[indice].translate(PARENTHESES)
    return "".join(morceaux)


def _agrandir(correspondance) -> str:
    return f"font-size: {float(correspondance.group(1)) * AGRANDISSEMENT:.1f}{correspondance.group(2)}"


def html_en_arabe(html: str, localisateur=None) -> str:
    """Le HTML d'un PDF mis en arabe : traduit, de droite à gauche, avec la police arabe."""
    html = _texte_arabe(html, localisateur or Localisateur({}))
    html = TAILLE_DE_POLICE.sub(_agrandir, html)
    css = CSS_ARABE.format(
        regulier=(DOSSIER_POLICES / "Amiri-Regular.ttf").as_posix(), gras=(DOSSIER_POLICES / "Amiri-Bold.ttf").as_posix(),
    )
    html = BALISE_HTML.sub('<html lang="ar" dir="rtl">', html, count=1)
    style = f"<style>{css}</style>"
    if FIN_DE_STYLE_OU_TETE.search(html):
        return FIN_DE_STYLE_OU_TETE.sub(lambda trouve: style + trouve.group(0), html, count=1)
    return style + html


def creer_pdf(html: str, destination, *, request=None, langue=None, etablissement_id=None, link_callback=None):
    """
    Écrit le PDF de `html` dans `destination` et rend le résultat de xhtml2pdf (`.err` vrai en cas d'échec).
    La langue est celle de la page de la personne (`request`) ; sans requête (envoi par courriel), on la donne avec l'établissement.
    """
    langue = langue or getattr(request, "LANGUAGE_CODE", "fr")
    if langue == "ar":
        if request is not None:
            localisateur = localisateur_pour(request)
        elif etablissement_id is not None:
            index = index_pour(etablissement_id)
            localisateur = Localisateur(index["cles"], index["formes"])
        else:
            localisateur = None
        html = html_en_arabe(html, localisateur)
    options = {"link_callback": link_callback} if link_callback else {}
    politique = _politique_de_lecture()
    if politique is not None:
        options["resource_policy"] = politique
    return pisa.CreatePDF(html, dest=destination, encoding="utf-8", **options)


def _politique_de_lecture():
    """
    Les dossiers de l'application que le générateur de PDF peut lire (polices, logos, images) : toujours les mêmes, d'où que le serveur soit
    lancé. Tout le reste du disque, et les adresses internes du réseau, restent interdits (protection de xhtml2pdf).
    """
    try:
        from xhtml2pdf.config.resources import ResourceAccessPolicy
    except ImportError:  # une autre version de xhtml2pdf, sans cette protection
        return None
    racines = [settings.MEDIA_ROOT, settings.STATIC_ROOT, *settings.STATICFILES_DIRS]
    return ResourceAccessPolicy(base_dir=Path(settings.BASE_DIR), extra_roots=tuple(Path(str(racine)) for racine in racines if racine))


def _installer_ordre_logique():
    """
    Un paragraphe de droite à gauche est coupé en lignes dans l'ordre LOGIQUE des mots (la première ligne porte le début de la phrase), puis
    chaque ligne est écrite de droite à gauche. Sans cela, xhtml2pdf coupe un texte déjà retourné : la première ligne porte la fin de la phrase.
    Ne touche que les paragraphes de droite à gauche ; les PDF français sont inchangés.
    """
    try:
        from bidi import get_display
        from xhtml2pdf import context as contexte, reportlab_paragraph as paragraphe, util as utilitaires

        if getattr(paragraphe.Paragraph, "_ordre_logique_installe", False):
            return
        d_origine = contexte.frag_text_language_check
        coupe_d_origine = paragraphe.Paragraph.breakLines
        relier = utilitaires._reshape_for

        def fragment(context, frag_text, font_name=None):
            if getattr(context, "is_rtl", False):
                return relier(frag_text, font_name)  # lettres reliées, ordre logique conservé
            return d_origine(context, frag_text, font_name)

        def visuel(texte):
            """Le texte (chaîne ou octets UTF-8, selon l'endroit où xhtml2pdf l'a rangé) dans l'ordre où il se dessine."""
            if isinstance(texte, bytes):
                return get_display(texte.decode("utf-8"), base_dir="R").encode("utf-8")
            return get_display(texte, base_dir="R")

        def couper(self, width):
            resultat = coupe_d_origine(self, width)
            if getattr(self, "dir", "ltr") != "rtl" or getattr(resultat, "_remis_en_ordre", False):
                return resultat  # (xhtml2pdf rend parfois la mise en page déjà faite d'un paragraphe : on ne la retourne pas deux fois)
            resultat._remis_en_ordre = True
            if getattr(resultat, "kind", None) == 0:
                resultat.lines = [(libre, [visuel(mot) for mot in reversed(mots)]) for libre, mots in resultat.lines]
                return resultat
            for ligne in resultat.lines:
                mots = []
                for morceau in ligne.words:
                    if isinstance(getattr(morceau, "text", None), (str, bytes)):
                        morceau = morceau.clone()  # jamais le fragment d'origine : la mise en page peut se refaire plusieurs fois
                        morceau.text = visuel(morceau.text)
                    mots.append(morceau)
                ligne.words = mots[::-1]
            return resultat

        contexte.frag_text_language_check = fragment
        paragraphe.Paragraph.breakLines = couper
        paragraphe.Paragraph._ordre_logique_installe = True
    except Exception:  # noqa: BLE001 - une autre version de xhtml2pdf : les PDF arabes restent lisibles, seules les lignes longues sont dans l'ordre d'avant
        logger.warning("Ordre logique des paragraphes arabes non installé (version de xhtml2pdf différente).", exc_info=True)


_installer_ordre_logique()
