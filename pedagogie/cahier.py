"""
Cahier de textes et suivi des programmes : qui peut les tenir, qui peut les lire, et les devoirs à venir des familles.

- Tenir (ajouter, corriger, supprimer) : l'enseignant affecté à la classe et à la matière, et la direction.
- Lire toutes les matières d'une classe : ceux qui tiennent le cahier, les directeurs de cycle, le censeur, le responsable pédagogique et les
  enseignants de la classe.
- Les parents et les élèves ne lisent que le cahier de LEUR classe, depuis la page « Devoirs ».
"""
import datetime

from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role
from pedagogie.models import SeanceCahier
from scolarite.models import Affectation, Inscription, classes_visibles_pour

ROLES_DIRECTION_PEDAGOGIQUE = {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL} | {Role.SUPER_ADMINISTRATEUR.value}
ROLES_LECTURE_CLASSE = ROLES_DIRECTION_PEDAGOGIQUE | {
    Role.DIRECTEUR_1ER_CYCLE.value, Role.DIRECTEUR_2EME_CYCLE.value, Role.DIRECTEUR_LYCEE.value, Role.CENSEUR.value,
    Role.RESPONSABLE_PEDAGOGIQUE.value,
}
JOURS_DE_DEVOIRS_RECENTS = 14


def peut_tenir(utilisateur, affectation) -> bool:
    """Ajouter, corriger ou supprimer le cahier et le programme de cette affectation."""
    if utilisateur.role == Role.ENSEIGNANT.value:
        return affectation.enseignant_id == utilisateur.pk
    return utilisateur.role in ROLES_DIRECTION_PEDAGOGIQUE and classes_visibles_pour(utilisateur).filter(pk=affectation.classe_id).exists()


def peut_lire_le_programme(utilisateur, affectation) -> bool:
    """Lire le programme d'une matière : ceux qui le tiennent et la supervision (directeurs, censeur, responsable pédagogique) de la classe."""
    if peut_tenir(utilisateur, affectation):
        return True
    return utilisateur.role in ROLES_LECTURE_CLASSE and classes_visibles_pour(utilisateur).filter(pk=affectation.classe_id).exists()


def peut_lire_la_classe(utilisateur, classe) -> bool:
    """Lire le cahier de toutes les matières d'une classe (personnel de l'école seulement)."""
    if not classes_visibles_pour(utilisateur).filter(pk=classe.pk).exists():
        return False
    if utilisateur.role == Role.ENSEIGNANT.value:
        return Affectation.objects.filter(enseignant=utilisateur, classe=classe).exists()
    return utilisateur.role in ROLES_LECTURE_CLASSE


def eleves_de_la_famille(utilisateur):
    """Les élèves dont le cahier est lisible par ce compte : ses enfants (parent) ou lui-même (élève)."""
    from comptes.models import Utilisateur

    if utilisateur.role == Role.PARENT.value:
        return Utilisateur.objects.filter(parents_lies=utilisateur, role=Role.ELEVE, etablissement_id=utilisateur.etablissement_id).order_by("nom", "prenom")
    if utilisateur.role == Role.ELEVE.value:
        return Utilisateur.objects.filter(pk=utilisateur.pk)
    return Utilisateur.objects.none()


def devoirs_des_familles(utilisateur, aujourdhui=None) -> list:
    """
    Pour chaque élève de la famille inscrit en cours : [{eleve, classe, a_rendre, recentes}] — les devoirs à rendre à partir d'aujourd'hui (les
    plus proches d'abord) et les séances des deux dernières semaines.
    """
    aujourdhui = aujourdhui or datetime.date.today()
    resultat = []
    for eleve in eleves_de_la_famille(utilisateur):
        inscription = Inscription.objects.filter(eleve=eleve, statut=Inscription.Statut.EN_COURS).select_related("classe").first()
        if inscription is None:
            continue
        seances = SeanceCahier.objects.filter(affectation__classe=inscription.classe).select_related("affectation")
        a_rendre = list(seances.filter(date_remise__gte=aujourdhui).exclude(travail_a_faire="").order_by("date_remise", "pk"))
        recentes = list(seances.filter(date_seance__gte=aujourdhui - datetime.timedelta(days=JOURS_DE_DEVOIRS_RECENTS)).order_by("-date_seance", "-pk"))
        resultat.append({"eleve": eleve, "classe": inscription.classe, "a_rendre": a_rendre, "recentes": recentes})
    return resultat
