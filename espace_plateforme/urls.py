from django.urls import path

from espace_plateforme import views

app_name = "espace_plateforme"

urlpatterns = [
    path("", views.liste_etablissements, name="liste_etablissements"),
    path("creer/", views.creer_etablissement, name="creer_etablissement"),
    path("<int:etablissement_id>/modifier/", views.modifier_etablissement, name="modifier_etablissement"),
    path("<int:etablissement_id>/comptes/", views.voir_comptes_etablissement, name="voir_comptes_etablissement"),
    path("<int:etablissement_id>/basculer-actif/", views.basculer_actif, name="basculer_actif"),
    path("<int:etablissement_id>/modifier-plan/", views.modifier_plan, name="modifier_plan"),
    path("<int:etablissement_id>/acceder/", views.acceder_etablissement, name="acceder_etablissement"),
    path("abonnements/", views.abonnements, name="abonnements"),
    path("abonnements/factures/", views.liste_factures, name="liste_factures"),
    path("abonnements/factures/emettre/", views.emettre_facture_vue, name="emettre_facture"),
    path("abonnements/factures/export.xlsx", views.exporter_factures_xlsx, name="exporter_factures_xlsx"),
    path("abonnements/factures/<int:facture_id>/payer/", views.payer_facture, name="payer_facture"),
    path("abonnements/factures/<int:facture_id>/annuler/", views.annuler_facture_vue, name="annuler_facture"),
    path("abonnements/factures/<int:facture_id>/pdf/", views.facture_pdf, name="facture_pdf"),
]
