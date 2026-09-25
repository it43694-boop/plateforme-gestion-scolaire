from django.urls import path

from scolarite import views

app_name = "scolarite"

urlpatterns = [
    path("eleves/", views.liste_eleves, name="liste_eleves"),
    path("eleves/<str:matricule>/dossier/", views.dossier_eleve, name="dossier_eleve"),
    path("eleves/inscrire/", views.inscrire_eleve, name="inscrire_eleve"),
    path("classes/", views.liste_classes, name="liste_classes"),
    path("matieres/", views.liste_matieres, name="liste_matieres"),
    path("classes/creer/", views.creer_classe, name="creer_classe"),
    path("classes/affecter-enseignant/", views.affecter_enseignant, name="affecter_enseignant"),
    path("classes/<int:classe_id>/passage-de-classe/", views.passage_de_classe, name="passage_de_classe"),
]
