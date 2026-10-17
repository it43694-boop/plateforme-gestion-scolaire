"""Courriel aux parents quand un paiement de scolarité est enregistré (reçu, montant, reste à payer)."""
import logging

from django.conf import settings
from django.db.models import Sum

from comptes.langue import langue_du_compte
from comptes.mail import envoyer_email
from comptes.roles import StatutCompte

logger = logging.getLogger(__name__)


def parents_a_prevenir(eleve):
    """Les parents liés à l'élève qui ont un compte actif et une adresse : jamais l'adresse automatique de l'élève (lue par personne)."""
    return list(eleve.parents_lies.filter(is_active=True, statut=StatutCompte.ACTIF).exclude(email=""))


def reste_a_payer(inscription) -> int:
    """Ce qui reste dû sur l'inscription après tous les paiements (jamais négatif)."""
    from finances.models import Paiement
    from scolarite.models import calculer_total_du

    paye = Paiement.objects.filter(inscription=inscription, est_supprime=False).aggregate(total=Sum("montant"))["total"] or 0
    return max(calculer_total_du(inscription) - paye, 0)


def prevenir_les_parents_du_paiement(paiement) -> int:
    """
    Un courriel par parent, dans sa langue. Renvoie le nombre de parents prévenus.
    Ne lève jamais d'erreur : un courriel manquant ne doit pas faire échouer un paiement déjà enregistré.
    """
    try:
        parents = parents_a_prevenir(paiement.eleve)
        if not parents:
            return 0
        etablissement = paiement.etablissement or paiement.eleve.etablissement
        devise = getattr(etablissement, "code_devise", "FCFA")
        solde = reste_a_payer(paiement.inscription)
        classe = paiement.inscription.classe
        lignes = [
            "Bonjour,",
            f"Un paiement de {paiement.montant} {devise} a été enregistré pour {paiement.eleve.nom_complet} ({classe.nom}).",
            f"Reçu n° {paiement.reference}.",
            f"Reste à payer : {solde} {devise}." if solde > 0 else "La scolarité est entièrement réglée.",
            "Merci de votre confiance.",
        ]
        contenu = "\n".join(lignes)
        for parent in parents:
            envoyer_email(
                sujet=f"Paiement enregistré - reçu {paiement.reference}", contenu=contenu,
                expediteur=settings.DEFAULT_FROM_EMAIL, destinataires=[parent.email],
                langue=langue_du_compte(parent), etablissement_id=getattr(etablissement, "pk", None),
            )
        return len(parents)
    except Exception:  # noqa: BLE001 - voir la docstring : le paiement est déjà enregistré
        logger.exception("Courriel de paiement non envoyé (paiement %s)", getattr(paiement, "pk", None))
        return 0
