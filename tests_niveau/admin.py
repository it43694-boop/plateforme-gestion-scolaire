from django.contrib import admin

from tests_niveau.models import Candidat


@admin.register(Candidat)
class CandidatAdmin(admin.ModelAdmin):
    list_display = ["nom_complet", "classe_visee", "date_test", "note_test", "decision"]
    list_filter = ["decision", "classe_visee__annee_scolaire", "classe_visee__cycle"]
    search_fields = ["nom", "prenom"]
    autocomplete_fields = ["classe_visee"]

    def get_queryset(self, request):
        from scolarite.models import classes_visibles_pour
        return super().get_queryset(request).filter(classe_visee__in=classes_visibles_pour(request.user))
