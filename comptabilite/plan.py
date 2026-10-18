"""
Plan comptable de base d'un établissement scolaire, selon le plan SYSCOHADA révisé (classes 1 à 8).

Ce n'est PAS le plan complet (plusieurs centaines de comptes) : c'est le sous-ensemble utile à une école, au niveau
des comptes à trois chiffres, avec trois subdivisions propres à la scolarité sur CINQ chiffres (70601, 70602, 70608) pour
ne jamais entrer en conflit avec un sous-compte officiel. L'établissement ajoute ses propres sous-comptes (2 à 10
chiffres) depuis la page « Plan comptable ». Les numéros et intitulés sont à faire valider par un expert-comptable.
"""

# Comptes de trésorerie utilisés par la comptabilisation automatique des paiements et des salaires
CAISSE = "571"
MONNAIE_ELECTRONIQUE = "551"
BANQUE = "521"
# Produits de la scolarité
DROITS_INSCRIPTION = "70601"
FRAIS_SCOLARITE = "70602"
AUTRES_SERVICES_VENDUS = "70608"  # frais annexes (examen, transport...) et cantine
VENTES_MARCHANDISES = "701"  # ventes de tenues (uniformes)
# Charges et dettes de personnel
REMUNERATIONS_PERSONNEL = "661"
CHARGES_SOCIALES = "664"
SECURITE_SOCIALE = "431"
AUTRES_ORGANISMES_SOCIAUX = "433"
IMPOTS_SUR_SALAIRES = "447"
# Résultat de l'exercice
RESULTAT_BENEFICE = "131"
RESULTAT_PERTE = "139"

PLAN_DE_BASE = [
    # --- Classe 1 : ressources durables
    ("101", "Capital social"),
    ("106", "Écarts de réévaluation"),
    ("111", "Réserve légale"),
    ("112", "Réserves statutaires ou contractuelles"),
    ("118", "Autres réserves"),
    ("121", "Report à nouveau créditeur"),
    ("129", "Report à nouveau débiteur"),
    ("131", "Résultat net de l'exercice : bénéfice"),
    ("139", "Résultat net de l'exercice : perte"),
    ("141", "Subventions d'équipement"),
    ("162", "Emprunts et dettes auprès des établissements de crédit"),
    ("165", "Dépôts et cautionnements reçus"),
    ("168", "Autres emprunts et dettes"),
    # --- Classe 2 : actif immobilisé
    ("212", "Brevets, licences, logiciels et droits similaires"),
    ("222", "Terrains nus"),
    ("223", "Terrains bâtis"),
    ("231", "Bâtiments sur sol propre"),
    ("232", "Bâtiments sur sol d'autrui"),
    ("235", "Aménagements de bureaux"),
    ("241", "Matériel et outillage"),
    ("244", "Matériel et mobilier (bureau, informatique, mobilier scolaire)"),
    ("245", "Matériel de transport"),
    ("281", "Amortissements des immobilisations incorporelles"),
    ("283", "Amortissements des bâtiments et agencements"),
    ("284", "Amortissements du matériel et du mobilier"),
    # --- Classe 3 : stocks
    ("311", "Marchandises (livres, uniformes)"),
    ("331", "Matières consommables"),
    # --- Classe 4 : tiers
    ("401", "Fournisseurs, dettes en compte"),
    ("408", "Fournisseurs, factures non parvenues"),
    ("409", "Fournisseurs débiteurs (avances et acomptes versés)"),
    ("411", "Clients : familles (scolarité à recevoir)"),
    ("416", "Clients douteux ou litigieux"),
    ("419", "Clients créditeurs (avances reçues des familles)"),
    ("421", "Personnel, avances et acomptes"),
    ("422", "Personnel, rémunérations dues"),
    ("428", "Personnel, charges à payer"),
    ("431", "Sécurité sociale (INPS)"),
    ("433", "Autres organismes sociaux (AMO)"),
    ("441", "État, impôt sur les bénéfices"),
    ("442", "État, autres impôts et taxes"),
    ("443", "État, TVA facturée"),
    ("445", "État, TVA récupérable"),
    ("447", "État, impôts retenus à la source (ITS sur salaires)"),
    ("471", "Débiteurs divers"),
    ("472", "Créditeurs divers"),
    # --- Classe 5 : trésorerie
    ("521", "Banques locales"),
    ("551", "Monnaie électronique (Mobile Money)"),
    ("571", "Caisse"),
    ("585", "Virements de fonds (transferts internes)"),
    # --- Classe 6 : charges des activités ordinaires
    ("601", "Achats de marchandises"),
    ("604", "Achats stockés de matières et fournitures consommables"),
    ("605", "Autres achats (eau, électricité, fournitures non stockables, petit matériel)"),
    ("614", "Transports du personnel"),
    ("618", "Autres frais de transport"),
    ("621", "Sous-traitance générale"),
    ("622", "Locations et charges locatives"),
    ("624", "Entretien, réparations et maintenance"),
    ("625", "Primes d'assurances"),
    ("626", "Études, recherches et documentation"),
    ("627", "Publicité, publications, relations publiques"),
    ("628", "Frais de télécommunications"),
    ("631", "Frais bancaires"),
    ("632", "Rémunérations d'intermédiaires et de conseils"),
    ("633", "Frais de formation du personnel"),
    ("635", "Cotisations"),
    ("638", "Autres charges externes"),
    ("641", "Impôts et taxes directs"),
    ("646", "Droits d'enregistrement"),
    ("647", "Pénalités et amendes fiscales"),
    ("648", "Autres impôts et taxes"),
    ("651", "Pertes sur créances (scolarité irrécouvrable)"),
    ("658", "Charges diverses"),
    ("661", "Rémunérations directes versées au personnel national"),
    ("663", "Indemnités forfaitaires versées au personnel"),
    ("664", "Charges sociales"),
    ("668", "Autres charges sociales"),
    ("671", "Intérêts des emprunts"),
    ("681", "Dotations aux amortissements d'exploitation"),
    # --- Classe 7 : produits des activités ordinaires
    ("701", "Ventes de marchandises (livres, uniformes)"),
    ("706", "Services vendus"),
    ("70601", "Droits d'inscription et de réinscription"),
    ("70602", "Frais de scolarité"),
    ("70608", "Autres services vendus (cantine, transport, activités)"),
    ("707", "Produits accessoires"),
    ("718", "Autres subventions d'exploitation"),
    ("758", "Produits divers (dons, legs)"),
    ("771", "Intérêts de prêts et créances diverses"),
    # --- Classe 8 : autres charges et produits
    ("891", "Impôts sur les bénéfices de l'exercice"),
]

# Intitulés des groupes (deux premiers chiffres) pour les états de synthèse
GROUPES = {
    "10": "Capital", "11": "Réserves", "12": "Report à nouveau", "13": "Résultat net de l'exercice",
    "14": "Subventions d'investissement", "15": "Provisions réglementées", "16": "Emprunts et dettes assimilées",
    "17": "Dettes de crédit-bail", "18": "Dettes liées à des participations", "19": "Provisions financières pour risques",
    "21": "Immobilisations incorporelles", "22": "Terrains", "23": "Bâtiments et agencements",
    "24": "Matériel, mobilier et actifs biologiques", "25": "Avances sur immobilisations",
    "26": "Titres de participation", "27": "Autres immobilisations financières", "28": "Amortissements", "29": "Dépréciations",
    "31": "Marchandises", "32": "Matières premières", "33": "Autres approvisionnements",
    "40": "Fournisseurs", "41": "Clients", "42": "Personnel", "43": "Organismes sociaux", "44": "État et collectivités",
    "45": "Organismes internationaux", "46": "Associés et groupe", "47": "Débiteurs et créditeurs divers", "48": "Créances et dettes HAO",
    "49": "Dépréciations et provisions à court terme",
    "50": "Titres de placement", "51": "Valeurs à encaisser", "52": "Banques", "53": "Établissements financiers",
    "55": "Monnaie électronique", "56": "Crédits de trésorerie", "57": "Caisse", "58": "Virements internes",
    "60": "Achats et variations de stocks", "61": "Transports", "62": "Services extérieurs", "63": "Autres services extérieurs",
    "64": "Impôts et taxes", "65": "Autres charges", "66": "Charges de personnel", "67": "Frais financiers et charges assimilées",
    "68": "Dotations aux amortissements", "69": "Dotations aux provisions",
    "70": "Ventes et services vendus", "71": "Subventions d'exploitation", "72": "Production immobilisée",
    "73": "Variations de stocks de produits", "75": "Autres produits", "77": "Revenus financiers et produits assimilés",
    "78": "Transferts de charges", "79": "Reprises de provisions",
    "81": "Valeurs comptables des cessions d'immobilisations", "82": "Produits des cessions d'immobilisations",
    "83": "Charges hors activités ordinaires", "84": "Produits hors activités ordinaires",
    "85": "Dotations hors activités ordinaires", "86": "Reprises hors activités ordinaires",
    "87": "Participation des travailleurs", "88": "Subventions d'équilibre", "89": "Impôts sur le résultat",
}


def libelle_groupe(numero: str) -> str:
    return GROUPES.get(numero[:2], f"Comptes {numero[:2]}")
