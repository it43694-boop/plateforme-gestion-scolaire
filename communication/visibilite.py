"""Ce qu'une personne a le droit de voir dans les annonces : celles de toute l'école, et celles de ses classes (jamais celles des autres classes)."""
from django.db.models import Q

from communication.models import Annonce, Portee
from scolarite.models import CYCLE_PAR_ROLE_CLOISONNE, classes_visibles_pour
from comptes.roles import Role

ROLES_A_PERIMETRE_DE_CLASSES = {Role.ENSEIGNANT.value, Role.PARENT.value, Role.ELEVE.value} | set(CYCLE_PAR_ROLE_CLOISONNE)


def annonces_visibles_pour(utilisateur):
    """
    Les annonces de l'école de l'utilisateur qu'il peut lire. Un enseignant, un parent, un élève et un directeur de cycle (ou censeur, surveillant
    général) ne lisent que les annonces de toute l'école et celles des classes qu'ils ont le droit de voir (voir `classes_visibles_pour`) ; un
    enseignant lit aussi les siennes. La direction, le secrétariat et les autres rôles lisent toutes les annonces de l'école.
    """
    annonces = Annonce.objects.filter(etablissement_id=utilisateur.etablissement_id)
    if utilisateur.role in ROLES_A_PERIMETRE_DE_CLASSES:
        annonces = annonces.filter(
            Q(portee=Portee.TOUTE_ECOLE) | Q(classe_ciblee__in=classes_visibles_pour(utilisateur)) | Q(auteur=utilisateur),
        )
    return annonces
