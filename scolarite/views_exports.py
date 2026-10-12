"""Export Excel de la liste des élèves d'une classe."""
import datetime

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from comptes.audit import enregistrer_action
from comptes.excel import ajouter_feuille_tableau, nom_fichier_sur, nouveau_classeur, reponse_xlsx
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


def liste_classe_classeur(utilisateur, classe):
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
    classeur = nouveau_classeur()
    ajouter_feuille_tableau(
        classeur, "Liste de classe", f"Liste des élèves - {classe.nom}",
        [
            ("Établissement", classe.annee_scolaire.etablissement.nom),
            ("Année scolaire", classe.annee_scolaire.libelle),
            (
                "Effectif",
                f"{len(inscriptions)} (dont {filles} fille{'s' if filles > 1 else ''} "
                f"et {garcons} garçon{'s' if garcons > 1 else ''})",
            ),
            ("Édité le", datetime.date.today()),
        ],
        entetes, lignes,
    )
    return classeur


@login_required
def exporter_liste_classe_xlsx(request, classe_id):
    # Une classe d'une autre école (ou d'un autre cycle pour un directeur de cycle) est « introuvable », comme une
    # classe qui n'existe pas.
    classe = get_object_or_404(classes_visibles_pour(request.user), id=classe_id)
    if not peut_exporter_liste_classe(request.user, classe):
        raise PermissionDenied("Vous n'avez pas le droit d'exporter la liste de cette classe.")
    enregistrer_action(acteur=request.user, action="export_liste_classe", cible=str(classe), request=request)
    return reponse_xlsx(
        liste_classe_classeur(request.user, classe),
        nom_fichier_sur("liste_eleves", classe.nom, classe.annee_scolaire.libelle),
    )
