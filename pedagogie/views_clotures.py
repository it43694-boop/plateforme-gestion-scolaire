"""Page de clôture des notes par trimestre (fondateur, administrateur général, développeur)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from comptes.audit import enregistrer_action
from pedagogie.clotures import ROLES_CLOTURE, cloturer, rouvrir
from pedagogie.models import PeriodeCloturee, Trimestre
from scolarite.models import AnneeScolaire


def _verifier_droit(request):
    if request.user.etablissement_id is None:
        raise Http404("Aucun établissement.")
    if request.user.role not in ROLES_CLOTURE:
        raise PermissionDenied("Seule la direction peut clôturer ou rouvrir les notes d'un trimestre.")


def _annee(request, annee_id):
    return get_object_or_404(AnneeScolaire, pk=annee_id, etablissement_id=request.user.etablissement_id)


@login_required
def clotures_notes(request):
    _verifier_droit(request)
    annees = AnneeScolaire.objects.filter(etablissement_id=request.user.etablissement_id).order_by("-date_debut")
    choisie = request.GET.get("annee", "")
    annee = annees.filter(pk=int(choisie)).first() if choisie.isdigit() else None
    annee = annee or AnneeScolaire.active(request.user.etablissement) or annees.first()
    lignes = []
    if annee is not None:
        clotures = {c.trimestre: c for c in PeriodeCloturee.objects.filter(annee_scolaire=annee).select_related("cloturee_par")}
        for valeur, libelle in Trimestre.choices:
            cloture = clotures.get(valeur)
            lignes.append({
                "valeur": valeur, "libelle": libelle, "cloturee": annee.est_archivee or cloture is not None,
                "par": cloture.cloturee_par if cloture else None, "le": cloture.cloturee_le if cloture else None,
            })
    return render(request, "pedagogie/clotures_notes.html", {"annee": annee, "annees": annees, "lignes": lignes})


@login_required
@require_POST
def cloturer_periode(request, annee_id, trimestre):
    _verifier_droit(request)
    annee = _annee(request, annee_id)
    if trimestre not in dict(Trimestre.choices):
        raise Http404("Trimestre inconnu.")
    if annee.est_archivee:
        messages.info(request, "Cette année scolaire est archivée : tous ses trimestres sont déjà clôturés.")
    elif cloturer(annee, trimestre, request.user):
        enregistrer_action(
            acteur=request.user, action="cloture_notes", cible=f"{annee.libelle} - {trimestre}", request=request,
        )
        messages.success(request, f"Notes du {dict(Trimestre.choices)[trimestre]} clôturées.")
    return redirect(f"{reverse('pedagogie:clotures_notes')}?annee={annee.pk}")


@login_required
@require_POST
def rouvrir_periode(request, annee_id, trimestre):
    _verifier_droit(request)
    annee = _annee(request, annee_id)
    if trimestre not in dict(Trimestre.choices):
        raise Http404("Trimestre inconnu.")
    try:
        if rouvrir(annee, trimestre):
            enregistrer_action(
                acteur=request.user, action="reouverture_notes", cible=f"{annee.libelle} - {trimestre}", request=request,
            )
            messages.success(request, f"Notes du {dict(Trimestre.choices)[trimestre]} rouvertes.")
    except ValidationError as erreur:
        messages.error(request, erreur.messages[0])
    return redirect(f"{reverse('pedagogie:clotures_notes')}?annee={annee.pk}")
