"""Registre de discipline : une classe (saisie des retards, avertissements, blâmes, convocations, exclusions) et l'historique d'un élève."""
import datetime

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from comptes.forms import BootstrapFormMixin
from comptes.models import Utilisateur
from pedagogie.discipline import (
    ROLES_SAISIE_DISCIPLINE, ROLES_SUPPRESSION_DISCIPLINE, SEUIL_DE_RETARDS, prevenir_les_parents, retards_du_mois,
)
from pedagogie.forms import EleveDeLaClasseMixin
from pedagogie.models import MesureDiscipline, TypeMesureDiscipline
from permissions_matrix.modules import Module
from scolarite.models import Affectation, classes_visibles_pour, eleve_de_l_etablissement_ou_404, eleve_visible_pour


class MesureDisciplineForm(EleveDeLaClasseMixin, BootstrapFormMixin, forms.Form):
    matricule_eleve = forms.CharField(label="Élève")
    date_mesure = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    type_mesure = forms.ChoiceField(label="Mesure", choices=TypeMesureDiscipline.choices)
    motif = forms.CharField(
        label="Motif", required=False, max_length=255, widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Obligatoire sauf pour un retard.",
    )

    def __init__(self, *args, classe, **kwargs):
        kwargs.setdefault("initial", {"date_mesure": datetime.date.today()})
        super().__init__(*args, **kwargs)
        self.preparer_champ_eleve(classe.id)

    def clean_date_mesure(self):
        date = self.cleaned_data["date_mesure"]
        if date > datetime.date.today():
            raise forms.ValidationError("Impossible d'enregistrer une mesure pour une date future.")
        return date

    def clean(self):
        donnees = super().clean()
        if donnees.get("type_mesure") and donnees["type_mesure"] != TypeMesureDiscipline.RETARD and not (donnees.get("motif") or "").strip():
            self.add_error("motif", "Indiquez le motif de la mesure.")
        return donnees


def _peut_saisir(utilisateur, classe) -> bool:
    if utilisateur.role not in ROLES_SAISIE_DISCIPLINE:
        return False
    if utilisateur.role == "enseignant":  # un enseignant ne traite que les classes où il est affecté
        return Affectation.objects.filter(enseignant=utilisateur, classe=classe).exists()
    return True


@module_requis(Module.ABSENCES)
@require_http_methods(["GET", "POST"])
def registre_discipline(request, classe_id):
    classe = get_object_or_404(classes_visibles_pour(request.user), id=classe_id)
    if not _peut_saisir(request.user, classe):
        raise PermissionDenied("Vous n'avez pas le droit d'enregistrer des mesures de discipline dans cette classe.")
    lecture_seule = classe.annee_scolaire.est_archivee
    formulaire = MesureDisciplineForm(request.POST or None, classe=classe)
    if request.method == "POST":
        if lecture_seule:
            raise PermissionDenied("Cette année scolaire est archivée.")
        if formulaire.is_valid():
            donnees = formulaire.cleaned_data
            eleve = Utilisateur.objects.get(matricule=donnees["matricule_eleve"], etablissement=request.user.etablissement)
            try:
                mesure = MesureDiscipline.objects.create(
                    eleve=eleve, classe=classe, date_mesure=donnees["date_mesure"], type_mesure=donnees["type_mesure"],
                    motif=(donnees["motif"] or "").strip(), enregistre_par=request.user,
                )
            except ValidationError as erreur:
                formulaire.add_error(None, erreur.messages[0])
            else:
                prevenus = prevenir_les_parents(mesure)
                enregistrer_action(
                    acteur=request.user, action="saisie_discipline", cible=eleve.matricule,
                    details={"type": mesure.type_mesure, "parents_prevenus": prevenus}, request=request,
                )
                message = f"{mesure.get_type_mesure_display()} enregistré(e) pour {eleve.nom_complet}."
                if prevenus:
                    message += " Les parents ont été prévenus."
                messages.success(request, message)
                return redirect("pedagogie:registre_discipline", classe_id=classe.id)
    mesures = MesureDiscipline.objects.filter(classe=classe).select_related("eleve").order_by("-date_mesure", "-pk")[:50]
    return render(request, "pedagogie/discipline_classe.html", {
        "classe": classe, "formulaire": formulaire, "mesures": mesures, "lecture_seule": lecture_seule,
        "peut_supprimer": request.user.role in ROLES_SUPPRESSION_DISCIPLINE, "seuil_de_retards": SEUIL_DE_RETARDS,
    })


@module_requis(Module.ABSENCES)
def historique_discipline(request, matricule):
    """L'historique de discipline d'un élève : lui-même, ses parents, l'enseignant qui lui enseigne et l'administration qui le suit."""
    eleve = eleve_de_l_etablissement_ou_404(request.user, matricule)
    if not eleve_visible_pour(request.user, eleve):
        raise PermissionDenied("Vous n'avez pas accès à l'historique de cet élève.")
    mesures = MesureDiscipline.objects.filter(eleve=eleve).select_related("classe")
    par_type = {ligne["type_mesure"]: ligne["total"] for ligne in mesures.values("type_mesure").annotate(total=Count("pk"))}
    page_obj = Paginator(mesures.order_by("-date_mesure", "-pk"), 30).get_page(request.GET.get("page"))
    return render(request, "pedagogie/discipline_eleve.html", {
        "eleve": eleve, "mesures": page_obj.object_list, "page_obj": page_obj, "total": mesures.count(),
        "totaux": [(libelle, par_type.get(code, 0)) for code, libelle in TypeMesureDiscipline.choices],
        "retards_ce_mois": retards_du_mois(eleve, datetime.date.today()), "seuil_de_retards": SEUIL_DE_RETARDS,
        "peut_supprimer": request.user.role in ROLES_SUPPRESSION_DISCIPLINE,
    })


@module_requis(Module.ABSENCES)
@require_POST
def supprimer_mesure_discipline(request, mesure_id):
    """Corriger une erreur de saisie : réservé à la vie scolaire et à la direction, pour une classe de leur périmètre."""
    if request.user.role not in ROLES_SUPPRESSION_DISCIPLINE:
        raise PermissionDenied("Vous n'avez pas le droit de supprimer une mesure de discipline.")
    mesure = get_object_or_404(MesureDiscipline.objects.select_related("eleve", "classe__annee_scolaire"), pk=mesure_id)
    get_object_or_404(classes_visibles_pour(request.user), pk=mesure.classe_id)  # une autre école ou un autre cycle : introuvable
    if mesure.classe.annee_scolaire.est_archivee:
        raise PermissionDenied("Cette année scolaire est archivée.")
    matricule = mesure.eleve.matricule
    enregistrer_action(
        acteur=request.user, action="suppression_discipline", cible=matricule, details={"type": mesure.type_mesure}, request=request,
    )
    mesure.delete()
    messages.success(request, "Mesure supprimée.")
    retour = request.POST.get("retour")
    if retour == "classe":
        return redirect("pedagogie:registre_discipline", classe_id=mesure.classe_id)
    return redirect("pedagogie:historique_discipline", matricule=matricule)
