from django.urls import path

from vitrine import views

app_name = "vitrine"

urlpatterns = [
    path("", views.accueil, name="accueil"),
    path("e/<slug:slug>/", views.choisir_etablissement, name="choisir_etablissement"),
]
