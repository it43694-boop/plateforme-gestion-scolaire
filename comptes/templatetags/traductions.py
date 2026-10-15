"""Textes écrits par le JavaScript (static/js/app.js), fournis dans la langue de la page : {% textes_js %}."""
from django import template
from django.utils import translation
from django.utils.html import json_script

from comptes.traduction import catalogue_pour

register = template.Library()

# Chaque texte que app.js affiche lui-même (la fonction t() de app.js les cherche ici ; en français le bloc est vide).
TEXTES_JS = (
    "Copié", "Aucun résultat.", "Solde de congés payés actuel :", "jour(s).",
    "Votre session a expiré : reconnectez-vous pour synchroniser", "saisie(s) en attente.",
    "saisie(s) en attente de synchronisation (hors-ligne).", "Synchroniser maintenant",
    "Une erreur est survenue, la saisie n'a pas été enregistrée.", "Mode clair", "Mode sombre",
    "Afficher le mot de passe", "Masquer le mot de passe",
)


@register.simple_tag
def textes_js():
    catalogue = catalogue_pour((translation.get_language() or "fr")[:2])
    return json_script({texte: traduit for texte in TEXTES_JS if (traduit := catalogue.traduire(texte))}, "textes-js")
