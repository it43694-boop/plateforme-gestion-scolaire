"""Conseils de classe : la liste des classes, le tableau d'un conseil (préparer, valider, rouvrir) et ses deux documents PDF."""
import datetime

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from comptes.excel import nom_fichier_sur
from comptes.pdf import creer_pdf
from pedagogie.clotures import periode_cloturee
from pedagogie.conseils import (
    ROLES_REOUVERTURE_CONSEIL, conseil_existant, enregistrer_le_conseil, lignes_du_conseil, nouveau_conseil, peut_tenir_un_conseil,
    rouvrir_le_conseil, superposer_la_saisie, trimestre_valide, valider_le_conseil,
)
from pedagogie.models import ConseilDeClasse, DecisionDePassage, Distinction, SanctionDuConseil, Trimestre
from permissions_matrix.modules import Module
from scolarite.documents import logo_en_donnees
from scolarite.models import AnneeScolaire, classes_visibles_pour


def _verifier_le_droit(request):
    if not peut_tenir_un_conseil(request.user):
        raise PermissionDenied("Vous n'avez pas accès aux conseils de classe.")


def _action_demandee(donnees) -> str:
    """
    L'action est soit un champ « action » (rouvrir), soit le NOM du bouton cliqué (enregistrer, suggestions, valider) : la valeur d'un bouton
    n'est jamais utilisée, parce que la page arabe traduit la valeur des boutons (« valider » deviendrait un mot arabe que le serveur ne connaît pas).
    """
    if donnees.get("action"):
        return donnees["action"]
    for nom in ("valider", "suggestions", "enregistrer"):
        if nom in donnees:
            return nom
    return "enregistrer"  # Entrée dans un champ de texte : on enregistre, on ne valide jamais


def _classe_et_trimestre(request, classe_id, trimestre):
    classe = get_object_or_404(classes_visibles_pour(request.user), id=classe_id)
    if not trimestre_valide(trimestre):
        raise Http404("Trimestre inconnu.")
    return classe, trimestre


@module_requis(Module.NOTES_BULLETINS)
def liste_conseils(request):
    """Les classes de l'année avec, pour chaque trimestre, où en est son conseil (pas préparé, en préparation, validé)."""
    _verifier_le_droit(request)
    annees = AnneeScolaire.objects.filter(etablissement_id=request.user.etablissement_id).order_by("-date_debut")
    choisie = request.GET.get("annee", "")
    annee = annees.filter(pk=int(choisie)).first() if choisie.isdigit() else None
    annee = annee or AnneeScolaire.active(request.user.etablissement) or annees.first()
    lignes = []
    if annee is not None:
        classes = list(classes_visibles_pour(request.user).filter(annee_scolaire=annee).order_by("cycle", "nom"))
        conseils = {(c.classe_id, c.trimestre): c for c in ConseilDeClasse.objects.filter(classe__in=classes)}
        for classe in classes:
            lignes.append({
                "classe": classe, "effectif": classe.effectif,
                "trimestres": [
                    {"valeur": valeur, "libelle": libelle, "conseil": conseils.get((classe.pk, valeur))} for valeur, libelle in Trimestre.choices
                ],
            })
    return render(request, "pedagogie/conseils_liste.html", {"annee": annee, "annees": annees, "lignes": lignes})


@module_requis(Module.NOTES_BULLETINS)
@require_http_methods(["GET", "POST"])
def conseil(request, classe_id, trimestre):
    _verifier_le_droit(request)
    classe, trimestre = _classe_et_trimestre(request, classe_id, trimestre)
    existant = conseil_existant(classe, trimestre)
    instance = existant or nouveau_conseil(classe, trimestre)
    adresse = reverse("pedagogie:conseil", args=[classe.pk, trimestre])
    saisie = None

    if request.method == "POST":
        action = _action_demandee(request.POST)
        try:
            if action == "rouvrir":
                if request.user.role not in ROLES_REOUVERTURE_CONSEIL:
                    raise PermissionDenied("Seule la direction générale peut rouvrir un conseil validé.")
                if existant is None:
                    raise Http404("Ce conseil n'existe pas encore.")
                rouvrir_le_conseil(existant)
                enregistrer_action(acteur=request.user, action="conseil_rouvert", cible=str(existant), request=request)
                messages.success(request, "Le conseil est rouvert : vous pouvez de nouveau le modifier.")
            elif action in ("enregistrer", "suggestions", "valider"):
                enregistrer_le_conseil(instance, request.POST, suggestions=action == "suggestions")
                enregistrer_action(acteur=request.user, action="conseil_enregistre", cible=str(instance), request=request)
                if action == "valider":
                    valider_le_conseil(instance, request.user)
                    enregistrer_action(acteur=request.user, action="conseil_valide", cible=str(instance), request=request)
                    messages.success(request, "Le conseil est validé : le procès-verbal et le tableau d'honneur sont prêts.")
                elif action == "suggestions":
                    messages.success(request, "Les distinctions et les décisions de passage proposées par les moyennes sont en place : vérifiez-les, puis enregistrez.")
                else:
                    messages.success(request, "Le conseil est enregistré.")
            else:
                raise Http404("Action inconnue.")
            return redirect(adresse)
        except ValidationError as erreur:
            messages.error(request, " ".join(erreur.messages))
            saisie = request.POST

    tableau = lignes_du_conseil(instance)
    if saisie is not None:
        superposer_la_saisie(tableau["lignes"], saisie)
    return render(request, "pedagogie/conseil.html", {
        "classe": classe, "trimestre": trimestre, "trimestre_libelle": dict(Trimestre.choices)[trimestre], "conseil": instance,
        "enregistre": existant is not None, "valide": instance.valide, "lignes": tableau["lignes"], "reperes": tableau["reperes"],
        "distinctions": Distinction.choices, "sanctions": SanctionDuConseil.choices, "passages": DecisionDePassage.choices,
        "notes_cloturees": periode_cloturee(classe, trimestre), "peut_rouvrir": request.user.role in ROLES_REOUVERTURE_CONSEIL,
        "saisie": saisie,
    })


def _conseil_pour_un_document(request, classe_id, trimestre):
    _verifier_le_droit(request)
    classe, trimestre = _classe_et_trimestre(request, classe_id, trimestre)
    existant = conseil_existant(classe, trimestre)
    if existant is None:
        messages.error(request, "Enregistrez d'abord le conseil : il n'y a encore rien à imprimer.")
        return None, redirect(reverse("pedagogie:conseil", args=[classe.pk, trimestre]))
    return existant, None


def _document(request, existant, gabarit, nom_document, action, contexte_en_plus=None):
    tableau = lignes_du_conseil(existant)
    contexte = {
        "conseil": existant, "classe": existant.classe, "etablissement": request.user.etablissement, "logo": logo_en_donnees(request.user.etablissement),
        "trimestre_libelle": existant.get_trimestre_display(), "lignes": tableau["lignes"], "reperes": tableau["reperes"],
        "valide": existant.valide, "edite_le": datetime.date.today(), **(contexte_en_plus(tableau["lignes"]) if contexte_en_plus else {}),
    }
    html = render_to_string(gabarit, contexte, request=request)
    reponse = HttpResponse(content_type="application/pdf")
    nom = nom_fichier_sur(nom_document, existant.classe.nom, existant.get_trimestre_display(), existant.classe.annee_scolaire.libelle)
    reponse["Content-Disposition"] = f'attachment; filename="{nom}.pdf"'
    if creer_pdf(html, reponse, request=request).err:
        return HttpResponse("Erreur lors de la génération du PDF.", status=500)
    enregistrer_action(acteur=request.user, action=action, cible=str(existant), request=request)
    return reponse


@module_requis(Module.NOTES_BULLETINS)
def proces_verbal_pdf(request, classe_id, trimestre):
    existant, retour = _conseil_pour_un_document(request, classe_id, trimestre)
    if retour:
        return retour
    return _document(request, existant, "pedagogie/conseil_pv_pdf.html", "proces_verbal_conseil", "export_proces_verbal_conseil")


@module_requis(Module.NOTES_BULLETINS)
def tableau_d_honneur_pdf(request, classe_id, trimestre):
    existant, retour = _conseil_pour_un_document(request, classe_id, trimestre)
    if retour:
        return retour
    return _document(request, existant, "pedagogie/conseil_honneur_pdf.html", "tableau_d_honneur", "export_tableau_d_honneur", lambda lignes: {
        "groupes": _groupes_d_honneur(lignes),
    })


def _groupes_d_honneur(lignes):
    """Les élèves distingués par le conseil, du niveau le plus haut au plus bas, chacun du meilleur rang au moins bon."""
    groupes = []
    for valeur, libelle in reversed(Distinction.choices):  # félicitations, encouragements, tableau d'honneur
        eleves = [ligne for ligne in lignes if ligne["distinction"] == valeur]
        if eleves:
            groupes.append({"libelle": libelle, "eleves": eleves})
    return groupes
