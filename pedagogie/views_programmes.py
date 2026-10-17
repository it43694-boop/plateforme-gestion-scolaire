"""Suivi des programmes : l'avancement de chaque matière chapitre par chapitre, et la vue d'ensemble de la direction (retards en tête)."""
import datetime

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from comptes.forms import BootstrapFormMixin
from pedagogie.cahier import peut_lire_le_programme, peut_tenir
from pedagogie.models import ChapitreProgramme
from permissions_matrix.modules import Module
from scolarite.models import Affectation, classes_visibles_pour


class ChapitreForm(BootstrapFormMixin, forms.ModelForm):
    pourcentage = forms.IntegerField(label="Avancement (%)", min_value=0, max_value=100, initial=0)

    class Meta:
        model = ChapitreProgramme
        fields = ["titre", "date_prevue", "pourcentage", "difficultes"]
        widgets = {"date_prevue": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def clean_titre(self):
        return " ".join(self.cleaned_data["titre"].split())


def _affectation_tenue_par(request, affectation_id):
    affectation = get_object_or_404(Affectation.objects.select_related("classe__annee_scolaire", "enseignant"), pk=affectation_id)
    get_object_or_404(classes_visibles_pour(request.user), pk=affectation.classe_id)
    if not peut_tenir(request.user, affectation):
        raise PermissionDenied("Vous ne tenez pas le programme de cette matière.")
    return affectation


def resume_du_programme(chapitres) -> dict:
    """{nombre, avancement (moyenne des chapitres, en %), en_retard} d'une liste de chapitres."""
    chapitres = list(chapitres)
    return {
        "nombre": len(chapitres),
        "avancement": round(sum(c.pourcentage for c in chapitres) / len(chapitres)) if chapitres else 0,
        "en_retard": sum(1 for c in chapitres if c.en_retard),
    }


@module_requis(Module.NOTES_BULLETINS)
@require_http_methods(["GET", "POST"])
def programme_affectation(request, affectation_id):
    """Le programme d'une matière : tenu par l'enseignant (ou la direction), lisible aussi par la supervision de la classe."""
    affectation = get_object_or_404(Affectation.objects.select_related("classe__annee_scolaire", "enseignant"), pk=affectation_id)
    get_object_or_404(classes_visibles_pour(request.user), pk=affectation.classe_id)
    if not peut_lire_le_programme(request.user, affectation):
        raise PermissionDenied("Vous n'avez pas accès au programme de cette matière.")
    peut_modifier = peut_tenir(request.user, affectation)
    lecture_seule = affectation.classe.annee_scolaire.est_archivee
    formulaire = ChapitreForm(request.POST or None)
    if request.method == "POST":
        if not peut_modifier:
            raise PermissionDenied("Vous ne tenez pas le programme de cette matière.")
        if lecture_seule:
            raise PermissionDenied("Cette année scolaire est archivée.")
        if formulaire.is_valid():
            chapitre = formulaire.save(commit=False)
            chapitre.affectation = affectation
            chapitre.ordre = (ChapitreProgramme.objects.filter(affectation=affectation).aggregate(m=Max("ordre"))["m"] or 0) + 1
            chapitre.save()
            enregistrer_action(acteur=request.user, action="ajout_chapitre_programme", cible=str(affectation), request=request)
            messages.success(request, "Chapitre ajouté au programme.")
            return redirect("pedagogie:programme_affectation", affectation_id=affectation.pk)
    chapitres = list(ChapitreProgramme.objects.filter(affectation=affectation))
    return render(request, "pedagogie/programme_affectation.html", {
        "affectation": affectation, "formulaire": formulaire, "chapitres": chapitres, "resume": resume_du_programme(chapitres),
        "lecture_seule": lecture_seule, "modifiable": peut_modifier and not lecture_seule,
    })


def _chapitre_tenu_par(request, chapitre_id):
    chapitre = get_object_or_404(ChapitreProgramme.objects.select_related("affectation__classe__annee_scolaire"), pk=chapitre_id)
    affectation = _affectation_tenue_par(request, chapitre.affectation_id)
    if affectation.classe.annee_scolaire.est_archivee:
        raise PermissionDenied("Cette année scolaire est archivée.")
    return chapitre


@module_requis(Module.NOTES_BULLETINS)
@require_http_methods(["GET", "POST"])
def modifier_chapitre(request, chapitre_id):
    chapitre = _chapitre_tenu_par(request, chapitre_id)
    formulaire = ChapitreForm(request.POST or None, instance=chapitre)
    if request.method == "POST" and formulaire.is_valid():
        formulaire.save()
        enregistrer_action(acteur=request.user, action="modification_chapitre_programme", cible=str(chapitre.affectation), request=request)
        messages.success(request, "Chapitre modifié.")
        return redirect("pedagogie:programme_affectation", affectation_id=chapitre.affectation_id)
    return render(request, "pedagogie/modifier_chapitre.html", {"formulaire": formulaire, "chapitre": chapitre})


@module_requis(Module.NOTES_BULLETINS)
@require_POST
def supprimer_chapitre(request, chapitre_id):
    chapitre = _chapitre_tenu_par(request, chapitre_id)
    affectation_id = chapitre.affectation_id
    enregistrer_action(acteur=request.user, action="suppression_chapitre_programme", cible=str(chapitre.affectation), request=request)
    chapitre.delete()
    messages.success(request, "Chapitre supprimé.")
    return redirect("pedagogie:programme_affectation", affectation_id=affectation_id)


@module_requis(Module.SUIVI_DES_COURS)
def avancement_programmes(request):
    """Pour la direction : l'avancement de chaque matière de chaque classe visible, les plus en retard d'abord."""
    affectations = list(
        Affectation.objects.filter(classe__in=classes_visibles_pour(request.user), classe__annee_scolaire__est_archivee=False)
        .select_related("classe__annee_scolaire", "enseignant").prefetch_related("chapitres").order_by("classe__nom", "matiere", "pk")
    )
    lignes = []
    for affectation in affectations:
        resume = resume_du_programme(affectation.chapitres.all())
        lignes.append({"affectation": affectation, **resume})
    # Les retards d'abord (le plus de chapitres en retard en tête), puis les moins avancés ; les matières sans programme à la fin.
    lignes.sort(key=lambda l: (l["nombre"] == 0, -l["en_retard"], l["avancement"], l["affectation"].classe.nom))
    return render(request, "pedagogie/avancement_programmes.html", {
        "lignes": lignes, "total_en_retard": sum(l["en_retard"] for l in lignes), "aujourdhui": datetime.date.today(),
    })
