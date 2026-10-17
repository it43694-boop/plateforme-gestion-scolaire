"""Export de la liste des élèves d'une classe : Excel, CSV et PDF."""
import csv
import datetime

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string

from comptes.audit import enregistrer_action
from comptes.excel import (
    ajouter_feuille_tableau, cellule_csv, ligne_csv_pour_langue, nom_fichier_sur, nouveau_classeur, reponse_xlsx,
)
from comptes.pdf import creer_pdf
from scolarite.documents import logo_en_donnees
from comptes.roles import Role
from permissions_matrix.models import PermissionMatrix
from scolarite.models import (
    ROLES_ETAT_CIVIL_ELEVE, ROLES_VOIENT_TOUT_ELEVE_DE_LETABLISSEMENT, Affectation, Inscription,
    classes_visibles_pour,
)


def peut_exporter_liste_classe(utilisateur, classe) -> bool:
    """
    Qui peut obtenir la liste des élèves d'une classe : l'administration qui voit tous les élèves (selon la matrice de
    permissions du module Élèves) et l'enseignant AFFECTÉ à cette classe. Jamais un parent, un élève ni un rôle sans
    lien avec les dossiers (bibliothécaire, personnel générique).
    """
    etablissement = utilisateur.etablissement
    if utilisateur.role in {Role.PARENT.value, Role.ELEVE.value}:
        return False
    if utilisateur.role == Role.ENSEIGNANT:
        return Affectation.objects.filter(enseignant=utilisateur, classe=classe).exists() and any(
            PermissionMatrix.a_acces(utilisateur.role, module, etablissement=etablissement)
            for module in ("notes_bulletins", "absences")
        )
    return utilisateur.role in ROLES_VOIENT_TOUT_ELEVE_DE_LETABLISSEMENT and PermissionMatrix.a_acces(
        utilisateur.role, "eleves", etablissement=etablissement,
    )


def droits_export_listes(utilisateur) -> dict:
    """
    Quels boutons « Excel » afficher à l'administration sur les pages de classes : même règle que les vues d'export (qui
    refusent de toute façon ce qui n'est pas autorisé), évaluée au niveau du rôle.
    """
    voit_tout = utilisateur.role in ROLES_VOIENT_TOUT_ELEVE_DE_LETABLISSEMENT
    etablissement = utilisateur.etablissement
    return {
        "peut_exporter_liste": voit_tout and PermissionMatrix.a_acces(utilisateur.role, "eleves", etablissement=etablissement),
        "peut_exporter_notes": voit_tout and PermissionMatrix.a_acces(utilisateur.role, "notes_bulletins", etablissement=etablissement),
        "peut_exporter_absences": voit_tout and PermissionMatrix.a_acces(utilisateur.role, "absences", etablissement=etablissement),
    }


def donnees_liste_classe(utilisateur, classe):
    """Les colonnes et les lignes de la liste d'une classe, communes aux trois formats (Excel, CSV, PDF)."""
    inscriptions = list(
        Inscription.objects.filter(classe=classe).select_related("eleve").order_by("eleve__nom", "eleve__prenom")
    )
    avec_naissance = utilisateur.role in ROLES_ETAT_CIVIL_ELEVE  # l'état civil n'est jamais exporté vers un enseignant
    entetes = ["N°", "Matricule", "Nom", "Prénom", "Sexe"] + (["Date de naissance"] if avec_naissance else []) + ["Statut"]
    lignes = []
    for numero, inscription in enumerate(inscriptions, start=1):
        eleve = inscription.eleve
        ligne = [numero, eleve.matricule, eleve.nom, eleve.prenom, eleve.get_sexe_display() if eleve.sexe else ""]
        if avec_naissance:
            ligne.append(eleve.date_naissance)
        ligne.append(inscription.get_statut_display())
        lignes.append(ligne)
    filles = sum(1 for i in inscriptions if i.eleve.sexe == "F")
    garcons = sum(1 for i in inscriptions if i.eleve.sexe == "M")
    effectif = f"{len(inscriptions)} (dont {filles} fille{'s' if filles > 1 else ''} et {garcons} garçon{'s' if garcons > 1 else ''})"
    return entetes, lignes, effectif


def liste_classe_classeur(utilisateur, classe):
    entetes, lignes, effectif = donnees_liste_classe(utilisateur, classe)
    classeur = nouveau_classeur()
    ajouter_feuille_tableau(
        classeur, "Liste de classe", f"Liste des élèves - {classe.nom}",
        [
            ("Établissement", classe.annee_scolaire.etablissement.nom),
            ("Année scolaire", classe.annee_scolaire.libelle),
            ("Effectif", effectif),
            ("Édité le", datetime.date.today()),
        ],
        entetes, lignes,
    )
    return classeur


def _classe_exportable(request, classe_id):
    # Une classe d'une autre école (ou d'un autre cycle pour un directeur de cycle) est « introuvable », comme une
    # classe qui n'existe pas.
    classe = get_object_or_404(classes_visibles_pour(request.user), id=classe_id)
    if not peut_exporter_liste_classe(request.user, classe):
        raise PermissionDenied("Vous n'avez pas le droit d'exporter la liste de cette classe.")
    return classe


@login_required
def exporter_liste_classe_xlsx(request, classe_id):
    classe = _classe_exportable(request, classe_id)
    enregistrer_action(acteur=request.user, action="export_liste_classe", cible=str(classe), request=request)
    return reponse_xlsx(
        liste_classe_classeur(request.user, classe),
        nom_fichier_sur("liste_eleves", classe.nom, classe.annee_scolaire.libelle),
        request=request,
    )


@login_required
def exporter_liste_classe_csv(request, classe_id):
    classe = _classe_exportable(request, classe_id)
    enregistrer_action(acteur=request.user, action="export_liste_classe", cible=str(classe), details={"format": "csv"}, request=request)
    entetes, lignes, _ = donnees_liste_classe(request.user, classe)
    reponse = HttpResponse(content_type="text/csv; charset=utf-8")
    nom = nom_fichier_sur("liste_eleves", classe.nom, classe.annee_scolaire.libelle)
    reponse["Content-Disposition"] = f'attachment; filename="{nom}.csv"'
    reponse.write("﻿")  # BOM UTF-8 : Excel affiche alors correctement les accents et l'arabe
    ecrivain = csv.writer(reponse, delimiter=";")
    ecrivain.writerow(ligne_csv_pour_langue(request, entetes))
    for ligne in lignes:
        # Un nom saisi par un utilisateur ne doit jamais être lu comme une formule par Excel (cellule_csv).
        ecrivain.writerow(ligne_csv_pour_langue(request, [cellule_csv(valeur) for valeur in ligne]))
    return reponse


@login_required
def exporter_liste_classe_pdf(request, classe_id):
    classe = _classe_exportable(request, classe_id)
    entetes, lignes, effectif = donnees_liste_classe(request.user, classe)
    html = render_to_string("scolarite/liste_classe_pdf.html", {
        "classe": classe, "entetes": entetes, "lignes": lignes, "effectif": effectif, "edite_le": datetime.date.today(),
        "logo": logo_en_donnees(request.user.etablissement),
    }, request=request)
    reponse = HttpResponse(content_type="application/pdf")
    nom = nom_fichier_sur("liste_eleves", classe.nom, classe.annee_scolaire.libelle)
    reponse["Content-Disposition"] = f'attachment; filename="{nom}.pdf"'
    if creer_pdf(html, reponse, request=request).err:
        return HttpResponse("Erreur lors de la génération du PDF.", status=500)
    enregistrer_action(acteur=request.user, action="export_liste_classe", cible=str(classe), details={"format": "pdf"}, request=request)
    return reponse
