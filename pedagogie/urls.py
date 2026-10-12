from django.urls import path

from pedagogie import views, views_exports

app_name = "pedagogie"

urlpatterns = [
    path("suivi-des-cours/", views.suivi_des_cours, name="suivi_des_cours"),
    path("mes-classes/", views.mes_classes, name="mes_classes"),
    path("notes/affectation/<int:affectation_id>/saisir/", views.saisir_note_vue, name="saisir_note"),
    path("notes/bulletin/<str:matricule>/", views.bulletin_eleve, name="bulletin_eleve"),
    path("notes/bulletin/<str:matricule>/export-pdf/", views.exporter_bulletin_pdf, name="exporter_bulletin_pdf"),
    path("bulletin/verifier/<uuid:jeton>/", views.verifier_bulletin, name="verifier_bulletin"),

    path("absences/classe/<int:classe_id>/saisir/", views.saisir_absence_vue, name="saisir_absence"),
    path("absences/historique/<str:matricule>/", views.historique_absences_eleve, name="historique_absences"),

    path(
        "notes/classe/<int:classe_id>/releve.xlsx", views_exports.exporter_releve_notes_xlsx,
        name="exporter_releve_notes_xlsx",
    ),
    path(
        "absences/classe/<int:classe_id>/export.xlsx", views_exports.exporter_absences_xlsx,
        name="exporter_absences_xlsx",
    ),

    path("emploi-du-temps/classe/<int:classe_id>/", views.gerer_emploi_du_temps, name="gerer_emploi_du_temps"),
    path("emploi-du-temps/creneau/<int:creneau_id>/supprimer/", views.supprimer_creneau, name="supprimer_creneau"),
    path(
        "emploi-du-temps/classe/<int:classe_id>/export-pdf/",
        views.exporter_emploi_du_temps_pdf, name="exporter_emploi_du_temps_pdf",
    ),
]
