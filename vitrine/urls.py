from django.urls import path

from vitrine import views

app_name = "vitrine"

urlpatterns = [
    path("", views.accueil, name="accueil"),
    path("e/<slug:slug>/", views.choisir_etablissement, name="choisir_etablissement"),
    path("mentions-legales/", views.mentions_legales, name="mentions_legales"),
    path("conditions-d-utilisation/", views.conditions_utilisation, name="conditions"),
    path("confidentialite/", views.confidentialite, name="confidentialite"),
]
