from django.urls import path

from comptabilite import views

app_name = "comptabilite"

urlpatterns = [
    path("", views.accueil, name="accueil"),
    path("mettre-a-jour/", views.synchroniser, name="synchroniser"),
    path("exercices/", views.exercices_vue, name="exercices"),
    path("exercices/<int:exercice_id>/cloturer/", views.cloturer, name="cloturer"),
    path("exercices/<int:exercice_id>/reporter/", views.reporter, name="reporter"),
    path("plan-comptable/", views.plan_comptable, name="plan_comptable"),
    path("journal/", views.journal_vue, name="journal"),
    path("ecritures/saisir/", views.saisir_ecriture, name="saisir_ecriture"),
    path("ecritures/operation/", views.operation_simple, name="operation_simple"),
    path("ecritures/<int:ecriture_id>/contrepasser/", views.contrepasser_ecriture, name="contrepasser"),
    path("grand-livre/", views.grand_livre, name="grand_livre"),
    path("balance/", views.balance, name="balance"),
    path("compte-de-resultat/", views.compte_de_resultat, name="compte_de_resultat"),
    path("bilan/", views.bilan, name="bilan"),
    path("etats.xlsx", views.exporter_etats, name="exporter_etats"),
]
