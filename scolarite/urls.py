from django.urls import path

from scolarite import views, views_exports, views_import

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
    path("eleves/importer/", views_import.importer_eleves, name="importer_eleves"),
    path("eleves/importer/modele.xlsx", views_import.modele_import_eleves, name="modele_import_eleves"),
    path("classes/<int:classe_id>/eleves.xlsx", views_exports.exporter_liste_classe_xlsx, name="exporter_liste_classe_xlsx"),
    path("classes/", views.liste_classes, name="liste_classes"),
    path("classes/niveaux/", views.definir_niveaux, name="definir_niveaux"),
    path("matieres/", views.liste_matieres, name="liste_matieres"),
    path("classes/creer/", views.creer_classe, name="creer_classe"),
    path("classes/<int:classe_id>/supprimer/", views.supprimer_classe, name="supprimer_classe"),
    path("classes/<int:classe_id>/resultats-examen/", views.saisir_resultats_examen, name="saisir_resultats_examen"),
    path("classes/affecter-enseignant/", views.affecter_enseignant, name="affecter_enseignant"),
    path("affectations/<int:affectation_id>/supprimer/", views.supprimer_affectation, name="supprimer_affectation"),
    path("classes/<int:classe_id>/passage-de-classe/", views.passage_de_classe, name="passage_de_classe"),
]
