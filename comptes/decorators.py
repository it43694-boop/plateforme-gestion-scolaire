from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def role_requis(*roles_autorises):
    """Restreint une vue à une liste de rôles précis (ex. validation de comptes)."""
    def decorateur(vue):
        @login_required
        @wraps(vue)
        def enveloppe(request, *args, **kwargs):
            if request.user.role not in [r.value if hasattr(r, "value") else r for r in roles_autorises]:
                raise PermissionDenied("Votre rôle ne permet pas d'accéder à cette page.")
            return vue(request, *args, **kwargs)
        return enveloppe
    return decorateur


def module_requis(module):
    """Restreint une vue selon la matrice de permissions pour le rôle courant."""
    def decorateur(vue):
        @login_required
        @wraps(vue)
        def enveloppe(request, *args, **kwargs):
            from permissions_matrix.models import PermissionMatrix
            module_valeur = module.value if hasattr(module, "value") else module
            if not PermissionMatrix.a_acces(request.user.role, module_valeur, etablissement=request.user.etablissement):
                raise PermissionDenied("Votre rôle n'a pas accès à ce module.")
            return vue(request, *args, **kwargs)
        return enveloppe
    return decorateur
