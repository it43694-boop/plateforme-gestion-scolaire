from django.urls import path

from finances import views

app_name = "finances"

urlpatterns = [
    path("suivi-paiements/", views.suivi_paiements, name="suivi_paiements"),
    path("paiements/", views.liste_paiements, name="liste_paiements"),
    path("paiements/enregistrer/", views.enregistrer_paiement_vue, name="enregistrer_paiement"),
    path("paiements/rechercher-eleve.json", views.rechercher_eleve_json, name="rechercher_eleve_json"),
    path("paiements/periodes-eleve.json", views.periodes_eleve_json, name="periodes_eleve_json"),
    path("paiements/<int:paiement_id>/corriger/", views.corriger_paiement_vue, name="corriger_paiement"),
    path("paiements/<int:paiement_id>/recu.pdf", views.exporter_recu_paiement_pdf, name="exporter_recu_paiement_pdf"),
    path("paiements/<int:paiement_id>/supprimer/", views.supprimer_paiement_vue, name="supprimer_paiement"),

    path("salaires/", views.liste_salaires, name="liste_salaires"),
    path("salaires/saisir/", views.saisir_salaire_vue, name="saisir_salaire"),
    path("salaires/bulletin/creer/", views.creer_bulletin_paie_vue, name="creer_bulletin_paie"),
    path("salaires/<int:salaire_id>/bulletin.pdf", views.bulletin_paie_pdf, name="bulletin_paie_pdf"),
    path("salaires/rechercher-employe.json", views.rechercher_employe_json, name="rechercher_employe_json"),
    path("salaires/<int:salaire_id>/payer/", views.marquer_salaire_paye_vue, name="marquer_salaire_paye"),
    path("salaires/<int:salaire_id>/supprimer/", views.supprimer_salaire_vue, name="supprimer_salaire"),

    path("personnel/contrats/", views.liste_contrats, name="liste_contrats"),
    path("personnel/contrats/creer/", views.creer_contrat_vue, name="creer_contrat"),
    path("personnel/contrats/<int:contrat_id>/cloturer/", views.cloturer_contrat_vue, name="cloturer_contrat"),
    path("personnel/conges/", views.liste_conges, name="liste_conges"),
    path("personnel/conges/enregistrer/", views.enregistrer_conge_vue, name="enregistrer_conge"),
    path("personnel/conges/solde.json", views.solde_conges_json, name="solde_conges_json"),

    path("caisse/", views.registre_caisse, name="registre_caisse"),
    path("caisse/journal-syscohada/", views.journal_caisse_syscohada, name="journal_caisse_syscohada"),
    path("caisse/journal-syscohada.csv", views.journal_caisse_syscohada_csv, name="journal_caisse_syscohada_csv"),
]
