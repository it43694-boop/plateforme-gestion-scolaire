"""
Cantine : ce que chaque élève doit, les inscriptions, l'appel du jour, les paiements.

Le calcul du dû est un pur calcul (`calculer_du`) pour qu'une liste entière se calcule sans requête par ligne : le nombre de repas et le total
payé arrivent déjà additionnés par la base (`avec_soldes`).
"""
import datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from cantine.models import InscriptionCantine, ModeCantine, PaiementCantine, RepasCantine
from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL
from finances.models import MouvementCaisse, generer_reference


def mois_commences(debut: datetime.date, fin: datetime.date) -> int:
    """Nombre de mois civils touchés entre deux dates, les deux mois inclus (tout mois commencé est dû)."""
    if fin < debut:
        return 0
    return (fin.year - debut.year) * 12 + fin.month - debut.month + 1


def calculer_du(*, mode: str, tarif: int, debut: datetime.date, fin: datetime.date | None, fin_annee: datetime.date,
                nombre_de_repas: int, aujourdhui: datetime.date) -> int:
    """
    Ce que l'élève doit à ce jour. Au mois : les mois commencés depuis l'inscription, jusqu'à sa fin ou à défaut jusqu'à aujourd'hui, sans
    dépasser la fin de l'année scolaire. Au repas : les repas servis.
    """
    if mode == ModeCantine.REPAS:
        return nombre_de_repas * tarif
    jusqu_a = min(fin or aujourdhui, fin_annee)
    return mois_commences(debut, jusqu_a) * tarif


def avec_soldes(inscriptions, aujourdhui=None):
    """
    Les inscriptions (un queryset) enrichies pour l'affichage : `nb_repas`, `total_paye`, `du` et `solde` (positif = reste à payer, négatif =
    payé d'avance). Deux sous-requêtes, jamais une requête par élève.
    """
    aujourdhui = aujourdhui or timezone.localdate()
    repas = RepasCantine.objects.filter(inscription=OuterRef("pk")).values("inscription").annotate(n=Count("pk")).values("n")
    paye = (
        PaiementCantine.objects.filter(inscription=OuterRef("pk"), annule=False).values("inscription")
        .annotate(total=Sum("montant")).values("total")
    )
    lignes = list(
        inscriptions.select_related("eleve", "formule", "annee_scolaire")
        .annotate(nb_repas=Coalesce(Subquery(repas), 0), total_paye=Coalesce(Subquery(paye), 0))
    )
    for inscription in lignes:
        inscription.du = calculer_du(
            mode=inscription.formule.mode, tarif=inscription.formule.montant, debut=inscription.date_debut, fin=inscription.date_fin,
            fin_annee=inscription.annee_scolaire.date_fin, nombre_de_repas=inscription.nb_repas, aujourdhui=aujourdhui,
        )
        inscription.solde = inscription.du - inscription.total_paye
        inscription.avance = max(-inscription.solde, 0)  # payé d'avance
    return lignes


def solde_de(inscription, aujourdhui=None) -> dict:
    """Le même calcul pour une seule inscription."""
    ligne = avec_soldes(InscriptionCantine.objects.filter(pk=inscription.pk), aujourdhui)[0]
    return {"nb_repas": ligne.nb_repas, "total_paye": ligne.total_paye, "du": ligne.du, "solde": ligne.solde, "avance": ligne.avance}


# ---------------------------------------------------------------------------
# Inscriptions
# ---------------------------------------------------------------------------

def inscrire(*, eleve, formule, annee, date_debut, acteur) -> InscriptionCantine:
    """Inscrit un élève à la cantine ; ValidationError s'il a déjà une inscription ouverte cette année."""
    if InscriptionCantine.objects.filter(eleve=eleve, annee_scolaire=annee, date_fin__isnull=True).exists():
        raise ValidationError(f"{eleve.nom_complet} est déjà inscrit(e) à la cantine.")
    inscription = InscriptionCantine(
        etablissement=annee.etablissement, eleve=eleve, annee_scolaire=annee, formule=formule, date_debut=date_debut, cree_par=acteur,
    )
    inscription.full_clean()
    inscription.save()
    return inscription


def terminer(*, inscription, date_fin, acteur) -> None:
    """Met fin à l'inscription (l'élève ne mange plus à la cantine) ; ses repas et ses paiements restent."""
    if not inscription.ouverte:
        raise ValidationError("Cette inscription est déjà terminée.")
    inscription.date_fin = date_fin
    inscription.full_clean()
    inscription.save(update_fields=["date_fin"])


# ---------------------------------------------------------------------------
# Appel du jour
# ---------------------------------------------------------------------------

def inscrits_ce_jour(etablissement, date):
    """Les inscriptions qui mangent à la cantine ce jour-là (commencées, pas terminées)."""
    return (
        InscriptionCantine.objects.filter(etablissement=etablissement, date_debut__lte=date, annee_scolaire__est_archivee=False)
        .filter(Q(date_fin__isnull=True) | Q(date_fin__gte=date))
        .select_related("eleve", "formule").order_by("eleve__nom", "eleve__prenom", "pk")
    )


def enregistrer_appel(*, etablissement, date, presents_ids, acteur) -> tuple[int, int]:
    """
    Enregistre l'appel d'un jour : seuls les élèves cochés ont mangé. Rejoue sans doublon (refaire l'appel le même jour corrige le
    précédent). Rend (repas ajoutés, repas retirés). Pas de date future.
    """
    if date > timezone.localdate():
        raise ValidationError("On ne peut pas faire l'appel d'un jour qui n'est pas encore venu.")
    with transaction.atomic():
        valides = {inscription.pk for inscription in inscrits_ce_jour(etablissement, date)}
        presents = set(presents_ids) & valides
        deja = set(RepasCantine.objects.filter(inscription__in=valides, date_repas=date).values_list("inscription_id", flat=True))
        a_ajouter = presents - deja
        RepasCantine.objects.bulk_create([RepasCantine(inscription_id=pk, date_repas=date, saisi_par=acteur) for pk in a_ajouter])
        a_retirer = deja - presents
        RepasCantine.objects.filter(inscription_id__in=a_retirer, date_repas=date).delete()
    return len(a_ajouter), len(a_retirer)


# ---------------------------------------------------------------------------
# Paiements
# ---------------------------------------------------------------------------

def enregistrer_paiement(*, inscription, montant, mode_paiement, acteur) -> PaiementCantine:
    """Crée le paiement ET sa ligne de Caisse, de façon atomique."""
    etablissement = inscription.etablissement
    with transaction.atomic():
        paiement = PaiementCantine(
            etablissement=etablissement, inscription=inscription, montant=montant, mode_paiement=mode_paiement, enregistre_par=acteur,
            reference=generer_reference("CAN", etablissement),
        )
        paiement.full_clean()
        paiement.save()
        MouvementCaisse.objects.create(
            type_mouvement=MouvementCaisse.TypeMouvement.ENTREE, montant=montant, etablissement=etablissement,
            description=f"Cantine - {inscription.eleve.nom_complet}", reference=generer_reference("CAI", etablissement),
            paiement_cantine=paiement,
        )
    return paiement


def annuler_paiement(*, paiement, acteur, motif: str = "") -> None:
    """Annulation réservée à la direction : le paiement et sa ligne de Caisse sont conservés, marqués « annulés »."""
    if acteur.role not in {role.value for role in ROLES_ACCES_TOTAL_INCONDITIONNEL}:
        raise ValidationError("Seule la direction peut annuler un paiement.")
    if paiement.annule:
        raise ValidationError("Ce paiement est déjà annulé.")
    maintenant = timezone.now()
    with transaction.atomic():
        paiement.annule, paiement.annule_par, paiement.annule_le, paiement.motif_annulation = True, acteur, maintenant, motif.strip()[:255]
        paiement.save(update_fields=["annule", "annule_par", "annule_le", "motif_annulation"])
        mouvement = getattr(paiement, "mouvement_caisse", None)
        if mouvement is not None and not mouvement.annule:
            mouvement.annule, mouvement.annule_par, mouvement.annule_le = True, acteur, maintenant
            mouvement.save(update_fields=["annule", "annule_par", "annule_le"])
