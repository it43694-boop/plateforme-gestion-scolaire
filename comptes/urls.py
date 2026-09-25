from django.contrib.auth import views as auth_views
from django.urls import path

from comptes import views

app_name = "comptes"

urlpatterns = [
    path("inscription/", views.inscription, name="inscription"),
    path("verifier-email/", views.verifier_email, name="verifier_email"),
    path("renvoyer-code/", views.renvoyer_code, name="renvoyer_code"),

    path("connexion/", views.connexion, name="connexion"),
    path("connexion/2fa/", views.verifier_2fa, name="verifier_2fa"),
    path("deconnexion/", views.deconnexion, name="deconnexion"),
    path("changer-mot-de-passe/", views.changer_mot_de_passe, name="changer_mot_de_passe"),
    path("changer-email/", views.changer_email, name="changer_email"),
    path("2fa/activer/", views.activer_2fa, name="activer_2fa"),
    path("2fa/desactiver/", views.desactiver_2fa, name="desactiver_2fa"),
    path("tableau-de-bord/", views.redirection_tableau_de_bord, name="redirection_tableau_de_bord"),
    path("portail-parent/", views.portail_parent, name="portail_parent"),
    path("notifications/", views.liste_notifications, name="liste_notifications"),
    path("notifications/lues/", views.marquer_notifications_lues, name="marquer_notifications_lues"),
    path("notifications/<int:notification_id>/lue/", views.marquer_notification_lue, name="marquer_notification_lue"),

    path("mot-de-passe-oublie/", views.mot_de_passe_oublie, name="mot_de_passe_oublie"),
    path(
        "reinitialiser-mot-de-passe/<uidb64>/<token>/",
        views.ReinitialiserMotDePasseView.as_view(),
        name="reinitialiser_mot_de_passe",
    ),

    path("comptes-en-attente/", views.comptes_en_attente, name="comptes_en_attente"),
    path("comptes-en-attente/<int:utilisateur_id>/valider/", views.valider_compte, name="valider_compte"),
    path("comptes-en-attente/<int:utilisateur_id>/refuser/", views.refuser_compte, name="refuser_compte"),
]
