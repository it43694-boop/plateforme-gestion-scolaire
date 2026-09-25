from django.urls import path

from tests_niveau import views

app_name = "tests_niveau"

urlpatterns = [
    path("", views.liste_candidats, name="liste_candidats"),
    path("ajouter/", views.ajouter_candidat, name="ajouter_candidat"),
    path("<int:candidat_id>/decision/<str:decision>/", views.decider_candidat_vue, name="decider_candidat"),
]
