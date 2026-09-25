from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_http_methods
from xhtml2pdf import pisa

from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from comptes.models import Utilisateur
from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role
from finances.forms import CorrigerPaiementForm, EnregistrerPaiementForm, SaisirSalaireForm
from finances.models import (
    MouvementCaisse, Paiement, Salaire,
    corriger_paiement, enregistrer_paiement, marquer_salaire_paye,
    supprimer_paiement, supprimer_salaire,
)
from permissions_matrix.modules import Module


def _est_direction(utilisateur) -> bool:
    return utilisateur.role in {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL}


# ---------------------------------------------------------------------------
# Finances (paiements de scolarité)
# ---------------------------------------------------------------------------

@module_requis(Module.FINANCES)
def rechercher_eleve_json(request):
    """Recherche en direct (JS) du nom d'un élève par matricule, pour l'aperçu avant paiement."""
    from django.http import JsonResponse
    matricule = request.GET.get("matricule", "").strip()
    eleve = Utilisateur.objects.filter(
        matricule=matricule, role=Role.ELEVE, etablissement=request.user.etablissement,
    ).first()
    if not eleve:
        return JsonResponse({"trouve": False})
    return JsonResponse({"trouve": True, "nom_complet": eleve.nom_complet})


@module_requis(Module.FINANCES)
def suivi_paiements(request):
    """
    Pour chaque élève inscrit : total dû (échéancier de sa classe), total
    déjà payé, solde restant. Répond directement à la question « qui n'a
    pas encore tout payé ? » - absente jusqu'ici de l'application.
    """
    from django.db.models import Q, Sum
    from django.db.models.functions import Coalesce
    from scolarite.models import Inscription, calculer_total_du, classes_visibles_pour

    filtre_statut = request.GET.get("statut", "")
    classe_id = request.GET.get("classe", "")

    inscriptions = Inscription.objects.filter(
        classe__in=classes_visibles_pour(request.user), statut=Inscription.Statut.EN_COURS,
    ).select_related("eleve", "classe", "classe__echeancier").annotate(
        total_paye=Coalesce(Sum("paiements__montant", filter=Q(paiements__est_supprime=False)), 0),
    ).order_by("classe__nom", "eleve__nom")

    if request.user.role == Role.PARENT:
        inscriptions = inscriptions.filter(eleve__parents_lies=request.user)

    if classe_id:
        inscriptions = inscriptions.filter(classe_id=classe_id)

    lignes = []
    for inscription in inscriptions:
        total_du = calculer_total_du(inscription)
        solde = total_du - inscription.total_paye
        statut = "paye" if solde <= 0 else ("partiel" if inscription.total_paye > 0 else "impaye")
        if filtre_statut and statut != filtre_statut:
            continue
        lignes.append({
            "inscription": inscription, "total_du": total_du,
            "total_paye": inscription.total_paye, "solde": solde, "statut": statut,
        })

    page_obj = Paginator(lignes, 30).get_page(request.GET.get("page"))
    return render(request, "finances/suivi_paiements.html", {
        "page_obj": page_obj, "lignes": page_obj.object_list,
        "classes": classes_visibles_pour(request.user) if request.user.role != Role.PARENT else classes_visibles_pour(request.user).filter(
            inscriptions__eleve__parents_lies=request.user,
        ).distinct(), "classe_id": classe_id, "filtre_statut": filtre_statut,
    })


@module_requis(Module.FINANCES)
def enregistrer_paiement_vue(request):
    matricule_recherche = request.GET.get("matricule", "").strip()
    eleve_apercu = None
    if matricule_recherche:
        eleve_apercu = Utilisateur.objects.filter(
            matricule=matricule_recherche, role=Role.ELEVE, etablissement=request.user.etablissement,
        ).first()

    initial = {"matricule_eleve": matricule_recherche} if matricule_recherche else None
    formulaire = EnregistrerPaiementForm(request.POST or None, etablissement=request.user.etablissement, initial=initial)
    if request.method == "POST" and formulaire.is_valid():
        paiement = enregistrer_paiement(
            eleve=formulaire.cleaned_data["eleve"],
            inscription=formulaire.cleaned_data["inscription"],
            tranche=formulaire.cleaned_data["tranche"],
            montant=formulaire.cleaned_data["montant"],
            mode_paiement=formulaire.cleaned_data["mode_paiement"],
            enregistre_par=request.user,
        )
        enregistrer_action(
            acteur=request.user, action="enregistrement_paiement",
            cible=paiement.reference,
            details={"eleve": paiement.eleve.matricule, "montant": paiement.montant},
            request=request,
        )
        messages.success(request, f"Paiement enregistré. Référence : {paiement.reference}")
        return redirect("finances:liste_paiements")
    return render(request, "finances/enregistrer_paiement.html", {
        "formulaire": formulaire, "eleve_apercu": eleve_apercu, "matricule_recherche": matricule_recherche,
    })


@module_requis(Module.FINANCES)
def exporter_recu_paiement_pdf(request, paiement_id):
    paiement = get_object_or_404(
        Paiement, id=paiement_id, est_supprime=False, etablissement=request.user.etablissement,
    )
    html = render_to_string("finances/recu_paiement_pdf.html", {"paiement": paiement}, request=request)

    reponse = HttpResponse(content_type="application/pdf")
    reponse["Content-Disposition"] = f'attachment; filename="recu_{paiement.reference}.pdf"'
    resultat = pisa.CreatePDF(html, dest=reponse, encoding="utf-8")
    if resultat.err:
        return HttpResponse("Erreur lors de la génération du reçu.", status=500)
    return reponse


@module_requis(Module.FINANCES)
def liste_paiements(request):
    paiements = Paiement.objects.filter(
        est_supprime=False, etablissement=request.user.etablissement,
    ).select_related("eleve", "inscription__classe")
    page_obj = Paginator(paiements, 25).get_page(request.GET.get("page"))
    return render(request, "finances/liste_paiements.html", {
        "page_obj": page_obj, "paiements": page_obj.object_list, "est_direction": _est_direction(request.user),
    })


@module_requis(Module.FINANCES)
def corriger_paiement_vue(request, paiement_id):
    paiement = get_object_or_404(
        Paiement, id=paiement_id, est_supprime=False, etablissement=request.user.etablissement,
    )
    formulaire = CorrigerPaiementForm(request.POST or None, etablissement=paiement.etablissement, initial={
        "montant": paiement.montant, "mode_paiement": paiement.mode_paiement,
    })
    if request.method == "POST" and formulaire.is_valid():
        corriger_paiement(
            paiement=paiement, montant=formulaire.cleaned_data["montant"],
            mode_paiement=formulaire.cleaned_data["mode_paiement"], acteur=request.user,
        )
        enregistrer_action(
            acteur=request.user, action="correction_paiement",
            cible=paiement.reference, request=request,
        )
        messages.success(request, "Paiement corrigé.")
        return redirect("finances:liste_paiements")
    return render(request, "finances/corriger_paiement.html", {"formulaire": formulaire, "paiement": paiement})


@module_requis(Module.FINANCES)
@require_http_methods(["POST"])
def supprimer_paiement_vue(request, paiement_id):
    if not _est_direction(request.user):
        raise PermissionDenied("Seule la direction peut supprimer un paiement.")
    paiement = get_object_or_404(
        Paiement, id=paiement_id, est_supprime=False, etablissement=request.user.etablissement,
    )
    supprimer_paiement(paiement=paiement, acteur=request.user)
    enregistrer_action(
        acteur=request.user, action="suppression_paiement",
        cible=paiement.reference, request=request,
    )
    messages.success(request, "Paiement supprimé (ligne de Caisse annulée).")
    return redirect("finances:liste_paiements")


# ---------------------------------------------------------------------------
# Salaires
# ---------------------------------------------------------------------------

@module_requis(Module.SALAIRES)
def rechercher_employe_json(request):
    """Recherche en direct (JS) du nom d'un employé par email, pour l'aperçu avant saisie de salaire."""
    from django.http import JsonResponse
    email = request.GET.get("email", "").strip()
    employe = Utilisateur.objects.filter(email__iexact=email, etablissement=request.user.etablissement).first()
    if not employe:
        return JsonResponse({"trouve": False})
    return JsonResponse({"trouve": True, "nom_complet": employe.nom_complet, "role": employe.get_role_display()})


@module_requis(Module.SALAIRES)
def saisir_salaire_vue(request):
    email_recherche = request.GET.get("email", "").strip()
    employe_apercu = None
    if email_recherche:
        employe_apercu = Utilisateur.objects.filter(
            email__iexact=email_recherche, etablissement=request.user.etablissement,
        ).first()

    initial = {"email_employe": email_recherche} if email_recherche else None
    formulaire = SaisirSalaireForm(request.POST or None, etablissement=request.user.etablissement, initial=initial)
    if request.method == "POST" and formulaire.is_valid():
        salaire = Salaire.objects.create(
            employe=formulaire.cleaned_data["employe"],
            etablissement=request.user.etablissement,
            periode=formulaire.cleaned_data["periode"],
            montant=formulaire.cleaned_data["montant"],
            enregistre_par=request.user,
        )
        enregistrer_action(
            acteur=request.user, action="saisie_salaire",
            cible=f"{salaire.employe.nom_complet} - {salaire.periode}", request=request,
        )
        messages.success(request, "Salaire enregistré (en attente de paiement).")
        return redirect("finances:liste_salaires")
    return render(request, "finances/saisir_salaire.html", {
        "formulaire": formulaire, "employe_apercu": employe_apercu, "email_recherche": email_recherche,
    })


@module_requis(Module.SALAIRES)
def liste_salaires(request):
    salaires = Salaire.objects.filter(
        est_supprime=False, etablissement=request.user.etablissement,
    ).select_related("employe")
    page_obj = Paginator(salaires, 25).get_page(request.GET.get("page"))
    return render(request, "finances/liste_salaires.html", {
        "page_obj": page_obj, "salaires": page_obj.object_list, "est_direction": _est_direction(request.user),
    })


@module_requis(Module.SALAIRES)
@require_http_methods(["POST"])
def marquer_salaire_paye_vue(request, salaire_id):
    salaire = get_object_or_404(
        Salaire, id=salaire_id, est_supprime=False, etablissement=request.user.etablissement,
    )
    try:
        marquer_salaire_paye(salaire=salaire, paye_par=request.user)
    except ValidationError as erreur:
        messages.error(request, "; ".join(erreur.messages) if hasattr(erreur, "messages") else str(erreur))
        return redirect("finances:liste_salaires")
    enregistrer_action(
        acteur=request.user, action="paiement_salaire",
        cible=salaire.reference, request=request,
    )
    messages.success(request, f"Salaire marqué payé. Référence : {salaire.reference}")
    return redirect("finances:liste_salaires")


@module_requis(Module.SALAIRES)
@require_http_methods(["POST"])
def supprimer_salaire_vue(request, salaire_id):
    if not _est_direction(request.user):
        raise PermissionDenied("Seule la direction peut supprimer un salaire.")
    salaire = get_object_or_404(
        Salaire, id=salaire_id, est_supprime=False, etablissement=request.user.etablissement,
    )
    supprimer_salaire(salaire=salaire, acteur=request.user)
    enregistrer_action(
        acteur=request.user, action="suppression_salaire",
        cible=f"{salaire.employe.nom_complet} - {salaire.periode}", request=request,
    )
    messages.success(request, "Salaire supprimé.")
    return redirect("finances:liste_salaires")


# ---------------------------------------------------------------------------
# Caisse (lecture seule - aucune saisie manuelle)
# ---------------------------------------------------------------------------

@module_requis(Module.CAISSE)
def registre_caisse(request):
    from django.db.models import Sum, Case, When, F, IntegerField
    mouvements = MouvementCaisse.objects.filter(
        etablissement=request.user.etablissement,
    ).select_related("paiement", "salaire")
    solde = mouvements.filter(annule=False).aggregate(
        solde=Sum(Case(
            When(type_mouvement=MouvementCaisse.TypeMouvement.ENTREE, then=F("montant")),
            When(type_mouvement=MouvementCaisse.TypeMouvement.SORTIE, then=-F("montant")),
            output_field=IntegerField(),
        ))
    )["solde"] or 0
    page_obj = Paginator(mouvements, 50).get_page(request.GET.get("page"))
    return render(request, "finances/registre_caisse.html", {
        "mouvements": page_obj.object_list, "page_obj": page_obj, "solde": solde,
    })
