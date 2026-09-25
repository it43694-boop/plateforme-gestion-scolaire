from django.contrib import admin

from comptes.admin import EtablissementAdminMixin
from pedagogie.models import Absence, CreneauEmploiDuTemps, Note, NoteHistorique, PresencePersonnel, VerificationBulletin


@admin.register(Note)
class NoteAdmin(EtablissementAdminMixin, admin.ModelAdmin):
    list_display = ["eleve", "affectation", "trimestre", "valeur", "modifie_le"]
    list_filter = ["trimestre", "affectation__classe"]
    search_fields = ["eleve__nom", "eleve__prenom", "eleve__matricule"]
    autocomplete_fields = ["eleve", "affectation"]


@admin.register(Absence)
class AbsenceAdmin(EtablissementAdminMixin, admin.ModelAdmin):
    list_display = ["eleve", "classe", "date_absence", "justifiee"]
    list_filter = ["justifiee", "classe__annee_scolaire", "classe__cycle"]
    search_fields = ["eleve__nom", "eleve__prenom", "eleve__matricule"]
    autocomplete_fields = ["eleve", "classe"]

    def get_queryset(self, request):
        from scolarite.models import classes_visibles_pour
        return super().get_queryset(request).filter(classe__in=classes_visibles_pour(request.user))


@admin.register(CreneauEmploiDuTemps)
class CreneauEmploiDuTempsAdmin(EtablissementAdminMixin, admin.ModelAdmin):
    list_display = ["classe", "jour_semaine", "heure_debut", "heure_fin", "affectation", "salle"]
    list_filter = ["jour_semaine", "classe"]
    autocomplete_fields = ["classe", "affectation"]


@admin.register(PresencePersonnel)
class PresencePersonnelAdmin(EtablissementAdminMixin, admin.ModelAdmin):
    list_display = ["employe", "date", "statut", "heure_arrivee", "heure_depart", "saisi_par"]
    list_filter = ["statut", "date"]
    search_fields = ["employe__nom", "employe__prenom", "employe__email"]
    autocomplete_fields = ["employe", "saisi_par"]


@admin.register(NoteHistorique)
class NoteHistoriqueAdmin(EtablissementAdminMixin, admin.ModelAdmin):
    list_display = ["note", "ancienne_valeur", "modifiee_par", "modifiee_le"]
    readonly_fields = [field.name for field in NoteHistorique._meta.fields]
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(VerificationBulletin)
class VerificationBulletinAdmin(EtablissementAdminMixin, admin.ModelAdmin):
    list_display = ["eleve", "inscription", "jeton", "cree_le", "actif"]
    list_filter = ["actif"]
    readonly_fields = [field.name for field in VerificationBulletin._meta.fields]
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
