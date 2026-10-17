from django.urls import path

from tests_niveau import views, views_publiques

app_name = "tests_niveau"

urlpatterns = [
    path("", views.liste_candidats, name="liste_candidats"),
    path("ajouter/", views.ajouter_candidat, name="ajouter_candidat"),
    path("pre-inscription/<str:jeton>/", views_publiques.preinscription, name="preinscription"),  # public : le lien secret d'une campagne
    path("pre-inscription/<str:jeton>/merci/", views_publiques.preinscription_merci, name="preinscription_merci"),
    path("campagnes/", views.campagnes, name="campagnes"),
    path("campagnes/<int:campagne_id>/basculer/", views.basculer_campagne, name="basculer_campagne"),
    path("<int:candidat_id>/convoquer/", views.convoquer_candidat, name="convoquer_candidat"),
    path("<int:candidat_id>/refuser-demande/", views.refuser_demande, name="refuser_demande"),
    path("<int:candidat_id>/decision/<str:decision>/", views.decider_candidat_vue, name="decider_candidat"),
]
