from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import DisallowedHost

from vitrine import ecole_memorisee


class MemoriserEcoleMiddleware:
    """
    Après chaque connexion, retient l'école de la personne (cookie d'un an, voir ecole_memorisee). La session garde en mémoire l'école déjà retenue :
    l'école n'est relue, et le cookie réécrit, que si elle change (première connexion, changement d'école).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        reponse = self.get_response(request)
        utilisateur = getattr(request, "user", None)
        if utilisateur is not None and utilisateur.is_authenticated and utilisateur.etablissement_id:
            if request.session.get("ecole_memorisee_id") != utilisateur.etablissement_id:
                etablissement = utilisateur.etablissement
                if etablissement is not None and etablissement.actif:
                    ecole_memorisee.memoriser(reponse, etablissement)
                    request.session["ecole_memorisee_id"] = utilisateur.etablissement_id
        return reponse


class AdresseSecondaireNonIndexeeMiddleware:
    """
    Le site répond aussi à l'adresse de l'hébergeur (onrender.com), que des cartes imprimées ou des signets peuvent encore utiliser : on ne la ferme
    pas. Mais Google y verrait une copie du site. Toute réponse faite à une autre adresse que l'adresse publique (URL_PUBLIQUE, avec ou sans « www »)
    porte donc « X-Robots-Tag: noindex » : les moteurs de recherche ne la retiennent pas, seule l'adresse publique est référencée.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        reponse = self.get_response(request)
        principal = (urlsplit(settings.URL_PUBLIQUE).hostname or "").lower()
        try:
            hote = request.get_host().split(":")[0].lower()
        except DisallowedHost:
            return reponse
        if hote not in (principal, "www." + principal):
            reponse["X-Robots-Tag"] = "noindex"
        return reponse
