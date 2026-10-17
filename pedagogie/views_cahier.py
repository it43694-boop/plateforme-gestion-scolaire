"""Cahier de textes : l'enseignant (ou la direction) note les séances et les devoirs ; les familles les consultent."""
import datetime

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from comptes.forms import BootstrapFormMixin
from comptes.roles import Role
from pedagogie.cahier import devoirs_des_familles, peut_lire_la_classe, peut_tenir
from pedagogie.models import SeanceCahier
from permissions_matrix.modules import Module
from scolarite.models import Affectation, Classe, classes_visibles_pour


class SeanceForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = SeanceCahier
        fields = ["date_seance", "contenu", "travail_a_faire", "date_remise"]
        widgets = {
            "date_seance": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "date_remise": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "contenu": forms.Textarea(attrs={"rows": 2}),
            "travail_a_faire": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("initial", {"date_seance": datetime.date.today()})
        super().__init__(*args, **kwargs)

    def clean_contenu(self):
        return " ".join(self.cleaned_data["contenu"].split())

    def clean_travail_a_faire(self):
        return " ".join((self.cleaned_data.get("travail_a_faire") or "").split())


def _affectation_tenue_par(request, affectation_id):
    affectation = get_object_or_404(Affectation.objects.select_related("classe__annee_scolaire", "enseignant"), pk=affectation_id)
    # Une classe d'une autre école est introuvable ; une classe de l'école qu'on ne tient pas est interdite.
    get_object_or_404(classes_visibles_pour(request.user), pk=affectation.classe_id)
    if not peut_tenir(request.user, affectation):
        raise PermissionDenied("Vous ne tenez pas le cahier de textes de cette matière.")
    return affectation


@module_requis(Module.NOTES_BULLETINS)
@require_http_methods(["GET", "POST"])
def cahier_affectation(request, affectation_id):
    """Le cahier de textes d'une matière dans une classe : ajouter une séance, voir les dernières."""
    affectation = _affectation_tenue_par(request, affectation_id)
    lecture_seule = affectation.classe.annee_scolaire.est_archivee
    formulaire = SeanceForm(request.POST or None)
    if request.method == "POST":
        if lecture_seule:
            raise PermissionDenied("Cette année scolaire est archivée.")
        if formulaire.is_valid():
            seance = formulaire.save(commit=False)
            seance.affectation, seance.cree_par = affectation, request.user
            seance.save()
            enregistrer_action(acteur=request.user, action="saisie_cahier_de_textes", cible=str(affectation), request=request)
            messages.success(request, "Séance ajoutée au cahier de textes.")
            return redirect("pedagogie:cahier_affectation", affectation_id=affectation.pk)
    seances = SeanceCahier.objects.filter(affectation=affectation)
    page_obj = Paginator(seances, 25).get_page(request.GET.get("page"))
    return render(request, "pedagogie/cahier_affectation.html", {
        "affectation": affectation, "formulaire": formulaire, "seances": page_obj.object_list, "page_obj": page_obj, "lecture_seule": lecture_seule,
    })


def _seance_tenue_par(request, seance_id):
    seance = get_object_or_404(SeanceCahier.objects.select_related("affectation__classe__annee_scolaire"), pk=seance_id)
    affectation = _affectation_tenue_par(request, seance.affectation_id)
    if affectation.classe.annee_scolaire.est_archivee:
        raise PermissionDenied("Cette année scolaire est archivée.")
    return seance


@module_requis(Module.NOTES_BULLETINS)
@require_http_methods(["GET", "POST"])
def modifier_seance(request, seance_id):
    seance = _seance_tenue_par(request, seance_id)
    formulaire = SeanceForm(request.POST or None, instance=seance)
    if request.method == "POST" and formulaire.is_valid():
        formulaire.save()
        enregistrer_action(acteur=request.user, action="modification_cahier_de_textes", cible=str(seance.affectation), request=request)
        messages.success(request, "Séance modifiée.")
        return redirect("pedagogie:cahier_affectation", affectation_id=seance.affectation_id)
    return render(request, "pedagogie/modifier_seance.html", {"formulaire": formulaire, "seance": seance})


@module_requis(Module.NOTES_BULLETINS)
@require_POST
def supprimer_seance(request, seance_id):
    seance = _seance_tenue_par(request, seance_id)
    affectation_id = seance.affectation_id
    enregistrer_action(acteur=request.user, action="suppression_cahier_de_textes", cible=str(seance.affectation), request=request)
    seance.delete()
    messages.success(request, "Séance supprimée.")
    return redirect("pedagogie:cahier_affectation", affectation_id=affectation_id)


@module_requis(Module.NOTES_BULLETINS)
def cahier_classe(request, classe_id):
    """Le cahier de textes de toutes les matières d'une classe (personnel de l'école)."""
    classe = get_object_or_404(classes_visibles_pour(request.user), pk=classe_id)
    if not peut_lire_la_classe(request.user, classe):
        raise PermissionDenied("Vous n'avez pas le droit de consulter le cahier de textes de cette classe.")
    affectations = list(Affectation.objects.filter(classe=classe).select_related("enseignant").order_by("matiere", "pk"))
    choisie = request.GET.get("affectation", "")
    seances = SeanceCahier.objects.filter(affectation__classe=classe).select_related("affectation__enseignant")
    if choisie.isdigit():
        seances = seances.filter(affectation_id=int(choisie))
    page_obj = Paginator(seances, 30).get_page(request.GET.get("page"))
    return render(request, "pedagogie/cahier_classe.html", {
        "classe": classe, "affectations": affectations, "affectation_id": choisie, "seances": page_obj.object_list, "page_obj": page_obj,
        "tenue_par_moi": {a.pk for a in affectations if peut_tenir(request.user, a)},
    })


@module_requis(Module.NOTES_BULLETINS)
def devoirs(request):
    """Les devoirs et les dernières séances de la classe de chaque enfant (parent) ou de l'élève lui-même."""
    if request.user.role not in {Role.PARENT.value, Role.ELEVE.value}:
        raise PermissionDenied("Cette page est réservée aux parents et aux élèves.")
    return render(request, "pedagogie/devoirs.html", {"familles": devoirs_des_familles(request.user)})
