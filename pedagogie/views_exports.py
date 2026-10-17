"""Exports Excel d'une classe : relevé de notes et absences."""
import datetime

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404

from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from comptes.excel import nom_fichier_sur, reponse_xlsx
from comptes.roles import Role
from pedagogie.exports import absences_classeur, releve_notes_classeur
from permissions_matrix.modules import Module
from scolarite.models import ROLES_VOIENT_TOUT_ELEVE_DE_LETABLISSEMENT, Affectation, classes_visibles_pour

ROLES_SANS_EXPORT = {Role.PARENT.value, Role.ELEVE.value}


def _date_du_parametre(request, nom):
    valeur = request.GET.get(nom, "").strip()
    if not valeur:
        return None
    try:
        return datetime.date.fromisoformat(valeur)
    except ValueError:  # date illisible = page introuvable, pas une erreur serveur
        raise Http404("Date invalide.")


@module_requis(Module.NOTES_BULLETINS)
def exporter_releve_notes_xlsx(request, classe_id):
    """
    Relevé de notes d'une classe. La direction obtient toutes les matières avec moyenne générale et rang ; un enseignant
    n'obtient que SES matières dans cette classe (jamais le classement, qui dépend des matières des autres).
    """
    if request.user.role in ROLES_SANS_EXPORT:
        raise PermissionDenied("Vous n'avez pas le droit d'exporter un relevé de notes.")
    classe = get_object_or_404(classes_visibles_pour(request.user), id=classe_id)
    affectations = Affectation.objects.filter(classe=classe).order_by("matiere", "id")
    if request.user.role == Role.ENSEIGNANT:
        affectations = affectations.filter(enseignant=request.user)
        if not affectations.exists():
            raise PermissionDenied("Vous n'êtes pas affecté à cette classe.")
        vue_complete = False
    elif request.user.role in ROLES_VOIENT_TOUT_ELEVE_DE_LETABLISSEMENT:
        vue_complete = True
    else:
        raise PermissionDenied("Vous n'avez pas le droit d'exporter un relevé de notes.")
    enregistrer_action(
        acteur=request.user, action="export_releve_notes", cible=str(classe),
        details={"vue": "complete" if vue_complete else "enseignant"}, request=request,
    )
    return reponse_xlsx(
        releve_notes_classeur(classe, affectations, vue_complete=vue_complete),
        nom_fichier_sur("releve_notes", classe.nom, classe.annee_scolaire.libelle),
        request=request,
    )


@module_requis(Module.ABSENCES)
def exporter_absences_xlsx(request, classe_id):
    """Absences d'une classe (synthèse par élève et détail), sur toute l'année ou entre deux dates (?du=&au=, aaaa-mm-jj)."""
    if request.user.role in ROLES_SANS_EXPORT:
        raise PermissionDenied("Vous n'avez pas le droit d'exporter les absences.")
    classe = get_object_or_404(classes_visibles_pour(request.user), id=classe_id)
    if request.user.role == Role.ENSEIGNANT:
        if not Affectation.objects.filter(enseignant=request.user, classe=classe).exists():
            raise PermissionDenied("Vous n'êtes pas affecté à cette classe.")
    elif request.user.role not in ROLES_VOIENT_TOUT_ELEVE_DE_LETABLISSEMENT:
        raise PermissionDenied("Vous n'avez pas le droit d'exporter les absences.")
    du, au = _date_du_parametre(request, "du"), _date_du_parametre(request, "au")
    enregistrer_action(acteur=request.user, action="export_absences_classe", cible=str(classe), request=request)
    return reponse_xlsx(
        absences_classeur(classe, du=du, au=au),
        nom_fichier_sur("absences", classe.nom, classe.annee_scolaire.libelle),
        request=request,
    )
