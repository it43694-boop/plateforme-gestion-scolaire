from django.urls import path

from espace_developpeur import views

app_name = "espace_developpeur"

urlpatterns = [
    path("etablissement/", views.parametres_etablissement, name="parametres_etablissement"),
    path("comptes/", views.liste_comptes, name="liste_comptes"),
    path("comptes/<int:utilisateur_id>/modifier/", views.modifier_compte, name="modifier_compte"),
    path("matrice-permissions/", views.matrice_permissions_vue, name="matrice_permissions"),
    path("journal-audit/", views.journal_audit, name="journal_audit"),
]
