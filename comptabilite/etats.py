"""
États comptables d'un exercice : journal, grand livre, balance, compte de résultat, bilan.

Convention : le solde d'un compte est « débit moins crédit » (positif = débiteur, négatif = créditeur). Pour la balance, le
compte de résultat et le bilan, les écritures de clôture sont écartées : ces états montrent la situation AVANT clôture et
sont donc identiques que l'exercice soit clôturé ou non (les charges et produits restent visibles). Le journal et le grand
livre montrent toutes les écritures, clôture comprise.
"""
from dataclasses import dataclass

from django.db.models import Sum

from comptabilite import plan
from comptabilite.models import CompteComptable, Ecriture, LigneEcriture

Origine = Ecriture.Origine


@dataclass
class SoldeCompte:
    numero: str
    libelle: str
    debit: int
    credit: int

    @property
    def solde(self) -> int:
        return self.debit - self.credit

    @property
    def solde_debiteur(self) -> int:
        return self.solde if self.solde > 0 else 0

    @property
    def solde_crediteur(self) -> int:
        return -self.solde if self.solde < 0 else 0

    @property
    def classe(self) -> int:
        return int(self.numero[0])


def soldes_par_compte(etablissement, exercice, *, inclure_cloture=False, jusqu_au=None):
    """Totaux débit/crédit de chaque compte mouvementé dans l'exercice, triés par numéro."""
    lignes = LigneEcriture.objects.filter(ecriture__etablissement=etablissement, ecriture__exercice=exercice)
    if not inclure_cloture:
        lignes = lignes.exclude(ecriture__origine=Origine.CLOTURE)
    if jusqu_au:
        lignes = lignes.filter(ecriture__date_ecriture__lte=jusqu_au)
    return [
        SoldeCompte(ligne["compte__numero"], ligne["compte__libelle"], ligne["debit"], ligne["credit"])
        for ligne in lignes.values("compte__numero", "compte__libelle").annotate(debit=Sum("debit"), credit=Sum("credit")).order_by("compte__numero")
    ]


# ---------------------------------------------------------------------------
# Journal et grand livre
# ---------------------------------------------------------------------------

def journal(etablissement, exercice, *, code_journal=None, du=None, au=None):
    ecritures = (
        Ecriture.objects.filter(etablissement=etablissement, exercice=exercice)
        .select_related("exercice", "contrepassation").prefetch_related("lignes__compte").order_by("date_ecriture", "id")
    )
    if code_journal:
        ecritures = ecritures.filter(journal=code_journal)
    if du:
        ecritures = ecritures.filter(date_ecriture__gte=du)
    if au:
        ecritures = ecritures.filter(date_ecriture__lte=au)
    return ecritures


@dataclass
class LigneGrandLivre:
    date: object
    numero: str
    journal: str
    libelle: str
    piece: str
    debit: int
    credit: int
    solde: int  # cumulé après cette ligne


def grand_livre_compte(etablissement, exercice, compte, *, du=None, au=None):
    """Mouvements d'un compte avec le solde cumulé. Renvoie (lignes, total débit, total crédit)."""
    lignes = LigneEcriture.objects.filter(
        ecriture__etablissement=etablissement, ecriture__exercice=exercice, compte=compte,
    ).select_related("ecriture").order_by("ecriture__date_ecriture", "ecriture__id", "id")
    if du:
        lignes = lignes.filter(ecriture__date_ecriture__gte=du)
    if au:
        lignes = lignes.filter(ecriture__date_ecriture__lte=au)
    resultat, cumul, total_debit, total_credit = [], 0, 0, 0
    for ligne in lignes:
        cumul += ligne.debit - ligne.credit
        total_debit += ligne.debit
        total_credit += ligne.credit
        ecriture = ligne.ecriture
        resultat.append(LigneGrandLivre(
            ecriture.date_ecriture, ecriture.numero, ecriture.journal, ligne.libelle or ecriture.libelle, ecriture.piece,
            ligne.debit, ligne.credit, cumul,
        ))
    return resultat, total_debit, total_credit


# ---------------------------------------------------------------------------
# Balance
# ---------------------------------------------------------------------------

def balance(etablissement, exercice, *, jusqu_au=None):
    """Balance générale : (lignes avec soldes débiteur et créditeur, totaux). Les totaux débit et crédit sont toujours égaux."""
    soldes = soldes_par_compte(etablissement, exercice, jusqu_au=jusqu_au)
    totaux = {
        "debit": sum(s.debit for s in soldes), "credit": sum(s.credit for s in soldes),
        "solde_debiteur": sum(s.solde for s in soldes if s.solde > 0), "solde_crediteur": sum(-s.solde for s in soldes if s.solde < 0),
    }
    totaux["equilibree"] = totaux["debit"] == totaux["credit"] and totaux["solde_debiteur"] == totaux["solde_crediteur"]
    return soldes, totaux


# ---------------------------------------------------------------------------
# Compte de résultat
# ---------------------------------------------------------------------------

def nature_resultat(numero: str):
    """'charge', 'produit' ou None pour un compte de bilan. Classe 8 : numéros de groupe impairs = charges, pairs = produits."""
    if numero[0] == "6":
        return "charge"
    if numero[0] == "7":
        return "produit"
    if numero[0] == "8":
        return "charge" if int(numero[1]) % 2 else "produit"
    return None


def _groupes(soldes, nature):
    """[(libellé du groupe, total, [soldes])] pour les comptes de cette nature ; montants positifs."""
    groupes = {}
    for solde in soldes:
        if nature_resultat(solde.numero) != nature:
            continue
        montant = solde.solde if nature == "charge" else -solde.solde
        groupes.setdefault(solde.numero[:2], []).append((solde, montant))
    return [
        {"code": code, "libelle": plan.libelle_groupe(code), "total": sum(m for _, m in lignes), "comptes": lignes}
        for code, lignes in sorted(groupes.items())
    ]


def compte_de_resultat(etablissement, exercice, *, jusqu_au=None):
    """Produits, charges et résultat, avec les soldes intermédiaires (exploitation, financier, hors activités ordinaires)."""
    soldes = soldes_par_compte(etablissement, exercice, jusqu_au=jusqu_au)
    produits, charges = _groupes(soldes, "produit"), _groupes(soldes, "charge")

    def total(groupes, predicat):
        return sum(g["total"] for g in groupes if predicat(g["code"]))

    exploitation = total(produits, lambda c: c[0] == "7" and c != "77") - total(charges, lambda c: c[0] == "6" and c != "67")
    financier = total(produits, lambda c: c == "77") - total(charges, lambda c: c == "67")
    hao = total(produits, lambda c: c[0] == "8") - total(charges, lambda c: c[0] == "8" and c not in ("87", "89"))
    participation = total(charges, lambda c: c == "87")
    impots = total(charges, lambda c: c == "89")
    total_produits, total_charges = sum(g["total"] for g in produits), sum(g["total"] for g in charges)
    return {
        "produits": produits, "charges": charges, "total_produits": total_produits, "total_charges": total_charges,
        "resultat": total_produits - total_charges,
        "soldes": [
            ("Résultat d'exploitation", exploitation), ("Résultat financier", financier),
            ("Résultat des activités ordinaires", exploitation + financier),
            ("Résultat hors activités ordinaires", hao), ("Participation des travailleurs", -participation),
            ("Impôts sur le résultat", -impots),
        ],
    }


# ---------------------------------------------------------------------------
# Bilan
# ---------------------------------------------------------------------------

def bilan(etablissement, exercice, *, jusqu_au=None):
    """
    Bilan simplifié. Chaque compte de bilan va à l'actif (soldes des classes 2 et 3, soldes débiteurs des classes 4 et 5) ou au
    passif (classe 1, soldes créditeurs des classes 4 et 5) ; le résultat de l'exercice (produits moins charges) complète le
    passif. Actif et passif sont égaux dès que toutes les écritures sont équilibrées (contrôle affiché).
    """
    soldes = soldes_par_compte(etablissement, exercice, jusqu_au=jusqu_au)
    actif = {"immobilisations": [], "stocks": [], "creances": [], "tresorerie": []}
    passif = {"capitaux": [], "dettes_financieres": [], "dettes": [], "tresorerie": []}
    resultat = 0
    for solde in soldes:
        classe = solde.classe
        if nature_resultat(solde.numero):
            resultat -= solde.solde  # produits (crédit) - charges (débit)
        elif classe == 1:
            groupe = "capitaux" if solde.numero[:2] in ("10", "11", "12", "13", "14", "15") else "dettes_financieres"
            passif[groupe].append((solde, -solde.solde))
        elif classe == 2:
            actif["immobilisations"].append((solde, solde.solde))
        elif classe == 3:
            actif["stocks"].append((solde, solde.solde))
        elif classe == 4:
            (actif["creances"].append((solde, solde.solde)) if solde.solde > 0 else passif["dettes"].append((solde, -solde.solde)))
        elif classe == 5:
            (actif["tresorerie"].append((solde, solde.solde)) if solde.solde > 0 else passif["tresorerie"].append((solde, -solde.solde)))
    sous_totaux_actif = {nom: sum(m for _, m in lignes) for nom, lignes in actif.items()}
    sous_totaux_passif = {nom: sum(m for _, m in lignes) for nom, lignes in passif.items()}
    total_actif = sum(sous_totaux_actif.values())
    total_passif = sum(sous_totaux_passif.values()) + resultat
    return {
        "actif": actif, "passif": passif, "sous_totaux_actif": sous_totaux_actif, "sous_totaux_passif": sous_totaux_passif,
        "resultat": resultat, "total_actif": total_actif, "total_passif": total_passif, "equilibre": total_actif == total_passif,
    }


def tableau_de_bord(etablissement, exercice):
    """Chiffres clés de l'exercice pour la page d'accueil de la comptabilité."""
    soldes = soldes_par_compte(etablissement, exercice)
    produits = sum(-s.solde for s in soldes if nature_resultat(s.numero) == "produit")
    charges = sum(s.solde for s in soldes if nature_resultat(s.numero) == "charge")
    tresorerie = sum(s.solde for s in soldes if s.classe == 5)
    return {"produits": produits, "charges": charges, "resultat": produits - charges, "tresorerie": tresorerie,
            "nombre_ecritures": Ecriture.objects.filter(etablissement=etablissement, exercice=exercice).count()}
