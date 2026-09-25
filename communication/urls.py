from django.urls import path

from communication import views

app_name = "communication"

urlpatterns = [
    path("", views.liste_annonces, name="liste_annonces"),
    path("publier/", views.publier_annonce, name="publier_annonce"),
    path("messages/", views.liste_conversations, name="liste_conversations"),
    path("messages/<int:eleve_id>/<int:autre_id>/", views.conversation, name="conversation"),
]
