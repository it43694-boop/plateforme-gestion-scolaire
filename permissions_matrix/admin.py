from django.contrib import admin

from comptes.audit import enregistrer_action
from comptes.admin import EtablissementAdminMixin
from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL
from permissions_matrix.models import PermissionMatrix


@admin.register(PermissionMatrix)
class PermissionMatrixAdmin(EtablissementAdminMixin, admin.ModelAdmin):
    """
    Administration technique de la matrice. Une interface dédiée, plus
    ergonomique (tableau croisé rôle x module en une page), sera construite
    dans la phase « Espace développeur » ; cette vue admin suffit pour le
    socle et reste pleinement fonctionnelle en attendant.
    """

    list_display = ["role", "module", "autorise", "modifie_le", "modifie_par"]
    list_filter = ["role", "module", "autorise"]
    list_editable = ["autorise"]
    search_fields = ["role", "module"]

    def has_module_permission(self, request):
        return request.user.role in {role.value for role in ROLES_ACCES_TOTAL_INCONDITIONNEL}

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.modifie_par = request.user
        super().save_model(request, obj, form, change)
        enregistrer_action(
            acteur=request.user,
            action="modification_matrice_permissions",
            cible=f"{obj.role} / {obj.module}",
            details={"autorise": obj.autorise},
            request=request,
        )
