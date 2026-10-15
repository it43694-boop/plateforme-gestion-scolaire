"""
Langue de chaque requête (LangueMiddleware) et traduction de la page produite (TraductionMiddleware).

Ordre de choix de la langue : le compte connecté (Utilisateur.langue), sinon le cookie du visiteur, sinon la langue par défaut de
l'école (Etablissement.langue_par_defaut : celle du compte connecté, ou celle choisie sur la page de connexion), sinon le français.
La langue est activée pour Django (formats de date, messages de validation intégrés, sens de lecture) ; la traduction des textes de
l'application, elle, est faite sur le HTML produit (voir comptes.traduction).
"""
from django.utils import translation

from comptes.langues import CODES_LANGUES, LANGUE_PAR_DEFAUT, NOM_COOKIE_LANGUE
from comptes.traduction import catalogue_pour, traduire_html


def langue_de_la_requete(request) -> str:
    utilisateur = getattr(request, "user", None)
    est_connecte = utilisateur is not None and getattr(utilisateur, "is_authenticated", False)
    if est_connecte and getattr(utilisateur, "langue", "") in CODES_LANGUES:
        return utilisateur.langue
    choix = request.COOKIES.get(NOM_COOKIE_LANGUE)
    if choix in CODES_LANGUES:
        return choix
    if est_connecte:
        etablissement = getattr(utilisateur, "etablissement", None)
        if etablissement is not None and etablissement.langue_par_defaut in CODES_LANGUES:
            return etablissement.langue_par_defaut
        return LANGUE_PAR_DEFAUT
    etablissement_id = request.session.get("etablissement_id") if hasattr(request, "session") else None
    if etablissement_id:
        from etablissement.models import Etablissement

        langue = Etablissement.objects.filter(pk=etablissement_id).values_list("langue_par_defaut", flat=True).first()
        if langue in CODES_LANGUES:
            return langue
    return LANGUE_PAR_DEFAUT


class LangueMiddleware:
    """Active la langue de la requête (après l'authentification : elle dépend du compte)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        langue = langue_de_la_requete(request)
        translation.activate(langue)
        request.LANGUAGE_CODE = langue
        try:
            reponse = self.get_response(request)
        finally:
            translation.deactivate()
        if "Content-Language" not in reponse:
            reponse["Content-Language"] = langue
        return reponse


class TraductionMiddleware:
    """
    Traduit le HTML d'une page quand la langue n'est pas le français. À placer juste après LangueMiddleware (il lit
    request.LANGUAGE_CODE). Ne touche ni aux PDF, ni aux fichiers, ni au JSON, ni aux réponses en flux.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        reponse = self.get_response(request)
        langue = getattr(request, "LANGUAGE_CODE", LANGUE_PAR_DEFAUT)
        if langue == LANGUE_PAR_DEFAUT or getattr(reponse, "streaming", False):
            return reponse
        if "text/html" not in reponse.get("Content-Type", ""):
            return reponse
        catalogue = catalogue_pour(langue)
        if not len(catalogue):
            return reponse
        jeu = reponse.charset or "utf-8"
        try:
            contenu = reponse.content.decode(jeu)
        except (UnicodeDecodeError, LookupError):
            return reponse
        reponse.content = traduire_html(contenu, catalogue).encode(jeu)
        if reponse.has_header("Content-Length"):
            reponse["Content-Length"] = str(len(reponse.content))
        return reponse
