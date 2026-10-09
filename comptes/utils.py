import re
from urllib.parse import quote

from django.conf import settings


def lien_whatsapp(telephone, message) -> str:
    """
    Lien wa.me pré-rempli - une alternative sans clé API, sans compte
    prestataire et sans coût à l'envoi automatisé de SMS/WhatsApp (hors de
    portée sans un fournisseur payant, cf. README section Assistant/À
    faire) : la personne connectée ouvre WhatsApp avec le message déjà
    rédigé et clique elle-même sur Envoyer - jamais un envoi silencieux
    déclenché par le serveur.

    Ne devine jamais un indicatif pays manquant : le logiciel reste
    générique (pas propre à un pays), donc un numéro saisi sans indicatif
    part tel quel plutôt que de risquer un mauvais indicatif ajouté à tort.
    """
    if not telephone:
        return ""
    chiffres = re.sub(r"\D", "", telephone)
    if not chiffres:
        return ""
    return f"https://wa.me/{chiffres}?text={quote(message)}"


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


# Mot de passe provisoire remis par l'école : lisible à voix haute et sur papier (pas de
# 0/O, 1/l/I), assez long pour résister à une devinette malgré le verrouillage de compte.
ALPHABET_MOT_DE_PASSE_PROVISOIRE = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
DUREE_MOT_DE_PASSE_PROVISOIRE_HEURES = 72


def generer_mot_de_passe_provisoire() -> str:
    """Mot de passe provisoire aléatoire au format XXXX-XXXX (jamais déduit du matricule ni du nom)."""
    import secrets

    caracteres = [secrets.choice(ALPHABET_MOT_DE_PASSE_PROVISOIRE) for _ in range(8)]
    return "".join(caracteres[:4]) + "-" + "".join(caracteres[4:])
