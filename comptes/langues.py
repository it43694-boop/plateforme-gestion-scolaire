"""
Langues d'affichage de la plateforme : le français (par défaut) et l'arabe (écrit de droite à gauche).

Ce module ne dépend d'aucun modèle : les modèles (Utilisateur.langue, Etablissement.langue_par_defaut) l'importent pour leurs choix.
Le choix de la langue se fait par utilisateur (compte), sinon par cookie (visiteur), sinon par l'école (langue par défaut), sinon
en français : voir comptes.langue.langue_de_la_requete.
"""

LANGUES = (("fr", "Français"), ("ar", "العربية"))
CODES_LANGUES = tuple(code for code, _ in LANGUES)
LANGUE_PAR_DEFAUT = "fr"
NOM_COOKIE_LANGUE = "yelenova_langue"
ANCIEN_NOM_COOKIE_LANGUE = "nexora_langue"  # l'ancien nom de la plateforme : un visiteur qui avait déjà choisi sa langue la garde
DUREE_COOKIE_LANGUE = 365 * 24 * 3600


def langue_valide(code) -> bool:
    return code in CODES_LANGUES


def autre_langue(code) -> str:
    """La langue vers laquelle le bouton bascule : l'arabe depuis le français, le français depuis l'arabe."""
    return "fr" if code == "ar" else "ar"


def nom_de_la_langue(code) -> str:
    """Le nom d'une langue écrit dans sa propre écriture (« العربية », « Français »)."""
    return dict(LANGUES).get(code, "")
