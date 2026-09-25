from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse


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
