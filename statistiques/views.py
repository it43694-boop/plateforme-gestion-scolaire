import csv
import re

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role
from finances.models import Paiement, TypeTranche
from pedagogie.models import Note
from permissions_matrix.modules import Module
from scolarite.models import (
    AnneeScolaire, Classe, Examen, FicheInfrastructure, Inscription, ResultatExamen, classes_visibles_pour,
    examens_pour_classe,
)
from statistiques.fiche import (
    cellule_csv, construire_fiche, infrastructures_avec_ratios, lignes_csv, statistiques_examens,
)
from statistiques.excel import TYPE_MIME_XLSX, classeur_fiche
from statistiques.forms import FicheInfrastructureForm

# La fiche d'infrastructures concerne toute l'école, pas un cycle : seuls la direction générale et le super
# administrateur la modifient (les directeurs de cycle la consultent).
ROLES_EDITION_INFRASTRUCTURE = {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL} | {Role.SUPER_ADMINISTRATEUR.value}


def _annee_selectionnee(request):
    annee_id = request.GET.get("annee")
    if annee_id:
        if not annee_id.isdigit():  # un identifiant non numérique est une page introuvable, pas une erreur serveur
            raise Http404("Année scolaire introuvable.")
        return get_object_or_404(AnneeScolaire, id=annee_id, etablissement=request.user.etablissement)
    return (
        AnneeScolaire.active(request.user.etablissement)
        or AnneeScolaire.objects.filter(etablissement=request.user.etablissement).order_by("-date_debut").first()
    )


def _repartition_par_sexe(inscriptions_qs):
    valeurs = inscriptions_qs.aggregate(
        hommes=Count("id", filter=Q(eleve__sexe="M")),
        femmes=Count("id", filter=Q(eleve__sexe="F")),
    )
    return {"M": valeurs["hommes"], "F": valeurs["femmes"]}


def _taux_reussite_echec(inscriptions_qs):
    valeurs = inscriptions_qs.aggregate(
        admis=Count("id", filter=Q(statut=Inscription.Statut.ADMIS)),
        redouble=Count("id", filter=Q(statut=Inscription.Statut.REDOUBLE)),
    )
    admis = valeurs["admis"]
    redouble = valeurs["redouble"]
    total_decide = admis + redouble
    if total_decide == 0:
        return {"taux_reussite": None, "taux_echec": None}
    return {
        "taux_reussite": round(100 * admis / total_decide, 1),
        "taux_echec": round(100 * redouble / total_decide, 1),
    }


@module_requis(Module.STATISTIQUES)
def vue_ensemble(request):
    annee = _annee_selectionnee(request)
    toutes_annees = AnneeScolaire.objects.filter(etablissement=request.user.etablissement)
    classes = classes_visibles_pour(request.user).filter(annee_scolaire=annee) if annee else Classe.objects.none()

    inscriptions = Inscription.objects.filter(classe__in=classes)
    contexte = {
        "annee": annee,
        "toutes_annees": toutes_annees,
        "classes": classes,
        "actif": "ensemble",
        "effectif_total": inscriptions.filter(statut=Inscription.Statut.EN_COURS).count(),
        "repartition_sexe": _repartition_par_sexe(inscriptions.filter(statut=Inscription.Statut.EN_COURS)),
        **_taux_reussite_echec(inscriptions),
    }
    return render(request, "statistiques/vue_ensemble.html", contexte)


@module_requis(Module.STATISTIQUES)
def statistiques_classe(request, classe_id):
    classe = get_object_or_404(classes_visibles_pour(request.user), id=classe_id)
    inscriptions = Inscription.objects.filter(classe=classe)
    contexte = {
        "classe": classe,
        "annee": classe.annee_scolaire,
        "toutes_annees": AnneeScolaire.objects.filter(etablissement=request.user.etablissement),
        "classes": classes_visibles_pour(request.user).filter(annee_scolaire=classe.annee_scolaire),
        "effectif": inscriptions.filter(statut=Inscription.Statut.EN_COURS).count(),
        "repartition_sexe": _repartition_par_sexe(inscriptions.filter(statut=Inscription.Statut.EN_COURS)),
        **_taux_reussite_echec(inscriptions),
    }
    return render(request, "statistiques/statistiques_classe.html", contexte)


@module_requis(Module.STATISTIQUES)
def statistiques_finances(request):
    annee = _annee_selectionnee(request)
    classes = classes_visibles_pour(request.user).filter(annee_scolaire=annee) if annee else Classe.objects.none()
    paiements = Paiement.objects.filter(inscription__classe__in=classes, est_supprime=False)

    totaux = {
        ligne["tranche"]: ligne["total"] or 0
        for ligne in paiements.values("tranche").annotate(total=Sum("montant"))
    }
    par_tranche = [
        {"libelle": tranche.label, "total": totaux.get(tranche.value, 0)}
        for tranche in TypeTranche
    ]

    return render(request, "statistiques/statistiques_finances.html", {
        "annee": annee, "toutes_annees": AnneeScolaire.objects.filter(etablissement=request.user.etablissement), "classes": classes, "actif": "finances",
        "par_tranche": par_tranche, "total_general": sum(item["total"] for item in par_tranche),
    })

@module_requis(Module.STATISTIQUES)
def exporter_effectifs_csv(request):
    annee = _annee_selectionnee(request)
    classes = classes_visibles_pour(request.user).filter(annee_scolaire=annee) if annee else Classe.objects.none()

    reponse = HttpResponse(content_type="text/csv; charset=utf-8")
    nom_fichier = f"effectifs_{annee.libelle if annee else 'sans_annee'}.csv"
    reponse["Content-Disposition"] = f'attachment; filename="{nom_fichier}"'
    reponse.write("﻿")  # BOM UTF-8 : nécessaire pour qu'Excel affiche correctement les accents
    writer = csv.writer(reponse)
    writer.writerow(["Classe", "Cycle", "Effectif", "Garçons", "Filles", "Taux de réussite (%)", "Taux d'échec (%)"])

    classes = classes.order_by("cycle", "nom").annotate(
        effectif_actif=Count("inscriptions", filter=Q(inscriptions__statut=Inscription.Statut.EN_COURS)),
        garcons=Count("inscriptions", filter=Q(
            inscriptions__statut=Inscription.Statut.EN_COURS, inscriptions__eleve__sexe="M",
        )),
        filles=Count("inscriptions", filter=Q(
            inscriptions__statut=Inscription.Statut.EN_COURS, inscriptions__eleve__sexe="F",
        )),
        admis=Count("inscriptions", filter=Q(inscriptions__statut=Inscription.Statut.ADMIS)),
        redouble=Count("inscriptions", filter=Q(inscriptions__statut=Inscription.Statut.REDOUBLE)),
    )
    for classe in classes:
        total_decide = classe.admis + classe.redouble
        taux_reussite = round(100 * classe.admis / total_decide, 1) if total_decide else ""
        taux_echec = round(100 * classe.redouble / total_decide, 1) if total_decide else ""
        writer.writerow([
            classe.nom, classe.get_cycle_display(),
            classe.effectif_actif, classe.garcons, classe.filles,
            taux_reussite, taux_echec,
        ])
    return reponse


@module_requis(Module.STATISTIQUES)
def exporter_finances_csv(request):
    annee = _annee_selectionnee(request)
    classes = classes_visibles_pour(request.user).filter(annee_scolaire=annee) if annee else Classe.objects.none()
    paiements = Paiement.objects.filter(inscription__classe__in=classes, est_supprime=False)

    reponse = HttpResponse(content_type="text/csv; charset=utf-8")
    nom_fichier = f"finances_{annee.libelle if annee else 'sans_annee'}.csv"
    reponse["Content-Disposition"] = f'attachment; filename="{nom_fichier}"'
    reponse.write("﻿")
    writer = csv.writer(reponse)
    devise = getattr(request.user.etablissement, "code_devise", "FCFA")
    writer.writerow(["Échéance", f"Total encaissé ({devise})"])

    total_general = 0
    totaux = {
        ligne["tranche"]: ligne["total"] or 0
        for ligne in paiements.values("tranche").annotate(total=Sum("montant"))
    }
    for tranche in TypeTranche:
        total = totaux.get(tranche.value, 0)
        writer.writerow([tranche.label, total])
        total_general += total
    writer.writerow(["Total général", total_general])
    return reponse


def _contexte_annee(request, annee, actif):
    """Contexte commun de la barre latérale des statistiques (année choisie, classes visibles)."""
    classes = classes_visibles_pour(request.user).filter(annee_scolaire=annee) if annee else Classe.objects.none()
    return {
        "annee": annee, "toutes_annees": AnneeScolaire.objects.filter(etablissement=request.user.etablissement),
        "classes": classes, "actif": actif,
    }


@module_requis(Module.STATISTIQUES)
def fiche_annuelle(request):
    annee = _annee_selectionnee(request)
    contexte = _contexte_annee(request, annee, "fiche")
    contexte["fiche"] = construire_fiche(request.user, annee) if annee else None
    return render(request, "statistiques/fiche_annuelle.html", contexte)


def _fiche_a_exporter(request):
    """(fiche, nom de fichier sans extension) de l'année demandée, limitée à ce que l'utilisateur peut voir."""
    annee = _annee_selectionnee(request)
    if annee is None:
        raise Http404("Aucune année scolaire.")
    nom_annee = re.sub(r"[^A-Za-z0-9_-]+", "_", annee.libelle) or "annee"
    return construire_fiche(request.user, annee), f"fiche_statistique_{nom_annee}"


@module_requis(Module.STATISTIQUES)
def exporter_fiche_annuelle_xlsx(request):
    """Même contenu que le CSV, en classeur Excel mis en forme (chiffres reconnus comme des nombres)."""
    fiche, nom_fichier = _fiche_a_exporter(request)
    reponse = HttpResponse(content_type=TYPE_MIME_XLSX)
    reponse["Content-Disposition"] = f'attachment; filename="{nom_fichier}.xlsx"'
    classeur_fiche(fiche).save(reponse)
    enregistrer_action(
        acteur=request.user, action="export_fiche_statistique_annuelle", cible=fiche["annee"].libelle,
        details={"format": "xlsx"}, request=request,
    )
    return reponse


@module_requis(Module.STATISTIQUES)
def exporter_fiche_annuelle_csv(request):
    fiche, nom_fichier = _fiche_a_exporter(request)
    reponse = HttpResponse(content_type="text/csv; charset=utf-8")
    reponse["Content-Disposition"] = f'attachment; filename="{nom_fichier}.csv"'
    reponse.write("\ufeff")  # BOM UTF-8 : accents corrects dans Excel
    writer = csv.writer(reponse, delimiter=";")
    for ligne in lignes_csv(fiche):
        writer.writerow([cellule_csv(valeur) for valeur in ligne])
    enregistrer_action(
        acteur=request.user, action="export_fiche_statistique_annuelle", cible=fiche["annee"].libelle, request=request,
    )
    return reponse


@module_requis(Module.STATISTIQUES)
def resultats_examens(request):
    """Taux de réussite aux examens officiels et accès à la saisie par classe."""
    annee = _annee_selectionnee(request)
    contexte = _contexte_annee(request, annee, "examens")
    classes = []
    for classe in contexte["classes"].annotate(
        nombre_inscrits=Count("inscriptions", distinct=True),
        nombre_resultats=Count("inscriptions__resultats_examens", distinct=True),
    ).order_by("cycle", "nom"):
        examens = examens_pour_classe(classe)
        if examens:
            classe.libelles_examens = [libelle for valeur, libelle in Examen.choices if valeur in examens]
            classes.append(classe)
    from scolarite.views import ROLES_RESULTATS_EXAMEN
    contexte.update({
        "classes_examens": classes, "examens": statistiques_examens(contexte["classes"]) if annee else [],
        "peut_saisir": request.user.role in ROLES_RESULTATS_EXAMEN,
    })
    return render(request, "statistiques/resultats_examens.html", contexte)


@module_requis(Module.STATISTIQUES)
def infrastructures(request):
    annee = _annee_selectionnee(request)
    contexte = _contexte_annee(request, annee, "infrastructures")
    peut_modifier = request.user.role in ROLES_EDITION_INFRASTRUCTURE
    contexte["peut_modifier"] = peut_modifier
    if annee is None:
        contexte.update({"formulaire": None, "infra": None})
        return render(request, "statistiques/infrastructures.html", contexte)

    fiche = FicheInfrastructure.objects.filter(etablissement=request.user.etablissement, annee_scolaire=annee).first()
    instance = fiche or FicheInfrastructure(etablissement=request.user.etablissement, annee_scolaire=annee)
    if request.method == "POST":
        if not peut_modifier:
            raise PermissionDenied("Seule la direction de l'établissement peut modifier la fiche d'infrastructures.")
        formulaire = FicheInfrastructureForm(request.POST, instance=instance)
        if formulaire.is_valid():
            objet = formulaire.save(commit=False)
            objet.modifie_par = request.user
            try:
                objet.save()
            except IntegrityError:  # deux enregistrements simultanés de la même fiche : on recharge
                messages.warning(request, "La fiche vient d'être modifiée par quelqu'un d'autre : rechargez-la.")
            else:
                enregistrer_action(
                    acteur=request.user, action="modification_fiche_infrastructures", cible=annee.libelle, request=request,
                )
                messages.success(request, "Fiche d'infrastructures enregistrée.")
            return redirect(f"{reverse('statistiques:infrastructures')}?annee={annee.id}")
    else:
        formulaire = FicheInfrastructureForm(instance=instance) if peut_modifier else None
    contexte.update({"formulaire": formulaire, "infra": infrastructures_avec_ratios(request.user, annee)})
    return render(request, "statistiques/infrastructures.html", contexte)
