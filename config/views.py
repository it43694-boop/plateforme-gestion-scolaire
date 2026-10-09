from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.templatetags.static import static


def sante(request):
    """
    Endpoint de supervision (load balancer / uptime monitor externe), sans
    authentification puisqu'un load balancer ne peut pas se connecter. Ne
    renvoie qu'un état booléen par dépendance, jamais de détail d'erreur.
    """
    etat = {"base_de_donnees": False, "cache": False}

    try:
        with connection.cursor() as curseur:
            curseur.execute("SELECT 1")
        etat["base_de_donnees"] = True
    except Exception:
        pass

    try:
        cache.set("verification_sante", "1", timeout=5)
        etat["cache"] = cache.get("verification_sante") == "1"
    except Exception:
        pass

    ok = all(etat.values())
    return JsonResponse({"ok": ok, **etat}, status=200 if ok else 503)


def manifeste_pwa(request):
    """
    Manifeste PWA généré dynamiquement : le nom affiché sur l'écran d'accueil
    du téléphone est celui de l'établissement de l'utilisateur connecté (même
    logique que le reste de l'application - voir templates/base.html), avec
    un repli générique pour un visiteur non connecté. L'icône reste la même
    pour tous les établissements, comme le favicon existant.
    """
    if request.user.is_authenticated and getattr(request.user, "etablissement", None):
        nom = request.user.etablissement.nom
    else:
        nom = settings.NOM_PLATEFORME

    limite = 15
    if len(nom) <= limite:
        nom_court = nom
    else:
        tronque = nom[:limite]
        dernier_espace = tronque.rfind(" ")
        nom_court = tronque[:dernier_espace] if dernier_espace > 0 else tronque

    manifeste = {
        "name": nom,
        "short_name": nom_court,
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#F1F2F4",
        "theme_color": "#12203D",
        "lang": "fr",
        "icons": [
            {"src": static("img/icons/icone-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": static("img/icons/icone-512.png"), "sizes": "512x512", "type": "image/png"},
            {
                "src": static("img/icons/icone-maskable-512.png"), "sizes": "512x512",
                "type": "image/png", "purpose": "maskable",
            },
        ],
    }
    return JsonResponse(manifeste, content_type="application/manifest+json")


def service_worker(request):
    """
    Servi à la racine (/sw.js, pas /static/sw.js) pour que la portée par
    défaut du service worker couvre toute l'application et pas seulement
    /static/ - condition nécessaire pour que le navigateur considère
    l'application comme installable.
    """
    chemin = Path(settings.BASE_DIR) / "static" / "js" / "sw.js"
    return HttpResponse(chemin.read_text(encoding="utf-8"), content_type="application/javascript")
