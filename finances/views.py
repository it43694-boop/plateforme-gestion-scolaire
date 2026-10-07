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
from finances.forms import (
    CloturerContratForm, CorrigerPaiementForm, CreerBulletinPaieForm, CreerContratForm, EnregistrerCongeForm,
    EnregistrerPaiementForm, SaisirSalaireForm,
)
from finances.models import (
    Contrat, DemandeConge, MouvementCaisse, Paiement, Salaire,
    contrat_actif_pour, corriger_paiement, creer_bulletin_paie, enregistrer_paiement, marquer_salaire_paye,
    solde_conges_payes, supprimer_paiement, supprimer_salaire,
)
from permissions_matrix.modules import Module


def _est_direction(utilisateur) -> bool:
    return utilisateur.role in {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL}


def _peut_gerer_les_paiements(utilisateur) -> bool:
    """
    Enregistrer un paiement, le corriger, ou rechercher un élève par nom
    pour ce faire sont des actions administratives (comptabilité/
    direction) : un parent a accès au module Finances uniquement pour
    suivre le solde de SES enfants (suivi_paiements, liste_paiements,
    reçu PDF - tous cloisonnés via eleve_visible_pour), jamais pour agir
    sur le paiement d'un élève, même le sien.
    """
    return utilisateur.role == Role.COMPTABLE.value or _est_direction(utilisateur)


# ---------------------------------------------------------------------------
# Finances (paiements de scolarité)
# ---------------------------------------------------------------------------

@module_requis(Module.FINANCES)
def rechercher_eleve_json(request):
    """
    Recherche en direct (JS) d'élèves par nom, prénom ou matricule - pour
    les sélectionner sans avoir à déjà connaître leur matricule par cœur
    (voir le champ de recherche sur la page d'enregistrement d'un paiement).
    Réservé à la comptabilité/direction : sert uniquement à enregistrer un
    paiement, une action qu'un parent n'a jamais le droit de faire (voir
    _peut_gerer_les_paiements) - sinon la liste des élèves de l'école
    entière lui serait exposée, pas seulement les siens.
    """
    if not _peut_gerer_les_paiements(request.user):
        raise PermissionDenied("Vous n'avez pas accès à cette recherche.")
    from django.db.models import Q
    from django.http import JsonResponse
    from scolarite.models import Inscription, classes_visibles_pour

    terme = request.GET.get("q", "").strip()
    if len(terme) < 2:
        return JsonResponse({"resultats": []})
    eleves = Utilisateur.objects.filter(
        role=Role.ELEVE, etablissement=request.user.etablissement,
        inscriptions__classe__in=classes_visibles_pour(request.user),
        inscriptions__statut=Inscription.Statut.EN_COURS,
    ).filter(
        Q(nom__icontains=terme) | Q(prenom__icontains=terme) | Q(matricule__icontains=terme),
    ).distinct().order_by("nom", "prenom")[:10]
    return JsonResponse({
        "resultats": [
            {"matricule": e.matricule, "nom_complet": f"{e.nom_complet} ({e.matricule})"}
            for e in eleves
        ],
    })


@module_requis(Module.FINANCES)
def periodes_eleve_json(request):
    """
    Mois (ou trimestres) couverts par l'échéancier de la classe d'un
    élève - pour cocher, à l'enregistrement d'un paiement, exactement
    ceux que ce versement règle. Même restriction que rechercher_eleve_json.
    """
    if not _peut_gerer_les_paiements(request.user):
        raise PermissionDenied("Vous n'avez pas accès à cette recherche.")
    from django.http import JsonResponse
    from scolarite.models import Inscription

    matricule = request.GET.get("matricule", "").strip()
    eleve = Utilisateur.objects.filter(
        matricule=matricule, role=Role.ELEVE, etablissement=request.user.etablissement,
    ).first()
    if not eleve:
        return JsonResponse({"periodes": []})
    inscription = Inscription.objects.filter(
        eleve=eleve, statut=Inscription.Statut.EN_COURS,
    ).select_related("classe__echeancier").order_by("-date_inscription").first()
    echeancier = getattr(inscription.classe, "echeancier", None) if inscription else None
    return JsonResponse({"periodes": echeancier.libelles_periodes() if echeancier else []})


@module_requis(Module.FINANCES)
def suivi_paiements(request):
    """
    Pour chaque élève inscrit : total dû (échéancier de sa classe), total
    déjà payé, solde restant. Répond directement à la question « qui n'a
    pas encore tout payé ? » - absente jusqu'ici de l'application.
    """
    from django.db.models import Prefetch, Q, Sum
    from django.db.models.functions import Coalesce
    from scolarite.models import AideScolarite, Inscription, calculer_total_du, classes_visibles_pour

    filtre_statut = request.GET.get("statut", "")
    classe_id = request.GET.get("classe", "")

    aides_actives = Prefetch(
        "aides_scolarite", queryset=AideScolarite.objects.filter(active=True), to_attr="aides_actives_prefetchees",
    )
    inscriptions = Inscription.objects.filter(
        classe__in=classes_visibles_pour(request.user), statut=Inscription.Statut.EN_COURS,
    ).select_related("eleve", "classe", "classe__echeancier", "classe__annee_scolaire").prefetch_related(
        aides_actives, "eleve__parents_lies",
    ).annotate(
        total_paye=Coalesce(Sum("paiements__montant", filter=Q(paiements__est_supprime=False)), 0),
    ).order_by("classe__nom", "eleve__nom")

    if request.user.role == Role.PARENT:
        inscriptions = inscriptions.filter(eleve__parents_lies=request.user)

    if classe_id:
        inscriptions = inscriptions.filter(classe_id=classe_id)

    devise = getattr(request.user.etablissement, "code_devise", "FCFA")
    lignes = []
    for inscription in inscriptions:
        total_du = calculer_total_du(inscription, aides_actives=inscription.aides_actives_prefetchees)
        solde = total_du - inscription.total_paye
        statut = "paye" if solde <= 0 else ("partiel" if inscription.total_paye > 0 else "impaye")
        if filtre_statut and statut != filtre_statut:
            continue
        # Équivalent de Utilisateur.telephone_effectif, mais à partir des
        # parents déjà préchargés (prefetch_related ci-dessus) plutôt que
        # via la propriété, qui ferait une requête par élève dans cette boucle.
        if not solde > 0:
            telephone_whatsapp = None
        elif inscription.eleve.telephone:
            telephone_whatsapp = inscription.eleve.telephone
        else:
            telephone_whatsapp = next(
                (p.telephone for p in inscription.eleve.parents_lies.all() if p.telephone), None,
            )
        message_whatsapp = (
            f"Bonjour, ceci est un rappel concernant le solde de scolarité de "
            f"{inscription.eleve.nom_complet} ({inscription.classe}) : {solde} {devise}."
        ) if telephone_whatsapp else ""
        lignes.append({
            "inscription": inscription, "total_du": total_du,
            "total_paye": inscription.total_paye, "solde": solde, "statut": statut,
            "telephone_whatsapp": telephone_whatsapp, "message_whatsapp": message_whatsapp,
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
    if not _peut_gerer_les_paiements(request.user):
        raise PermissionDenied("Vous n'avez pas le droit d'enregistrer un paiement.")
    formulaire = EnregistrerPaiementForm(request.POST or None, etablissement=request.user.etablissement)
    if request.method == "POST" and formulaire.is_valid():
        paiement = enregistrer_paiement(
            eleve=formulaire.cleaned_data["eleve"],
            inscription=formulaire.cleaned_data["inscription"],
            tranche=formulaire.cleaned_data["tranche"],
            montant=formulaire.cleaned_data["montant"],
            mode_paiement=formulaire.cleaned_data["mode_paiement"],
            enregistre_par=request.user,
            periodes_couvertes=formulaire.cleaned_data["periodes"],
        )
        enregistrer_action(
            acteur=request.user, action="enregistrement_paiement",
            cible=paiement.reference,
            details={"eleve": paiement.eleve.matricule, "montant": paiement.montant},
            request=request,
        )
        messages.success(request, f"Paiement enregistré. Référence : {paiement.reference}")
        return redirect("finances:liste_paiements")
    return render(request, "finances/enregistrer_paiement.html", {"formulaire": formulaire})


@module_requis(Module.FINANCES)
def exporter_recu_paiement_pdf(request, paiement_id):
    from scolarite.models import eleve_visible_pour

    paiement = get_object_or_404(
        Paiement, id=paiement_id, est_supprime=False, etablissement=request.user.etablissement,
    )
    if not eleve_visible_pour(request.user, paiement.eleve):
        raise PermissionDenied("Vous n'avez pas accès à ce reçu.")
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
    if request.user.role == Role.PARENT:
        paiements = paiements.filter(eleve__parents_lies=request.user)
    page_obj = Paginator(paiements, 25).get_page(request.GET.get("page"))
    return render(request, "finances/liste_paiements.html", {
        "page_obj": page_obj, "paiements": page_obj.object_list, "est_direction": _est_direction(request.user),
        "peut_gerer_les_paiements": _peut_gerer_les_paiements(request.user),
    })


@module_requis(Module.FINANCES)
def corriger_paiement_vue(request, paiement_id):
    if not _peut_gerer_les_paiements(request.user):
        raise PermissionDenied("Vous n'avez pas le droit de corriger un paiement.")
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
    """
    Recherche en direct (JS) d'employés par nom, prénom ou email - pour les
    sélectionner sans avoir à déjà connaître leur email par cœur (voir le
    champ de recherche sur la page de saisie d'un salaire).
    """
    from django.db.models import Q
    from django.http import JsonResponse

    terme = request.GET.get("q", "").strip()
    if len(terme) < 2:
        return JsonResponse({"resultats": []})
    employes = Utilisateur.objects.filter(
        etablissement=request.user.etablissement,
    ).exclude(role=Role.ELEVE).filter(
        Q(nom__icontains=terme) | Q(prenom__icontains=terme) | Q(email__icontains=terme),
    ).order_by("nom", "prenom")[:10]
    return JsonResponse({
        "resultats": [
            {"email": e.email, "nom_complet": f"{e.nom_complet} ({e.get_role_display()})"}
            for e in employes
        ],
    })


@module_requis(Module.SALAIRES)
def saisir_salaire_vue(request):
    formulaire = SaisirSalaireForm(request.POST or None, etablissement=request.user.etablissement)
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
    return render(request, "finances/saisir_salaire.html", {"formulaire": formulaire})


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


@module_requis(Module.SALAIRES)
def creer_bulletin_paie_vue(request):
    """
    Bulletin de paie détaillé (brut, cotisations INPS/AMO calculées selon
    les taux de l'établissement, ITS saisi à la main, net calculé) - crée
    un Salaire comme saisir_salaire_vue, mais avec le détail complet
    plutôt qu'un simple montant. Voir finances.models.creer_bulletin_paie.
    """
    formulaire = CreerBulletinPaieForm(request.POST or None, etablissement=request.user.etablissement)
    if request.method == "POST" and formulaire.is_valid():
        try:
            salaire = creer_bulletin_paie(
                employe=formulaire.cleaned_data["employe"], periode=formulaire.cleaned_data["periode"],
                salaire_brut=formulaire.cleaned_data["salaire_brut"], its=formulaire.cleaned_data["its"],
                enregistre_par=request.user,
            )
        except ValidationError as erreur:
            messages.error(request, "; ".join(erreur.messages) if hasattr(erreur, "messages") else str(erreur))
            return render(request, "finances/creer_bulletin_paie.html", {"formulaire": formulaire})
        enregistrer_action(
            acteur=request.user, action="creation_bulletin_paie",
            cible=f"{salaire.employe.nom_complet} - {salaire.periode}", request=request,
        )
        messages.success(request, f"Bulletin de paie créé (net : {salaire.montant}).")
        return redirect("finances:liste_salaires")
    return render(request, "finances/creer_bulletin_paie.html", {"formulaire": formulaire})


@module_requis(Module.SALAIRES)
def bulletin_paie_pdf(request, salaire_id):
    salaire = get_object_or_404(
        Salaire, id=salaire_id, est_supprime=False, etablissement=request.user.etablissement,
    )
    html = render_to_string("finances/bulletin_paie_pdf.html", {"salaire": salaire}, request=request)
    reponse = HttpResponse(content_type="application/pdf")
    reponse["Content-Disposition"] = f'attachment; filename="bulletin_{salaire.employe.matricule or salaire.employe.id}_{salaire.periode}.pdf"'
    resultat = pisa.CreatePDF(html, dest=reponse, encoding="utf-8")
    if resultat.err:
        return HttpResponse("Erreur lors de la génération du bulletin.", status=500)
    return reponse


# ---------------------------------------------------------------------------
# Personnel - contrats
# ---------------------------------------------------------------------------

@module_requis(Module.SALAIRES)
def liste_contrats(request):
    contrats = Contrat.objects.filter(etablissement=request.user.etablissement).select_related("employe")
    page_obj = Paginator(contrats, 25).get_page(request.GET.get("page"))
    return render(request, "finances/liste_contrats.html", {"page_obj": page_obj, "contrats": page_obj.object_list})


@module_requis(Module.SALAIRES)
def creer_contrat_vue(request):
    formulaire = CreerContratForm(request.POST or None, etablissement=request.user.etablissement)
    if request.method == "POST" and formulaire.is_valid():
        contrat = Contrat.objects.create(
            employe=formulaire.cleaned_data["employe"], type_contrat=formulaire.cleaned_data["type_contrat"],
            poste=formulaire.cleaned_data["poste"], date_debut=formulaire.cleaned_data["date_debut"],
            date_fin=formulaire.cleaned_data["date_fin"], salaire_base=formulaire.cleaned_data["salaire_base"],
            cree_par=request.user,
        )
        enregistrer_action(
            acteur=request.user, action="creation_contrat",
            cible=f"{contrat.employe.nom_complet} - {contrat.poste}", request=request,
        )
        messages.success(request, f"Contrat créé pour {contrat.employe.nom_complet}.")
        return redirect("finances:liste_contrats")
    return render(request, "finances/creer_contrat.html", {"formulaire": formulaire})


@module_requis(Module.SALAIRES)
@require_http_methods(["POST"])
def cloturer_contrat_vue(request, contrat_id):
    contrat = get_object_or_404(Contrat, id=contrat_id, etablissement=request.user.etablissement)
    formulaire = CloturerContratForm(request.POST)
    if formulaire.is_valid():
        contrat.date_fin = formulaire.cleaned_data["date_fin"]
        try:
            contrat.full_clean()
        except ValidationError as erreur:
            messages.error(request, "; ".join(erreur.messages) if hasattr(erreur, "messages") else str(erreur))
            return redirect("finances:liste_contrats")
        contrat.save(update_fields=["date_fin"])
        enregistrer_action(
            acteur=request.user, action="cloture_contrat",
            cible=f"{contrat.employe.nom_complet} - {contrat.poste}", request=request,
        )
        messages.success(request, "Contrat clôturé.")
    else:
        messages.error(request, "Date de fin invalide.")
    return redirect("finances:liste_contrats")


# ---------------------------------------------------------------------------
# Personnel - congés
# ---------------------------------------------------------------------------

@module_requis(Module.SALAIRES)
def liste_conges(request):
    conges = DemandeConge.objects.filter(etablissement=request.user.etablissement).select_related("employe")
    page_obj = Paginator(conges, 25).get_page(request.GET.get("page"))
    return render(request, "finances/liste_conges.html", {"page_obj": page_obj, "conges": page_obj.object_list})


@module_requis(Module.SALAIRES)
def enregistrer_conge_vue(request):
    formulaire = EnregistrerCongeForm(request.POST or None, etablissement=request.user.etablissement)
    if request.method == "POST" and formulaire.is_valid():
        conge = DemandeConge.objects.create(
            employe=formulaire.cleaned_data["employe"], type_conge=formulaire.cleaned_data["type_conge"],
            date_debut=formulaire.cleaned_data["date_debut"], date_fin=formulaire.cleaned_data["date_fin"],
            motif=formulaire.cleaned_data["motif"], statut=formulaire.cleaned_data["statut"],
            enregistre_par=request.user,
        )
        enregistrer_action(
            acteur=request.user, action="enregistrement_conge",
            cible=f"{conge.employe.nom_complet} - {conge.date_debut} au {conge.date_fin}", request=request,
        )
        messages.success(request, f"Congé enregistré pour {conge.employe.nom_complet} ({conge.nombre_jours} jour(s)).")
        return redirect("finances:liste_conges")
    return render(request, "finances/enregistrer_conge.html", {"formulaire": formulaire})


@module_requis(Module.SALAIRES)
def solde_conges_json(request):
    """Solde de congés payés de l'employé sélectionné (voir EnregistrerCongeForm) - affiché en direct en JS."""
    from django.http import JsonResponse

    email = request.GET.get("email", "").strip()
    employe = Utilisateur.objects.filter(email__iexact=email, etablissement=request.user.etablissement).first()
    if not employe:
        return JsonResponse({"solde": None})
    return JsonResponse({"solde": solde_conges_payes(employe)})


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
