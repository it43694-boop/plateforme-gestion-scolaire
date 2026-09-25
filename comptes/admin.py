from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from comptes.models import CodeVerificationEmail, EmailOutbox, JournalAudit, Notification, Utilisateur
from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL


class EtablissementAdminMixin:
    """Cloisonne les objets métier dans l'admin selon l'établissement."""

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.role in {role.value for role in ROLES_ACCES_TOTAL_INCONDITIONNEL}:
            return queryset
        if not request.user.etablissement_id:
            return queryset.none()
        field_names = {field.name for field in queryset.model._meta.fields}
        if "etablissement" in field_names:
            return queryset.filter(etablissement_id=request.user.etablissement_id)
        if "classe" in field_names:
            return queryset.filter(classe__annee_scolaire__etablissement_id=request.user.etablissement_id)
        if "affectation" in field_names:
            return queryset.filter(affectation__classe__annee_scolaire__etablissement_id=request.user.etablissement_id)
        if "eleve" in field_names:
            return queryset.filter(eleve__etablissement_id=request.user.etablissement_id)
        if "utilisateur" in field_names:
            return queryset.filter(utilisateur__etablissement_id=request.user.etablissement_id)
        return queryset.none()

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff

    def save_model(self, request, obj, form, change):
        if not change and hasattr(obj, "etablissement_id") and request.user.role not in {
            role.value for role in ROLES_ACCES_TOTAL_INCONDITIONNEL
        }:
            obj.etablissement_id = request.user.etablissement_id
        super().save_model(request, obj, form, change)

    def has_change_permission(self, request, obj=None):
        if not super().has_change_permission(request, obj):
            return False
        return obj is None or self.get_queryset(request).filter(pk=obj.pk).exists()

    def has_delete_permission(self, request, obj=None):
        if not super().has_delete_permission(request, obj):
            return False
        return obj is None or self.get_queryset(request).filter(pk=obj.pk).exists()


@admin.register(Utilisateur)
class UtilisateurAdmin(EtablissementAdminMixin, DjangoUserAdmin):
    model = Utilisateur
    ordering = ["nom", "prenom"]
    list_display = [
        "email", "prenom", "nom", "role", "statut", "email_verifie",
        "is_active", "matricule",
    ]
    list_filter = ["role", "statut", "email_verifie", "is_active"]
    search_fields = ["email", "prenom", "nom", "matricule", "telephone"]
    filter_horizontal = ["parents_lies", "groups", "user_permissions"]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Identité", {"fields": ("prenom", "nom", "telephone", "profession", "date_naissance")}),
        ("Rôle et statut", {"fields": ("role", "statut", "matricule", "parents_lies")}),
        ("Vérification et sécurité", {
            "fields": (
                "email_verifie", "tentatives_connexion_echouees", "verrouille_jusqu_a",
            ),
        }),
        ("Accès", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_creation", "derniere_modification")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "prenom", "nom", "role", "password1", "password2"),
        }),
    )
    readonly_fields = ["date_creation", "derniere_modification", "last_login"]

    def get_queryset(self, request):
        queryset = admin.ModelAdmin.get_queryset(self, request)
        if request.user.role in {role.value for role in ROLES_ACCES_TOTAL_INCONDITIONNEL}:
            return queryset
        return queryset.filter(etablissement_id=request.user.etablissement_id)


@admin.register(CodeVerificationEmail)
class CodeVerificationEmailAdmin(EtablissementAdminMixin, admin.ModelAdmin):
    list_display = ["utilisateur", "code", "cree_le", "expire_le", "utilise"]
    list_filter = ["utilise"]
    search_fields = ["utilisateur__email"]
    readonly_fields = [f.name for f in CodeVerificationEmail._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(JournalAudit)
class JournalAuditAdmin(EtablissementAdminMixin, admin.ModelAdmin):
    list_display = ["horodatage", "acteur", "action", "cible", "adresse_ip"]
    list_filter = ["action"]
    search_fields = ["acteur__email", "action", "cible"]
    readonly_fields = [f.name for f in JournalAudit._meta.fields]
    date_hierarchy = "horodatage"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # Journal en ajout seul, y compris pour les superutilisateurs.
        return False


@admin.register(Notification)
class NotificationAdmin(EtablissementAdminMixin, admin.ModelAdmin):
    list_display = ["destinataire", "titre", "lue_le", "cree_le"]
    list_filter = ["lue_le", "cree_le"]
    search_fields = ["destinataire__email", "destinataire__nom", "titre", "message"]
    readonly_fields = ["cree_le"]


@admin.register(EmailOutbox)
class EmailOutboxAdmin(admin.ModelAdmin):
    list_display = ["sujet", "destinataires", "tentatives", "prochaine_tentative", "envoye_le"]
    list_filter = ["envoye_le", "tentatives"]
    search_fields = ["sujet", "expediteur"]
    readonly_fields = [field.name for field in EmailOutbox._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
