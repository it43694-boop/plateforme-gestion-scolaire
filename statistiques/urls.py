from django.urls import path

from statistiques import views

app_name = "statistiques"

urlpatterns = [
    path("", views.vue_ensemble, name="vue_ensemble"),
    path("classe/<int:classe_id>/", views.statistiques_classe, name="statistiques_classe"),
    path("finances/", views.statistiques_finances, name="statistiques_finances"),
    path("fiche-annuelle/", views.fiche_annuelle, name="fiche_annuelle"),
    path("fiche-annuelle.csv", views.exporter_fiche_annuelle_csv, name="exporter_fiche_annuelle_csv"),
    path("fiche-annuelle.xlsx", views.exporter_fiche_annuelle_xlsx, name="exporter_fiche_annuelle_xlsx"),
    path("examens/", views.resultats_examens, name="resultats_examens"),
    path("infrastructures/", views.infrastructures, name="infrastructures"),
    path("export/effectifs.csv", views.exporter_effectifs_csv, name="exporter_effectifs_csv"),
    path("export/finances.csv", views.exporter_finances_csv, name="exporter_finances_csv"),
]
