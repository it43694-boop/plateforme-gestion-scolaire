"""Frais annexes (tenue, examen, transport...) et arriérés des années passées : pages de la comptabilité et de la direction."""
from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from comptes.forms import BootstrapFormMixin
from finances.annexes import inscriptions_passees, lignes_d_arrieres
from finances.models import FraisAnnexe, Paiement
from finances.views import _peut_gerer_les_paiements
from permissions_matrix.modules import Module
from scolarite.models import AnneeScolaire, Classe, Inscription


class FraisAnnexeForm(BootstrapFormMixin, forms.ModelForm):
    montant = forms.IntegerField(label="Montant", min_value=1)

    class Meta:
        model = FraisAnnexe
        fields = ["annee_scolaire", "classe", "libelle", "montant", "date_limite"]
        widgets = {"date_limite": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, etablissement, **kwargs):
        super().__init__(*args, **kwargs)
        self.etablissement = etablissement
        self.fields["annee_scolaire"].queryset = AnneeScolaire.objects.filter(etablissement=etablissement, est_archivee=False).order_by("-date_debut")
        self.fields["classe"].queryset = Classe.objects.filter(annee_scolaire__etablissement=etablissement, annee_scolaire__est_archivee=False).select_related("annee_scolaire")
        self.fields["classe"].empty_label = "Toute l'école"
        self.fields["classe"].label = "Classe"
        self.fields["annee_scolaire"].label = "Année scolaire"
        self.fields["montant"].label = f"Montant ({getattr(etablissement, 'code_devise', 'FCFA')})"

    def clean_libelle(self):
        return " ".join(self.cleaned_data["libelle"].split())

    def clean(self):
        cleaned = super().clean()
        classe, annee = cleaned.get("classe"), cleaned.get("annee_scolaire")
        if classe and annee and classe.annee_scolaire_id != annee.pk:
            self.add_error("classe", "Cette classe n'appartient pas à l'année scolaire choisie.")
        return cleaned

    def save(self, commit=True):
        frais = super().save(commit=False)
        frais.etablissement = self.etablissement
        if commit:
            frais.save()
        return frais


def _droit(request):
    if not _peut_gerer_les_paiements(request.user):
        raise PermissionDenied("Vous n'avez pas le droit de gérer les frais annexes.")


@module_requis(Module.FINANCES)
@require_http_methods(["GET", "POST"])
def frais_annexes(request):
    _droit(request)
    ecole = request.user.etablissement
    formulaire = FraisAnnexeForm(request.POST or None, etablissement=ecole)
    if request.method == "POST" and formulaire.is_valid():
        frais = formulaire.save(commit=False)
        frais.cree_par = request.user
        frais.save()
        enregistrer_action(acteur=request.user, action="creation_frais_annexe", cible=frais.libelle, details={"montant": frais.montant}, request=request)
        messages.success(request, "Frais annexe ajouté.")
        return redirect("finances:frais_annexes")
    liste = []
    for frais in FraisAnnexe.objects.filter(etablissement=ecole).select_related("annee_scolaire", "classe"):
        concernes = Inscription.objects.filter(classe__annee_scolaire_id=frais.annee_scolaire_id).exclude(statut=Inscription.Statut.ABANDON)
        if frais.classe_id:
            concernes = concernes.filter(classe_id=frais.classe_id)
        paiements = Paiement.objects.filter(frais_annexe=frais, est_supprime=False).aggregate(total=Sum("montant"), payeurs=Count("eleve", distinct=True))
        nombre = concernes.count()
        liste.append({
            "frais": frais, "concernes": nombre, "total_attendu": nombre * frais.montant,
            "total_paye": paiements["total"] or 0, "payeurs": paiements["payeurs"] or 0,
            "supprimable": not Paiement.objects.filter(frais_annexe=frais).exists(),
        })
    return render(request, "finances/frais_annexes.html", {"formulaire": formulaire, "liste": liste})


@module_requis(Module.FINANCES)
@require_POST
def supprimer_frais_annexe(request, frais_id):
    _droit(request)
    frais = get_object_or_404(FraisAnnexe, pk=frais_id, etablissement=request.user.etablissement)
    if Paiement.objects.filter(frais_annexe=frais).exists():
        messages.error(request, "Ce frais annexe a déjà reçu des paiements : il ne peut plus être supprimé.")
    else:
        enregistrer_action(acteur=request.user, action="suppression_frais_annexe", cible=frais.libelle, request=request)
        frais.delete()
        messages.success(request, "Frais annexe supprimé.")
    return redirect("finances:frais_annexes")


@module_requis(Module.FINANCES)
def arrieres(request):
    """Les élèves qui doivent encore de l'argent pour une année passée, avec un lien pour régler (paiement pré-rempli)."""
    _droit(request)
    annee_id = request.GET.get("annee", "")
    recherche = request.GET.get("q", "").strip()
    inscriptions = inscriptions_passees(request.user).select_related("eleve", "classe__annee_scolaire")
    if annee_id.isdigit():
        inscriptions = inscriptions.filter(classe__annee_scolaire_id=int(annee_id))
    if recherche:
        inscriptions = inscriptions.filter(Q(eleve__nom__icontains=recherche) | Q(eleve__prenom__icontains=recherche) | Q(eleve__matricule__icontains=recherche))
    lignes = lignes_d_arrieres(inscriptions)
    page_obj = Paginator(lignes, 30).get_page(request.GET.get("page"))
    return render(request, "finances/arrieres.html", {
        "page_obj": page_obj, "lignes": page_obj.object_list, "total": sum(ligne["solde"] for ligne in lignes),
        "annees": AnneeScolaire.objects.filter(etablissement=request.user.etablissement).order_by("-date_debut"),
        "annee_id": annee_id, "recherche": recherche,
    })
