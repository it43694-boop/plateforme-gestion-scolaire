"""
Matrice de permissions par défaut - dérivée du tableau des rôles et de la
description de chaque module dans le cahier des charges (sections 3 et 5).

Interprétation retenue là où le cahier ne détaille pas explicitement le
module (ex. accès de l'Assistant, de la Bibliothèque ou de la
Communication pour un rôle donné) : ces choix restent modifiables sans
redéploiement depuis l'espace développeur - c'est précisément la raison
d'être de cette matrice. Toute décision différente du commanditaire peut
être appliquée en modifiant les lignes correspondantes, sans toucher au
code.

Les rôles à accès total inconditionnel (développeur, fondateur,
administrateur_general) ne figurent pas ici : ils contournent la matrice
par construction (voir PermissionMatrix.a_acces).
"""

from comptes.roles import Role
from permissions_matrix.modules import Module

M = Module

MATRICE_PAR_DEFAUT = {
    Role.DIRECTEUR_1ER_CYCLE: {
        M.CLASSES, M.ELEVES, M.ENSEIGNANTS, M.EMPLOI_DU_TEMPS, M.SUIVI_DES_COURS,
        M.NOTES_BULLETINS, M.ABSENCES, M.TESTS_DE_NIVEAU, M.STATISTIQUES,
        M.BIBLIOTHEQUE, M.COMMUNICATION, M.ASSISTANT,
    },
    Role.DIRECTEUR_2EME_CYCLE: {
        M.CLASSES, M.ELEVES, M.ENSEIGNANTS, M.EMPLOI_DU_TEMPS, M.SUIVI_DES_COURS,
        M.NOTES_BULLETINS, M.ABSENCES, M.TESTS_DE_NIVEAU, M.STATISTIQUES,
        M.BIBLIOTHEQUE, M.COMMUNICATION, M.ASSISTANT,
    },
    # Rôle technique réservé : périmètre large, mais jamais la gestion des
    # rôles/matrice, réservée exclusivement au développeur.
    Role.SUPER_ADMINISTRATEUR: set(Module) - {M.ESPACE_DEVELOPPEUR},
    Role.SECRETAIRE: {
        M.CLASSES, M.ELEVES, M.TESTS_DE_NIVEAU, M.COMMUNICATION, M.ASSISTANT,
    },
    Role.COMPTABLE: {
        M.FINANCES, M.CAISSE, M.SALAIRES, M.STATISTIQUES, M.ASSISTANT,
    },
    Role.RESPONSABLE_PEDAGOGIQUE: {
        M.ENSEIGNANTS, M.SUIVI_DES_COURS, M.STATISTIQUES, M.NOTES_BULLETINS, M.ASSISTANT,
    },
    Role.BIBLIOTHECAIRE: {
        M.BIBLIOTHEQUE, M.ASSISTANT,
    },
    # Rôle générique : aucun module par défaut, précisé ensuite par le développeur.
    Role.PERSONNEL: set(),
    Role.ENSEIGNANT: {
        M.CLASSES, M.EMPLOI_DU_TEMPS, M.NOTES_BULLETINS,
        M.ABSENCES, M.BIBLIOTHEQUE, M.COMMUNICATION, M.ASSISTANT,
    },
    Role.PARENT: {
        M.ELEVES, M.FINANCES, M.NOTES_BULLETINS, M.ABSENCES, M.COMMUNICATION,
    },
    Role.ELEVE: {
        M.ELEVES, M.NOTES_BULLETINS, M.ABSENCES, M.EMPLOI_DU_TEMPS, M.BIBLIOTHEQUE, M.COMMUNICATION,
    },
}


def generer_lignes():
    """Retourne la liste complète (role, module, autorise) pour tous les rôles couverts."""
    lignes = []
    for role, modules_autorises in MATRICE_PAR_DEFAUT.items():
        for module in Module:
            lignes.append({
                "role": role.value,
                "module": module.value,
                "autorise": module in modules_autorises,
            })
    return lignes
