from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.utils import timezone
from django.db.models import Count
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from comptes.audit import enregistrer_action
from comptes.models import Utilisateur
from comptes.roles import Role, StatutCompte
from espace_developpeur.forms import ParametresEtablissementForm
from espace_plateforme.forms import (
    CreerEtablissementForm, EmettreFactureForm, ModifierPlanEtablissementForm, ReglementFactureForm,
)
from etablissement.abonnements import annuler_facture, emettre_facture, enregistrer_reglement, synthese_abonnements
from etablissement.models import Etablissement, FactureAbonnement, PlanEtablissement
from permissions_matrix.models import PermissionMatrix

# Distinction volontaire : le rôle "développeur" gère SON établissement
# (identité, rôles, matrice) ; seul un superutilisateur - le propriétaire
# de la plateforme - peut créer et administrer les établissements
# eux-mêmes. Ce n'est pas un rôle métier de plus, mais le statut technique
# Django déjà utilisé pour le tout premier compte (créé via createsuperuser).
est_proprietaire_plateforme = user_passes_test(lambda u: u.is_authenticated and u.is_superuser)


@est_proprietaire_plateforme
def modifier_etablissement(request, etablissement_id):
    etablissement = get_object_or_404(Etablissement, id=etablissement_id)
    formulaire = ParametresEtablissementForm(request.POST or None, request.FILES or None, instance=etablissement)
    if request.method == "POST" and formulaire.is_valid():
        formulaire.save()
        enregistrer_action(
            acteur=request.user, action="modification_etablissement_par_plateforme",
            cible=etablissement.nom, request=request,
        )
        messages.success(request, f"Établissement « {etablissement.nom} » mis à jour.")
        return redirect("espace_plateforme:liste_etablissements")
    return render(request, "espace_plateforme/modifier_etablissement.html", {
        "formulaire": formulaire, "etablissement": etablissement,
    })


@est_proprietaire_plateforme
def voir_comptes_etablissement(request, etablissement_id):
    etablissement = get_object_or_404(Etablissement, id=etablissement_id)
    comptes = Utilisateur.objects.filter(etablissement=etablissement).order_by("nom", "prenom")
    page_obj = Paginator(comptes, 30).get_page(request.GET.get("page"))
    return render(request, "espace_plateforme/comptes_etablissement.html", {
        "etablissement": etablissement, "page_obj": page_obj, "comptes": page_obj.object_list,
    })


@est_proprietaire_plateforme
def liste_etablissements(request):
    etablissements = Etablissement.objects.all().order_by("nom")
    # Détection des codes d'établissement en double : seul le propriétaire de la plateforme voit
    # toutes les écoles ; une école, elle, n'apprend jamais qu'une autre porte le même code.
    comptes_codes = {}
    for code in Etablissement.objects.exclude(code_etablissement="").values_list("code_etablissement", flat=True):
        code_normalise = " ".join(code.split()).upper()
        if code_normalise:
            comptes_codes[code_normalise] = comptes_codes.get(code_normalise, 0) + 1
    codes_en_double = {code for code, nombre in comptes_codes.items() if nombre > 1}
    for etablissement in etablissements:
        etablissement.nb_comptes = etablissement.utilisateurs.count()
        code_normalise = " ".join(etablissement.code_etablissement.split()).upper()
        etablissement.code_en_double = code_normalise in codes_en_double
    return render(request, "espace_plateforme/liste_etablissements.html", {
        "etablissements": etablissements, "plan_choices": PlanEtablissement.choices,
    })


@est_proprietaire_plateforme
def creer_etablissement(request):
    formulaire = CreerEtablissementForm(request.POST or None)
    if request.method == "POST" and formulaire.is_valid():
        with transaction.atomic():
            etablissement = Etablissement.objects.create(
                nom=formulaire.cleaned_data["nom"], devise=formulaire.cleaned_data["devise"],
            )
            PermissionMatrix.seed_pour(etablissement)
            developpeur = Utilisateur(
                email=formulaire.cleaned_data["email_developpeur"],
                prenom=formulaire.cleaned_data["prenom_developpeur"],
                nom=formulaire.cleaned_data["nom_developpeur"],
                role=Role.DEVELOPPEUR, etablissement=etablissement,
                statut=StatutCompte.ACTIF, is_active=True, email_verifie=True,
            )
            developpeur.set_password(formulaire.cleaned_data["mot_de_passe_developpeur"])
            developpeur.full_clean(exclude=["password"])
            developpeur.save()

        enregistrer_action(
            acteur=request.user, action="creation_etablissement",
            cible=etablissement.nom, details={"developpeur": developpeur.email}, request=request,
        )
        messages.success(
            request,
            f"Établissement « {etablissement.nom} » créé, avec {developpeur.nom_complet} "
            f"comme premier administrateur ({developpeur.email}).",
        )
        return redirect("espace_plateforme:liste_etablissements")
    return render(request, "espace_plateforme/creer_etablissement.html", {"formulaire": formulaire})


@est_proprietaire_plateforme
@require_http_methods(["POST"])
def modifier_plan(request, etablissement_id):
    etablissement = get_object_or_404(Etablissement, id=etablissement_id)
    ancien_plan = etablissement.plan
    ancien_professionnel = etablissement.inclut_professionnel
    ancien_prescolaire = etablissement.inclut_prescolaire
    formulaire = ModifierPlanEtablissementForm(request.POST, instance=etablissement)
    if formulaire.is_valid():
        formulaire.save()
        enregistrer_action(
            acteur=request.user, action="modification_plan_etablissement",
            cible=etablissement.nom,
            details={
                "plan": f"{ancien_plan} -> {etablissement.plan}",
                "inclut_professionnel": f"{ancien_professionnel} -> {etablissement.inclut_professionnel}",
                "inclut_prescolaire": f"{ancien_prescolaire} -> {etablissement.inclut_prescolaire}",
            },
            request=request,
        )
        messages.success(request, f"Formule d'abonnement de « {etablissement.nom} » mise à jour.")
    else:
        messages.error(request, "Formule d'abonnement invalide.")
    return redirect("espace_plateforme:liste_etablissements")


@est_proprietaire_plateforme
@require_http_methods(["POST"])
def acceder_etablissement(request, etablissement_id):
    """
    Connecte le propriétaire au compte développeur de l'école (le plus ancien
    compte actif), sans qu'il ait à connaître ses identifiants. Réservé au
    propriétaire sans établissement, uniquement en POST (CSRF) ; chaque début
    et fin d'accès est écrit dans le journal d'audit de l'école, et toute
    action faite pendant l'accès y est marquée « via le propriétaire »
    (comptes.audit.enregistrer_action). Voir AccesDelegueMiddleware pour les
    garde-fous (mot de passe/email/2FA du compte protégés).
    """
    from django.contrib.auth import login

    from comptes.middleware import (
        CLE_SESSION_ACCES_DELEGUE, CLE_SESSION_ACCES_DELEGUE_EMAIL, est_proprietaire_sans_etablissement,
    )

    if not est_proprietaire_sans_etablissement(request.user):
        messages.error(request, "Seul le propriétaire de la plateforme, sans établissement, peut accéder à une école.")
        return redirect("espace_plateforme:liste_etablissements")

    etablissement = get_object_or_404(Etablissement, id=etablissement_id)
    if not etablissement.actif:
        messages.error(request, f"« {etablissement.nom} » est suspendu : réactivez-le avant d'y accéder.")
        return redirect("espace_plateforme:liste_etablissements")

    developpeur = Utilisateur.objects.filter(
        etablissement=etablissement, role=Role.DEVELOPPEUR, statut=StatutCompte.ACTIF,
        is_active=True, is_superuser=False,
    ).order_by("date_creation", "id").first()
    if developpeur is None:
        messages.error(request, f"« {etablissement.nom} » n'a aucun compte développeur actif.")
        return redirect("espace_plateforme:liste_etablissements")

    proprietaire = request.user
    ancienne_connexion = developpeur.last_login
    login(request, developpeur, backend="django.contrib.auth.backends.ModelBackend")
    # login() ouvre une session neuve (le compte change) puis met à jour
    # last_login : on le remet, pour que « dernière connexion » reste celle de
    # la personne de l'école et non la nôtre.
    Utilisateur.objects.filter(pk=developpeur.pk).update(last_login=ancienne_connexion)
    request.session["etablissement_id"] = etablissement.id
    request.session[CLE_SESSION_ACCES_DELEGUE] = proprietaire.id
    request.session[CLE_SESSION_ACCES_DELEGUE_EMAIL] = proprietaire.email
    enregistrer_action(
        acteur=developpeur, action="acces_delegue_debut", cible=developpeur.email,
        details={"proprietaire": proprietaire.email}, request=request,
    )
    return redirect("comptes:redirection_tableau_de_bord")


@est_proprietaire_plateforme
@require_http_methods(["POST"])
def basculer_actif(request, etablissement_id):
    etablissement = get_object_or_404(Etablissement, id=etablissement_id)
    etablissement.actif = not etablissement.actif
    etablissement.save(update_fields=["actif"])
    enregistrer_action(
        acteur=request.user, action="bascule_actif_etablissement",
        cible=etablissement.nom, details={"actif": etablissement.actif}, request=request,
    )
    messages.success(
        request,
        f"Établissement « {etablissement.nom} » {'réactivé' if etablissement.actif else 'désactivé'}.",
    )
    return redirect("espace_plateforme:liste_etablissements")


# ---------------------------------------------------------------------------
# Abonnements et factures (propriétaire de la plateforme)
# ---------------------------------------------------------------------------

@est_proprietaire_plateforme
def abonnements(request):
    """Situation d'abonnement de chaque école et totaux (encaissé cette année, à encaisser, en retard)."""
    lignes, totaux = synthese_abonnements()
    return render(request, "espace_plateforme/abonnements.html", {"lignes": lignes, "totaux": totaux})


def _factures_filtrees(request):
    factures = FactureAbonnement.objects.select_related("etablissement")
    statut = request.GET.get("statut", "")
    if statut == "en_retard":
        factures = factures.filter(statut=FactureAbonnement.Statut.EMISE, date_echeance__lt=timezone.localdate())
    elif statut in FactureAbonnement.Statut.values:
        factures = factures.filter(statut=statut)
    ecole = request.GET.get("etablissement", "")
    if ecole:
        if not ecole.isdigit():
            raise Http404("Établissement introuvable.")
        factures = factures.filter(etablissement_id=ecole)
    return factures, statut, ecole


@est_proprietaire_plateforme
def liste_factures(request):
    factures, statut, ecole = _factures_filtrees(request)
    page_obj = Paginator(factures, 30).get_page(request.GET.get("page"))
    from urllib.parse import urlencode

    filtres = urlencode({cle: valeur for cle, valeur in (("statut", statut), ("etablissement", ecole)) if valeur})
    return render(request, "espace_plateforme/factures.html", {
        "page_obj": page_obj, "factures": page_obj.object_list, "statut": statut, "ecole": ecole,
        "filtres": filtres + "&" if filtres else "",
        "etablissements": Etablissement.objects.order_by("nom"),
        "statuts": [("emise", "Émises"), ("en_retard", "En retard"), ("payee", "Payées"), ("annulee", "Annulées")],
    })


@est_proprietaire_plateforme
@require_http_methods(["GET", "POST"])
def emettre_facture_vue(request):
    initial = {}
    pre_ecole = request.GET.get("etablissement", "")
    if pre_ecole.isdigit():
        initial["etablissement"] = pre_ecole
    formulaire = EmettreFactureForm(request.POST or None, initial=initial)
    if request.method == "POST" and formulaire.is_valid():
        donnees = formulaire.cleaned_data
        try:
            facture = emettre_facture(
                etablissement=donnees["etablissement"], periode_debut=donnees["periode_debut"],
                periode_fin=donnees["periode_fin"], montant=donnees["montant"], cree_par=request.user,
                date_emission=donnees["date_emission"], date_echeance=donnees["date_echeance"],
                libelle=donnees["libelle"],
            )
        except ValidationError as erreur:
            formulaire.add_error(None, erreur)
        else:
            enregistrer_action(
                acteur=request.user, action="emission_facture_abonnement", cible=facture.numero,
                details={"etablissement": facture.etablissement.nom, "montant": facture.montant}, request=request,
            )
            messages.success(request, f"Facture {facture.numero} émise pour « {facture.etablissement.nom} ».")
            return redirect("espace_plateforme:liste_factures")
    return render(request, "espace_plateforme/emettre_facture.html", {"formulaire": formulaire})


@est_proprietaire_plateforme
@require_http_methods(["GET", "POST"])
def payer_facture(request, facture_id):
    facture = get_object_or_404(FactureAbonnement.objects.select_related("etablissement"), id=facture_id)
    if facture.statut != FactureAbonnement.Statut.EMISE:
        messages.error(request, f"La facture {facture.numero} est {facture.get_statut_display().lower()} : aucun règlement à enregistrer.")
        return redirect("espace_plateforme:liste_factures")
    formulaire = ReglementFactureForm(request.POST or None)
    if request.method == "POST" and formulaire.is_valid():
        donnees = formulaire.cleaned_data
        try:
            enregistrer_reglement(
                facture=facture, date_paiement=donnees["date_paiement"], mode_reglement=donnees["mode_reglement"],
                reference=donnees["reference"], acteur=request.user,
            )
        except ValidationError as erreur:
            formulaire.add_error(None, erreur)
        else:
            enregistrer_action(
                acteur=request.user, action="reglement_facture_abonnement", cible=facture.numero,
                details={"etablissement": facture.etablissement.nom, "montant": facture.montant,
                         "mode": donnees["mode_reglement"]}, request=request,
            )
            messages.success(request, f"Règlement de la facture {facture.numero} enregistré.")
            if not facture.etablissement.actif:
                messages.warning(
                    request,
                    f"« {facture.etablissement.nom} » est toujours désactivé : réactivez-le depuis la liste des établissements.",
                )
            return redirect("espace_plateforme:liste_factures")
    return render(request, "espace_plateforme/payer_facture.html", {"formulaire": formulaire, "facture": facture})


@est_proprietaire_plateforme
@require_http_methods(["POST"])
def annuler_facture_vue(request, facture_id):
    facture = get_object_or_404(FactureAbonnement, id=facture_id)
    try:
        annuler_facture(facture=facture, motif=request.POST.get("motif", ""), acteur=request.user)
    except ValidationError as erreur:
        messages.error(request, " ".join(erreur.messages))
    else:
        enregistrer_action(
            acteur=request.user, action="annulation_facture_abonnement", cible=facture.numero,
            details={"motif": request.POST.get("motif", "").strip()[:255]}, request=request,
        )
        messages.success(request, f"Facture {facture.numero} annulée.")
    return redirect("espace_plateforme:liste_factures")


@est_proprietaire_plateforme
def facture_pdf(request, facture_id):
    from django.http import HttpResponse
    from django.template.loader import render_to_string
    from xhtml2pdf import pisa

    facture = get_object_or_404(FactureAbonnement.objects.select_related("etablissement"), id=facture_id)
    html = render_to_string("espace_plateforme/facture_pdf.html", {
        "facture": facture, "editeur": {
            "nom": settings.EDITEUR_NOM, "statut": settings.EDITEUR_STATUT, "adresse": settings.EDITEUR_ADRESSE,
            "email": settings.EDITEUR_EMAIL, "telephone": settings.EDITEUR_TELEPHONE,
            "immatriculation": settings.EDITEUR_IMMATRICULATION,
        },
        "instructions_paiement": settings.ABONNEMENT_INSTRUCTIONS_PAIEMENT,
        "nom_commercial": settings.NOM_COMMERCIAL,
    }, request=request)
    reponse = HttpResponse(content_type="application/pdf")
    reponse["Content-Disposition"] = f'attachment; filename="facture_{facture.numero}.pdf"'
    if pisa.CreatePDF(html, dest=reponse, encoding="utf-8").err:
        return HttpResponse("Erreur lors de la génération de la facture.", status=500)
    return reponse


@est_proprietaire_plateforme
def exporter_factures_xlsx(request):
    from comptes.excel import ajouter_feuille_tableau, nouveau_classeur, reponse_xlsx

    factures, _, _ = _factures_filtrees(request)
    classeur = nouveau_classeur()
    ajouter_feuille_tableau(
        classeur, "Factures", "Factures d'abonnement", [("Édité le", timezone.localdate())],
        ["Numéro", "Établissement", "Libellé", "Début", "Fin", "Montant (FCFA)", "Émise le", "À payer avant le", "Statut",
         "Payée le", "Mode de règlement", "Référence"],
        [
            [f.numero, f.etablissement.nom, f.libelle, f.periode_debut, f.periode_fin, f.montant, f.date_emission,
             f.date_echeance, "En retard" if f.en_retard else f.get_statut_display(), f.date_paiement,
             f.get_mode_reglement_display() if f.mode_reglement else "", f.reference_reglement]
            for f in factures
        ],
        total=["Total", "", "", "", "", sum(f.montant for f in factures if f.statut != FactureAbonnement.Statut.ANNULEE)],
        formats={6: "#,##0"},
    )
    enregistrer_action(acteur=request.user, action="export_factures_abonnement", cible="factures", request=request)
    return reponse_xlsx(classeur, "factures_abonnement")
