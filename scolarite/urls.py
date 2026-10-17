from django.urls import path

from scolarite import (
    views, views_anciens, views_calendrier, views_cartes, views_documents, views_exports, views_import, views_photos,
)

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
    path("eleves/<str:matricule>/corriger/", views.corriger_dossier_eleve, name="corriger_dossier_eleve"),
    path("eleves/<str:matricule>/photo/", views_photos.photo_eleve, name="photo_eleve"),
    path("eleves/<str:matricule>/photo/envoyer/", views_photos.envoyer_photo_eleve, name="envoyer_photo_eleve"),
    path("eleves/<str:matricule>/photo/supprimer/", views_photos.supprimer_photo_eleve, name="supprimer_photo_eleve"),
    path("classes/<int:classe_id>/photos/", views_photos.importer_photos_classe, name="importer_photos_classe"),
    path("classes/<int:classe_id>/cartes.pdf", views_cartes.cartes_classe_pdf, name="cartes_classe_pdf"),
    path("anciens-eleves/", views_anciens.anciens_eleves, name="anciens_eleves"),
    path("eleves/<str:matricule>/reintegrer/", views_anciens.reintegrer_eleve, name="reintegrer_eleve"),
    path("calendrier/", views_calendrier.calendrier, name="calendrier"),
    path("calendrier/ajouter/", views_calendrier.ajouter_evenement, name="ajouter_evenement"),
    path("calendrier/<int:evenement_id>/modifier/", views_calendrier.modifier_evenement, name="modifier_evenement"),
    path("calendrier/<int:evenement_id>/supprimer/", views_calendrier.supprimer_evenement, name="supprimer_evenement"),
    path("eleves/<str:matricule>/carte.pdf", views_cartes.carte_eleve_pdf, name="carte_eleve_pdf"),
    path("eleves/<str:matricule>/documents/<slug:code>/", views_documents.document_officiel, name="document_officiel"),
    path(
        "eleves/<str:matricule>/cloturer/",
        views.cloturer_inscription_vue, name="cloturer_inscription",
    ),
    path("verifier/<uuid:jeton>/", views.verifier_document, name="verifier_document"),
    path("eleves/inscrire/", views.inscrire_eleve, name="inscrire_eleve"),
    path("eleves/importer/", views_import.importer_eleves, name="importer_eleves"),
    path("eleves/importer/modele.xlsx", views_import.modele_import_eleves, name="modele_import_eleves"),
    path("classes/<int:classe_id>/eleves.xlsx", views_exports.exporter_liste_classe_xlsx, name="exporter_liste_classe_xlsx"),
    path("classes/<int:classe_id>/eleves.csv", views_exports.exporter_liste_classe_csv, name="exporter_liste_classe_csv"),
    path("classes/<int:classe_id>/eleves.pdf", views_exports.exporter_liste_classe_pdf, name="exporter_liste_classe_pdf"),
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
