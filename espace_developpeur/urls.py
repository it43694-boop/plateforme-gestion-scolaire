from django.urls import path

from espace_developpeur import views

app_name = "espace_developpeur"

urlpatterns = [
    path("etablissement/", views.parametres_etablissement, name="parametres_etablissement"),
    path("comptes/", views.liste_comptes, name="liste_comptes"),
    path("comptes/<int:utilisateur_id>/modifier/", views.modifier_compte, name="modifier_compte"),
    path(
        "comptes/<int:utilisateur_id>/reinitialiser-2fa/",
        views.reinitialiser_2fa_compte, name="reinitialiser_2fa_compte",
    ),
    path("matrice-permissions/", views.matrice_permissions_vue, name="matrice_permissions"),
    path("annees-scolaires/", views.annees_scolaires, name="annees_scolaires"),
    path("annees-scolaires/<int:annee_id>/activer/", views.activer_annee_scolaire, name="activer_annee_scolaire"),
    path("annees-scolaires/<int:annee_id>/archiver/", views.archiver_annee_scolaire, name="archiver_annee_scolaire"),
    path("journal-audit/", views.journal_audit, name="journal_audit"),
]
