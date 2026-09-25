from django.urls import path

from espace_plateforme import views

app_name = "espace_plateforme"

urlpatterns = [
    path("", views.liste_etablissements, name="liste_etablissements"),
    path("creer/", views.creer_etablissement, name="creer_etablissement"),
    path("<int:etablissement_id>/modifier/", views.modifier_etablissement, name="modifier_etablissement"),
    path("<int:etablissement_id>/comptes/", views.voir_comptes_etablissement, name="voir_comptes_etablissement"),
    path("<int:etablissement_id>/basculer-actif/", views.basculer_actif, name="basculer_actif"),
]
