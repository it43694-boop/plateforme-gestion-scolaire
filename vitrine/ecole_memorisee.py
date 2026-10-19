"""
L'école d'une personne, retenue pendant un an dans un cookie : à son retour sur l'accueil, elle n'a plus à la chercher dans la liste.

Le cookie ne contient que le nom court (slug) de l'école, rien sur la personne, et ne donne aucun droit : il sert seulement à proposer « Continuer vers
mon école ». Une école suspendue ou inconnue est ignorée.
"""
from django.conf import settings

from etablissement.models import Etablissement

NOM_COOKIE = "yelenova_ecole"
DUREE_COOKIE = 365 * 24 * 3600  # un an : la session, elle, ne dure que 30 minutes


def lire(request):
    """L'école retenue pour ce visiteur (active), ou None."""
    slug = (request.COOKIES.get(NOM_COOKIE) or "")[:100]
    return Etablissement.objects.filter(slug=slug, actif=True).first() if slug else None


def memoriser(reponse, etablissement):
    reponse.set_cookie(
        NOM_COOKIE, etablissement.slug, max_age=DUREE_COOKIE, httponly=True, samesite="Lax", secure=settings.SESSION_COOKIE_SECURE,
    )


def oublier(reponse):
    reponse.delete_cookie(NOM_COOKIE)
