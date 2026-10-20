"""Paiements Mobile Money déclarés par les parents : le parent déclare, la comptabilité valide (dans « Enregistrer un paiement ») ou refuse avec un motif."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit

from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from comptes.roles import Role
from finances.declarations import declarer, refuser
from finances.forms_declarations import DeclarerPaiementForm, RefuserDeclarationForm
from finances.models import PaiementDeclare, StatutDeclaration
from finances.views import _peut_gerer_les_paiements
from permissions_matrix.modules import Module


@module_requis(Module.FINANCES)
@ratelimit(key="user", rate="20/h", method="POST", block=False)
@require_http_methods(["GET", "POST"])
def declarer_paiement(request):
    """Un parent déclare un paiement Mobile Money pour l'un de ses enfants ; il voit l'état de ses déclarations (à valider, validé, refusé avec le motif)."""
    if request.user.role != Role.PARENT:
        raise PermissionDenied("Seul un parent déclare un paiement.")
    etablissement = request.user.etablissement
    formulaire = DeclarerPaiementForm(request.POST or None, request.FILES or None, parent=request.user, etablissement=etablissement)
    if request.method == "GET":
        enfant = formulaire.fields["eleve"].queryset.filter(matricule=request.GET.get("eleve", "")).first()
        if enfant is not None:
            formulaire.initial["eleve"] = enfant.pk
    elif getattr(request, "limited", False):
        messages.error(request, "Trop de déclarations en peu de temps. Réessayez dans une heure.")
    elif formulaire.is_valid():
        donnees = formulaire.cleaned_data
        try:
            declaration = declarer(
                parent=request.user, eleve=donnees["eleve"], montant=donnees["montant"], operateur=donnees["operateur"],
                reference=donnees["reference_transaction"], date_du_paiement=donnees["date_du_paiement"],
                telephone=donnees["telephone_payeur"], capture=donnees.get("capture"),
            )
        except ValidationError as erreur:
            formulaire.add_error(None, erreur.messages[0])
        else:
            enregistrer_action(
                acteur=request.user, action="declaration_paiement", cible=declaration.reference_transaction,
                details={"eleve": declaration.eleve.matricule, "montant": declaration.montant, "operateur": declaration.operateur}, request=request,
            )
            messages.success(request, "Votre déclaration est envoyée. L'école la vérifie, puis vous recevrez une notification et le reçu.")
            return redirect("finances:declarer_paiement")
    mes_declarations = (
        PaiementDeclare.objects.filter(etablissement=etablissement, eleve__parents_lies=request.user)
        .select_related("eleve", "inscription__classe", "paiement")[:30]
    )
    return render(request, "finances/declarer_paiement.html", {
        "formulaire": formulaire, "declarations": mes_declarations, "instructions": etablissement.instructions_mobile_money,
        "devise": getattr(etablissement, "code_devise", "FCFA"), "a_des_enfants": formulaire.fields["eleve"].queryset.exists(),
    })


@module_requis(Module.FINANCES)
def declarations(request):
    """La liste des paiements déclarés de l'école : à valider d'abord ; la comptabilité et la direction seulement."""
    if not _peut_gerer_les_paiements(request.user):
        raise PermissionDenied("Vous n'avez pas le droit de traiter les paiements déclarés.")
    etablissement = request.user.etablissement
    toutes = PaiementDeclare.objects.filter(etablissement=etablissement)
    statut = request.GET.get("statut", StatutDeclaration.EN_ATTENTE)
    liste = toutes.select_related("eleve", "inscription__classe", "declare_par", "traite_par", "paiement")
    if statut in StatutDeclaration.values:
        liste = liste.filter(statut=statut)
    else:
        statut = "tous"
    page_obj = Paginator(liste, 25).get_page(request.GET.get("page"))
    return render(request, "finances/declarations.html", {
        "page_obj": page_obj, "declarations": page_obj.object_list, "statut": statut,
        "a_valider": toutes.filter(statut=StatutDeclaration.EN_ATTENTE).count(), "devise": getattr(etablissement, "code_devise", "FCFA"),
    })


@module_requis(Module.FINANCES)
@require_http_methods(["GET", "POST"])
def refuser_declaration(request, declaration_id):
    if not _peut_gerer_les_paiements(request.user):
        raise PermissionDenied("Vous n'avez pas le droit de traiter les paiements déclarés.")
    declaration = get_object_or_404(
        PaiementDeclare.objects.select_related("eleve", "inscription__classe", "declare_par"), pk=declaration_id, etablissement=request.user.etablissement,
    )
    if declaration.statut != StatutDeclaration.EN_ATTENTE:
        messages.info(request, "Cette déclaration a déjà été traitée.")
        return redirect("finances:declarations")
    formulaire = RefuserDeclarationForm(request.POST or None)
    if request.method == "POST" and formulaire.is_valid():
        try:
            refuser(declaration, acteur=request.user, motif=formulaire.cleaned_data["motif"])
        except ValidationError as erreur:
            formulaire.add_error("motif", erreur.messages[0])
        else:
            enregistrer_action(
                acteur=request.user, action="refus_paiement_declare", cible=declaration.reference_transaction,
                details={"eleve": declaration.eleve.matricule, "montant": declaration.montant}, request=request,
            )
            messages.success(request, "Déclaration refusée : le parent en est informé.")
            return redirect("finances:declarations")
    return render(request, "finances/refuser_declaration.html", {
        "formulaire": formulaire, "declaration": declaration, "devise": getattr(request.user.etablissement, "code_devise", "FCFA"),
    })
