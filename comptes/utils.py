from django.conf import settings


def ip_client_fiable(request) -> str:
    """
    Adresse IP réelle du client, à travers le(s) proxy(s) de confiance placés
    devant l'application (ex. le routeur de la plateforme d'hébergement).

    Le premier champ de X-Forwarded-For est fourni par le client lui-même et
    donc falsifiable à volonté (un simple en-tête HTTP) : s'y fier permettrait
    de contourner le verrouillage anti-brute-force et de fausser l'adresse IP
    inscrite au journal d'audit. Seuls les champs ajoutés par nos propres
    proxys de confiance, en partant de la droite, sont fiables.

    NB_PROXYS_CONFIANCE (paramètre, défaut 1) doit correspondre exactement au
    nombre de sauts de confiance entre le client et Django (ex. 1 pour Render
    seul, 2 si un CDN comme Cloudflare est ajouté devant Render).
    """
    entete = request.META.get("HTTP_X_FORWARDED_FOR", "")
    sauts = [ip.strip() for ip in entete.split(",") if ip.strip()]
    nb_proxys_confiance = getattr(settings, "NB_PROXYS_CONFIANCE", 1)

    if sauts and nb_proxys_confiance > 0:
        index = max(len(sauts) - nb_proxys_confiance, 0)
        return sauts[index]

    return request.META.get("REMOTE_ADDR", "")
