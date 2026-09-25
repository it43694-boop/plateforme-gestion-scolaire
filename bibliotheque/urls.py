from django.urls import path

from bibliotheque import views

app_name = "bibliotheque"

urlpatterns = [
    path("", views.liste_documents, name="liste_documents"),
    path("ajouter/", views.ajouter_document, name="ajouter_document"),
    path("importer-zip/", views.importer_zip, name="importer_zip"),
    path("exporter-zip/", views.exporter_zip, name="exporter_zip"),
]
