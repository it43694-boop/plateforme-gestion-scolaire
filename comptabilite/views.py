"""Pages de la comptabilité : tableau de bord, exercices, plan comptable, journal, saisie, grand livre, balance, résultat, bilan."""
import datetime

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from comptabilite import etats
from comptabilite.forms import CompteForm, EcritureLibreForm, ExerciceForm, OperationForm
from comptabilite.models import CompteComptable, Ecriture, Exercice, Journal
from comptabilite.permissions import acces_comptabilite, peut_ecrire
from comptabilite.services import (
    cloturer_exercice, contrepasser, creer_compte, creer_ecriture, creer_exercice, ecarts_caisse, enregistrer_operation,
    exercice_suivant, reporter_a_nouveau, synchroniser_caisse,
)
from comptes.audit import enregistrer_action

ECRITURES_PAR_PAGE = 40
MESSAGES_IGNORES_AFFICHES = 5


# ---------------------------------------------------------------------------
# Aides communes
# ---------------------------------------------------------------------------

def _exercice_choisi(request):
    """(exercice demandé ou, à défaut, celui d'aujourd'hui ou le plus récent ; tous les exercices de l'école)."""
    exercices = Exercice.objects.filter(etablissement=request.user.etablissement)
    choisi = request.GET.get("exercice") or request.POST.get("exercice")
    if choisi:
        if not choisi.isdigit():  # identifiant invalide = page introuvable, pas une erreur serveur
            raise Http404("Exercice introuvable.")
        return get_object_or_404(exercices, id=choisi), exercices
    aujourdhui = timezone.localdate()
    return exercices.filter(date_debut__lte=aujourdhui, date_fin__gte=aujourdhui).first() or exercices.first(), exercices


def _date_du_parametre(request, nom):
    valeur = request.GET.get(nom, "").strip()
    if not valeur:
        return None
    try:
        return datetime.date.fromisoformat(valeur)
    except ValueError:
        raise Http404("Date invalide.")


def _commun(request, exercice, exercices, onglet):
    """Contexte de la barre de navigation des pages de comptabilité."""
    return {
        "exercice": exercice, "exercices": exercices, "onglet": onglet, "peut_ecrire": peut_ecrire(request.user),
        "non_comptabilises": len(ecarts_caisse(request.user.etablissement)) if exercice else 0,
    }


def _vers_journal(exercice_id):
    return redirect(f"{reverse('comptabilite:journal')}?exercice={exercice_id}")


def _exercice_de_l_ecole(request, exercice_id):
    return get_object_or_404(Exercice, id=exercice_id, etablissement=request.user.etablissement)


# ---------------------------------------------------------------------------
# Tableau de bord
# ---------------------------------------------------------------------------

@acces_comptabilite()
def accueil(request):
    exercice, exercices = _exercice_choisi(request)
    contexte = _commun(request, exercice, exercices, "accueil")
    if exercice is not None:
        contexte["fiche"] = etats.tableau_de_bord(request.user.etablissement, exercice)
        contexte["dernieres"] = etats.journal(request.user.etablissement, exercice).order_by("-date_ecriture", "-id")[:8]
    return render(request, "comptabilite/accueil.html", contexte)


@acces_comptabilite(ecriture=True)
@require_http_methods(["POST"])
def synchroniser(request):
    """Passe en comptabilité les paiements, salaires, corrections et annulations de la caisse qui n'y sont pas encore."""
    resultat = synchroniser_caisse(request.user.etablissement, acteur=request.user)
    if resultat.creees:
        messages.success(request, f"{resultat.creees} écriture{'s' if resultat.creees > 1 else ''} passée{'s' if resultat.creees > 1 else ''} depuis la caisse.")
    elif not resultat.ignorees:
        messages.info(request, "La comptabilité est déjà à jour avec la caisse.")
    for texte in resultat.ignorees[:MESSAGES_IGNORES_AFFICHES]:
        messages.warning(request, f"Non comptabilisé : {texte}")
    if len(resultat.ignorees) > MESSAGES_IGNORES_AFFICHES:
        messages.warning(request, f"… et {len(resultat.ignorees) - MESSAGES_IGNORES_AFFICHES} autre(s) mouvement(s) non comptabilisé(s).")
    enregistrer_action(
        acteur=request.user, action="synchronisation_comptable", cible="caisse",
        details={"creees": resultat.creees, "ignorees": len(resultat.ignorees)}, request=request,
    )
    retour = request.POST.get("retour") or ""
    return redirect(retour if retour.startswith("/comptabilite/") and not retour.startswith("//") else "comptabilite:accueil")


# ---------------------------------------------------------------------------
# Exercices
# ---------------------------------------------------------------------------

@acces_comptabilite()
@require_http_methods(["GET", "POST"])
def exercices_vue(request):
    etablissement = request.user.etablissement
    formulaire = ExerciceForm(request.POST or None) if peut_ecrire(request.user) else None
    if request.method == "POST":
        if not peut_ecrire(request.user):
            raise PermissionDenied("Votre rôle ne peut pas créer d'exercice.")
        if formulaire.is_valid():
            try:
                exercice = creer_exercice(etablissement=etablissement, **formulaire.cleaned_data)
            except ValidationError as erreur:
                formulaire.add_error(None, erreur)
            else:
                enregistrer_action(acteur=request.user, action="creation_exercice_comptable", cible=exercice.libelle, request=request)
                messages.success(request, f"Exercice « {exercice.libelle} » créé.")
                return redirect("comptabilite:exercices")
    lignes = []
    for exercice in Exercice.objects.filter(etablissement=etablissement):
        suivant = exercice_suivant(exercice)
        lignes.append({
            "exercice": exercice, "suivant": suivant,
            "reporte": Ecriture.objects.filter(etablissement=etablissement, report_de=exercice).exists(),
            "nombre_ecritures": exercice.ecritures.count(),
        })
    exercice, tous = _exercice_choisi(request) if request.method == "GET" else (None, None)
    contexte = _commun(request, exercice, tous or Exercice.objects.filter(etablissement=etablissement), "exercices")
    contexte.update({"lignes": lignes, "formulaire": formulaire})
    return render(request, "comptabilite/exercices.html", contexte)


@acces_comptabilite(ecriture=True)
@require_http_methods(["POST"])
def cloturer(request, exercice_id):
    exercice = _exercice_de_l_ecole(request, exercice_id)
    try:
        cloturer_exercice(exercice=exercice, acteur=request.user)
    except ValidationError as erreur:
        messages.error(request, " ".join(erreur.messages))
    else:
        enregistrer_action(acteur=request.user, action="cloture_exercice_comptable", cible=exercice.libelle, request=request)
        messages.success(request, f"Exercice « {exercice.libelle} » clôturé : le résultat est enregistré et plus aucune écriture n'y est possible.")
    return redirect("comptabilite:exercices")


@acces_comptabilite(ecriture=True)
@require_http_methods(["POST"])
def reporter(request, exercice_id):
    exercice = _exercice_de_l_ecole(request, exercice_id)
    try:
        report = reporter_a_nouveau(exercice=exercice, acteur=request.user)
    except ValidationError as erreur:
        messages.error(request, " ".join(erreur.messages))
    else:
        enregistrer_action(acteur=request.user, action="report_a_nouveau_comptable", cible=exercice.libelle, request=request)
        messages.success(request, "Soldes reportés dans l'exercice suivant." if report else "Aucun solde à reporter.")
    return redirect("comptabilite:exercices")


# ---------------------------------------------------------------------------
# Plan comptable
# ---------------------------------------------------------------------------

@acces_comptabilite()
@require_http_methods(["GET", "POST"])
def plan_comptable(request):
    etablissement = request.user.etablissement
    formulaire = CompteForm(request.POST or None) if peut_ecrire(request.user) else None
    if request.method == "POST":
        if not peut_ecrire(request.user):
            raise PermissionDenied("Votre rôle ne peut pas modifier le plan comptable.")
        if formulaire.is_valid():
            try:
                compte = creer_compte(etablissement=etablissement, **formulaire.cleaned_data)
            except ValidationError as erreur:
                formulaire.add_error(None, erreur)
            else:
                enregistrer_action(acteur=request.user, action="creation_compte_comptable", cible=compte.numero, request=request)
                messages.success(request, f"Compte {compte.numero} ajouté.")
                return redirect("comptabilite:plan_comptable")
    recherche = request.GET.get("q", "").strip()
    comptes = CompteComptable.objects.filter(etablissement=etablissement)
    if recherche:
        comptes = comptes.filter(Q(numero__startswith=recherche) | Q(libelle__icontains=recherche))
    par_classe = {}
    for compte in comptes:
        par_classe.setdefault(compte.classe, []).append(compte)
    libelles_classes = {
        1: "Ressources durables", 2: "Actif immobilisé", 3: "Stocks", 4: "Tiers", 5: "Trésorerie",
        6: "Charges des activités ordinaires", 7: "Produits des activités ordinaires", 8: "Autres charges et produits",
    }
    exercice, exercices = _exercice_choisi(request) if request.method == "GET" else (None, Exercice.objects.filter(etablissement=etablissement))
    contexte = _commun(request, exercice, exercices, "plan")
    contexte.update({
        "formulaire": formulaire, "recherche": recherche,
        "classes": [(classe, libelles_classes[classe], comptes) for classe, comptes in sorted(par_classe.items())],
    })
    return render(request, "comptabilite/plan_comptable.html", contexte)


# ---------------------------------------------------------------------------
# Journal et saisie
# ---------------------------------------------------------------------------

@acces_comptabilite()
def journal_vue(request):
    exercice, exercices = _exercice_choisi(request)
    code = request.GET.get("journal", "")
    if code and code not in Journal.values:
        raise Http404("Journal inconnu.")
    contexte = _commun(request, exercice, exercices, "journal")
    contexte.update({"journaux": Journal.choices, "code": code, "du": request.GET.get("du", ""), "au": request.GET.get("au", "")})
    if exercice is not None:
        ecritures = etats.journal(
            request.user.etablissement, exercice, code_journal=code or None,
            du=_date_du_parametre(request, "du"), au=_date_du_parametre(request, "au"),
        )
        page = Paginator(ecritures, ECRITURES_PAR_PAGE).get_page(request.GET.get("page"))
        from urllib.parse import urlencode
        filtres = urlencode({cle: valeur for cle, valeur in (
            ("exercice", exercice.id), ("journal", code), ("du", request.GET.get("du", "")), ("au", request.GET.get("au", ""))) if valeur})
        contexte.update({"page_obj": page, "ecritures": page.object_list, "filtres": filtres + "&"})
    return render(request, "comptabilite/journal.html", contexte)


def _comptes_pour_saisie(request):
    return CompteComptable.objects.filter(etablissement=request.user.etablissement).order_by("numero")


@acces_comptabilite(ecriture=True)
@require_http_methods(["GET", "POST"])
def saisir_ecriture(request):
    formulaire = EcritureLibreForm(request.POST or None)
    if request.method == "POST" and formulaire.is_valid():
        donnees = formulaire.cleaned_data
        try:
            ecriture = creer_ecriture(
                etablissement=request.user.etablissement, journal=donnees["journal"], date_ecriture=donnees["date_ecriture"],
                libelle=donnees["libelle"], piece=donnees["piece"], lignes=donnees["lignes"], cree_par=request.user,
            )
        except ValidationError as erreur:
            formulaire.add_error(None, erreur)
        else:
            enregistrer_action(
                acteur=request.user, action="ecriture_comptable", cible=ecriture.numero,
                details={"journal": ecriture.journal, "montant": ecriture.total}, request=request,
            )
            messages.success(request, f"Écriture {ecriture.numero} enregistrée.")
            return _vers_journal(ecriture.exercice_id)
    exercice, exercices = _exercice_choisi(request) if request.method == "GET" else (None, Exercice.objects.filter(etablissement=request.user.etablissement))
    contexte = _commun(request, exercice, exercices, "saisie")
    contexte.update({"formulaire": formulaire, "comptes": _comptes_pour_saisie(request)})
    return render(request, "comptabilite/saisir_ecriture.html", contexte)


@acces_comptabilite(ecriture=True)
@require_http_methods(["GET", "POST"])
def operation_simple(request):
    formulaire = OperationForm(request.POST or None, etablissement=request.user.etablissement)
    if request.method == "POST" and formulaire.is_valid():
        donnees = formulaire.cleaned_data
        try:
            ecriture = enregistrer_operation(
                etablissement=request.user.etablissement, type_operation=donnees["type_operation"],
                date_ecriture=donnees["date_ecriture"], montant=donnees["montant"], compte=donnees["compte"], mode=donnees["mode"],
                libelle=donnees["libelle"], piece=donnees["piece"], cree_par=request.user,
            )
        except ValidationError as erreur:
            formulaire.add_error(None, erreur)
        else:
            enregistrer_action(
                acteur=request.user, action="ecriture_comptable", cible=ecriture.numero,
                details={"journal": ecriture.journal, "montant": ecriture.total, "type": donnees["type_operation"]}, request=request,
            )
            messages.success(request, f"{'Dépense' if donnees['type_operation'] == 'depense' else 'Recette'} enregistrée : écriture {ecriture.numero}.")
            return _vers_journal(ecriture.exercice_id)
    exercice, exercices = _exercice_choisi(request) if request.method == "GET" else (None, Exercice.objects.filter(etablissement=request.user.etablissement))
    contexte = _commun(request, exercice, exercices, "operation")
    contexte["formulaire"] = formulaire
    return render(request, "comptabilite/operation_simple.html", contexte)


@acces_comptabilite(ecriture=True)
@require_http_methods(["POST"])
def contrepasser_ecriture(request, ecriture_id):
    ecriture = get_object_or_404(Ecriture, id=ecriture_id, etablissement=request.user.etablissement)
    try:
        inverse = contrepasser(ecriture=ecriture, acteur=request.user, motif=request.POST.get("motif", ""))
    except ValidationError as erreur:
        messages.error(request, " ".join(erreur.messages))
    else:
        enregistrer_action(
            acteur=request.user, action="contrepassation_comptable", cible=ecriture.numero,
            details={"contrepassation": inverse.numero}, request=request,
        )
        messages.success(request, f"Écriture {ecriture.numero} annulée par {inverse.numero}.")
    return _vers_journal(ecriture.exercice_id)


# ---------------------------------------------------------------------------
# États
# ---------------------------------------------------------------------------

@acces_comptabilite()
def grand_livre(request):
    exercice, exercices = _exercice_choisi(request)
    contexte = _commun(request, exercice, exercices, "grand_livre")
    numero = request.GET.get("compte", "").strip()
    contexte.update({"numero": numero, "du": request.GET.get("du", ""), "au": request.GET.get("au", "")})
    if exercice is not None:
        etablissement = request.user.etablissement
        contexte["comptes_mouvementes"] = etats.soldes_par_compte(etablissement, exercice, inclure_cloture=True)
        if numero:
            compte = get_object_or_404(CompteComptable, etablissement=etablissement, numero=numero)
            lignes, debit, credit = etats.grand_livre_compte(
                etablissement, exercice, compte, du=_date_du_parametre(request, "du"), au=_date_du_parametre(request, "au"),
            )
            contexte.update({"compte": compte, "lignes": lignes, "total_debit": debit, "total_credit": credit})
    return render(request, "comptabilite/grand_livre.html", contexte)


@acces_comptabilite()
def balance(request):
    exercice, exercices = _exercice_choisi(request)
    contexte = _commun(request, exercice, exercices, "balance")
    jusqu_au = _date_du_parametre(request, "jusqu_au")
    contexte["jusqu_au"] = request.GET.get("jusqu_au", "")
    if exercice is not None:
        lignes, totaux = etats.balance(request.user.etablissement, exercice, jusqu_au=jusqu_au)
        contexte.update({"lignes": lignes, "totaux": totaux})
    return render(request, "comptabilite/balance.html", contexte)


@acces_comptabilite()
def compte_de_resultat(request):
    exercice, exercices = _exercice_choisi(request)
    contexte = _commun(request, exercice, exercices, "resultat")
    jusqu_au = _date_du_parametre(request, "jusqu_au")
    contexte["jusqu_au"] = request.GET.get("jusqu_au", "")
    if exercice is not None:
        contexte["etat"] = etats.compte_de_resultat(request.user.etablissement, exercice, jusqu_au=jusqu_au)
    return render(request, "comptabilite/compte_de_resultat.html", contexte)


@acces_comptabilite()
def bilan(request):
    exercice, exercices = _exercice_choisi(request)
    contexte = _commun(request, exercice, exercices, "bilan")
    jusqu_au = _date_du_parametre(request, "jusqu_au")
    contexte["jusqu_au"] = request.GET.get("jusqu_au", "")
    if exercice is not None:
        contexte["etat"] = etats.bilan(request.user.etablissement, exercice, jusqu_au=jusqu_au)
    return render(request, "comptabilite/bilan.html", contexte)


@acces_comptabilite()
def exporter_etats(request):
    from comptabilite.exports import classeur_etats
    from comptes.excel import nom_fichier_sur, reponse_xlsx

    exercice, _ = _exercice_choisi(request)
    if exercice is None:
        raise Http404("Aucun exercice.")
    enregistrer_action(acteur=request.user, action="export_etats_comptables", cible=exercice.libelle, request=request)
    return reponse_xlsx(classeur_etats(request.user.etablissement, exercice), nom_fichier_sur("etats_comptables", exercice.libelle))
