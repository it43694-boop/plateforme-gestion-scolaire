"""
Aides aux tests de l'arabe pur (jamais importées par l'application) : voir ce qu'un PDF contiendrait en lettres latines, ouvrir une page en arabe.
"""
from unittest import mock

from django.test import Client
from xhtml2pdf import pisa

from comptes.langues import NOM_COOKIE_LANGUE
from comptes.traduction import ADRESSES, LETTRE_OU_CHIFFRE_LATIN, restes_latins


class CaptureHtmlDuPdf:
    """
    Garde le HTML (déjà traduit si la page est en arabe) que `comptes.pdf.creer_pdf` donne au fabricant de PDF, sans changer le PDF produit.

        with CaptureHtmlDuPdf() as capture:
            client.get(adresse_du_pdf)
        capture.restes_latins()   # les textes qui ne sont pas en arabe pur
    """

    def __init__(self):
        self.pages = []
        self._reel = pisa.CreatePDF

    def __enter__(self):
        def espion(html, *args, **kwargs):
            self.pages.append(html)
            return self._reel(html, *args, **kwargs)

        self._patch = mock.patch("comptes.pdf.pisa.CreatePDF", side_effect=espion)
        self._patch.start()
        return self

    def __exit__(self, *exception):
        self._patch.stop()

    @property
    def html(self):
        return "\n".join(self.pages)

    def restes_latins(self):
        return restes_latins(self.html)


def client_en(compte, langue):
    """Un client connecté dont la langue est `langue` (cookie de langue)."""
    client = Client()
    client.force_login(compte)
    client.cookies[NOM_COOKIE_LANGUE] = langue
    return client
def restes_hors_textes_saisis(contenu: str, saisis=()):
    """
    Les textes d'une page arabe qui contiennent encore du latin, sans ce que l'école a saisi elle-même (nom d'une formule, d'un article...) :
    un texte qui ne doit son latin qu'à ces mots saisis est accepté, tout autre reste est signalé.
    """
    gardes = []
    for texte in restes_latins(contenu):
        reste = texte
        for saisi in saisis:
            reste = reste.replace(saisi, "")
        if LETTRE_OU_CHIFFRE_LATIN.search(ADRESSES.sub("", reste)):
            gardes.append(texte)
    return gardes
