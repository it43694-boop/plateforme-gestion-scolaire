from django.contrib import admin

from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL
from etablissement.models import Etablissement


@admin.register(Etablissement)
class EtablissementAdmin(admin.ModelAdmin):
    list_display = ["nom", "devise"]
    search_fields = ["nom", "slug"]

    def has_module_permission(self, request):
        return request.user.role in {role.value for role in ROLES_ACCES_TOTAL_INCONDITIONNEL}

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if self.has_module_permission(request):
            return queryset
        return queryset.filter(pk=request.user.etablissement_id)

    def has_add_permission(self, request):
        # Singleton : pas de création si un enregistrement existe déjà.
        return not Etablissement.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
