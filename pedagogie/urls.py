from django.urls import path

from pedagogie import views, views_cahier, views_clotures, views_discipline, views_exports, views_mensuel, views_programmes

app_name = "pedagogie"

urlpatterns = [
    path("suivi-des-cours/", views.suivi_des_cours, name="suivi_des_cours"),
    path("mes-classes/", views.mes_classes, name="mes_classes"),
    path("notes/affectation/<int:affectation_id>/saisir/", views.saisir_note_vue, name="saisir_note"),
    path("notes/bulletin/<str:matricule>/", views.bulletin_eleve, name="bulletin_eleve"),
    path("notes/bulletin/<str:matricule>/export-pdf/", views.exporter_bulletin_pdf, name="exporter_bulletin_pdf"),
    path("notes/classe/<int:classe_id>/bulletins.pdf", views.exporter_bulletins_classe_pdf, name="exporter_bulletins_classe_pdf"),
    path("bulletin/verifier/<uuid:jeton>/", views.verifier_bulletin, name="verifier_bulletin"),

    path("absences/classe/<int:classe_id>/saisir/", views.saisir_absence_vue, name="saisir_absence"),
    path("conduite/classe/<int:classe_id>/", views.saisir_conduite_vue, name="saisir_conduite"),
    path("absences/historique/<str:matricule>/", views.historique_absences_eleve, name="historique_absences"),
    path("cahier/affectation/<int:affectation_id>/", views_cahier.cahier_affectation, name="cahier_affectation"),
    path("cahier/classe/<int:classe_id>/", views_cahier.cahier_classe, name="cahier_classe"),
    path("cahier/seance/<int:seance_id>/modifier/", views_cahier.modifier_seance, name="modifier_seance"),
    path("cahier/seance/<int:seance_id>/supprimer/", views_cahier.supprimer_seance, name="supprimer_seance"),
    path("devoirs/", views_cahier.devoirs, name="devoirs"),
    path("programme/affectation/<int:affectation_id>/", views_programmes.programme_affectation, name="programme_affectation"),
    path("programme/chapitre/<int:chapitre_id>/modifier/", views_programmes.modifier_chapitre, name="modifier_chapitre"),
    path("programme/chapitre/<int:chapitre_id>/supprimer/", views_programmes.supprimer_chapitre, name="supprimer_chapitre"),
    path("programmes/", views_programmes.avancement_programmes, name="avancement_programmes"),
    path("notes/clotures/", views_clotures.clotures_notes, name="clotures_notes"),
    path("notes/clotures/<int:annee_id>/<str:trimestre>/cloturer/", views_clotures.cloturer_periode, name="cloturer_periode"),
    path("notes/clotures/<int:annee_id>/<str:trimestre>/rouvrir/", views_clotures.rouvrir_periode, name="rouvrir_periode"),
    path("mensuel/", views_mensuel.classes, name="mensuel_classes"),
    path("mensuel/classe/<int:classe_id>/disciplines/", views_mensuel.disciplines, name="mensuel_disciplines"),
    path("mensuel/classe/<int:classe_id>/annee/", views_mensuel.annuel, name="mensuel_annuel"),
    path("mensuel/classe/<int:classe_id>/<int:annee>/<int:mois>/", views_mensuel.grille, name="mensuel_grille"),
    path("mensuel/classe/<int:classe_id>/<int:annee>/<int:mois>/resultats/", views_mensuel.resultats, name="mensuel_resultats"),
    path("mensuel/classe/<int:classe_id>/<int:annee>/<int:mois>/bulletins.pdf", views_mensuel.bulletins_classe_pdf, name="mensuel_bulletins_classe_pdf"),
    path("mensuel/eleve/<str:matricule>/", views_mensuel.bulletins_eleve, name="mensuel_eleve"),
    path("mensuel/eleve/<str:matricule>/<int:annee>/<int:mois>/bulletin.pdf", views_mensuel.bulletin_pdf, name="mensuel_bulletin_pdf"),
    path("discipline/classe/<int:classe_id>/", views_discipline.registre_discipline, name="registre_discipline"),
    path("discipline/eleve/<str:matricule>/", views_discipline.historique_discipline, name="historique_discipline"),
    path("discipline/mesure/<int:mesure_id>/supprimer/", views_discipline.supprimer_mesure_discipline, name="supprimer_mesure_discipline"),

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
