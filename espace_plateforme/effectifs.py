"""
Effectifs d'une école par cycle, pour que le propriétaire de la plateforme facture chaque cycle : les élèves inscrits et le personnel de l'année
scolaire en cours. Seuls des nombres sont produits, jamais un nom. Les parents d'élèves ne sont pas comptés.

Ce qui est compté
- Élèves : les inscriptions « en cours » de l'année scolaire active, par cycle de la classe (un élève par inscription).
- Enseignants : les enseignants actifs affectés à au moins une classe du cycle cette année. Un enseignant qui enseigne dans deux cycles est compté dans
  chacun (c'est ce qui se facture) ; la ligne « sans cycle » ne le compte plus.
- Direction du cycle : les comptes actifs du rôle propre au cycle (directeur du 1er cycle, du 2ème cycle ; directeur du lycée, censeur et surveillant général
  pour le lycée).
- Sans cycle : tout autre membre du personnel actif (fondateur, secrétariat, comptabilité, bibliothèque, enseignant sans classe cette année...).
"""
from dataclasses import dataclass, field

from django.db.models import Count

from comptes.models import Utilisateur
from comptes.roles import Role, StatutCompte
from etablissement.models import TarifCycle
from scolarite.models import Affectation, AnneeScolaire, Cycle, Inscription, cycles_autorises_pour

ROLES_DE_DIRECTION_PAR_CYCLE = {
    Cycle.PREMIER_CYCLE.value: (Role.DIRECTEUR_1ER_CYCLE.value,),
    Cycle.DEUXIEME_CYCLE.value: (Role.DIRECTEUR_2EME_CYCLE.value,),
    Cycle.LYCEE.value: (Role.DIRECTEUR_LYCEE.value, Role.CENSEUR.value, Role.SURVEILLANT_GENERAL.value),
}
ROLES_HORS_PERSONNEL = (Role.PARENT.value, Role.ELEVE.value)  # des familles, pas du personnel de l'école
ORDRE_DES_CYCLES = [cycle for cycle, _ in Cycle.choices]  # préscolaire, 1er cycle, 2ème cycle, lycée, professionnel


@dataclass
class LigneCycle:
    cycle: str
    libelle: str
    dans_la_formule: bool
    eleves: int = 0
    enseignants: int = 0
    direction: int = 0
    tarif: object = None  # le TarifCycle de l'école pour ce cycle, ou None
    montant_cumule: int = 0  # pour la vue d'ensemble de la plateforme : la somme des montants estimés des écoles

    @property
    def cycle_ouvert(self) -> bool:
        """Un cycle ouvert : couvert par la formule de l'école, ou qui compte déjà des comptes (même hors formule)."""
        return self.dans_la_formule or not self.vide

    @property
    def montant_estime(self) -> int:
        """Le montant annuel d'après le tarif : le nombre d'élèves fois le montant, ou le forfait si le cycle est ouvert ; 0 sans tarif."""
        if self.tarif is None:
            return 0
        if self.tarif.mode == TarifCycle.Mode.PAR_ELEVE:
            return self.eleves * self.tarif.montant
        return self.tarif.montant if self.cycle_ouvert else 0

    @property
    def personnel(self) -> int:
        return self.enseignants + self.direction

    @property
    def total(self) -> int:
        return self.eleves + self.personnel

    @property
    def hors_formule(self) -> bool:
        """Des comptes dans un cycle que la formule de l'école ne couvre pas : à régulariser ou à facturer en plus."""
        return not self.dans_la_formule and self.total > 0

    @property
    def vide(self) -> bool:
        return self.total == 0


@dataclass
class EffectifsEcole:
    etablissement: object
    annee: object  # l'année scolaire active, ou None si l'école n'en a pas
    lignes: list = field(default_factory=list)
    sans_cycle: int = 0

    @property
    def lignes_utiles(self) -> list:
        """Les cycles à montrer : ceux de la formule, ceux où il y a des comptes (même hors formule) et ceux qui ont un tarif (jamais un tarif caché)."""
        return [ligne for ligne in self.lignes if ligne.dans_la_formule or not ligne.vide or ligne.tarif is not None]

    @property
    def eleves(self) -> int:
        return sum(ligne.eleves for ligne in self.lignes)

    @property
    def personnel(self) -> int:
        return sum(ligne.personnel for ligne in self.lignes) + self.sans_cycle

    @property
    def total(self) -> int:
        return self.eleves + self.personnel

    @property
    def a_regulariser(self) -> bool:
        return any(ligne.hors_formule for ligne in self.lignes)

    @property
    def montant_estime(self) -> int:
        return sum(ligne.montant_estime for ligne in self.lignes)

    @property
    def a_des_tarifs(self) -> bool:
        return any(ligne.tarif is not None for ligne in self.lignes)


def effectifs_de_l_ecole(etablissement) -> EffectifsEcole:
    annee = AnneeScolaire.active(etablissement)
    autorises = cycles_autorises_pour(etablissement)
    lignes = {cycle: LigneCycle(cycle, libelle, cycle in autorises) for cycle, libelle in Cycle.choices}
    resultat = EffectifsEcole(etablissement=etablissement, annee=annee, lignes=[lignes[cycle] for cycle in ORDRE_DES_CYCLES])
    for tarif in TarifCycle.objects.filter(etablissement=etablissement):
        if tarif.cycle in lignes:
            lignes[tarif.cycle].tarif = tarif
    personnel = Utilisateur.objects.filter(etablissement=etablissement, is_active=True, statut=StatutCompte.ACTIF).exclude(role__in=ROLES_HORS_PERSONNEL)
    comptes_par_cycle = set()  # les membres du personnel déjà rattachés à un cycle
    if annee is not None:
        for ligne in (
            Inscription.objects.filter(classe__annee_scolaire=annee, statut=Inscription.Statut.EN_COURS)
            .values("classe__cycle").annotate(nombre=Count("eleve", distinct=True))
        ):
            if ligne["classe__cycle"] in lignes:
                lignes[ligne["classe__cycle"]].eleves = ligne["nombre"]
        enseignants = (
            Affectation.objects.filter(classe__annee_scolaire=annee, enseignant__in=personnel)
            .values("classe__cycle", "enseignant_id").distinct()
        )
        for ligne in enseignants:
            if ligne["classe__cycle"] in lignes:
                lignes[ligne["classe__cycle"]].enseignants += 1
            comptes_par_cycle.add(ligne["enseignant_id"])
    for cycle, roles in ROLES_DE_DIRECTION_PAR_CYCLE.items():
        for identifiant in personnel.filter(role__in=roles).values_list("pk", flat=True):
            lignes[cycle].direction += 1
            comptes_par_cycle.add(identifiant)
    resultat.sans_cycle = personnel.exclude(pk__in=comptes_par_cycle).count()
    return resultat


def effectifs_de_toutes_les_ecoles(etablissements) -> list:
    return [effectifs_de_l_ecole(etablissement) for etablissement in etablissements]


def total_par_cycle(effectifs: list) -> list:
    """Les mêmes lignes de cycle, additionnées sur toutes les écoles données (pour la vue d'ensemble de la plateforme)."""
    totaux = {cycle: LigneCycle(cycle, libelle, True) for cycle, libelle in Cycle.choices}
    for ecole in effectifs:
        for ligne in ecole.lignes:
            totaux[ligne.cycle].eleves += ligne.eleves
            totaux[ligne.cycle].enseignants += ligne.enseignants
            totaux[ligne.cycle].direction += ligne.direction
            totaux[ligne.cycle].montant_cumule += ligne.montant_estime
    return [totaux[cycle] for cycle in ORDRE_DES_CYCLES]
