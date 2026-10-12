"""Export Excel de tous les états d'un exercice : journal, grand livre, balance, compte de résultat, bilan."""
import datetime

from comptabilite import etats
from comptabilite.models import CompteComptable
from comptes.excel import ajouter_feuille_tableau, nouveau_classeur

FORMAT_MONTANT = "#,##0"


def classeur_etats(etablissement, exercice):
    classeur = nouveau_classeur()
    en_tete = [
        ("Établissement", etablissement.nom), ("Exercice", str(exercice)),
        ("Situation", "Clôturé" if exercice.cloture else "Ouvert"), ("Édité le", datetime.date.today()),
    ]

    # --- Journal : une ligne par ligne d'écriture
    lignes = []
    for ecriture in etats.journal(etablissement, exercice):
        for ligne in ecriture.lignes.all():
            lignes.append([
                ecriture.date_ecriture, ecriture.numero, ecriture.journal, ecriture.piece, ecriture.libelle,
                ligne.compte.numero, ligne.compte.libelle, ligne.debit or None, ligne.credit or None,
            ])
    ajouter_feuille_tableau(
        classeur, "Journal", "Journal", en_tete,
        ["Date", "N° d'écriture", "Journal", "Pièce", "Libellé", "Compte", "Intitulé du compte", "Débit", "Crédit"], lignes,
        total=["", "", "", "", "Total", "", "", sum(r[7] or 0 for r in lignes), sum(r[8] or 0 for r in lignes)],
        formats={8: FORMAT_MONTANT, 9: FORMAT_MONTANT},
    )

    # --- Grand livre : tous les comptes mouvementés, avec le solde cumulé
    lignes = []
    comptes = {c.numero: c for c in CompteComptable.objects.filter(etablissement=etablissement)}
    for solde in etats.soldes_par_compte(etablissement, exercice, inclure_cloture=True):
        mouvements, _, _ = etats.grand_livre_compte(etablissement, exercice, comptes[solde.numero])
        for m in mouvements:
            lignes.append([solde.numero, solde.libelle, m.date, m.numero, m.libelle, m.debit or None, m.credit or None, m.solde])
    ajouter_feuille_tableau(
        classeur, "Grand livre", "Grand livre", en_tete,
        ["Compte", "Intitulé", "Date", "N° d'écriture", "Libellé", "Débit", "Crédit", "Solde cumulé"], lignes,
        formats={6: FORMAT_MONTANT, 7: FORMAT_MONTANT, 8: FORMAT_MONTANT},
    )

    # --- Balance
    soldes, totaux = etats.balance(etablissement, exercice)
    ajouter_feuille_tableau(
        classeur, "Balance", "Balance générale (avant écritures de clôture)", en_tete,
        ["Compte", "Intitulé", "Débit", "Crédit", "Solde débiteur", "Solde créditeur"],
        [[s.numero, s.libelle, s.debit, s.credit, s.solde if s.solde > 0 else None, -s.solde if s.solde < 0 else None] for s in soldes],
        total=["Total", "", totaux["debit"], totaux["credit"], totaux["solde_debiteur"], totaux["solde_crediteur"]],
        formats={3: FORMAT_MONTANT, 4: FORMAT_MONTANT, 5: FORMAT_MONTANT, 6: FORMAT_MONTANT},
    )

    # --- Compte de résultat
    resultat = etats.compte_de_resultat(etablissement, exercice)
    lignes = []
    for titre, groupes in (("Produits", resultat["produits"]), ("Charges", resultat["charges"])):
        for groupe in groupes:
            lignes.append([titre, f"{groupe['code']} - {groupe['libelle']}", "", groupe["total"]])
            lignes += [["", "", f"{s.numero} - {s.libelle}", montant] for s, montant in groupe["comptes"]]
    lignes += [["Soldes", libelle, "", montant] for libelle, montant in resultat["soldes"]]
    ajouter_feuille_tableau(
        classeur, "Compte de résultat", "Compte de résultat", en_tete, ["Rubrique", "Groupe", "Compte", "Montant"], lignes,
        total=["Résultat net (produits - charges)", "", "", resultat["resultat"]], formats={4: FORMAT_MONTANT},
    )

    # --- Bilan
    bilan = etats.bilan(etablissement, exercice)
    libelles_actif = {"immobilisations": "Actif immobilisé", "stocks": "Stocks", "creances": "Créances et emplois assimilés", "tresorerie": "Trésorerie - actif"}
    libelles_passif = {"capitaux": "Capitaux propres", "dettes_financieres": "Dettes financières", "dettes": "Dettes circulantes", "tresorerie": "Trésorerie - passif"}
    lignes = []
    for cle, libelle in libelles_actif.items():
        lignes.append(["Actif", libelle, "", bilan["sous_totaux_actif"][cle]])
        lignes += [["", "", f"{s.numero} - {s.libelle}", montant] for s, montant in bilan["actif"][cle]]
    lignes.append(["Actif", "TOTAL ACTIF", "", bilan["total_actif"]])
    for cle, libelle in libelles_passif.items():
        lignes.append(["Passif", libelle, "", bilan["sous_totaux_passif"][cle]])
        lignes += [["", "", f"{s.numero} - {s.libelle}", montant] for s, montant in bilan["passif"][cle]]
    lignes.append(["Passif", "Résultat de l'exercice", "", bilan["resultat"]])
    lignes.append(["Passif", "TOTAL PASSIF", "", bilan["total_passif"]])
    ajouter_feuille_tableau(
        classeur, "Bilan", "Bilan simplifié", en_tete + [("Équilibre actif / passif", "Équilibré" if bilan["equilibre"] else "NON ÉQUILIBRÉ")],
        ["Côté", "Rubrique", "Compte", "Montant"], lignes, formats={4: FORMAT_MONTANT},
    )
    return classeur
