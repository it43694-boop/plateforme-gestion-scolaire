from django.contrib import admin

from comptes.admin import EtablissementAdminMixin
from scolarite.models import AideScolarite, Affectation, AnneeScolaire, Classe, EcheancierFrais, Inscription, TransfertEleve


@admin.register(AnneeScolaire)
class AnneeScolaireAdmin(EtablissementAdminMixin, admin.ModelAdmin):
    list_display = ["libelle", "date_debut", "date_fin", "est_active"]
    list_editable = ["est_active"]


class EcheancierFraisInline(admin.StackedInline):
    model = EcheancierFrais
    extra = 0


@admin.register(Classe)
class ClasseAdmin(EtablissementAdminMixin, admin.ModelAdmin):
    list_display = ["nom", "cycle", "annee_scolaire", "effectif"]
    list_filter = ["cycle", "annee_scolaire"]
    search_fields = ["nom"]
    inlines = [EcheancierFraisInline]

    def get_queryset(self, request):
        from scolarite.models import classes_visibles_pour
        return classes_visibles_pour(request.user).select_related("annee_scolaire")


@admin.register(Affectation)
class AffectationAdmin(EtablissementAdminMixin, admin.ModelAdmin):
    list_display = ["enseignant", "classe", "matiere", "coefficient"]
    list_filter = ["classe__annee_scolaire", "classe__cycle"]
    search_fields = ["enseignant__nom", "enseignant__prenom", "classe__nom"]
    autocomplete_fields = ["enseignant", "classe"]

    def get_queryset(self, request):
        from scolarite.models import classes_visibles_pour
        return super().get_queryset(request).filter(classe__in=classes_visibles_pour(request.user))


@admin.register(Inscription)
class InscriptionAdmin(EtablissementAdminMixin, admin.ModelAdmin):
    list_display = ["eleve", "classe", "statut", "date_inscription"]
    list_filter = ["statut", "classe__annee_scolaire", "classe__cycle"]
    search_fields = ["eleve__nom", "eleve__prenom", "eleve__matricule"]
    autocomplete_fields = ["eleve", "classe"]

    def get_queryset(self, request):
        from scolarite.models import classes_visibles_pour
        return super().get_queryset(request).filter(classe__in=classes_visibles_pour(request.user))


@admin.register(AideScolarite)
class AideScolariteAdmin(EtablissementAdminMixin, admin.ModelAdmin):
    list_display = ["inscription", "type_aide", "montant", "pourcentage", "active", "accordee_par"]
    list_filter = ["type_aide", "active"]
    search_fields = ["inscription__eleve__nom", "inscription__eleve__prenom", "motif"]
    autocomplete_fields = ["inscription", "accordee_par"]


@admin.register(TransfertEleve)
class TransfertEleveAdmin(EtablissementAdminMixin, admin.ModelAdmin):
    list_display = ["inscription", "destination_libelle", "etablissement_destination", "date_transfert"]
    list_filter = ["date_transfert"]
    search_fields = ["inscription__eleve__nom", "inscription__eleve__prenom", "destination_libelle"]
    autocomplete_fields = ["inscription", "etablissement_destination", "enregistre_par"]
