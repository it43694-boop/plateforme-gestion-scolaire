from django.urls import path

from scolarite import views

app_name = "scolarite"

urlpatterns = [
    path("eleves/", views.liste_eleves, name="liste_eleves"),
    path("recherche/", views.recherche_globale, name="recherche_globale"),
    path("eleves/<str:matricule>/dossier/", views.dossier_eleve, name="dossier_eleve"),
    path(
        "eleves/<str:matricule>/attestation/",
        views.generer_attestation_scolarite, name="generer_attestation_scolarite",
    ),
    path(
        "eleves/<str:matricule>/mot-de-passe-provisoire/",
        views.mot_de_passe_provisoire, name="mot_de_passe_provisoire",
    ),
    path(
        "eleves/<str:matricule>/cloturer/",
        views.cloturer_inscription_vue, name="cloturer_inscription",
    ),
    path("verifier/<uuid:jeton>/", views.verifier_document, name="verifier_document"),
    path("eleves/inscrire/", views.inscrire_eleve, name="inscrire_eleve"),
    path("classes/", views.liste_classes, name="liste_classes"),
    path("matieres/", views.liste_matieres, name="liste_matieres"),
    path("classes/creer/", views.creer_classe, name="creer_classe"),
    path("classes/<int:classe_id>/supprimer/", views.supprimer_classe, name="supprimer_classe"),
    path("classes/affecter-enseignant/", views.affecter_enseignant, name="affecter_enseignant"),
    path("affectations/<int:affectation_id>/supprimer/", views.supprimer_affectation, name="supprimer_affectation"),
    path("classes/<int:classe_id>/passage-de-classe/", views.passage_de_classe, name="passage_de_classe"),
]
