"""
Registre de discipline : qui peut l'utiliser et prévenir les parents.

Les parents reçoivent un courriel (dans leur langue) et une notification pour toute mesure, sauf pour un retard : un retard isolé n'est pas
signalé, le courriel part au TROISIÈME retard du mois exactement (pas aux suivants : la famille est déjà prévenue).
"""
import logging

from django.conf import settings
from django.urls import reverse

from comptes.langue import langue_du_compte
from comptes.mail import envoyer_email
from comptes.models import Notification
from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role, StatutCompte
from pedagogie.models import MesureDiscipline, TypeMesureDiscipline

logger = logging.getLogger(__name__)

SEUIL_DE_RETARDS = 3

# La vie scolaire et la direction (comme la conduite, plus tous les directeurs de cycle) ; le secrétariat et l'enseignant de la classe
# enregistrent aussi une mesure. Jamais un parent, un élève, un comptable ni un bibliothécaire.
ROLES_SUPPRESSION_DISCIPLINE = {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL} | {
    Role.DIRECTEUR_1ER_CYCLE.value, Role.DIRECTEUR_2EME_CYCLE.value, Role.DIRECTEUR_LYCEE.value, Role.CENSEUR.value,
    Role.SURVEILLANT_GENERAL.value, Role.SUPER_ADMINISTRATEUR.value,
}
ROLES_SAISIE_DISCIPLINE = ROLES_SUPPRESSION_DISCIPLINE | {Role.SECRETAIRE.value, Role.ENSEIGNANT.value}


def retards_du_mois(eleve, date) -> int:
    """Le nombre de retards de l'élève dans le mois (calendaire) de `date`."""
    return MesureDiscipline.objects.filter(
        eleve=eleve, type_mesure=TypeMesureDiscipline.RETARD, date_mesure__year=date.year, date_mesure__month=date.month,
    ).count()


def parents_a_prevenir(eleve):
    """Les parents liés à l'élève qui ont un compte actif et une adresse : jamais l'adresse automatique de l'élève (lue par personne)."""
    return list(eleve.parents_lies.filter(is_active=True, statut=StatutCompte.ACTIF).exclude(email=""))


def _message(mesure, nombre_de_retards: int):
    eleve, classe = mesure.eleve, mesure.classe
    date = mesure.date_mesure.strftime("%d/%m/%Y")
    if mesure.type_mesure == TypeMesureDiscipline.RETARD:
        titre = f"Retards répétés - {eleve.nom_complet}"
        lignes = [
            "Bonjour,",
            f"{eleve.nom_complet} ({classe.nom}) est arrivé(e) en retard {nombre_de_retards} fois ce mois-ci.",
            "Merci de veiller à sa ponctualité. Pour en parler, contactez l'établissement.",
        ]
    else:
        titre = f"Mesure de discipline - {eleve.nom_complet}"
        lignes = [
            "Bonjour,",
            f"Une mesure de discipline a été enregistrée pour {eleve.nom_complet} ({classe.nom}).",
            f"Mesure : {mesure.get_type_mesure_display()}",
            f"Date : {date}",
            f"Motif : {mesure.motif}",
            "Pour en parler, merci de contacter l'établissement.",
        ]
    return titre, "\n".join(lignes)


def prevenir_les_parents(mesure) -> int:
    """
    Prévient les parents (courriel + notification) quand la règle le demande ; rend le nombre de parents prévenus.
    Ne lève jamais d'erreur : un courriel manquant ne doit pas faire échouer une mesure déjà enregistrée.
    """
    try:
        nombre_de_retards = 0
        if mesure.type_mesure == TypeMesureDiscipline.RETARD:
            nombre_de_retards = retards_du_mois(mesure.eleve, mesure.date_mesure)
            if nombre_de_retards != SEUIL_DE_RETARDS:
                return 0
        parents = parents_a_prevenir(mesure.eleve)
        if not parents:
            return 0
        etablissement = mesure.classe.annee_scolaire.etablissement
        titre, contenu = _message(mesure, nombre_de_retards)
        adresse = reverse("pedagogie:historique_discipline", args=[mesure.eleve.matricule])
        for parent in parents:
            Notification.objects.create(destinataire=parent, etablissement=etablissement, titre=titre, message=contenu.split("\n", 1)[1][:200], url=adresse)
            envoyer_email(
                sujet=titre, contenu=contenu, expediteur=settings.DEFAULT_FROM_EMAIL, destinataires=[parent.email],
                langue=langue_du_compte(parent), etablissement_id=etablissement.pk,
            )
        return len(parents)
    except Exception:  # noqa: BLE001 - voir la docstring
        logger.exception("Parents non prévenus d'une mesure de discipline (mesure %s)", getattr(mesure, "pk", None))
        return 0
