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
