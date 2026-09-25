from django.urls import path

from statistiques import views

app_name = "statistiques"

urlpatterns = [
    path("", views.vue_ensemble, name="vue_ensemble"),
    path("classe/<int:classe_id>/", views.statistiques_classe, name="statistiques_classe"),
    path("finances/", views.statistiques_finances, name="statistiques_finances"),
    path("export/effectifs.csv", views.exporter_effectifs_csv, name="exporter_effectifs_csv"),
    path("export/finances.csv", views.exporter_finances_csv, name="exporter_finances_csv"),
]
