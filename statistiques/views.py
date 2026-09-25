import csv

from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from comptes.decorators import module_requis
from comptes.roles import Role
from finances.models import Paiement, TypeTranche
from pedagogie.models import Note
from permissions_matrix.modules import Module
from scolarite.models import AnneeScolaire, Classe, Inscription, classes_visibles_pour


def _annee_selectionnee(request):
    annee_id = request.GET.get("annee")
    if annee_id:
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
