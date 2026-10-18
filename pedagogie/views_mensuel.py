"""
Bulletin mensuel du premier cycle : disciplines de la classe, grille de saisie du mois (par le maître), résultats, moyenne de l'année, bulletins
PDF (un élève ou toute la classe). Les parents et les élèves voient seulement les bulletins de leurs enfants et d'eux-mêmes.
"""
import datetime
from decimal import Decimal

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
from comptes.roles import Role
from pedagogie import mensuel
from pedagogie.models import DisciplineMensuelle
from permissions_matrix.modules import Module
from scolarite.documents import logo_en_donnees
from scolarite.models import (
    Cycle, Inscription, classes_visibles_pour, eleve_de_l_etablissement_ou_404, eleve_visible_pour,
)

MAXIMUM_BULLETINS_PAR_PDF = 150


def _valeur(note) -> str:
    """Une note pour une case de saisie : 9,5 et 10 (pas 9,50 ni 10,00)."""
    return format(note.normalize(), "f") if note is not None else ""


def _entier(valeur) -> int:
    """Un numéro envoyé par un formulaire ; 0 (donc introuvable) s'il n'est pas un nombre."""
    return int(valeur) if str(valeur or "").isdigit() else 0


def _classe(request, classe_id):
    """La classe du premier cycle (une autre école ou un autre cycle : introuvable)."""
    classe = get_object_or_404(classes_visibles_pour(request.user).select_related("annee_scolaire"), pk=classe_id)
    if classe.cycle != Cycle.PREMIER_CYCLE:
        raise Http404("Le bulletin mensuel concerne le premier cycle.")
    return classe


def _mois(annee_civile, numero) -> datetime.date:
    try:
        return mensuel.mois_depuis_adresse(annee_civile, numero)
    except ValueError:
        raise Http404("Mois inconnu.") from None


def _liste_des_mois(classe, choisi):
    """Les mois de l'année de la classe, pour passer de l'un à l'autre : [(adresse, libellé, est le mois choisi)]."""
    return [(mois, mois == choisi) for mois in mensuel.mois_de_l_annee(classe.annee_scolaire)]


def _exiger_saisie(utilisateur, classe):
    if not mensuel.peut_saisir(utilisateur, classe):
        raise PermissionDenied("Vous ne remplissez pas les notes de cette classe.")


def _exiger_consultation(utilisateur, classe):
    if not mensuel.peut_consulter(utilisateur, classe):
        raise PermissionDenied("Vous n'avez pas accès aux résultats de cette classe.")


# ---------------------------------------------------------------------------
# Les classes
# ---------------------------------------------------------------------------

@module_requis(Module.NOTES_BULLETINS)
def classes(request):
    """Les classes du premier cycle dont l'utilisateur remplit ou consulte les notes du mois."""
    ecole = request.user.etablissement
    if ecole is None:
        raise Http404("Aucun établissement.")
    candidates = classes_visibles_pour(request.user).filter(cycle=Cycle.PREMIER_CYCLE, annee_scolaire__est_archivee=False).select_related("annee_scolaire")
    if request.user.role == Role.ENSEIGNANT:
        candidates = candidates.filter(affectations__enseignant=request.user).distinct()
    elif request.user.role in {Role.PARENT, Role.ELEVE}:
        raise PermissionDenied("Cette page est réservée au personnel de l'école.")
    lignes = []
    for classe in candidates.order_by("nom"):
        if mensuel.peut_consulter(request.user, classe):
            mois = mensuel.mois_courant_de_la_classe(classe)
            lignes.append({
                "classe": classe, "mois": mois, "disciplines": classe.disciplines_mensuelles.filter(active=True).count(),
                "peut_saisir": mensuel.peut_saisir(request.user, classe),
            })
    return render(request, "pedagogie/mensuel_classes.html", {"lignes": lignes})


# ---------------------------------------------------------------------------
# Les disciplines d'une classe
# ---------------------------------------------------------------------------

@module_requis(Module.NOTES_BULLETINS)
@require_http_methods(["GET", "POST"])
def disciplines(request, classe_id):
    classe = _classe(request, classe_id)
    _exiger_saisie(request.user, classe)
    lecture_seule = classe.annee_scolaire.est_archivee
    if request.method == "POST":
        if lecture_seule:
            raise PermissionDenied("Cette année scolaire est archivée.")
        action, message = request.POST.get("action", ""), ""
        try:
            if action == "habituelles":
                nombre = mensuel.creer_disciplines_habituelles(classe)
                message = f"{nombre} discipline(s) ajoutée(s)."
            elif action == "ajouter":
                mensuel.ajouter_discipline(classe, request.POST.get("libelle", ""))
                message = "Discipline ajoutée."
            elif action == "copier":
                source = get_object_or_404(classes_visibles_pour(request.user), pk=_entier(request.POST.get("source")))
                nombre = mensuel.copier_disciplines(source, classe)
                message = f"{nombre} discipline(s) reprise(s)."
            elif action in {"renommer", "basculer", "supprimer"}:
                discipline = get_object_or_404(DisciplineMensuelle, pk=_entier(request.POST.get("discipline")), classe=classe)
                if action == "renommer":
                    mensuel.renommer_discipline(discipline, request.POST.get("libelle", ""))
                    message = "Discipline renommée."
                elif action == "basculer":
                    discipline.active = not discipline.active
                    discipline.save(update_fields=["active"])
                    message = "Discipline activée." if discipline.active else "Discipline désactivée : elle n'apparaît plus dans la saisie ni sur le bulletin."
                else:
                    mensuel.supprimer_discipline(discipline)
                    message = "Discipline supprimée."
            else:
                raise Http404("Action inconnue.")
        except ValidationError as erreur:
            messages.error(request, erreur.messages[0])
        else:
            enregistrer_action(acteur=request.user, action="disciplines_mensuelles", cible=str(classe), details={"action": action}, request=request)
            messages.success(request, message)
        return redirect("pedagogie:mensuel_disciplines", classe_id=classe.pk)
    autres = classes_visibles_pour(request.user).filter(cycle=Cycle.PREMIER_CYCLE).exclude(pk=classe.pk).filter(disciplines_mensuelles__isnull=False).distinct().order_by("-annee_scolaire__date_debut", "nom")
    return render(request, "pedagogie/mensuel_disciplines.html", {
        "classe": classe, "disciplines": DisciplineMensuelle.objects.filter(classe=classe), "lecture_seule": lecture_seule, "autres_classes": autres,
        "mois": mensuel.mois_courant_de_la_classe(classe),
    })


# ---------------------------------------------------------------------------
# La grille du mois
# ---------------------------------------------------------------------------

@module_requis(Module.NOTES_BULLETINS)
@require_http_methods(["GET", "POST"])
def grille(request, classe_id, annee, mois):
    classe = _classe(request, classe_id)
    _exiger_consultation(request.user, classe)
    mois = _mois(annee, mois)
    peut_saisir = mensuel.peut_saisir(request.user, classe)
    resultat = mensuel.calculer_mois(classe, mois, avec_observations=True)
    erreurs, saisies_en_erreur, observations_en_erreur = {}, {}, {}
    modifiable = peut_saisir and not resultat.cloture
    if request.method == "POST":
        if not peut_saisir:
            raise PermissionDenied("Vous ne remplissez pas les notes de cette classe.")
        saisies, observations = {}, {}
        for ligne in resultat.lignes:
            if f"o_{ligne.eleve.pk}" in request.POST:  # une observation absente de l'envoi n'est pas touchée (comme une note) ; présente et vide, elle s'efface
                observations[ligne.eleve.pk] = request.POST[f"o_{ligne.eleve.pk}"]
            for discipline in resultat.disciplines:
                nom = f"n_{ligne.eleve.pk}_{discipline.pk}"
                if nom in request.POST:
                    saisies[(ligne.eleve.pk, discipline.pk)] = request.POST[nom]
        try:
            bilan = mensuel.enregistrer_notes(classe=classe, mois=mois, saisies=saisies, acteur=request.user, observations=observations)
        except mensuel.ErreursDeSaisie as echec:
            erreurs = echec.erreurs
            saisies_en_erreur, observations_en_erreur = saisies, observations
            messages.error(request, f"{len(erreurs)} note(s) à corriger : rien n'a été enregistré.")
        except ValidationError as erreur:
            messages.error(request, erreur.messages[0])
        else:
            enregistrer_action(
                acteur=request.user, action="saisie_notes_mensuelles", cible=f"{classe} - {mois:%m/%Y}", details=bilan, request=request,
            )
            messages.success(request, "Les notes du mois sont enregistrées.")
            return redirect("pedagogie:mensuel_grille", classe_id=classe.pk, annee=mois.year, mois=mois.month)
    lignes = []
    for ligne in resultat.lignes:
        cases = []
        for discipline in resultat.disciplines:
            cle = (ligne.eleve.pk, discipline.pk)
            valeur = saisies_en_erreur[cle] if cle in saisies_en_erreur else _valeur(ligne.notes.get(discipline.pk))
            cases.append({"discipline": discipline, "valeur": valeur, "erreur": erreurs.get(cle, "")})
        lignes.append({
            "eleve": ligne.eleve, "cases": cases, "total": ligne.total, "moyenne": ligne.moyenne, "rang": ligne.rang,
            "observation": observations_en_erreur.get(ligne.eleve.pk, ligne.observation),
        })
    precedent = [m for m, _ in _liste_des_mois(classe, mois) if m < mois]
    suivant = [m for m, _ in _liste_des_mois(classe, mois) if m > mois]
    return render(request, "pedagogie/mensuel_grille.html", {
        "classe": classe, "mois": mois, "resultat": resultat, "lignes": lignes, "modifiable": modifiable, "peut_saisir": peut_saisir,
        "mois_de_l_annee": _liste_des_mois(classe, mois), "precedent": precedent[-1] if precedent else None, "suivant": suivant[0] if suivant else None,
        "annee_archivee": classe.annee_scolaire.est_archivee,
    })


# ---------------------------------------------------------------------------
# Résultats du mois et de l'année
# ---------------------------------------------------------------------------

@module_requis(Module.NOTES_BULLETINS)
def resultats(request, classe_id, annee, mois):
    classe = _classe(request, classe_id)
    _exiger_consultation(request.user, classe)
    mois = _mois(annee, mois)
    resultat = mensuel.calculer_mois(classe, mois)
    classes_lignes = sorted(resultat.lignes, key=lambda ligne: (ligne.rang is None, ligne.rang or 0, ligne.eleve.nom, ligne.eleve.prenom))
    return render(request, "pedagogie/mensuel_resultats.html", {
        "classe": classe, "mois": mois, "resultat": resultat, "lignes": classes_lignes, "mois_de_l_annee": _liste_des_mois(classe, mois),
        "avec_notes": sum(1 for ligne in resultat.lignes if ligne.moyenne is not None),
    })


@module_requis(Module.NOTES_BULLETINS)
def annuel(request, classe_id):
    classe = _classe(request, classe_id)
    _exiger_consultation(request.user, classe)
    resultat = mensuel.calculer_annee(classe)
    lignes = sorted(resultat.lignes, key=lambda ligne: (ligne.rang is None, ligne.rang or 0, ligne.eleve.nom, ligne.eleve.prenom))
    for ligne in lignes:
        ligne.cases = [ligne.moyennes.get(mois) for mois in resultat.mois]  # une moyenne (ou rien) par mois, dans l'ordre des colonnes
    return render(request, "pedagogie/mensuel_annuel.html", {
        "classe": classe, "resultat": resultat, "lignes": lignes, "mois_courant": mensuel.mois_courant_de_la_classe(classe),
        "admis": sum(1 for ligne in resultat.lignes if ligne.admis), "non_admis": sum(1 for ligne in resultat.lignes if ligne.admis is False),
    })


# ---------------------------------------------------------------------------
# Les bulletins PDF
# ---------------------------------------------------------------------------

def _bulletins(resultat, lignes):
    return [{"ligne": ligne, "notes": [(discipline, ligne.notes.get(discipline.pk)) for discipline in resultat.disciplines]} for ligne in lignes]


def _pdf(request, classe, mois, resultat, lignes, nom_fichier):
    ecole = classe.annee_scolaire.etablissement
    html = render_to_string("pedagogie/mensuel_bulletin_pdf.html", {
        "etablissement": ecole, "logo": logo_en_donnees(ecole), "classe": classe, "annee": classe.annee_scolaire, "mois": mois, "resultat": resultat,
        "bulletins": _bulletins(resultat, lignes), "seuil": mensuel.seuil_de_passage(ecole),
    }, request=request)
    reponse = HttpResponse(content_type="application/pdf")
    reponse["Content-Disposition"] = f'attachment; filename="{nom_fichier}.pdf"'
    if creer_pdf(html, reponse, request=request).err:
        return HttpResponse("Erreur lors de la génération du bulletin.", status=500)
    return reponse


@module_requis(Module.NOTES_BULLETINS)
def bulletins_classe_pdf(request, classe_id, annee, mois):
    classe = _classe(request, classe_id)
    _exiger_consultation(request.user, classe)
    mois = _mois(annee, mois)
    resultat = mensuel.calculer_mois(classe, mois, avec_observations=True)
    lignes = [ligne for ligne in resultat.lignes if ligne.moyenne is not None]
    if not lignes:
        messages.error(request, "Aucun élève n'a de note pour ce mois : aucun bulletin à imprimer.")
        return redirect("pedagogie:mensuel_resultats", classe_id=classe.pk, annee=mois.year, mois=mois.month)
    if len(lignes) > MAXIMUM_BULLETINS_PAR_PDF:
        messages.error(request, f"Cette classe a plus de {MAXIMUM_BULLETINS_PAR_PDF} élèves : imprimez les bulletins un par un.")
        return redirect("pedagogie:mensuel_resultats", classe_id=classe.pk, annee=mois.year, mois=mois.month)
    reponse = _pdf(request, classe, mois, resultat, lignes, nom_fichier_sur("bulletins", classe.nom, f"{mois:%Y-%m}"))
    enregistrer_action(
        acteur=request.user, action="export_bulletins_mensuels_classe", cible=f"{classe} - {mois:%m/%Y}", details={"bulletins": len(lignes)}, request=request,
    )
    return reponse


def _inscription_du_premier_cycle(request, eleve):
    """L'inscription du premier cycle de l'élève : celle demandée (`?inscription=`), sinon l'inscription en cours."""
    inscriptions = Inscription.objects.filter(eleve=eleve, classe__cycle=Cycle.PREMIER_CYCLE).select_related("classe", "classe__annee_scolaire")
    demandee = request.GET.get("inscription", "")
    inscription = inscriptions.filter(pk=int(demandee)).first() if demandee.isdigit() else inscriptions.filter(statut=Inscription.Statut.EN_COURS).first()
    if inscription is None:
        raise Http404("Cet élève n'est pas dans une classe du premier cycle.")
    return inscription


@module_requis(Module.NOTES_BULLETINS)
def bulletins_eleve(request, matricule):
    """Les bulletins mensuels d'un élève : l'élève, ses parents, son maître et la direction."""
    el = eleve_de_l_etablissement_ou_404(request.user, matricule)
    if not eleve_visible_pour(request.user, el):
        raise PermissionDenied("Vous n'avez pas accès aux bulletins de cet élève.")
    inscription = _inscription_du_premier_cycle(request, el)
    classe = inscription.classe
    lignes = []
    for mois in mensuel.mois_de_l_annee(classe.annee_scolaire):
        resultat = mensuel.calculer_mois(classe, mois)
        ligne = next((l for l in resultat.lignes if l.eleve.pk == el.pk), None)
        if ligne is not None and ligne.moyenne is not None:
            lignes.append({"mois": mois, "ligne": ligne, "effectif": resultat.effectif})
    annuel_de_la_classe = mensuel.calculer_annee(classe)
    annuel_de_l_eleve = next((l for l in annuel_de_la_classe.lignes if l.eleve.pk == el.pk), None)
    return render(request, "pedagogie/mensuel_eleve.html", {
        "eleve": el, "inscription": inscription, "classe": classe, "lignes": lignes, "annuel": annuel_de_l_eleve, "effectif": annuel_de_la_classe.effectif,
        "seuil": annuel_de_la_classe.seuil, "voit_la_decision": request.user.role not in {Role.PARENT, Role.ELEVE},
        "autres_inscriptions": Inscription.objects.filter(eleve=el, classe__cycle=Cycle.PREMIER_CYCLE).select_related("classe__annee_scolaire").order_by("-classe__annee_scolaire__date_debut"),
    })


@module_requis(Module.NOTES_BULLETINS)
def bulletin_pdf(request, matricule, annee, mois):
    el = eleve_de_l_etablissement_ou_404(request.user, matricule)
    if not eleve_visible_pour(request.user, el):
        raise PermissionDenied("Vous n'avez pas accès au bulletin de cet élève.")
    inscription = _inscription_du_premier_cycle(request, el)
    classe = inscription.classe
    mois = _mois(annee, mois)
    resultat = mensuel.calculer_mois(classe, mois, avec_observations=True)
    ligne = next((l for l in resultat.lignes if l.eleve.pk == el.pk), None)
    if ligne is None or ligne.moyenne is None:
        raise Http404("Aucune note pour ce mois.")
    reponse = _pdf(request, classe, mois, resultat, [ligne], nom_fichier_sur("bulletin", el.matricule, f"{mois:%Y-%m}"))
    enregistrer_action(acteur=request.user, action="export_bulletin_mensuel", cible=el.matricule, details={"mois": f"{mois:%Y-%m}"}, request=request)
    return reponse
