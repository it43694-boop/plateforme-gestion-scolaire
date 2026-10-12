"""
Opérations comptables : plan comptable, exercices, écritures, contre-passation, comptabilisation automatique de la caisse
(paiements et salaires), clôture d'exercice et report des soldes.

Aucune écriture n'est jamais modifiée ni supprimée : toute correction est une nouvelle écriture.
"""
import datetime
from collections import defaultdict
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from comptabilite import plan
from comptabilite.models import CompteComptable, Ecriture, Exercice, Journal, LigneEcriture

Origine = Ecriture.Origine


# ---------------------------------------------------------------------------
# Plan comptable
# ---------------------------------------------------------------------------

def assurer_plan_comptable(etablissement):
    """Crée les comptes du plan de base manquants (idempotent : à appeler avant tout accès à la comptabilité)."""
    existants = set(CompteComptable.objects.filter(etablissement=etablissement).values_list("numero", flat=True))
    manquants = [
        CompteComptable(etablissement=etablissement, numero=numero, libelle=libelle, systeme=True)
        for numero, libelle in plan.PLAN_DE_BASE if numero not in existants
    ]
    if manquants:
        CompteComptable.objects.bulk_create(manquants, ignore_conflicts=True)


def creer_compte(*, etablissement, numero, libelle):
    """Ajoute un sous-compte personnalisé au plan de l'établissement."""
    numero, libelle = (numero or "").strip(), (libelle or "").strip()
    if not libelle:
        raise ValidationError("L'intitulé du compte est obligatoire.")
    compte = CompteComptable(etablissement=etablissement, numero=numero, libelle=libelle, systeme=False)
    compte.clean()
    if CompteComptable.objects.filter(etablissement=etablissement, numero=numero).exists():
        raise ValidationError(f"Le compte {numero} existe déjà.")
    compte.save()
    return compte


# ---------------------------------------------------------------------------
# Exercices
# ---------------------------------------------------------------------------

def exercice_pour_date(etablissement, date, *, ouvert=True):
    exercices = Exercice.objects.filter(etablissement=etablissement, date_debut__lte=date, date_fin__gte=date)
    if ouvert:
        exercices = exercices.filter(cloture=False)
    return exercices.first()


def creer_exercice(*, etablissement, libelle, date_debut, date_fin):
    exercice = Exercice(etablissement=etablissement, libelle=(libelle or "").strip(), date_debut=date_debut, date_fin=date_fin)
    if not exercice.libelle:
        raise ValidationError("Le libellé de l'exercice est obligatoire.")
    exercice.clean()
    if Exercice.objects.filter(etablissement=etablissement, libelle=exercice.libelle).exists():
        raise ValidationError(f"Un exercice « {exercice.libelle} » existe déjà.")
    exercice.save()
    return exercice


# ---------------------------------------------------------------------------
# Écritures
# ---------------------------------------------------------------------------

def _prochain_numero(etablissement, exercice, journal) -> str:
    prefixe = f"{journal}-{exercice.date_fin.year}-"
    dernier = (
        Ecriture.objects.filter(etablissement=etablissement, numero__startswith=prefixe).order_by("-numero")
        .values_list("numero", flat=True).first()
    )
    return f"{prefixe}{(int(dernier.rsplit('-', 1)[1]) + 1) if dernier else 1:06d}"


def _lignes_normalisees(etablissement, lignes):
    """[(compte ou numéro, débit, crédit, libellé)] -> [(CompteComptable, débit, crédit, libellé)] validées."""
    comptes = {c.numero: c for c in CompteComptable.objects.filter(etablissement=etablissement)}
    resultat = []
    for position, ligne in enumerate(lignes, start=1):
        compte, debit, credit = ligne[0], int(ligne[1] or 0), int(ligne[2] or 0)
        libelle = ligne[3] if len(ligne) > 3 else ""
        if isinstance(compte, CompteComptable):
            if compte.etablissement_id != etablissement.pk:
                raise ValidationError(f"Ligne {position} : ce compte n'appartient pas à l'établissement.")
        else:
            compte = comptes.get(str(compte).strip())
            if compte is None:
                raise ValidationError(f"Ligne {position} : le compte « {ligne[0]} » n'existe pas dans votre plan comptable.")
        if debit < 0 or credit < 0:
            raise ValidationError(f"Ligne {position} : les montants ne peuvent pas être négatifs.")
        if debit and credit:
            raise ValidationError(f"Ligne {position} : une ligne est soit au débit, soit au crédit, pas les deux.")
        if not debit and not credit:
            raise ValidationError(f"Ligne {position} : indiquez un montant au débit ou au crédit.")
        resultat.append((compte, debit, credit, (libelle or "").strip()[:255]))
    return resultat


def creer_ecriture(*, etablissement, journal, date_ecriture, libelle, lignes, piece="", origine=Origine.MANUELLE,
                   cree_par=None, mouvement_caisse=None, contrepasse_de=None, report_de=None):
    """
    Passe une écriture équilibrée dans l'exercice qui couvre sa date (qui doit être ouvert).
    `lignes` : [(compte ou numéro de compte, débit, crédit, libellé de ligne)].
    """
    libelle = (libelle or "").strip()
    if not libelle:
        raise ValidationError("Le libellé de l'écriture est obligatoire.")
    if journal not in Journal.values:
        raise ValidationError("Journal inconnu.")
    exercice = exercice_pour_date(etablissement, date_ecriture, ouvert=False)
    if exercice is None:
        raise ValidationError(f"Aucun exercice ne couvre le {date_ecriture:%d/%m/%Y} : créez d'abord l'exercice correspondant.")
    if exercice.cloture:
        raise ValidationError(f"L'exercice « {exercice.libelle} » est clôturé : aucune écriture ne peut plus y être passée.")
    normalisees = _lignes_normalisees(etablissement, lignes)
    if len(normalisees) < 2:
        raise ValidationError("Une écriture comporte au moins deux lignes.")
    total_debit = sum(ligne[1] for ligne in normalisees)
    total_credit = sum(ligne[2] for ligne in normalisees)
    if total_debit != total_credit:
        raise ValidationError(f"Écriture déséquilibrée : débits {total_debit}, crédits {total_credit}.")

    for _ in range(5):
        numero = None
        try:
            with transaction.atomic():
                exercice = Exercice.objects.select_for_update().get(pk=exercice.pk)
                if exercice.cloture:
                    raise ValidationError("L'exercice vient d'être clôturé.")
                numero = _prochain_numero(etablissement, exercice, journal)
                ecriture = Ecriture.objects.create(
                    etablissement=etablissement, exercice=exercice, journal=journal,
                    numero=numero, date_ecriture=date_ecriture,
                    piece=(piece or "").strip()[:60], libelle=libelle[:255], origine=origine, mouvement_caisse=mouvement_caisse,
                    contrepasse_de=contrepasse_de, report_de=report_de, cree_par=cree_par,
                )
                LigneEcriture.objects.bulk_create([
                    LigneEcriture(ecriture=ecriture, compte=compte, libelle=lib, debit=debit, credit=credit)
                    for compte, debit, credit, lib in normalisees
                ])
            return ecriture
        except IntegrityError:
            if contrepasse_de is not None and Ecriture.objects.filter(contrepasse_de=contrepasse_de).exists():
                raise ValidationError("Cette écriture a déjà été contre-passée.")
            # Deux écritures simultanées ont pris le même numéro : on réessaie. Toute autre contrainte violée est une erreur.
            if numero is None or not Ecriture.objects.filter(etablissement=etablissement, numero=numero).exists():
                raise
    raise RuntimeError("Impossible d'attribuer un numéro d'écriture après plusieurs tentatives.")


MOTIFS_REFUS_CONTREPASSATION = {
    Origine.AUTOMATIQUE: "Cette écriture vient d'un paiement ou d'un salaire : annulez ou corrigez le paiement (ou le salaire) "
                         "d'origine, la comptabilité se mettra à jour.",
    Origine.CLOTURE: "L'écriture de clôture ne se contre-passe pas.",
    Origine.REPORT: "L'écriture de report à nouveau ne se contre-passe pas.",
    Origine.CONTREPASSATION: "Une contre-passation ne se contre-passe pas : passez une nouvelle écriture.",
}


def contrepasser(*, ecriture, acteur=None, date=None, motif=""):
    """Annule une écriture manuelle par une écriture inverse (débits et crédits échangés), jamais en la supprimant."""
    if ecriture.origine in MOTIFS_REFUS_CONTREPASSATION:
        raise ValidationError(MOTIFS_REFUS_CONTREPASSATION[ecriture.origine])
    if hasattr(ecriture, "contrepassation"):
        raise ValidationError("Cette écriture a déjà été contre-passée.")
    texte = f"Contre-passation de {ecriture.numero}" + (f" : {motif.strip()}" if (motif or "").strip() else "")
    return creer_ecriture(
        etablissement=ecriture.etablissement, journal=ecriture.journal, date_ecriture=date or timezone.localdate(),
        libelle=texte, piece=ecriture.piece, origine=Origine.CONTREPASSATION, cree_par=acteur, contrepasse_de=ecriture,
        lignes=[(ligne.compte, ligne.credit, ligne.debit, ligne.libelle) for ligne in ecriture.lignes.select_related("compte")],
    )


MODES_TRESORERIE = {
    "especes": plan.CAISSE, "mobile_money": plan.MONNAIE_ELECTRONIQUE, "virement": plan.BANQUE, "cheque": plan.BANQUE,
}


def journal_pour_tresorerie(numero_compte) -> str:
    return Journal.CAISSE if numero_compte == plan.CAISSE else Journal.BANQUE


def enregistrer_operation(*, etablissement, type_operation, date_ecriture, montant, compte, mode, libelle, piece="", cree_par=None):
    """
    Dépense ou recette en deux lignes, sans connaître le débit et le crédit : une dépense débite le compte de charge (ou
    d'immobilisation, de dette...) et crédite la trésorerie ; une recette fait l'inverse.
    """
    if type_operation not in ("depense", "recette"):
        raise ValidationError("Type d'opération inconnu.")
    if mode not in MODES_TRESORERIE:
        raise ValidationError("Mode de règlement inconnu.")
    montant = int(montant or 0)
    if montant <= 0:
        raise ValidationError("Le montant doit être strictement positif.")
    if not isinstance(compte, CompteComptable):
        compte = CompteComptable.objects.filter(etablissement=etablissement, numero=str(compte).strip()).first()
        if compte is None:
            raise ValidationError("Compte inconnu.")
    if compte.etablissement_id != etablissement.pk or compte.classe in (5, 8):
        raise ValidationError("Choisissez un compte de charge, de produit, d'immobilisation, de stock ou de tiers (pas un compte de trésorerie).")
    if type_operation == "depense" and compte.classe in (7,):
        raise ValidationError("Une dépense ne s'impute pas sur un compte de produit.")
    if type_operation == "recette" and compte.classe in (6,):
        raise ValidationError("Une recette ne s'impute pas sur un compte de charge.")
    tresorerie = MODES_TRESORERIE[mode]
    sens_tresorerie = (0, montant) if type_operation == "depense" else (montant, 0)
    sens_compte = (montant, 0) if type_operation == "depense" else (0, montant)
    return creer_ecriture(
        etablissement=etablissement, journal=journal_pour_tresorerie(tresorerie), date_ecriture=date_ecriture,
        libelle=libelle, piece=piece, cree_par=cree_par,
        lignes=[(compte, *sens_compte, ""), (tresorerie, *sens_tresorerie, "")],
    )


# ---------------------------------------------------------------------------
# Comptabilisation automatique de la caisse (paiements de scolarité et salaires payés)
# ---------------------------------------------------------------------------

def vecteur_attendu(mouvement) -> dict:
    """
    Ce que le mouvement de caisse doit avoir produit en comptabilité : {numéro de compte: montant} (débit positif,
    crédit négatif). Un mouvement annulé ne doit rien produire. La somme est toujours nulle.

    - paiement de scolarité : débit de la trésorerie (caisse, monnaie électronique ou banque selon le mode de paiement),
      crédit du produit (droits d'inscription ou frais de scolarité) ;
    - salaire payé : avec bulletin détaillé, débit des rémunérations (brut) et des charges sociales patronales, crédit de la
      caisse (net payé), de la sécurité sociale, des organismes sociaux (AMO) et de l'État (ITS) ; sans détail (ou si le
      bulletin n'est pas équilibré), le net seulement.
    """
    if mouvement.annule:
        return {}
    montant = mouvement.montant
    if mouvement.paiement_id:
        paiement = mouvement.paiement
        tresorerie = MODES_TRESORERIE.get(paiement.mode_paiement, plan.BANQUE)
        produit = plan.DROITS_INSCRIPTION if paiement.tranche == "inscription" else plan.FRAIS_SCOLARITE
        return {tresorerie: montant, produit: -montant}
    salaire = mouvement.salaire
    champs = (salaire.salaire_brut, salaire.cotisation_inps_salarie, salaire.cotisation_inps_employeur,
              salaire.cotisation_amo_salarie, salaire.cotisation_amo_employeur)
    if all(valeur is not None for valeur in champs):
        brut, inps_salarie, inps_employeur, amo_salarie, amo_employeur = champs
        its = salaire.its or 0
        if brut - inps_salarie - amo_salarie - its == montant:
            detail = {
                plan.REMUNERATIONS_PERSONNEL: brut, plan.CHARGES_SOCIALES: inps_employeur + amo_employeur,
                plan.CAISSE: -montant, plan.SECURITE_SOCIALE: -(inps_salarie + inps_employeur),
                plan.AUTRES_ORGANISMES_SOCIAUX: -(amo_salarie + amo_employeur), plan.IMPOTS_SUR_SALAIRES: -its,
            }
            return {compte: valeur for compte, valeur in detail.items() if valeur}
    return {plan.REMUNERATIONS_PERSONNEL: montant, plan.CAISSE: -montant}


@dataclass
class Ecart:
    mouvement: object
    delta: dict
    premiere_ecriture: bool


def ecarts_caisse(etablissement) -> list:
    """
    Mouvements de caisse dont la comptabilité n'est pas à jour : écart entre ce qui est attendu (`vecteur_attendu`) et ce
    qui est déjà passé en écriture. Couvre un nouveau paiement ou salaire, une correction de montant ou de mode de
    paiement, et une annulation, sans cas particulier.
    """
    from finances.models import MouvementCaisse

    mouvements = list(
        MouvementCaisse.objects.filter(etablissement=etablissement).select_related("paiement", "salaire").order_by("date_mouvement", "id")
    )
    passe = defaultdict(lambda: defaultdict(int))
    for ligne in LigneEcriture.objects.filter(
        ecriture__etablissement=etablissement, ecriture__mouvement_caisse__isnull=False,
    ).values("ecriture__mouvement_caisse_id", "compte__numero").annotate(debit=Sum("debit"), credit=Sum("credit")):
        passe[ligne["ecriture__mouvement_caisse_id"]][ligne["compte__numero"]] += ligne["debit"] - ligne["credit"]
    deja_ecrits = set(
        Ecriture.objects.filter(etablissement=etablissement, mouvement_caisse__isnull=False).values_list("mouvement_caisse_id", flat=True)
    )
    ecarts = []
    for mouvement in mouvements:
        attendu = vecteur_attendu(mouvement)
        delta = {compte: attendu.get(compte, 0) - passe[mouvement.pk].get(compte, 0) for compte in {*attendu, *passe[mouvement.pk]}}
        delta = {compte: valeur for compte, valeur in delta.items() if valeur}
        if delta:
            ecarts.append(Ecart(mouvement=mouvement, delta=delta, premiere_ecriture=mouvement.pk not in deja_ecrits))
    return ecarts


def date_de_comptabilisation(ecart, aujourdhui) -> datetime.date:
    """Une première écriture porte la date du mouvement ; une régularisation (correction, annulation) celle du jour."""
    if ecart.premiere_ecriture:
        return timezone.localtime(ecart.mouvement.date_mouvement).date()
    return aujourdhui


@dataclass
class ResultatSynchronisation:
    creees: int = 0
    ignorees: list = field(default_factory=list)  # messages : mouvements qui n'ont pas pu être comptabilisés


def synchroniser_caisse(etablissement, acteur=None, aujourdhui=None) -> ResultatSynchronisation:
    """
    Passe en comptabilité tout ce qui manque (voir `ecarts_caisse`). Idempotent : sans nouveau paiement ni correction,
    elle ne crée rien. Une première écriture porte la date du mouvement ; une régularisation (correction, annulation)
    porte la date du jour et passe en journal d'opérations diverses.
    """
    aujourdhui = aujourdhui or timezone.localdate()
    assurer_plan_comptable(etablissement)
    resultat = ResultatSynchronisation()
    for ecart in ecarts_caisse(etablissement):
        mouvement = ecart.mouvement
        date_ecriture = date_de_comptabilisation(ecart, aujourdhui)
        exercice = exercice_pour_date(etablissement, date_ecriture, ouvert=False)
        if exercice is None:
            resultat.ignorees.append(f"{mouvement.reference} : aucun exercice ne couvre le {date_ecriture:%d/%m/%Y}.")
            continue
        if exercice.cloture:
            resultat.ignorees.append(f"{mouvement.reference} : l'exercice « {exercice.libelle} » est clôturé.")
            continue
        lignes = [(compte, max(valeur, 0), max(-valeur, 0), "") for compte, valeur in sorted(ecart.delta.items())]
        if ecart.premiere_ecriture:
            tresorerie = next((compte for compte in ecart.delta if compte in (plan.CAISSE, plan.MONNAIE_ELECTRONIQUE, plan.BANQUE)), plan.CAISSE)
            journal, libelle = journal_pour_tresorerie(tresorerie), mouvement.description
        else:
            journal = Journal.OPERATIONS_DIVERSES
            libelle = f"Régularisation {mouvement.reference} ({'annulation' if mouvement.annule else 'correction'})"
        try:
            creer_ecriture(
                etablissement=etablissement, journal=journal, date_ecriture=date_ecriture, libelle=libelle,
                piece=mouvement.reference, lignes=lignes, origine=Origine.AUTOMATIQUE, cree_par=acteur, mouvement_caisse=mouvement,
            )
        except ValidationError as erreur:
            resultat.ignorees.append(f"{mouvement.reference} : {' '.join(erreur.messages)}")
        else:
            resultat.creees += 1
    return resultat


# ---------------------------------------------------------------------------
# Clôture d'exercice et report des soldes
# ---------------------------------------------------------------------------

def _soldes(etablissement, exercice, classes, *, sans_cloture):
    """{numéro de compte: (compte, solde débiteur positif / créditeur négatif)} pour les classes demandées."""
    filtre_classes = Q()
    for classe in classes:
        filtre_classes |= Q(compte__numero__startswith=classe)
    lignes = LigneEcriture.objects.filter(filtre_classes, ecriture__etablissement=etablissement, ecriture__exercice=exercice)
    if sans_cloture:
        lignes = lignes.exclude(ecriture__origine=Origine.CLOTURE)
    soldes = {}
    for ligne in lignes.values("compte_id", "compte__numero").annotate(debit=Sum("debit"), credit=Sum("credit")):
        solde = ligne["debit"] - ligne["credit"]
        if solde:
            soldes[ligne["compte__numero"]] = (ligne["compte_id"], solde)
    return soldes


def cloturer_exercice(*, exercice, acteur=None):
    """
    Clôture : solde les comptes de charges et de produits (classes 6, 7, 8) dans le résultat de l'exercice (compte 131 en cas
    de bénéfice, 139 en cas de perte) par une écriture de clôture, puis verrouille l'exercice. Irréversible.
    """
    etablissement = exercice.etablissement
    with transaction.atomic():
        exercice = Exercice.objects.select_for_update().get(pk=exercice.pk)
        if exercice.cloture:
            raise ValidationError("Cet exercice est déjà clôturé.")
        assurer_plan_comptable(etablissement)
        aujourdhui = timezone.localdate()
        # seuls comptent les mouvements qui se comptabiliseraient dans CET exercice
        en_attente = [
            e for e in ecarts_caisse(etablissement)
            if exercice.date_debut <= date_de_comptabilisation(e, aujourdhui) <= exercice.date_fin
        ]
        if en_attente:
            raise ValidationError(
                f"Mettez d'abord la comptabilité à jour : {len(en_attente)} mouvement(s) de caisse (paiements, salaires) "
                "ne sont pas encore comptabilisés."
            )
        soldes = _soldes(etablissement, exercice, "678", sans_cloture=True)
        if soldes:
            comptes = {c.pk: c for c in CompteComptable.objects.filter(pk__in=[compte_id for compte_id, _ in soldes.values()])}
            lignes = [(comptes[compte_id], max(-solde, 0), max(solde, 0), "Solde du compte") for compte_id, solde in soldes.values()]
            resultat = -sum(solde for _, solde in soldes.values())  # produits - charges
            if resultat > 0:
                lignes.append((plan.RESULTAT_BENEFICE, 0, resultat, "Bénéfice de l'exercice"))
            elif resultat < 0:
                lignes.append((plan.RESULTAT_PERTE, -resultat, 0, "Perte de l'exercice"))
            creer_ecriture(
                etablissement=etablissement, journal=Journal.OPERATIONS_DIVERSES, date_ecriture=exercice.date_fin,
                libelle=f"Détermination du résultat de l'exercice {exercice.libelle}", origine=Origine.CLOTURE,
                cree_par=acteur, lignes=lignes,
            )
        exercice.cloture, exercice.cloture_le, exercice.cloture_par = True, timezone.now(), acteur
        exercice.save(update_fields=["cloture", "cloture_le", "cloture_par"])
    return exercice


def exercice_suivant(exercice):
    return Exercice.objects.filter(etablissement=exercice.etablissement, date_debut__gt=exercice.date_fin).order_by("date_debut").first()


def reporter_a_nouveau(*, exercice, acteur=None):
    """
    Reporte les soldes des comptes de bilan (classes 1 à 5) d'un exercice CLÔTURÉ au premier jour de l'exercice suivant
    (écriture « à-nouveaux »). Une seule fois par exercice.
    """
    if not exercice.cloture:
        raise ValidationError("Clôturez d'abord cet exercice.")
    suivant = exercice_suivant(exercice)
    if suivant is None:
        raise ValidationError("Créez d'abord l'exercice suivant : le report se fait à son premier jour.")
    if suivant.cloture:
        raise ValidationError("L'exercice suivant est déjà clôturé.")
    if Ecriture.objects.filter(etablissement=exercice.etablissement, report_de=exercice).exists():
        raise ValidationError("Les soldes de cet exercice ont déjà été reportés.")
    soldes = _soldes(exercice.etablissement, exercice, "12345", sans_cloture=False)
    if not soldes:
        return None
    comptes = {c.pk: c for c in CompteComptable.objects.filter(pk__in=[compte_id for compte_id, _ in soldes.values()])}
    lignes = [(comptes[compte_id], max(solde, 0), max(-solde, 0), "Report") for compte_id, solde in soldes.values()]
    return creer_ecriture(
        etablissement=exercice.etablissement, journal=Journal.A_NOUVEAUX, date_ecriture=suivant.date_debut,
        libelle=f"Report à nouveau des soldes de l'exercice {exercice.libelle}", origine=Origine.REPORT,
        cree_par=acteur, report_de=exercice, lignes=lignes,
    )
