from django.urls import path

from cantine import views

app_name = "cantine"

urlpatterns = [
    path("", views.tableau, name="tableau"),
    path("inscrire/", views.inscrire_eleves, name="inscrire_eleves"),
    path("appel/", views.appel, name="appel"),
    path("formules/", views.formules, name="formules"),
    path("formules/<int:formule_id>/basculer/", views.basculer_formule, name="basculer_formule"),
    path("inscriptions/<int:inscription_id>/", views.fiche_inscription, name="fiche_inscription"),
    path("inscriptions/<int:inscription_id>/terminer/", views.terminer_inscription, name="terminer_inscription"),
    path("inscriptions/<int:inscription_id>/payer/", views.paiement, name="paiement"),
    path("paiements/<int:paiement_id>/recu.pdf", views.recu_pdf, name="recu_pdf"),
    path("paiements/<int:paiement_id>/annuler/", views.annuler_paiement, name="annuler_paiement"),
    path("mon-suivi/", views.mon_suivi, name="mon_suivi"),
]
