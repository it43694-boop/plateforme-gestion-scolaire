from django.urls import path

from communication import views, views_diffusion, views_equipes

app_name = "communication"

urlpatterns = [
    path("", views.liste_annonces, name="liste_annonces"),
    path("publier/", views.publier_annonce, name="publier_annonce"),
    path("equipes/", views_equipes.liste_equipes, name="liste_equipes"),
    path("equipes/<int:fil_id>/", views_equipes.fil_equipe, name="fil_equipe"),
    path("messages-aux-familles/", views_diffusion.messages_a_envoyer, name="messages_a_envoyer"),
    path("messages/", views.liste_conversations, name="liste_conversations"),
    path("messages/<int:eleve_id>/<int:autre_id>/", views.conversation, name="conversation"),
]
