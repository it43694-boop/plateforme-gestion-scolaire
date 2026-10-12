"""Accès à la comptabilité : module « Caisse » de la matrice de permissions, propre à un établissement, écriture réservée."""
from functools import wraps

from django.core.exceptions import PermissionDenied

from comptabilite.services import assurer_plan_comptable
from comptes.decorators import module_requis
from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role
from permissions_matrix.modules import Module

# Qui peut passer, clôturer ou reporter des écritures : la direction et le comptable. Les autres rôles qui ont reçu le module
# « Caisse » dans la matrice (ex. super administrateur) consultent les états sans pouvoir écrire.
ROLES_ECRITURE = {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL} | {Role.COMPTABLE.value}


def peut_ecrire(utilisateur) -> bool:
    return utilisateur.role in ROLES_ECRITURE


def acces_comptabilite(ecriture=False):
    """
    Réserve une vue aux rôles ayant le module Caisse, dans un établissement (jamais le propriétaire de la plateforme sans
    établissement : il verrait des lignes sans établissement). `ecriture=True` : réservée à ceux qui peuvent écrire.
    """
    def decorateur(vue):
        @module_requis(Module.CAISSE)
        @wraps(vue)
        def enveloppe(request, *args, **kwargs):
            if request.user.etablissement_id is None:
                raise PermissionDenied("La comptabilité est propre à un établissement.")
            if ecriture and not peut_ecrire(request.user):
                raise PermissionDenied("Votre rôle peut consulter la comptabilité mais pas y passer d'écritures.")
            assurer_plan_comptable(request.user.etablissement)
            return vue(request, *args, **kwargs)
        return enveloppe
    return decorateur
