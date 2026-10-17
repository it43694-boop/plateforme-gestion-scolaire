"""Pages de l'import Excel des élèves : modèle à télécharger, aperçu des erreurs, confirmation, résultat."""
import secrets

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from permissions_matrix.modules import Module
from scolarite.import_eleves import (
    COLONNES, LIGNES_MAX, ErreurFichier, ImportInvalide, importer, lire_classeur, modele_xlsx, valider,
)
from scolarite.models import AnneeScolaire
from scolarite.views import ROLES_INSCRIPTION_ELEVE_INTERDITE

CLE_SESSION = "import_eleves_en_attente"
TYPE_MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ERREURS_AFFICHEES = 100


def _verifier_droit(request):
    """Même droit que l'inscription d'un élève : le personnel, jamais un parent ni un élève."""
    if request.user.role in ROLES_INSCRIPTION_ELEVE_INTERDITE:
        raise PermissionDenied("Vous n'avez pas le droit d'inscrire des élèves.")


def _annee_choisie(request):
    annees = AnneeScolaire.objects.filter(etablissement=request.user.etablissement).order_by("-date_debut")
    choisie = request.POST.get("annee") or request.GET.get("annee")
    if choisie:
        if not str(choisie).isdigit():  # identifiant invalide = page introuvable, pas une erreur serveur
            raise Http404("Année scolaire introuvable.")
        return get_object_or_404(annees, id=choisie), annees
    return AnneeScolaire.active(request.user.etablissement) or annees.first(), annees


@module_requis(Module.ELEVES)
def modele_import_eleves(request):
    _verifier_droit(request)
    annee, _ = _annee_choisie(request)
    if annee is None:
        raise Http404("Aucune année scolaire.")
    reponse = HttpResponse(content_type=TYPE_MIME_XLSX)
    reponse["Content-Disposition"] = 'attachment; filename="modele_import_eleves.xlsx"'
    modele_xlsx(request.user, annee, langue=getattr(request, "LANGUAGE_CODE", "fr")).save(reponse)
    return reponse


@module_requis(Module.ELEVES)
@require_http_methods(["GET", "POST"])
def importer_eleves(request):
    _verifier_droit(request)
    annee, annees = _annee_choisie(request)
    contexte = {"annee": annee, "annees": annees, "colonnes": COLONNES, "lignes_max": LIGNES_MAX}
    if request.method == "GET":
        return render(request, "scolarite/importer_eleves.html", contexte)

    action = request.POST.get("action", "apercu")
    if annee is None:
        messages.error(request, "Créez d'abord une année scolaire et ses classes.")
        return render(request, "scolarite/importer_eleves.html", contexte)
    if action == "annuler":
        request.session.pop(CLE_SESSION, None)
        messages.info(request, "Import annulé : aucun élève n'a été créé.")
        return redirect("scolarite:importer_eleves")
    if action == "confirmer":
        return _confirmer(request, annee, contexte)
    return _apercu(request, annee, contexte)


def _apercu(request, annee, contexte):
    request.session.pop(CLE_SESSION, None)  # un nouvel aperçu remplace tout import en attente
    fichier = request.FILES.get("fichier")
    if fichier is None:
        messages.error(request, "Choisissez d'abord le fichier Excel à importer.")
        return render(request, "scolarite/importer_eleves.html", contexte)
    try:
        lecture = lire_classeur(fichier)
    except ErreurFichier as erreur:
        messages.error(request, str(erreur))
        return render(request, "scolarite/importer_eleves.html", contexte)

    resultats = valider(lecture.lignes, request.user, annee)
    refusees = [resultat for resultat in resultats if resultat.erreurs]
    contexte.update({
        "resultats": resultats, "nombre_lignes": len(resultats), "nombre_refusees": len(refusees),
        "refusees": refusees[:ERREURS_AFFICHEES], "erreurs_masquees": max(len(refusees) - ERREURS_AFFICHEES, 0),
        "colonnes_ignorees": lecture.colonnes_ignorees,
    })
    if not refusees:
        jeton = secrets.token_urlsafe(16)
        request.session[CLE_SESSION] = {"jeton": jeton, "annee": annee.id, "lignes": lecture.lignes}
        contexte["jeton"] = jeton
    return render(request, "scolarite/importer_eleves.html", contexte)


def _confirmer(request, annee, contexte):
    en_attente = request.session.pop(CLE_SESSION, None)  # usage unique : un rechargement ne recrée jamais les élèves
    jeton = request.POST.get("jeton", "")
    if not en_attente or en_attente["annee"] != annee.id or not secrets.compare_digest(en_attente["jeton"].encode(), jeton.encode()):
        messages.error(
            request, "Aucun import en attente (déjà effectué, annulé ou expiré). Envoyez de nouveau votre fichier.",
        )
        return redirect("scolarite:importer_eleves")
    try:
        crees = importer(en_attente["lignes"], request.user, annee)
    except ImportInvalide as erreur:
        messages.error(
            request,
            "L'import a été refusé et rien n'a été créé : corrigez les lignes signalées "
            "(les données ont peut-être changé depuis l'aperçu).",
        )
        contexte.update({
            "nombre_refusees": len(erreur.lignes), "refusees": erreur.lignes[:ERREURS_AFFICHEES],
            "nombre_lignes": len(en_attente["lignes"]), "erreurs_masquees": 0, "colonnes_ignorees": [],
        })
        return render(request, "scolarite/importer_eleves.html", contexte)

    enregistrer_action(
        acteur=request.user, action="import_eleves_excel", cible=annee.libelle,
        details={"nombre": len(crees), "classes": sorted({str(classe) for _, classe in crees})}, request=request,
    )
    contexte["crees"] = [(eleve, classe) for eleve, classe in crees]
    messages.success(request, f"{len(crees)} élève(s) inscrit(s).")
    return render(request, "scolarite/importer_eleves.html", contexte)
