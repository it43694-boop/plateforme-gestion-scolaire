"""Anciens élèves : la liste de ceux qui ont quitté l'école et leur réintégration dans une classe."""
from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from comptes.forms import BootstrapFormMixin
from permissions_matrix.modules import Module
from scolarite.anciens import (
    STATUTS_DE_SORTIE, classes_de_reintegration, derniere_sortie_par_eleve, est_ancien_eleve, reintegrer,
)
from scolarite.models import (
    ROLES_ETAT_CIVIL_ELEVE, AnneeScolaire, Classe, Inscription, eleve_de_l_etablissement_ou_404, eleve_visible_pour,
)


class ReintegrationForm(BootstrapFormMixin, forms.Form):
    classe = forms.ModelChoiceField(label="Classe", queryset=Classe.objects.none())

    def __init__(self, *args, classes, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["classe"].queryset = classes.select_related("annee_scolaire")
        self.fields["classe"].label_from_instance = str


def _verifier_droit(utilisateur):
    if utilisateur.role not in ROLES_ETAT_CIVIL_ELEVE:
        raise PermissionDenied("Vous n'avez pas le droit de gérer les anciens élèves.")


@module_requis(Module.ELEVES)
def anciens_eleves(request):
    _verifier_droit(request.user)
    annee_id = request.GET.get("annee", "")
    recherche = request.GET.get("q", "").strip()
    lignes = derniere_sortie_par_eleve(request.user, annee_id=int(annee_id) if annee_id.isdigit() else None, recherche=recherche)
    page_obj = Paginator(lignes, 30).get_page(request.GET.get("page"))
    return render(request, "scolarite/anciens_eleves.html", {
        "page_obj": page_obj, "lignes": page_obj.object_list, "total": len(lignes), "recherche": recherche, "annee_id": annee_id,
        "annees": AnneeScolaire.objects.filter(etablissement=request.user.etablissement).order_by("-date_debut"),
    })


@module_requis(Module.ELEVES)
@require_http_methods(["GET", "POST"])
def reintegrer_eleve(request, matricule):
    _verifier_droit(request.user)
    eleve = eleve_de_l_etablissement_ou_404(request.user, matricule)
    if not eleve_visible_pour(request.user, eleve):
        raise PermissionDenied("Vous n'avez pas accès au dossier de cet élève.")
    if not est_ancien_eleve(eleve):
        messages.error(request, "Cet élève n'a pas quitté l'établissement : il n'y a rien à réintégrer.")
        return redirect("scolarite:dossier_eleve", matricule=eleve.matricule)
    formulaire = ReintegrationForm(request.POST or None, classes=classes_de_reintegration(request.user))
    if request.method == "POST" and formulaire.is_valid():
        classe = formulaire.cleaned_data["classe"]
        ancienne = Inscription.objects.filter(eleve=eleve, statut__in=STATUTS_DE_SORTIE).order_by("-classe__annee_scolaire__date_debut").first()
        try:
            inscription = reintegrer(eleve, classe)
        except ValidationError as erreur:
            formulaire.add_error(None, erreur.messages[0])
        else:
            enregistrer_action(
                acteur=request.user, action="reintegration_eleve", cible=eleve.matricule,
                details={"classe": str(classe), "sortie": ancienne.statut if ancienne else "", "inscription": inscription.pk}, request=request,
            )
            messages.success(request, f"{eleve.nom_complet} est réintégré(e) en {classe.nom}.")
            return redirect("scolarite:dossier_eleve", matricule=eleve.matricule)
    return render(request, "scolarite/reintegrer_eleve.html", {"eleve": eleve, "formulaire": formulaire})
