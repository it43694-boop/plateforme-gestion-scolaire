from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from permissions_matrix.modules import Module
from scolarite.models import classes_visibles_pour
from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role
from tests_niveau.forms import AjouterCandidatForm
from tests_niveau.forms_publics import CampagneForm, ConvocationForm
from tests_niveau.models import (
    Candidat, CampagnePreinscription, Decision, StatutDemande, candidats_visibles_pour, decider_candidat,
)
from tests_niveau.preinscription import annoncer_la_decision, convoquer, refuser_la_demande

ROLES_CAMPAGNES = {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL} | {Role.SUPER_ADMINISTRATEUR.value}
STATUTS_SANS_DECISION = (StatutDemande.RECUE, StatutDemande.REFUSEE)  # il faut d'abord convoquer au test


@module_requis(Module.TESTS_DE_NIVEAU)
def liste_candidats(request):
    candidats = candidats_visibles_pour(request.user)
    demande = request.GET.get("demande", "")
    if demande in StatutDemande.values:
        candidats = candidats.filter(statut_demande=demande)
    else:
        demande = ""
    page_obj = Paginator(candidats, 25).get_page(request.GET.get("page"))
    a_traiter = candidats_visibles_pour(request.user).filter(statut_demande=StatutDemande.RECUE).count()
    return render(request, "tests_niveau/liste_candidats.html", {
        "page_obj": page_obj, "candidats": page_obj.object_list, "demande": demande, "a_traiter": a_traiter,
        "statuts": StatutDemande.choices, "peut_gerer_campagnes": request.user.role in ROLES_CAMPAGNES,
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
    if candidat.statut_demande in STATUTS_SANS_DECISION:
        messages.error(request, "Convoquez d'abord ce candidat au test : la décision vient après.")
        return redirect("tests_niveau:liste_candidats")

    try:
        decider_candidat(candidat=candidat, decision=decision_valeur, acteur=request.user)
    except ValidationError as erreur:
        messages.error(request, "; ".join(erreur.messages))
    else:
        if candidat.statut_demande == StatutDemande.CONVOQUE:
            Candidat.objects.filter(pk=candidat.pk).update(statut_demande=StatutDemande.TRAITEE)
        prevenue = annoncer_la_decision(candidat)  # courriel à la famille, si elle a donné une adresse
        enregistrer_action(
            acteur=request.user, action="decision_candidat",
            cible=candidat.nom_complet, details={"decision": decision_valeur, "famille_prevenue": prevenue}, request=request,
        )
        messages.success(request, f"{candidat.nom_complet} : {candidat.get_decision_display().lower()}.")
    return redirect("tests_niveau:liste_candidats")


@module_requis(Module.TESTS_DE_NIVEAU)
@require_http_methods(["GET", "POST"])
def convoquer_candidat(request, candidat_id):
    """Répondre à une demande en ligne : convoquer la famille au test (date choisie, courriel envoyé)."""
    candidat = get_object_or_404(candidats_visibles_pour(request.user), id=candidat_id)
    if candidat.statut_demande not in (StatutDemande.RECUE, StatutDemande.CONVOQUE):
        messages.error(request, "Cette demande ne peut plus être convoquée.")
        return redirect("tests_niveau:liste_candidats")
    formulaire = ConvocationForm(request.POST or None, initial={"date_test": candidat.date_test} if candidat.date_test else None)
    if request.method == "POST" and formulaire.is_valid():
        prevenue = convoquer(candidat, formulaire.cleaned_data["date_test"])
        enregistrer_action(
            acteur=request.user, action="convocation_candidat", cible=candidat.nom_complet,
            details={"date_test": formulaire.cleaned_data["date_test"].isoformat(), "famille_prevenue": prevenue}, request=request,
        )
        messages.success(request, f"{candidat.nom_complet} est convoqué(e) au test." + (" La famille a été prévenue." if prevenue else ""))
        return redirect("tests_niveau:liste_candidats")
    return render(request, "tests_niveau/convoquer_candidat.html", {"candidat": candidat, "formulaire": formulaire})


@module_requis(Module.TESTS_DE_NIVEAU)
@require_http_methods(["POST"])
def refuser_demande(request, candidat_id):
    """Répondre à une demande en ligne : la refuser (courriel envoyé à la famille)."""
    candidat = get_object_or_404(candidats_visibles_pour(request.user), id=candidat_id)
    if candidat.statut_demande != StatutDemande.RECUE:
        messages.error(request, "Seule une demande reçue peut être refusée ici.")
        return redirect("tests_niveau:liste_candidats")
    prevenue = refuser_la_demande(candidat)
    enregistrer_action(
        acteur=request.user, action="refus_demande_preinscription", cible=candidat.nom_complet, details={"famille_prevenue": prevenue}, request=request,
    )
    messages.success(request, "Demande refusée." + (" La famille a été prévenue." if prevenue else ""))
    return redirect("tests_niveau:liste_candidats")


def _verifier_droit_campagnes(utilisateur):
    if utilisateur.role not in ROLES_CAMPAGNES or utilisateur.etablissement_id is None:
        raise PermissionDenied("Seule la direction gère les campagnes de pré-inscription.")


@module_requis(Module.TESTS_DE_NIVEAU)
@require_http_methods(["GET", "POST"])
def campagnes(request):
    """Les campagnes de pré-inscription de l'école : en ouvrir une, voir son lien à partager, la fermer ou la rouvrir."""
    _verifier_droit_campagnes(request.user)
    formulaire = CampagneForm(request.POST or None, etablissement=request.user.etablissement)
    if request.method == "POST" and formulaire.is_valid():
        campagne = formulaire.save(commit=False)
        campagne.cree_par = request.user
        campagne.save()
        enregistrer_action(acteur=request.user, action="creation_campagne_preinscription", cible=campagne.titre, request=request)
        messages.success(request, "Campagne de pré-inscription créée : partagez son lien avec les familles.")
        return redirect("tests_niveau:campagnes")
    liste = [
        {"campagne": c, "lien": request.build_absolute_uri(reverse("tests_niveau:preinscription", args=[c.jeton])), "demandes": c.demandes.count(), "ouverte": c.est_ouverte()}
        for c in CampagnePreinscription.objects.filter(etablissement=request.user.etablissement).select_related("annee_scolaire")
    ]
    return render(request, "tests_niveau/campagnes.html", {"formulaire": formulaire, "liste": liste})


@module_requis(Module.TESTS_DE_NIVEAU)
@require_http_methods(["POST"])
def basculer_campagne(request, campagne_id):
    _verifier_droit_campagnes(request.user)
    campagne = get_object_or_404(CampagnePreinscription, pk=campagne_id, etablissement=request.user.etablissement)
    campagne.active = not campagne.active
    campagne.save(update_fields=["active"])
    enregistrer_action(
        acteur=request.user, action="ouverture_campagne_preinscription" if campagne.active else "fermeture_campagne_preinscription",
        cible=campagne.titre, request=request,
    )
    messages.success(request, "Campagne rouverte." if campagne.active else "Campagne fermée : le lien ne reçoit plus de demande.")
    return redirect("tests_niveau:campagnes")
