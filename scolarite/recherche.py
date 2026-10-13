"""
Retrouver un élève par son nom : personne ne retient le matricule de chacun.

La recherche ne tient compte ni des majuscules, ni des accents, ni de l'ordre des mots (« aissata maiga » trouve « MAIGA Aïssata ») :
les noms maliens portent souvent des accents et chacun les écrit à sa façon. Elle se fait en Python sur des listes déjà limitées
à ce que la personne a le droit de voir (une classe, ses classes, son école), jamais sur toute la base.
"""
import re
import unicodedata
from collections import Counter

INTROUVABLE = "introuvable"
PLUSIEURS = "plusieurs"


def normaliser(texte) -> str:
    """Minuscules, sans accents, espaces simples : « Aïssata  MAIGA » -> « aissata maiga »."""
    decompose = unicodedata.normalize("NFKD", str(texte or ""))
    sans_accents = "".join(caractere for caractere in decompose if not unicodedata.combining(caractere))
    return re.sub(r"\s+", " ", sans_accents.casefold()).strip()


def _valeur(objet, chemin):
    """Valeur d'un champ, éventuellement à travers une relation (« eleve.nom »)."""
    for nom in chemin.split("."):
        objet = getattr(objet, nom, "")
    return objet


def filtrer(personnes, terme, *champs, limite=None) -> list:
    """
    Les personnes dont les `champs` (« nom », ou « eleve.nom » à travers une relation) contiennent TOUS les mots du terme, dans
    n'importe quel ordre, accents et casse ignorés. Un terme vide ne trouve personne.
    """
    mots = normaliser(terme).split()
    if not mots:
        return []
    trouvees = []
    for personne in personnes:
        texte = normaliser(" ".join(str(_valeur(personne, champ) or "") for champ in champs))
        if all(mot in texte for mot in mots):
            trouvees.append(personne)
            if limite and len(trouvees) >= limite:
                break
    return trouvees


def trouver_eleve(saisie, eleves):
    """
    Résout ce que la personne a tapé en UN élève de la liste `eleves` : (élève, None), ou (None, INTROUVABLE / PLUSIEURS).

    Accepté : le matricule seul ; « NOM Prénom (matricule) » ou « NOM Prénom - matricule » (le dernier mot est le matricule) ;
    le nom complet, dans un sens ou dans l'autre, si un seul élève de la liste le porte. Jamais un bout de nom : une saisie
    à moitié tapée ne doit pas pouvoir noter ou marquer absent le mauvais élève.
    """
    eleves = list(eleves)
    saisie = (saisie or "").strip()
    if not saisie:
        return None, INTROUVABLE
    par_matricule = {eleve.matricule: eleve for eleve in eleves if eleve.matricule}
    if saisie in par_matricule:
        return par_matricule[saisie], None
    mots = re.sub(r"[()]", " ", saisie).split()
    if mots and mots[-1] in par_matricule:
        return par_matricule[mots[-1]], None
    cle = normaliser(saisie)
    egaux = [
        eleve for eleve in eleves
        if cle in (normaliser(f"{eleve.prenom} {eleve.nom}"), normaliser(f"{eleve.nom} {eleve.prenom}"))
    ]
    if len(egaux) == 1:
        return egaux[0], None
    return None, (PLUSIEURS if egaux else INTROUVABLE)


def options_de_saisie(eleves) -> list[str]:
    """
    Les propositions d'une liste déroulante de saisie : « NOM Prénom », triées par nom. Le matricule n'est ajouté que pour
    distinguer des homonymes : il n'a pas à s'afficher pour tout le monde (c'est aussi l'identifiant de connexion de l'élève).
    """
    ordonnes = sorted(eleves, key=lambda e: (normaliser(e.nom), normaliser(e.prenom)))
    homonymes = Counter(normaliser(f"{e.nom} {e.prenom}") for e in ordonnes)
    return [
        f"{e.nom} {e.prenom} ({e.matricule})" if homonymes[normaliser(f"{e.nom} {e.prenom}")] > 1 else f"{e.nom} {e.prenom}"
        for e in ordonnes
    ]
