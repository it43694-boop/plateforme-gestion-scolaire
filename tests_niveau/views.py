from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from permissions_matrix.modules import Module
from scolarite.models import classes_visibles_pour
from tests_niveau.forms import AjouterCandidatForm
from tests_niveau.models import Candidat, Decision, candidats_visibles_pour, decider_candidat


@module_requis(Module.TESTS_DE_NIVEAU)
def liste_candidats(request):
    candidats = candidats_visibles_pour(request.user)
    page_obj = Paginator(candidats, 25).get_page(request.GET.get("page"))
    return render(request, "tests_niveau/liste_candidats.html", {
        "page_obj": page_obj, "candidats": page_obj.object_list,
    })


@module_requis(Module.TESTS_DE_NIVEAU)
def ajouter_candidat(request):
    formulaire = AjouterCandidatForm(request.POST or None, classes_disponibles=classes_visibles_pour(request.user))
    if request.method == "POST" and formulaire.is_valid():
        candidat = formulaire.save(commit=False)
        candidat.cree_par = request.user
        candidat.full_clean()
        candidat.save()
        enregistrer_action(
            acteur=request.user, action="ajout_candidat", cible=candidat.nom_complet, request=request,
        )
        messages.success(request, f"Candidat {candidat.nom_complet} enregistré.")
        return redirect("tests_niveau:liste_candidats")
    return render(request, "tests_niveau/ajouter_candidat.html", {"formulaire": formulaire})


@module_requis(Module.TESTS_DE_NIVEAU)
@require_http_methods(["POST"])
def decider_candidat_vue(request, candidat_id, decision):
    candidat = get_object_or_404(candidats_visibles_pour(request.user), id=candidat_id)
    try:
        decision_valeur = {"admis": Decision.ADMIS, "refuse": Decision.REFUSE}[decision]
    except KeyError:
        messages.error(request, "Décision invalide.")
        return redirect("tests_niveau:liste_candidats")

    try:
        decider_candidat(candidat=candidat, decision=decision_valeur, acteur=request.user)
    except ValidationError as erreur:
        messages.error(request, "; ".join(erreur.messages))
    else:
        enregistrer_action(
            acteur=request.user, action="decision_candidat",
            cible=candidat.nom_complet, details={"decision": decision_valeur}, request=request,
        )
        messages.success(request, f"{candidat.nom_complet} : {candidat.get_decision_display().lower()}.")
    return redirect("tests_niveau:liste_candidats")
