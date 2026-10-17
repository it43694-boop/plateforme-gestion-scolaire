"""
Calendrier scolaire : lecture pour tous les comptes de l'école ; ajout, modification et suppression par le secrétariat et la direction.
Les dates « réservées au personnel » n'apparaissent ni chez les parents ni chez les élèves.
"""
import datetime
from itertools import groupby

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from comptes.audit import enregistrer_action
from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role
from scolarite.forms import EvenementCalendrierForm
from scolarite.models import AnneeScolaire, EvenementCalendrier, TypeEvenement, evenements_visibles_pour

ROLES_GESTION_CALENDRIER = {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL} | {
    Role.SECRETAIRE.value, Role.SUPER_ADMINISTRATEUR.value, Role.DIRECTEUR_1ER_CYCLE.value, Role.DIRECTEUR_2EME_CYCLE.value,
    Role.DIRECTEUR_LYCEE.value,
}


def _ecole_du_compte(request):
    if request.user.etablissement_id is None:
        raise Http404("Aucun établissement.")
    return request.user.etablissement


def _peut_gerer(utilisateur) -> bool:
    return utilisateur.role in ROLES_GESTION_CALENDRIER


def _annee_choisie(request, ecole):
    annees = AnneeScolaire.objects.filter(etablissement=ecole).order_by("-date_debut")
    choisie = request.GET.get("annee", "")
    if choisie.isdigit():
        annee = annees.filter(pk=int(choisie)).first()
        if annee:
            return annee, annees
    return AnneeScolaire.active(ecole) or annees.first(), annees


@login_required
def calendrier(request):
    ecole = _ecole_du_compte(request)
    annee, annees = _annee_choisie(request, ecole)
    evenements = evenements_visibles_pour(request.user)
    type_choisi = request.GET.get("type", "")
    if type_choisi in TypeEvenement.values:
        evenements = evenements.filter(type_evenement=type_choisi)
    else:
        type_choisi = ""
    if annee is not None:
        evenements = evenements.filter(date_debut__lte=annee.date_fin).exclude(date_fin__lt=annee.date_debut)
    liste = [e for e in evenements.order_by("date_debut", "date_fin", "pk") if annee is None or e.fin >= annee.date_debut]
    mois = [(cle, list(groupe)) for cle, groupe in groupby(liste, key=lambda e: (e.date_debut.year, e.date_debut.month))]
    return render(request, "scolarite/calendrier.html", {
        "annee": annee, "annees": annees, "mois": [(datetime.date(a, m, 1), groupe) for (a, m), groupe in mois],
        "types": TypeEvenement.choices, "type_choisi": type_choisi, "peut_gerer": _peut_gerer(request.user),
        "aujourdhui": datetime.date.today(), "total": len(liste),
    })


def _verifier_gestion(request):
    _ecole_du_compte(request)
    if not _peut_gerer(request.user):
        raise PermissionDenied("Vous n'avez pas le droit de modifier le calendrier.")


@login_required
@require_http_methods(["GET", "POST"])
def ajouter_evenement(request):
    _verifier_gestion(request)
    formulaire = EvenementCalendrierForm(request.POST or None)
    if request.method == "POST" and formulaire.is_valid():
        evenement = formulaire.save(commit=False)
        evenement.etablissement = request.user.etablissement
        evenement.cree_par = request.user
        evenement.save()
        enregistrer_action(acteur=request.user, action="ajout_evenement_calendrier", cible=evenement.titre, request=request)
        messages.success(request, "Évènement ajouté au calendrier.")
        return redirect("scolarite:calendrier")
    return render(request, "scolarite/formulaire_evenement.html", {"formulaire": formulaire, "evenement": None})


@login_required
@require_http_methods(["GET", "POST"])
def modifier_evenement(request, evenement_id):
    _verifier_gestion(request)
    evenement = get_object_or_404(EvenementCalendrier, pk=evenement_id, etablissement_id=request.user.etablissement_id)
    formulaire = EvenementCalendrierForm(request.POST or None, instance=evenement)
    if request.method == "POST" and formulaire.is_valid():
        formulaire.save()
        enregistrer_action(acteur=request.user, action="modification_evenement_calendrier", cible=evenement.titre, request=request)
        messages.success(request, "Évènement modifié.")
        return redirect("scolarite:calendrier")
    return render(request, "scolarite/formulaire_evenement.html", {"formulaire": formulaire, "evenement": evenement})


@login_required
@require_POST
def supprimer_evenement(request, evenement_id):
    _verifier_gestion(request)
    evenement = get_object_or_404(EvenementCalendrier, pk=evenement_id, etablissement_id=request.user.etablissement_id)
    enregistrer_action(acteur=request.user, action="suppression_evenement_calendrier", cible=evenement.titre, request=request)
    evenement.delete()
    messages.success(request, "Évènement supprimé.")
    return redirect("scolarite:calendrier")
