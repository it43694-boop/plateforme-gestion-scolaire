import secrets

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse


class AxesLikeLockoutMiddleware:
    """
    Filet de sécurité supplémentaire : si un utilisateur authentifié se
    retrouve avec un compte verrouillé (concurrence entre onglets, session
    encore active après un verrouillage déclenché ailleurs), on le déconnecte
    immédiatement plutôt que de le laisser naviguer.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            if hasattr(user, "verrouille") and user.verrouille():
                from django.contrib.auth import logout
                logout(request)
                messages.error(
                    request,
                    "Votre compte a été temporairement verrouillé suite à plusieurs "
                    "tentatives de connexion échouées. Réessayez plus tard.",
                )
                return redirect(reverse("comptes:connexion"))
        return self.get_response(request)


class ContentSecurityPolicyMiddleware:
    """
    Défense en profondeur contre l'injection de script (XSS) : seuls les
    scripts de même origine ou portant le nonce généré pour cette requête
    s'exécutent - un script injecté par un champ mal échappé ne le porte pas.

    L'admin Django est exclu : ses widgets embarquent des scripts internes au
    framework qui n'ont pas été audités ici pour la compatibilité avec un
    nonce, et l'admin est un périmètre de confiance différent (accès déjà
    réservé aux comptes autorisés) - le restreindre sans vérification
    reviendrait à risquer de casser des fonctionnalités du framework.

    style-src reste en 'unsafe-inline' : de nombreux gabarits utilisent des
    attributs style="" ; les retirer un par un est un chantier séparé, sans
    lien avec la protection contre l'injection de script (le vecteur XSS le
    plus dangereux, seul visé ici).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/admin/"):
            return self.get_response(request)

        request.csp_nonce = secrets.token_urlsafe(16)
        reponse = self.get_response(request)
        reponse["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{request.csp_nonce}'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' https: data:; "
            "font-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'"
        )
        return reponse
