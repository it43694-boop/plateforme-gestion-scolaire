from django.urls import path

from scolarite import views_verification
from vitrine import views

app_name = "vitrine"

urlpatterns = [
    path("", views.accueil, name="accueil"),
    path("e/<slug:slug>/", views.choisir_etablissement, name="choisir_etablissement"),
    path("ecole/changer/", views.changer_ecole, name="changer_ecole"),
    path("ecole/rechercher.json", views.rechercher_etablissement, name="rechercher_etablissement"),
    path("mentions-legales/", views.mentions_legales, name="mentions_legales"),
    path("conditions-d-utilisation/", views.conditions_utilisation, name="conditions"),
    path("confidentialite/", views.confidentialite, name="confidentialite"),
    path("verifier/", views_verification.verifier, name="verifier"),
]
