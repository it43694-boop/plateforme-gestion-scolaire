"""
Bulletin mensuel du premier cycle (1ère à 6ème année).

Au Mali, un élève du premier cycle passe une composition chaque mois. Le maître de la classe, qui enseigne toutes les disciplines, note chacune sur 10
(coefficient 1 partout). Sur le bulletin du mois :
- le total des notes, la moyenne sur 10 = total / nombre de disciplines notées (une discipline non notée, par exemple l'anglais d'un élève absent,
  n'entre ni dans le total ni dans la division), le rang dans la classe, la plus forte et la plus faible moyenne de la classe ;
- l'appréciation (calculée sur l'échelle à six niveaux, ramenée de 10 à 20) et l'observation écrite par le maître.

La moyenne de l'année est la MOYENNE DES MOYENNES MENSUELLES (les mois où l'élève a une moyenne) ; l'élève passe si elle atteint la moyenne de passage
de l'école (5 sur 10 par défaut). Le trimestre de la 6ème année (en plus des compositions) n'est pas encore pris en compte.

Un trimestre clôturé par la direction (voir `pedagogie.clotures`) ferme la saisie de ses trois mois : octobre-décembre, janvier-mars, avril et la suite.
"""
import datetime
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from comptes.models import Utilisateur
from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role
from pedagogie.clotures import periode_cloturee, verifier_periode_ouverte
from pedagogie.models import DisciplineMensuelle, NoteMensuelle, ObservationMensuelle, Trimestre, appreciation_pour
from scolarite.models import Affectation, Cycle, Inscription

DISCIPLINES_HABITUELLES = (
    "Dictée", "Questions de dictée", "Expression écrite", "Vocabulaire", "Grammaire", "Conjugaison", "Mathématiques", "Questions de cours", "Anglais",
    "Informatique", "Lecture", "Récitation", "Écriture", "Dessin", "Chant",
)
MOYENNE_DE_PASSAGE_PAR_DEFAUT = Decimal("5")
NOTE_MAXIMALE = Decimal("10")
DEUX_DECIMALES = Decimal("0.01")
ROLES_GESTION = {role.value for role in ROLES_ACCES_TOTAL_INCONDITIONNEL} | {Role.SUPER_ADMINISTRATEUR.value}


def arrondi(valeur) -> Decimal:
    """Deux décimales, la moitié vers le haut (8,745 devient 8,75)."""
    return Decimal(valeur).quantize(DEUX_DECIMALES, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Les mois
# ---------------------------------------------------------------------------

def premier_du_mois(date: datetime.date) -> datetime.date:
    return date.replace(day=1)


def mois_de_l_annee(annee) -> list:
    """Le premier jour de chaque mois de l'année scolaire, du début à la fin."""
    mois, fin = premier_du_mois(annee.date_debut), premier_du_mois(annee.date_fin)
    liste = []
    while mois <= fin:
        liste.append(mois)
        mois = datetime.date(mois.year + (mois.month == 12), mois.month % 12 + 1, 1)
    return liste


def mois_depuis_adresse(annee_civile: int, numero: int) -> datetime.date:
    """Le premier jour du mois d'une adresse (`2025`, `10`) ; ValueError si ce n'est pas un vrai mois."""
    return datetime.date(annee_civile, numero, 1)


def trimestre_du_mois(mois: datetime.date) -> str:
    """Le trimestre qui contient ce mois : septembre à décembre, janvier à mars, puis avril et la suite."""
    if mois.month >= 9:
        return Trimestre.T1
    return Trimestre.T2 if mois.month <= 3 else Trimestre.T3


def mois_courant_de_la_classe(classe, aujourdhui=None) -> datetime.date:
    """Le mois à proposer en ouvrant la saisie : le mois en cours s'il est dans l'année de la classe, sinon le plus proche."""
    aujourdhui = premier_du_mois(aujourdhui or datetime.date.today())
    mois = mois_de_l_annee(classe.annee_scolaire)
    if aujourdhui < mois[0]:
        return mois[0]
    return aujourdhui if aujourdhui <= mois[-1] else mois[-1]


# ---------------------------------------------------------------------------
# Droits
# ---------------------------------------------------------------------------

def est_premier_cycle(classe) -> bool:
    return classe.cycle == Cycle.PREMIER_CYCLE


def peut_saisir(utilisateur, classe) -> bool:
    """
    Remplir et corriger les notes de la classe : le maître de la classe (toute affectation à cette classe : il enseigne tout), la direction générale,
    le super administrateur et le directeur du 1er cycle (le cloisonnement par cycle est fait avant, par `classes_visibles_pour`).
    """
    if not est_premier_cycle(classe):
        return False
    if utilisateur.role == Role.ENSEIGNANT:
        return Affectation.objects.filter(enseignant=utilisateur, classe=classe).exists()
    return utilisateur.role in ROLES_GESTION or utilisateur.role == Role.DIRECTEUR_1ER_CYCLE


def peut_consulter(utilisateur, classe) -> bool:
    """Voir les résultats de la classe et imprimer ses bulletins : ceux qui saisissent, plus le responsable pédagogique."""
    return peut_saisir(utilisateur, classe) or (est_premier_cycle(classe) and utilisateur.role == Role.RESPONSABLE_PEDAGOGIQUE)


# ---------------------------------------------------------------------------
# Les disciplines d'une classe
# ---------------------------------------------------------------------------

def disciplines_actives(classe) -> list:
    return list(DisciplineMensuelle.objects.filter(classe=classe, active=True))


def _normaliser(libelle: str) -> str:
    return " ".join((libelle or "").split())


def _existe(classe, libelle: str, sauf=None) -> bool:
    """Une discipline de ce nom (sans tenir compte des majuscules, accents compris : la base ne le fait pas toujours) existe-t-elle dans la classe ?"""
    candidats = DisciplineMensuelle.objects.filter(classe=classe)
    if sauf is not None:
        candidats = candidats.exclude(pk=sauf.pk)
    cle = _normaliser(libelle).casefold()
    return any(_normaliser(nom).casefold() == cle for nom in candidats.values_list("libelle", flat=True))


def _prochain_ordre(classe) -> int:
    dernier = DisciplineMensuelle.objects.filter(classe=classe).order_by("-ordre").values_list("ordre", flat=True).first()
    return 0 if dernier is None else dernier + 1


def ajouter_discipline(classe, libelle: str) -> DisciplineMensuelle:
    libelle = _normaliser(libelle)
    if not libelle:
        raise ValidationError("Indiquez le nom de la discipline.")
    if len(libelle) > 80:
        raise ValidationError("Le nom de la discipline ne dépasse pas 80 caractères.")
    if _existe(classe, libelle):
        raise ValidationError("Cette discipline existe déjà dans la classe.")
    return DisciplineMensuelle.objects.create(classe=classe, libelle=libelle, ordre=_prochain_ordre(classe))


def creer_disciplines_habituelles(classe) -> int:
    """Ajoute la liste habituelle du premier cycle (celle des bulletins) ; celles qui existent déjà sont gardées. Rend le nombre ajouté."""
    ajoutees = 0
    for libelle in DISCIPLINES_HABITUELLES:
        if not _existe(classe, libelle):
            DisciplineMensuelle.objects.create(classe=classe, libelle=libelle, ordre=_prochain_ordre(classe))
            ajoutees += 1
    return ajoutees


def copier_disciplines(source, cible) -> int:
    """Reprend les disciplines actives d'une autre classe de la même école (les nouvelles années repartent d'une classe de l'année passée)."""
    if source.pk == cible.pk:
        raise ValidationError("Choisissez une autre classe.")
    if source.annee_scolaire.etablissement_id != cible.annee_scolaire.etablissement_id:
        raise ValidationError("Cette classe n'appartient pas à votre établissement.")
    ajoutees = 0
    for discipline in DisciplineMensuelle.objects.filter(classe=source, active=True):
        if not _existe(cible, discipline.libelle):
            DisciplineMensuelle.objects.create(classe=cible, libelle=discipline.libelle, ordre=_prochain_ordre(cible))
            ajoutees += 1
    return ajoutees


def renommer_discipline(discipline, libelle: str) -> None:
    libelle = _normaliser(libelle)
    if not libelle or len(libelle) > 80:
        raise ValidationError("Indiquez un nom de discipline de 80 caractères au plus.")
    if _existe(discipline.classe, libelle, sauf=discipline):
        raise ValidationError("Cette discipline existe déjà dans la classe.")
    discipline.libelle = libelle
    discipline.save(update_fields=["libelle"])


def supprimer_discipline(discipline) -> None:
    """Une discipline qui a déjà des notes ne se supprime pas : on la désactive."""
    if discipline.notes.exists():
        raise ValidationError("Cette discipline a déjà des notes : désactivez-la plutôt que de la supprimer.")
    discipline.delete()


# ---------------------------------------------------------------------------
# Les calculs
# ---------------------------------------------------------------------------

def eleves_de_la_classe(classe) -> list:
    """Les élèves actuellement inscrits dans la classe, par ordre alphabétique."""
    return list(
        Utilisateur.objects.filter(role=Role.ELEVE, inscriptions__classe=classe, inscriptions__statut=Inscription.Statut.EN_COURS)
        .distinct().order_by("nom", "prenom", "pk")
    )


@dataclass
class LigneEleve:
    eleve: object
    notes: dict = field(default_factory=dict)  # numéro de la discipline -> note
    total: Decimal | None = None
    nombre: int = 0
    moyenne: Decimal | None = None
    rang: int | None = None
    appreciation: str = ""
    observation: str = ""


@dataclass
class ResultatMois:
    classe: object
    mois: datetime.date
    disciplines: list
    lignes: list
    effectif: int
    plus_forte: Decimal | None
    plus_faible: Decimal | None
    cloture: bool


def rang_de_competition(moyennes: dict, cle):
    """Rang parmi {clé: moyenne}, ex æquo au même rang puis saut (1, 2, 2, 4) ; None s'il n'y a pas de moyenne."""
    if cle not in moyennes:
        return None
    return sorted(moyennes.values(), reverse=True).index(moyennes[cle]) + 1


def appreciation_du_mois(moyenne) -> str:
    """L'appréciation d'une moyenne sur 10 : l'échelle à six niveaux est sur 20, on double."""
    return appreciation_pour(moyenne * 2) if moyenne is not None else ""


def calculer_mois(classe, mois: datetime.date, avec_observations: bool = False) -> ResultatMois:
    eleves = eleves_de_la_classe(classe)
    disciplines = disciplines_actives(classe)
    notes_par_eleve = {eleve.pk: {} for eleve in eleves}
    for note in NoteMensuelle.objects.filter(discipline__in=disciplines, mois=mois, eleve__in=eleves):
        notes_par_eleve[note.eleve_id][note.discipline_id] = note.valeur
    observations = {}
    if avec_observations:
        observations = dict(ObservationMensuelle.objects.filter(classe=classe, mois=mois).values_list("eleve_id", "observation"))
    lignes = []
    for eleve in eleves:
        notes = notes_par_eleve[eleve.pk]
        ligne = LigneEleve(eleve=eleve, notes=notes, nombre=len(notes), observation=observations.get(eleve.pk, ""))
        if notes:
            ligne.total = sum(notes.values(), Decimal("0"))
            ligne.moyenne = arrondi(ligne.total / ligne.nombre)
            ligne.appreciation = appreciation_du_mois(ligne.moyenne)
        lignes.append(ligne)
    moyennes = {ligne.eleve.pk: ligne.moyenne for ligne in lignes if ligne.moyenne is not None}
    for ligne in lignes:
        ligne.rang = rang_de_competition(moyennes, ligne.eleve.pk)
    return ResultatMois(
        classe=classe, mois=mois, disciplines=disciplines, lignes=lignes, effectif=len(eleves),
        plus_forte=max(moyennes.values()) if moyennes else None, plus_faible=min(moyennes.values()) if moyennes else None,
        cloture=periode_cloturee(classe, trimestre_du_mois(mois)),
    )


def seuil_de_passage(etablissement) -> Decimal:
    valeur = getattr(etablissement, "moyenne_passage_premier_cycle", None)
    return Decimal(valeur) if valeur is not None else MOYENNE_DE_PASSAGE_PAR_DEFAUT


@dataclass
class LigneAnnuelle:
    eleve: object
    moyennes: dict = field(default_factory=dict)  # premier jour du mois -> moyenne du mois
    moyenne_annuelle: Decimal | None = None
    rang: int | None = None
    mois_manquants: int = 0
    admis: bool | None = None  # None : pas encore de moyenne


@dataclass
class ResultatAnnuel:
    classe: object
    mois: list  # les mois où la classe a au moins une note
    lignes: list
    effectif: int
    seuil: Decimal
    plus_forte: Decimal | None
    plus_faible: Decimal | None


def calculer_annee(classe) -> ResultatAnnuel:
    """Les moyennes de chaque mois et la moyenne de l'année (moyenne des moyennes mensuelles) de toute la classe."""
    eleves = eleves_de_la_classe(classe)
    disciplines = disciplines_actives(classe)
    par_eleve_et_mois = {}
    for note in NoteMensuelle.objects.filter(discipline__in=disciplines, eleve__in=eleves):
        cumul = par_eleve_et_mois.setdefault((note.eleve_id, note.mois), [Decimal("0"), 0])
        cumul[0] += note.valeur
        cumul[1] += 1
    mois_notes = sorted({mois for (_, mois) in par_eleve_et_mois})
    seuil = seuil_de_passage(classe.annee_scolaire.etablissement)
    lignes = []
    for eleve in eleves:
        ligne = LigneAnnuelle(eleve=eleve)
        for mois in mois_notes:
            cumul = par_eleve_et_mois.get((eleve.pk, mois))
            if cumul:
                ligne.moyennes[mois] = arrondi(cumul[0] / cumul[1])
        ligne.mois_manquants = len(mois_notes) - len(ligne.moyennes)
        if ligne.moyennes:
            ligne.moyenne_annuelle = arrondi(sum(ligne.moyennes.values(), Decimal("0")) / len(ligne.moyennes))
            ligne.admis = ligne.moyenne_annuelle >= seuil
        lignes.append(ligne)
    moyennes = {ligne.eleve.pk: ligne.moyenne_annuelle for ligne in lignes if ligne.moyenne_annuelle is not None}
    for ligne in lignes:
        ligne.rang = rang_de_competition(moyennes, ligne.eleve.pk)
    return ResultatAnnuel(
        classe=classe, mois=mois_notes, lignes=lignes, effectif=len(eleves), seuil=seuil,
        plus_forte=max(moyennes.values()) if moyennes else None, plus_faible=min(moyennes.values()) if moyennes else None,
    )


# ---------------------------------------------------------------------------
# La saisie
# ---------------------------------------------------------------------------

class ErreursDeSaisie(Exception):
    """Une ou plusieurs notes sont refusées : `erreurs` = {(élève, discipline): message}. Rien n'a été enregistré."""

    def __init__(self, erreurs):
        super().__init__("notes refusées")
        self.erreurs = erreurs


def lire_note(texte):
    """Une note tapée : « 9,5 » ou « 9.5 » ; vide (ou un tiret) = pas noté. ValidationError si ce n'est pas une note de 0 à 10 à deux décimales."""
    brut = (texte or "").strip().replace(",", ".")
    if brut in ("", "-", "—"):
        return None
    try:
        valeur = Decimal(brut)
    except InvalidOperation:
        raise ValidationError("Ce n'est pas une note : écrivez un nombre comme 9 ou 9,5.") from None
    if not valeur.is_finite():
        raise ValidationError("Ce n'est pas une note : écrivez un nombre comme 9 ou 9,5.")
    if valeur < 0 or valeur > NOTE_MAXIMALE:
        raise ValidationError("Une note est comprise entre 0 et 10.")
    if valeur.as_tuple().exponent < -2:
        raise ValidationError("Une note a deux décimales au plus.")
    return valeur


def _verifier_saisie_possible(classe, mois):
    if not est_premier_cycle(classe):
        raise ValidationError("Le bulletin mensuel est réservé aux classes du premier cycle (1ère à 6ème année).")
    if not (premier_du_mois(classe.annee_scolaire.date_debut) <= mois <= premier_du_mois(classe.annee_scolaire.date_fin)):
        raise ValidationError("Ce mois n'appartient pas à l'année scolaire de la classe.")
    verifier_periode_ouverte(classe, trimestre_du_mois(mois))


def enregistrer_notes(*, classe, mois, saisies: dict, acteur, observations: dict | None = None) -> dict:
    """
    Enregistre la grille d'un mois : `saisies` = {(numéro de l'élève, numéro de la discipline): texte tapé}. Tout ou rien : une note refusée n'en
    enregistre aucune (ErreursDeSaisie). Une case vide efface la note ; une case absente de `saisies` n'est pas touchée. Les élèves et les
    disciplines qui ne sont pas ceux de la classe sont ignorés. `observations` = {numéro de l'élève: texte}.
    """
    _verifier_saisie_possible(classe, mois)
    eleves_valides = {eleve.pk for eleve in eleves_de_la_classe(classe)}
    disciplines_valides = {discipline.pk for discipline in disciplines_actives(classe)}
    valeurs, erreurs = {}, {}
    for cle, texte in saisies.items():
        if cle[0] not in eleves_valides or cle[1] not in disciplines_valides:
            continue
        try:
            valeurs[cle] = lire_note(texte)
        except ValidationError as erreur:
            erreurs[cle] = erreur.messages[0]
    if erreurs:
        raise ErreursDeSaisie(erreurs)
    bilan = {"crees": 0, "modifiees": 0, "supprimees": 0, "observations": 0}
    with transaction.atomic():
        existantes = {
            (note.eleve_id, note.discipline_id): note for note in NoteMensuelle.objects.filter(discipline__classe=classe, mois=mois)
        }
        for cle, valeur in valeurs.items():
            actuelle = existantes.get(cle)
            if valeur is None:
                if actuelle is not None:
                    actuelle.delete()
                    bilan["supprimees"] += 1
            elif actuelle is None:
                NoteMensuelle.objects.create(eleve_id=cle[0], discipline_id=cle[1], mois=mois, valeur=valeur, saisie_par=acteur)
                bilan["crees"] += 1
            elif actuelle.valeur != valeur:
                actuelle.valeur, actuelle.saisie_par = valeur, acteur
                actuelle.save(update_fields=["valeur", "saisie_par", "modifie_le"])
                bilan["modifiees"] += 1
        for eleve_id, texte in (observations or {}).items():
            if eleve_id not in eleves_valides:
                continue
            texte = _normaliser(texte)[:255]
            if texte:
                _, cree = ObservationMensuelle.objects.update_or_create(
                    eleve_id=eleve_id, classe=classe, mois=mois, defaults={"observation": texte, "saisie_par": acteur},
                )
                bilan["observations"] += 1
            else:
                ObservationMensuelle.objects.filter(eleve_id=eleve_id, classe=classe, mois=mois).delete()
    return bilan
