"""
Facturation de l'abonnement des écoles à la plateforme : émission, règlement, annulation, situation d'un abonnement.

Réservé au propriétaire de la plateforme (voir espace_plateforme). Montants en FCFA. Une facture n'est jamais supprimée :
émise, elle est payée ou annulée avec un motif ; une facture payée ne s'annule pas.
"""
import datetime
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from etablissement.models import Etablissement, FactureAbonnement, PlanEtablissement

DELAI_PAIEMENT_PAR_DEFAUT_JOURS = 15
STATUT = FactureAbonnement.Statut


def libelle_par_defaut(plan, periode_debut, periode_fin) -> str:
    formule = dict(PlanEtablissement.choices).get(plan, "")
    return (
        f"Abonnement {formule} - du {periode_debut:%d/%m/%Y} au {periode_fin:%d/%m/%Y}" if formule
        else f"Abonnement - du {periode_debut:%d/%m/%Y} au {periode_fin:%d/%m/%Y}"
    )


def prochain_numero(annee: int) -> str:
    """ABO-AAAA-NNNN : numérotation continue sur toute la plateforme, qui repart de 1 chaque année."""
    prefixe = f"ABO-{annee}-"
    dernier = (
        FactureAbonnement.objects.filter(numero__startswith=prefixe).order_by("-numero")
        .values_list("numero", flat=True).first()
    )
    suite = int(dernier.rsplit("-", 1)[1]) + 1 if dernier else 1
    return f"{prefixe}{suite:04d}"


def emettre_facture(*, etablissement, periode_debut, periode_fin, montant, cree_par,
                    date_echeance=None, libelle="", date_emission=None):
    """Émet une facture (statut « émise »). Lève ValidationError si la période chevauche une autre facture, etc."""
    date_emission = date_emission or timezone.localdate()
    date_echeance = date_echeance or date_emission + datetime.timedelta(days=DELAI_PAIEMENT_PAR_DEFAUT_JOURS)
    libelle = (libelle or "").strip() or libelle_par_defaut(etablissement.plan, periode_debut, periode_fin)
    for _ in range(5):
        facture = FactureAbonnement(
            etablissement=etablissement, numero=prochain_numero(date_emission.year), libelle=libelle,
            plan=etablissement.plan, periode_debut=periode_debut, periode_fin=periode_fin, montant=montant,
            date_emission=date_emission, date_echeance=date_echeance, cree_par=cree_par,
        )
        facture.clean_fields(exclude=["numero"])
        facture.clean()
        try:
            with transaction.atomic():
                facture.save()
            return facture
        except IntegrityError:
            # Deux émissions simultanées ont pris le même numéro : on réessaie avec le suivant. Toute autre
            # contrainte violée est une vraie erreur.
            if not FactureAbonnement.objects.filter(numero=facture.numero).exists():
                raise
    raise RuntimeError("Impossible d'attribuer un numéro de facture après plusieurs tentatives.")


def enregistrer_reglement(*, facture, date_paiement, mode_reglement, reference="", acteur=None):
    """Marque une facture émise comme payée. Une facture payée ou annulée ne peut plus être réglée."""
    with transaction.atomic():
        facture = FactureAbonnement.objects.select_for_update().get(pk=facture.pk)
        if facture.statut == STATUT.PAYEE:
            raise ValidationError("Cette facture est déjà payée.")
        if facture.statut == STATUT.ANNULEE:
            raise ValidationError("Cette facture est annulée : elle ne peut plus être réglée.")
        if date_paiement > timezone.localdate():
            raise ValidationError("La date du règlement ne peut pas être dans le futur.")
        if date_paiement < facture.date_emission:
            raise ValidationError("Le règlement ne peut pas précéder l'émission de la facture.")
        if mode_reglement not in FactureAbonnement.ModeReglement.values:
            raise ValidationError("Mode de règlement invalide.")
        facture.statut = STATUT.PAYEE
        facture.date_paiement = date_paiement
        facture.mode_reglement = mode_reglement
        facture.reference_reglement = (reference or "").strip()
        facture.save(update_fields=["statut", "date_paiement", "mode_reglement", "reference_reglement"])
        return facture


def annuler_facture(*, facture, motif, acteur=None):
    """Annule une facture émise, avec un motif obligatoire. Une facture payée ne s'annule pas."""
    motif = (motif or "").strip()
    if not motif:
        raise ValidationError("Indiquez le motif de l'annulation.")
    with transaction.atomic():
        facture = FactureAbonnement.objects.select_for_update().get(pk=facture.pk)
        if facture.statut == STATUT.PAYEE:
            raise ValidationError("Une facture payée ne peut pas être annulée.")
        if facture.statut == STATUT.ANNULEE:
            raise ValidationError("Cette facture est déjà annulée.")
        facture.statut = STATUT.ANNULEE
        facture.motif_annulation = motif[:255]
        facture.save(update_fields=["statut", "motif_annulation"])
        return facture


# ---------------------------------------------------------------------------
# Alertes du propriétaire : factures à payer et factures en retard
# ---------------------------------------------------------------------------

def _montant(valeur) -> str:
    return f"{valeur:,}".replace(",", " ")


def alertes_factures(aujourdhui=None) -> list[dict]:
    """
    Les alertes affichées en haut des pages du propriétaire (liste des établissements, abonnements, factures) : d'abord les
    factures émises dont l'échéance est dépassée, puis celles qui restent à payer dans les délais. Le propriétaire n'a pas de
    tableau de bord (il est renvoyé vers la liste des établissements) : c'est là qu'elles se voient. Les écoles concernées sont
    dans `factures`.
    """
    aujourdhui = aujourdhui or timezone.localdate()
    emises = list(
        FactureAbonnement.objects.filter(statut=STATUT.EMISE).select_related("etablissement").order_by("date_echeance", "id")
    )
    en_retard = [f for f in emises if f.date_echeance < aujourdhui]
    a_payer = [f for f in emises if f.date_echeance >= aujourdhui]
    alertes = []
    if en_retard:
        jours = (aujourdhui - en_retard[0].date_echeance).days
        alertes.append({
            "type": "abonnement", "gravite": "danger", "statut": "en_retard", "details": [], "factures": en_retard,
            "titre": f"{len(en_retard)} facture{'s' if len(en_retard) > 1 else ''} d'abonnement en retard de paiement",
            "description": f"{_montant(sum(f.montant for f in en_retard))} FCFA à encaisser ; la plus ancienne a {jours} jour{'s' if jours > 1 else ''} de retard.",
        })
    if a_payer:
        prochaine = a_payer[0].date_echeance
        alertes.append({
            "type": "abonnement", "gravite": "attention", "statut": "a_payer", "details": [], "factures": a_payer,
            "titre": f"{len(a_payer)} facture{'s' if len(a_payer) > 1 else ''} d'abonnement à payer",
            "description": f"{_montant(sum(f.montant for f in a_payer))} FCFA à encaisser ; prochaine échéance le {prochaine:%d/%m/%Y}.",
        })
    return alertes


# ---------------------------------------------------------------------------
# Situation d'un abonnement
# ---------------------------------------------------------------------------

LIBELLES_SITUATION = {
    "en_retard": "En retard de paiement",
    "a_jour": "À jour",
    "en_attente": "Facture à payer",
    "expire": "Abonnement expiré",
    "aucune": "Aucune facture",
}


@dataclass
class SituationAbonnement:
    code: str
    couvert_jusqu_au: datetime.date | None = None
    nombre_en_retard: int = 0
    montant_en_retard: int = 0
    montant_a_payer: int = 0  # factures émises, échues ou non

    @property
    def libelle(self):
        return LIBELLES_SITUATION[self.code]


def _situation(factures, aujourdhui) -> SituationAbonnement:
    emises = [f for f in factures if f.statut == STATUT.EMISE]
    payees = [f for f in factures if f.statut == STATUT.PAYEE]
    en_retard = [f for f in emises if f.date_echeance < aujourdhui]
    couvert_jusqu_au = max((f.periode_fin for f in payees), default=None)
    if en_retard:
        code = "en_retard"
    elif any(f.periode_debut <= aujourdhui <= f.periode_fin for f in payees):
        code = "a_jour"
    elif emises:
        code = "en_attente"
    elif payees:
        code = "expire"
    else:
        code = "aucune"
    return SituationAbonnement(
        code=code, couvert_jusqu_au=couvert_jusqu_au, nombre_en_retard=len(en_retard),
        montant_en_retard=sum(f.montant for f in en_retard), montant_a_payer=sum(f.montant for f in emises),
    )


def situation_abonnement(etablissement, aujourdhui=None) -> SituationAbonnement:
    aujourdhui = aujourdhui or timezone.localdate()
    return _situation(
        list(FactureAbonnement.objects.filter(etablissement=etablissement).exclude(statut=STATUT.ANNULEE)), aujourdhui,
    )


def synthese_abonnements(aujourdhui=None):
    """
    Vue d'ensemble pour le propriétaire : [(établissement, situation)] pour toutes les écoles (une seule requête de
    factures) et les totaux « encaissé cette année », « à encaisser », « en retard ».
    """
    aujourdhui = aujourdhui or timezone.localdate()
    par_ecole = {}
    for facture in FactureAbonnement.objects.exclude(statut=STATUT.ANNULEE):
        par_ecole.setdefault(facture.etablissement_id, []).append(facture)
    lignes = [
        (etablissement, _situation(par_ecole.get(etablissement.pk, []), aujourdhui))
        for etablissement in Etablissement.objects.order_by("nom")
    ]
    factures = [f for liste in par_ecole.values() for f in liste]
    totaux = {
        "encaisse_annee": sum(
            f.montant for f in factures if f.statut == STATUT.PAYEE and f.date_paiement and f.date_paiement.year == aujourdhui.year
        ),
        "en_retard": sum(f.montant for f in factures if f.statut == STATUT.EMISE and f.date_echeance < aujourdhui),
        "a_encaisser": sum(f.montant for f in factures if f.statut == STATUT.EMISE and f.date_echeance >= aujourdhui),
        "ecoles_a_jour": sum(1 for _, situation in lignes if situation.code == "a_jour"),
        "ecoles_en_retard": sum(1 for _, situation in lignes if situation.code == "en_retard"),
        "annee": aujourdhui.year,
    }
    return lignes, totaux
