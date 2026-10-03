"""
Rôles applicatifs - plateforme de gestion scolaire.

Liste figée telle que définie au cahier des charges (section « Rôles et
permissions »). Un rôle nouveau nécessite une évolution de code (migration +
ajout ici) : ce n'est pas une donnée libre, contrairement à la matrice de
permissions qui, elle, reste modifiable sans redéploiement depuis l'espace
développeur.
"""

from django.db import models


class Role(models.TextChoices):
    DEVELOPPEUR = "developpeur", "Développeur"
    FONDATEUR = "fondateur", "Fondateur"
    ADMINISTRATEUR_GENERAL = "administrateur_general", "Administrateur général"
    DIRECTEUR_1ER_CYCLE = "directeur_1er_cycle", "Directeur du 1er cycle"
    DIRECTEUR_2EME_CYCLE = "directeur_2eme_cycle", "Directeur du 2ème cycle"
    DIRECTEUR_LYCEE = "directeur_lycee", "Directeur du lycée"
    SUPER_ADMINISTRATEUR = "super_administrateur", "Super administrateur"
    SECRETAIRE = "secretaire", "Secrétaire"
    COMPTABLE = "comptable", "Comptable"
    RESPONSABLE_PEDAGOGIQUE = "responsable_pedagogique", "Responsable pédagogique"
    BIBLIOTHECAIRE = "bibliothecaire", "Bibliothécaire"
    PERSONNEL = "personnel", "Personnel (générique)"
    ENSEIGNANT = "enseignant", "Enseignant"
    PARENT = "parent", "Parent"
    ELEVE = "eleve", "Élève"


# Rôles pouvant valider un compte en attente (secrétariat ou direction)
ROLES_VALIDATION_COMPTES = {
    Role.SECRETAIRE,
    Role.FONDATEUR,
    Role.ADMINISTRATEUR_GENERAL,
    Role.DEVELOPPEUR,
}

# Rôles ayant accès complet à toute l'application, matrice de permissions
# non applicable (le développeur reste le seul à pouvoir la modifier).
ROLES_ACCES_TOTAL_INCONDITIONNEL = {
    Role.DEVELOPPEUR,
    Role.FONDATEUR,
    Role.ADMINISTRATEUR_GENERAL,
}

# Rôles pour lesquels la 2FA n'est plus optionnelle (comptes.middleware.
# ForcerActivation2FAMiddleware) : accès total inconditionnel, plus les deux
# rôles techniques/financiers les plus exposés en cas de mot de passe seul
# compromis. Un mot de passe volé ne suffit plus à agir sur ces comptes-là.
ROLES_2FA_OBLIGATOIRE = ROLES_ACCES_TOTAL_INCONDITIONNEL | {
    Role.SUPER_ADMINISTRATEUR,
    Role.COMPTABLE,
}

# Statuts de compte
class StatutCompte(models.TextChoices):
    EN_ATTENTE_VERIFICATION_EMAIL = "en_attente_verification_email", "En attente de vérification de l'email"
    EN_ATTENTE_VALIDATION = "en_attente_validation", "En attente de validation (secrétariat/direction)"
    ACTIF = "actif", "Actif"
    SUSPENDU = "suspendu", "Suspendu"
    DESACTIVE = "desactive", "Désactivé"
