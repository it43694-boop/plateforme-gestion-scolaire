import secrets

from django.conf import settings
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


class ForcerActivation2FAMiddleware:
    """
    Rend l'authentification à deux facteurs obligatoire (pas seulement
    recommandée) pour les rôles de ROLES_2FA_OBLIGATOIRE (comptes.roles) :
    un mot de passe seul ne doit plus suffire à agir sur ces comptes-là.

    Ne bloque jamais complètement l'accès - seule la page d'activation, la
    déconnexion et la supervision technique restent joignables tant que la
    2FA n'est pas activée, pour qu'il n'y ait aucun risque de verrouillage
    définitif : la personne peut toujours se déconnecter ou terminer
    l'activation, jamais rester coincée sans issue.
    """

    CHEMINS_EXEMPTES = {"/comptes/2fa/activer/", "/comptes/deconnexion/", "/healthz"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.TESTING:
            return self.get_response(request)

        from comptes.roles import ROLES_2FA_OBLIGATOIRE

        user = getattr(request, "user", None)
        if (
            user is not None
            and getattr(user, "is_authenticated", False)
            and user.role in {r.value for r in ROLES_2FA_OBLIGATOIRE}
            and not user.deux_facteurs_actif
            and request.path not in self.CHEMINS_EXEMPTES
        ):
            messages.warning(
                request,
                "Votre rôle exige l'activation de l'authentification à deux facteurs avant de continuer.",
            )
            return redirect(reverse("comptes:activer_2fa"))
        return self.get_response(request)


def est_proprietaire_sans_etablissement(utilisateur) -> bool:
    """
    Le propriétaire de la plateforme : superutilisateur rattaché à aucun
    établissement. Il gère les écoles depuis l'espace Plateforme, mais n'a
    aucune école « à lui » - les pages métier (élèves, finances...) n'ont donc
    rien à lui montrer, sauf d'éventuelles lignes orphelines sans établissement.
    """
    return bool(
        getattr(utilisateur, "is_authenticated", False)
        and utilisateur.is_superuser and not utilisateur.etablissement_id
    )


class ProprietairePlateformeMiddleware:
    """
    Cloisonne le propriétaire de la plateforme hors des pages métier d'un
    établissement. Sans cela, ses requêtes filtrées par établissement
    deviennent `etablissement IS NULL` : il verrait (et pourrait modifier)
    toute ligne orpheline sans établissement, et créerait des données qui
    n'appartiennent à aucune école.

    Liste blanche (refus par défaut) : une future application métier est donc
    fermée au propriétaire tant qu'on ne l'autorise pas explicitement ici. Les
    pages publiques de vérification de document (`/verifier/`) restent
    ouvertes, comme pour un visiteur anonyme.
    """

    PREFIXES_AUTORISES = (
        "/plateforme/", "/comptes/", "/admin/", "/static/", "/media/", "/e/",
        "/healthz", "/sw.js", "/manifest.webmanifest",
    )
    # /comptes/ regroupe le compte personnel (mot de passe, 2FA, notifications)
    # mais aussi la validation des comptes en attente, propre à une école.
    PREFIXES_REFUSES = ("/comptes/comptes-en-attente/", "/comptes/portail-parent/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        chemin = request.path
        if (
            est_proprietaire_sans_etablissement(getattr(request, "user", None))
            and chemin != "/"
            and "/verifier/" not in chemin
            and (not chemin.startswith(self.PREFIXES_AUTORISES) or chemin.startswith(self.PREFIXES_REFUSES))
        ):
            messages.info(
                request,
                "Votre compte propriétaire n'est rattaché à aucun établissement : "
                "utilisez cet espace pour gérer les établissements.",
            )
            return redirect(reverse("espace_plateforme:liste_etablissements"))
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

    style-src ne porte plus 'unsafe-inline' : tous les attributs style=""
    ont été déplacés vers des classes CSS (static/css/toumai.css). Les
    templates PDF (xhtml2pdf) et l'email HTML restent hors de portée de
    cette CSP - ils sont rendus par des moteurs distincts, jamais servis
    au navigateur avec cet en-tête.
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
            "style-src 'self'; "
            "img-src 'self' https: data:; "
            "font-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'"
        )
        return reponse
