"""
Cantine : le gérant (rôle « Personnel » avec le module Cantine) et la direction inscrivent les élèves, font l'appel du jour, encaissent et
délivrent les reçus ; les parents et les élèves consultent seulement leur propre suivi.
"""
import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from cantine import services
from cantine.forms import AnnulationForm, FormuleForm, InscrireForm, PaiementCantineForm, TerminerForm
from cantine.models import FormuleCantine, InscriptionCantine, PaiementCantine, RepasCantine
from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from comptes.excel import nom_fichier_sur
from comptes.models import Utilisateur
from comptes.pdf import creer_pdf
from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role
from permissions_matrix.modules import Module
from scolarite.models import AnneeScolaire, Classe, Inscription

DIRECTION = {role.value for role in ROLES_ACCES_TOTAL_INCONDITIONNEL}


def _ecole(request):
    if request.user.etablissement_id is None:
        raise Http404("Aucun établissement.")
    return request.user.etablissement


def _annee(ecole):
    return AnneeScolaire.active(ecole)


def _inscription_de_l_ecole(request, inscription_id):
    return get_object_or_404(
        InscriptionCantine.objects.select_related("eleve", "formule", "annee_scolaire"), pk=inscription_id, etablissement=_ecole(request),
    )


def _classes_des_eleves(eleves_ids, annee):
    """{id de l'élève: nom de sa classe de l'année} en une seule requête."""
    if annee is None:
        return {}
    return {
        ligne.eleve_id: ligne.classe.nom
        for ligne in Inscription.objects.filter(eleve_id__in=eleves_ids, classe__annee_scolaire=annee, statut=Inscription.Statut.EN_COURS)
        .select_related("classe")
    }


# ---------------------------------------------------------------------------
# Tableau de bord et fiches
# ---------------------------------------------------------------------------

@module_requis(Module.CANTINE)
def tableau(request):
    ecole = _ecole(request)
    annee = _annee(ecole)
    recherche = request.GET.get("q", "").strip()
    etat = request.GET.get("etat", "ouvertes")
    if etat not in {"ouvertes", "impayes", "terminees", "toutes"}:
        etat = "ouvertes"
    base = InscriptionCantine.objects.filter(etablissement=ecole, annee_scolaire=annee) if annee else InscriptionCantine.objects.none()
    if recherche:
        base = base.filter(Q(eleve__nom__icontains=recherche) | Q(eleve__prenom__icontains=recherche) | Q(eleve__matricule__icontains=recherche))
    lignes = services.avec_soldes(base)
    inscrits = sum(1 for ligne in lignes if ligne.ouverte)
    if etat == "ouvertes":
        lignes = [ligne for ligne in lignes if ligne.ouverte]
    elif etat == "impayes":
        lignes = [ligne for ligne in lignes if ligne.solde > 0]
    elif etat == "terminees":
        lignes = [ligne for ligne in lignes if not ligne.ouverte]
    page_obj = Paginator(lignes, 30).get_page(request.GET.get("page"))
    classes = _classes_des_eleves([ligne.eleve_id for ligne in page_obj.object_list], annee)
    for ligne in page_obj.object_list:
        ligne.classe_nom = classes.get(ligne.eleve_id, "")
    return render(request, "cantine/tableau.html", {
        "annee": annee, "page_obj": page_obj, "lignes": page_obj.object_list, "etat": etat, "recherche": recherche,
        "inscrits": inscrits, "total_du": sum(ligne.du for ligne in lignes), "total_paye": sum(ligne.total_paye for ligne in lignes),
        "total_reste": sum(ligne.solde for ligne in lignes if ligne.solde > 0), "nombre": len(lignes),
        "formules_actives": FormuleCantine.objects.filter(etablissement=ecole, active=True).exists(),
    })


@module_requis(Module.CANTINE)
def fiche_inscription(request, inscription_id):
    inscription = _inscription_de_l_ecole(request, inscription_id)
    solde = services.solde_de(inscription)
    repas = RepasCantine.objects.filter(inscription=inscription).order_by("-date_repas")[:60]
    paiements = PaiementCantine.objects.filter(inscription=inscription).select_related("enregistre_par").order_by("-date_paiement", "-pk")
    return render(request, "cantine/fiche.html", {
        "inscription": inscription, **solde, "repas": repas, "paiements": paiements,
        "peut_annuler": request.user.role in DIRECTION,
        "annee_ouverte": not inscription.annee_scolaire.est_archivee,
        "formulaire_fin": TerminerForm(),
        "formulaire_annulation": AnnulationForm(),
    })


# ---------------------------------------------------------------------------
# Inscription des élèves
# ---------------------------------------------------------------------------

@module_requis(Module.CANTINE)
@require_http_methods(["GET", "POST"])
def inscrire_eleves(request):
    ecole = _ecole(request)
    annee = _annee(ecole)
    if annee is None:
        messages.error(request, "Aucune année scolaire active : impossible d'inscrire des élèves à la cantine.")
        return redirect("cantine:tableau")
    formules = FormuleCantine.objects.filter(etablissement=ecole, active=True)
    if not formules.exists():
        messages.info(request, "Créez d'abord une formule (un tarif) de cantine.")
        return redirect("cantine:formules")
    classes = Classe.objects.filter(annee_scolaire=annee).order_by("cycle", "nom")
    choisie = request.GET.get("classe") or request.POST.get("classe") or ""
    classe = classes.filter(pk=int(choisie)).first() if choisie.isdigit() else None
    formulaire, deja_inscrits = None, []
    if classe is not None:
        de_la_classe = Utilisateur.objects.filter(
            role=Role.ELEVE, etablissement=ecole, inscriptions__classe=classe, inscriptions__statut=Inscription.Statut.EN_COURS,
        ).distinct().order_by("nom", "prenom")
        ouvertes = set(
            InscriptionCantine.objects.filter(eleve__in=de_la_classe, annee_scolaire=annee, date_fin__isnull=True).values_list("eleve_id", flat=True)
        )
        deja_inscrits = [eleve for eleve in de_la_classe if eleve.pk in ouvertes]
        formulaire = InscrireForm(request.POST or None, formules=formules, eleves=de_la_classe.exclude(pk__in=ouvertes))
        if request.method == "POST" and formulaire.is_valid():
            donnees = formulaire.cleaned_data
            inscrits, refus = 0, []
            for eleve in donnees["eleves"]:
                try:
                    services.inscrire(eleve=eleve, formule=donnees["formule"], annee=annee, date_debut=donnees["date_debut"], acteur=request.user)
                    inscrits += 1
                except ValidationError as erreur:
                    refus.append(erreur.messages[0])
            if inscrits:
                enregistrer_action(
                    acteur=request.user, action="inscription_cantine", cible=str(classe),
                    details={"eleves": inscrits, "formule": donnees["formule"].libelle}, request=request,
                )
                messages.success(request, f"{inscrits} élève(s) inscrit(s) à la cantine.")
            for message in refus:
                messages.error(request, message)
            return redirect("cantine:tableau")
    return render(request, "cantine/inscrire.html", {
        "annee": annee, "classes": classes, "classe": classe, "formulaire": formulaire, "deja_inscrits": deja_inscrits,
    })


@module_requis(Module.CANTINE)
@require_POST
def terminer_inscription(request, inscription_id):
    inscription = _inscription_de_l_ecole(request, inscription_id)
    if inscription.annee_scolaire.est_archivee:
        raise PermissionDenied("Cette année scolaire est archivée.")
    formulaire = TerminerForm(request.POST)
    if formulaire.is_valid():
        try:
            services.terminer(inscription=inscription, date_fin=formulaire.cleaned_data["date_fin"], acteur=request.user)
        except ValidationError as erreur:
            messages.error(request, erreur.messages[0])
        else:
            enregistrer_action(acteur=request.user, action="fin_inscription_cantine", cible=inscription.eleve.matricule, request=request)
            messages.success(request, f"{inscription.eleve.nom_complet} n'est plus inscrit(e) à la cantine.")
    else:
        messages.error(request, "Indiquez une date valide.")
    return redirect("cantine:fiche_inscription", inscription_id=inscription.pk)


# ---------------------------------------------------------------------------
# Paiements
# ---------------------------------------------------------------------------

@module_requis(Module.CANTINE)
@require_http_methods(["GET", "POST"])
def paiement(request, inscription_id):
    inscription = _inscription_de_l_ecole(request, inscription_id)
    formulaire = PaiementCantineForm(request.POST or None, etablissement=inscription.etablissement)
    if request.method == "POST" and formulaire.is_valid():
        try:
            enregistre = services.enregistrer_paiement(
                inscription=inscription, montant=formulaire.cleaned_data["montant"], mode_paiement=formulaire.cleaned_data["mode_paiement"],
                acteur=request.user,
            )
        except ValidationError as erreur:
            formulaire.add_error(None, erreur.messages[0])
        else:
            enregistrer_action(
                acteur=request.user, action="paiement_cantine", cible=enregistre.reference, details={"montant": enregistre.montant}, request=request,
            )
            messages.success(request, f"Paiement enregistré : reçu {enregistre.reference}.")
            return redirect("cantine:fiche_inscription", inscription_id=inscription.pk)
    return render(request, "cantine/paiement.html", {"inscription": inscription, "formulaire": formulaire, **services.solde_de(inscription)})


@module_requis(Module.CANTINE)
def recu_pdf(request, paiement_id):
    enregistre = get_object_or_404(
        PaiementCantine.objects.select_related("inscription__eleve", "inscription__formule", "enregistre_par", "etablissement"),
        pk=paiement_id, etablissement=_ecole(request),
    )
    html = render_to_string("cantine/recu_pdf.html", {"paiement": enregistre, "inscription": enregistre.inscription, "etablissement": enregistre.etablissement}, request=request)
    reponse = HttpResponse(content_type="application/pdf")
    reponse["Content-Disposition"] = f'attachment; filename="{nom_fichier_sur("recu", enregistre.reference)}.pdf"'
    if creer_pdf(html, reponse, request=request).err:
        return HttpResponse("Erreur lors de la génération du reçu.", status=500)
    return reponse


@module_requis(Module.CANTINE)
@require_POST
def annuler_paiement(request, paiement_id):
    if request.user.role not in DIRECTION:
        raise PermissionDenied("Seule la direction peut annuler un paiement.")
    enregistre = get_object_or_404(PaiementCantine.objects.select_related("inscription"), pk=paiement_id, etablissement=_ecole(request))
    formulaire = AnnulationForm(request.POST)
    if not formulaire.is_valid():
        messages.error(request, "Indiquez le motif de l'annulation.")
    else:
        try:
            services.annuler_paiement(paiement=enregistre, acteur=request.user, motif=formulaire.cleaned_data["motif"])
        except ValidationError as erreur:
            messages.error(request, erreur.messages[0])
        else:
            enregistrer_action(acteur=request.user, action="annulation_paiement_cantine", cible=enregistre.reference, request=request)
            messages.success(request, f"Le paiement {enregistre.reference} est annulé.")
    return redirect("cantine:fiche_inscription", inscription_id=enregistre.inscription_id)


# ---------------------------------------------------------------------------
# Appel du jour
# ---------------------------------------------------------------------------

def _date_de_l_appel(valeur) -> datetime.date:
    try:
        return datetime.date.fromisoformat(valeur) if valeur else timezone.localdate()
    except ValueError:
        return timezone.localdate()


@module_requis(Module.CANTINE)
@require_http_methods(["GET", "POST"])
def appel(request):
    ecole = _ecole(request)
    date = _date_de_l_appel(request.POST.get("date") or request.GET.get("date"))
    if date > timezone.localdate():
        messages.error(request, "On ne peut pas faire l'appel d'un jour qui n'est pas encore venu.")
        date = timezone.localdate()
    if request.method == "POST":
        presents = [int(valeur) for valeur in request.POST.getlist("presents") if valeur.isdigit()]
        try:
            ajoutes, retires = services.enregistrer_appel(etablissement=ecole, date=date, presents_ids=presents, acteur=request.user)
        except ValidationError as erreur:
            messages.error(request, erreur.messages[0])
        else:
            enregistrer_action(
                acteur=request.user, action="appel_cantine", cible=date.isoformat(), details={"presents": len(presents)}, request=request,
            )
            messages.success(request, "Appel de la cantine enregistré.")
            return redirect(f"{reverse('cantine:appel')}?date={date.isoformat()}")
    inscrits = list(services.inscrits_ce_jour(ecole, date))
    ont_mange = set(RepasCantine.objects.filter(date_repas=date, inscription__in=inscrits).values_list("inscription_id", flat=True))
    annee = _annee(ecole)
    classes = _classes_des_eleves([inscription.eleve_id for inscription in inscrits], annee)
    for inscription in inscrits:
        inscription.classe_nom = classes.get(inscription.eleve_id, "")
        inscription.a_mange = inscription.pk in ont_mange
    return render(request, "cantine/appel.html", {
        "date": date, "aujourdhui": timezone.localdate(), "inscrits": inscrits, "presents": len(ont_mange),
    })


# ---------------------------------------------------------------------------
# Formules (tarifs)
# ---------------------------------------------------------------------------

@module_requis(Module.CANTINE)
@require_http_methods(["GET", "POST"])
def formules(request):
    ecole = _ecole(request)
    formulaire = FormuleForm(request.POST or None, etablissement=ecole)
    if request.method == "POST" and formulaire.is_valid():
        formule = formulaire.save()
        enregistrer_action(acteur=request.user, action="creation_formule_cantine", cible=formule.libelle, details={"montant": formule.montant}, request=request)
        messages.success(request, "Formule ajoutée.")
        return redirect("cantine:formules")
    liste = []
    for formule in FormuleCantine.objects.filter(etablissement=ecole):
        liste.append({"formule": formule, "inscrits": formule.inscriptions.filter(date_fin__isnull=True).count()})
    return render(request, "cantine/formules.html", {"formulaire": formulaire, "liste": liste})


@module_requis(Module.CANTINE)
@require_POST
def basculer_formule(request, formule_id):
    formule = get_object_or_404(FormuleCantine, pk=formule_id, etablissement=_ecole(request))
    formule.active = not formule.active
    formule.save(update_fields=["active"])
    enregistrer_action(
        acteur=request.user, action="activation_formule_cantine" if formule.active else "desactivation_formule_cantine", cible=formule.libelle,
        request=request,
    )
    messages.success(request, "Formule activée." if formule.active else "Formule désactivée : elle ne se propose plus aux nouvelles inscriptions.")
    return redirect("cantine:formules")


# ---------------------------------------------------------------------------
# Les familles
# ---------------------------------------------------------------------------

@login_required
def mon_suivi(request):
    """Pour un parent (ses enfants) ou un élève (lui-même) : formule, repas servis, ce qui est payé, ce qui reste."""
    from pedagogie.cahier import eleves_de_la_famille

    if request.user.role not in {Role.PARENT.value, Role.ELEVE.value}:
        raise PermissionDenied("Cette page est réservée aux parents et aux élèves.")
    eleves = list(eleves_de_la_famille(request.user))
    inscriptions = services.avec_soldes(
        InscriptionCantine.objects.filter(eleve__in=eleves, etablissement_id=request.user.etablissement_id).order_by("-date_debut", "pk")
    ) if eleves else []
    par_eleve = {eleve.pk: [] for eleve in eleves}
    for inscription in inscriptions:
        par_eleve[inscription.eleve_id].append(inscription)
    return render(request, "cantine/mon_suivi.html", {"familles": [(eleve, par_eleve[eleve.pk]) for eleve in eleves]})
