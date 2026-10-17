"""
Langue de chaque requête (LangueMiddleware) et traduction de la page produite (TraductionMiddleware).

Ordre de choix de la langue : le compte connecté (Utilisateur.langue), sinon le cookie du visiteur, sinon la langue par défaut de
l'école (Etablissement.langue_par_defaut : celle du compte connecté, ou celle choisie sur la page de connexion), sinon le français.
La langue est activée pour Django (formats de date, messages de validation intégrés, sens de lecture) ; la traduction des textes de
l'application, elle, est faite sur le HTML produit (voir comptes.traduction).
"""
from django.utils import translation

from comptes.langues import CODES_LANGUES, LANGUE_PAR_DEFAUT, NOM_COOKIE_LANGUE
from comptes.arabisation import chiffres_ascii, finaliser_arabe, localisateur_pour
from comptes.traduction import catalogue_pour, traduire_html


def texte_pour_langue(request, texte):
    """
    Un texte destiné à une réponse qui n'est pas une page HTML (liste de résultats d'une recherche, message d'un enregistrement en JavaScript) :
    en arabe, les noms de l'école, les mots du catalogue et les chiffres sont écrits en arabe, comme dans les pages. Le français ne change pas.
    """
    if not isinstance(texte, str) or getattr(request, "LANGUAGE_CODE", LANGUE_PAR_DEFAUT) != "ar":
        return texte
    original = localisateur_pour(request).remplacer(texte)
    traduction = catalogue_pour("ar").traduire(original)
    return finaliser_arabe(traduction if traduction is not None else original)


def texte_en_langue(texte, langue, etablissement_id=None):
    """
    Un texte écrit en dehors d'une page (courriel, message pré-écrit) pour quelqu'un dont la langue est `langue` : en arabe, ligne par ligne, les
    noms de l'école (`etablissement_id`), les phrases du catalogue et les chiffres sont en arabe. Le français ne change pas.
    """
    if langue != "ar" or not isinstance(texte, str) or not texte.strip():
        return texte
    from comptes.arabisation import Localisateur, index_pour

    index = index_pour(etablissement_id if etablissement_id is not None else "public")
    localisateur = Localisateur(index["cles"], index["formes"])
    catalogue = catalogue_pour("ar")
    lignes = []
    for ligne in texte.split("\n"):
        if not ligne.strip():
            lignes.append(ligne)
            continue
        original = localisateur.remplacer(ligne)
        traduction = catalogue.traduire(original)
        lignes.append(finaliser_arabe(traduction if traduction is not None else original))
    return "\n".join(lignes)


def langue_du_compte(utilisateur, repli=None) -> str:
    """La langue d'un compte (choisie avec le bouton de langue), sinon celle par défaut de son école, sinon `repli`, sinon le français."""
    if utilisateur is not None:
        if getattr(utilisateur, "langue", "") in CODES_LANGUES:
            return utilisateur.langue
        etablissement = getattr(utilisateur, "etablissement", None)
        if etablissement is not None and etablissement.langue_par_defaut in CODES_LANGUES:
            return etablissement.langue_par_defaut
    return repli if repli in CODES_LANGUES else LANGUE_PAR_DEFAUT


def donnees_pour_langue(request, donnees):
    """`texte_pour_langue` appliqué à toutes les chaînes d'une structure JSON (dictionnaires, listes), en laissant les clés intactes."""
    if isinstance(donnees, dict):
        return {cle: donnees_pour_langue(request, valeur) for cle, valeur in donnees.items()}
    if isinstance(donnees, (list, tuple)):
        return [donnees_pour_langue(request, valeur) for valeur in donnees]
    return texte_pour_langue(request, donnees)


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


class ChiffresOccidentauxMiddleware:
    """
    Ce qu'on tape avec des chiffres arabes (٠١٢٣...) arrive au reste de l'application en 0123... : montants, dates, téléphones, matricules et
    recherches se comprennent de la même façon dans les deux langues. Les mots de passe sont laissés tels quels (ils doivent correspondre
    exactement à ce qui a été choisi), de même que le jeton CSRF.
    """

    CHAMPS_INTOUCHABLES = ("password", "mot_de_passe", "mdp", "csrfmiddlewaretoken")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method in ("POST", "PUT", "PATCH") and request.content_type in ("application/x-www-form-urlencoded", "multipart/form-data"):
            request.POST = self._convertir(request.POST)
        if request.GET:
            request.GET = self._convertir(request.GET)
        return self.get_response(request)

    def _convertir(self, donnees):
        if not any(chiffres_ascii(valeur) != valeur for _, valeurs in donnees.lists() for valeur in valeurs):
            return donnees
        copie = donnees.copy()  # QueryDict modifiable
        for cle, valeurs in donnees.lists():
            if not any(mot in cle.lower() for mot in self.CHAMPS_INTOUCHABLES):
                copie.setlist(cle, [chiffres_ascii(valeur) for valeur in valeurs])
        copie._mutable = False
        return copie


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
        arabe = langue == "ar"  # arabe « pur » : noms de l'école et chiffres en arabe aussi
        reponse.content = traduire_html(
            contenu, catalogue, localisateur=localisateur_pour(request) if arabe else None, chiffres=finaliser_arabe if arabe else None,
        ).encode(jeu)
        if reponse.has_header("Content-Length"):
            reponse["Content-Length"] = str(len(reponse.content))
        return reponse
