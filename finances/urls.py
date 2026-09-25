from django.urls import path

from finances import views

app_name = "finances"

urlpatterns = [
    path("suivi-paiements/", views.suivi_paiements, name="suivi_paiements"),
    path("paiements/", views.liste_paiements, name="liste_paiements"),
    path("paiements/enregistrer/", views.enregistrer_paiement_vue, name="enregistrer_paiement"),
    path("paiements/rechercher-eleve.json", views.rechercher_eleve_json, name="rechercher_eleve_json"),
    path("paiements/<int:paiement_id>/corriger/", views.corriger_paiement_vue, name="corriger_paiement"),
    path("paiements/<int:paiement_id>/recu.pdf", views.exporter_recu_paiement_pdf, name="exporter_recu_paiement_pdf"),
    path("paiements/<int:paiement_id>/supprimer/", views.supprimer_paiement_vue, name="supprimer_paiement"),

    path("salaires/", views.liste_salaires, name="liste_salaires"),
    path("salaires/saisir/", views.saisir_salaire_vue, name="saisir_salaire"),
    path("salaires/rechercher-employe.json", views.rechercher_employe_json, name="rechercher_employe_json"),
    path("salaires/<int:salaire_id>/payer/", views.marquer_salaire_paye_vue, name="marquer_salaire_paye"),
    path("salaires/<int:salaire_id>/supprimer/", views.supprimer_salaire_vue, name="supprimer_salaire"),

    path("caisse/", views.registre_caisse, name="registre_caisse"),
]
