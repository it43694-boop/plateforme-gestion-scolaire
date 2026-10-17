"""
Clôture des notes par trimestre.

La direction clôture un trimestre pour toute une année scolaire : plus aucune note (matières, conduite) ne s'y saisit ni ne s'y corrige. Elle peut
le rouvrir. Une année archivée est toujours clôturée. Seuls le fondateur, l'administrateur général et le développeur clôturent ou rouvrent.
"""
from django.core.exceptions import ValidationError

from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL
from pedagogie.models import PeriodeCloturee, Trimestre

ROLES_CLOTURE = {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL}
MESSAGE_ANNEE_ARCHIVEE = "Cette année scolaire est archivée : les notes ne s'y modifient plus."


def trimestres_clotures(annee) -> set:
    """Les trimestres clôturés de l'année : tous si elle est archivée."""
    if annee.est_archivee:
        return {valeur for valeur, _ in Trimestre.choices}
    return set(PeriodeCloturee.objects.filter(annee_scolaire=annee).values_list("trimestre", flat=True))


def periode_cloturee(classe, trimestre) -> bool:
    annee = classe.annee_scolaire
    return annee.est_archivee or PeriodeCloturee.objects.filter(annee_scolaire=annee, trimestre=trimestre).exists()


def verifier_periode_ouverte(classe, trimestre):
    """Lève ValidationError si les notes de ce trimestre ne peuvent plus changer pour cette classe."""
    if classe.annee_scolaire.est_archivee:
        raise ValidationError(MESSAGE_ANNEE_ARCHIVEE)
    if PeriodeCloturee.objects.filter(annee_scolaire=classe.annee_scolaire, trimestre=trimestre).exists():
        libelle = dict(Trimestre.choices).get(trimestre, "Ce trimestre")
        raise ValidationError(f"Les notes du {libelle} sont clôturées : la direction doit les rouvrir pour les modifier.")


def cloturer(annee, trimestre, par) -> bool:
    """Clôture le trimestre ; rend False s'il l'était déjà."""
    _, cree = PeriodeCloturee.objects.get_or_create(annee_scolaire=annee, trimestre=trimestre, defaults={"cloturee_par": par})
    return cree


def rouvrir(annee, trimestre) -> bool:
    """Rouvre le trimestre ; rend False s'il n'était pas clôturé. Impossible pour une année archivée."""
    if annee.est_archivee:
        raise ValidationError(MESSAGE_ANNEE_ARCHIVEE)
    supprimees, _ = PeriodeCloturee.objects.filter(annee_scolaire=annee, trimestre=trimestre).delete()
    return bool(supprimees)
