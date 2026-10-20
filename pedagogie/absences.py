"""Les parents sont prévenus dès qu'une absence de leur enfant est signalée."""
import datetime
import logging

from django.urls import reverse
from django.utils import timezone

from comptes.push import notifier
from comptes.roles import StatutCompte

logger = logging.getLogger(__name__)

JOURS_MAXIMUM = 3  # une absence saisie bien après coup (rattrapage du registre) ne réveille pas les familles


def prevenir_les_parents_de_l_absence(absence) -> int:
    """
    Une notification (et un message sur le téléphone, s'il est activé) pour chaque parent lié à l'élève, qui n'ont pas de courriel à lire pour cela.
    Renvoie le nombre de parents prévenus ; ne lève jamais d'erreur (l'absence est déjà enregistrée).
    """
    try:
        if absence.date_absence < timezone.localdate() - datetime.timedelta(days=JOURS_MAXIMUM):
            return 0
        eleve = absence.eleve
        parents = list(eleve.parents_lies.filter(is_active=True, statut=StatutCompte.ACTIF))
        if not parents:
            return 0
        jour = absence.date_absence.strftime("%d/%m/%Y")
        suite = " (justifiée)" if absence.justifiee else ""
        notifier(
            parents, titre=f"Absence de {eleve.prenom}", etablissement=eleve.etablissement,
            message=f"{eleve.nom_complet} est signalé(e) absent(e) le {jour}{suite}.",
            url=reverse("pedagogie:historique_absences", args=[eleve.matricule]),
        )
        return len(parents)
    except Exception:  # noqa: BLE001
        logger.exception("Notification d'absence non créée (absence %s)", getattr(absence, "pk", None))
        return 0
