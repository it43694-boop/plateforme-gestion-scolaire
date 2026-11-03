"""
Import Excel des numéros d'un cycle, pour une classe : on télécharge le modèle (les élèves de la classe et leur matricule d'origine y sont déjà
écrits), on écrit le numéro de chacun dans la dernière colonne, puis on renvoie le fichier.

Le fichier ne crée et n'enregistre rien : ses numéros sont posés dans les champs de la page « Numéros du cycle », où la personne les vérifie
avant d'enregistrer (mêmes règles que la saisie à la main). Un élève se reconnaît à son matricule d'origine ; à défaut de matricule, à son
prénom et son nom, s'ils ne désignent qu'un seul élève de la classe. Une ligne sans numéro est ignorée (elle n'efface rien).
"""
from collections import defaultdict

from comptes.arabisation import chiffres_ascii
from comptes.excel import ajouter_feuille_tableau, nouveau_classeur
from scolarite.import_eleves import ErreurFichier, _cle_arabe, _normaliser, _texte, lire_rangees  # noqa: F401 (ErreurFichier réexportée)

# Titres reconnus (le titre du modèle, en français ou en arabe, ou la clé technique) -> clé de colonne.
ENTETES = {
    "matricule": "matricule", "matricule_d_origine": "matricule", "matricule_origine": "matricule",
    "prenom": "prenom", "prenoms": "prenom", "nom": "nom",
    "numero_du_cycle": "numero", "numero": "numero", "numero_cycle": "numero", "nouveau_numero": "numero",
}
ENTETES_ARABES = {
    _cle_arabe("رقم التسجيل الأصلي"): "matricule", _cle_arabe("رقم التسجيل"): "matricule",
    _cle_arabe("رقم التسجيل في المرحلة"): "numero", _cle_arabe("رقم المرحلة"): "numero",
}


def _colonnes(valeurs) -> dict:
    """`{position: clé}` pour une ligne dont on reconnaît des titres."""
    colonnes = {}
    for position, titre in enumerate(valeurs):
        texte = _texte(titre)
        cle = ENTETES.get(_normaliser(texte)) or ENTETES_ARABES.get(_cle_arabe(texte)) if texte else None
        if cle and cle not in colonnes.values():
            colonnes[position] = cle
    return colonnes


def lire_numeros(fichier) -> list:
    """
    Les lignes qui portent un numéro : `[(numéro de ligne Excel, {matricule, prenom, nom, numero})]`. Lève ErreurFichier si le fichier est
    inutilisable (format, taille, colonnes absentes).
    """
    rangees = lire_rangees(fichier)
    for debut, (_, valeurs) in enumerate(rangees):
        colonnes = _colonnes(valeurs)
        if "numero" in colonnes.values():
            break
    else:
        raise ErreurFichier(
            "Colonne « Numéro du cycle » introuvable : téléchargez le modèle de la classe et écrivez les numéros dans cette colonne."
        )
    cles = set(colonnes.values())
    if "matricule" not in cles and not {"prenom", "nom"} <= cles:
        raise ErreurFichier(
            "Colonne « Matricule d'origine » introuvable : téléchargez le modèle de la classe, sans changer ses titres."
        )
    lignes = []
    for numero, valeurs in rangees[debut + 1:]:
        ligne = {cle: _texte(valeurs[position]) if position < len(valeurs) else "" for position, cle in colonnes.items()}
        if ligne.get("numero"):
            lignes.append((numero, ligne))
    return lignes


def associer(eleves, lignes) -> tuple[dict, list]:
    """
    Relie chaque ligne à un élève de la classe (`eleves` : `{id: élève}`). Rend `({id de l'élève: numéro}, [messages d'erreur])`.
    """
    par_matricule = {eleve.matricule.casefold(): eleve_id for eleve_id, eleve in eleves.items() if eleve.matricule}
    par_nom = defaultdict(list)
    for eleve_id, eleve in eleves.items():
        par_nom[(_normaliser(eleve.prenom), _normaliser(eleve.nom))].append(eleve_id)
    saisies, vues, erreurs = {}, {}, []
    for numero_ligne, ligne in lignes:
        matricule = chiffres_ascii(ligne.get("matricule", "")).strip()
        if matricule:
            candidats = [par_matricule[matricule.casefold()]] if matricule.casefold() in par_matricule else []
        else:
            candidats = par_nom.get((_normaliser(ligne.get("prenom", "")), _normaliser(ligne.get("nom", ""))), [])
        if len(candidats) > 1:
            erreurs.append(f"Ligne {numero_ligne} : plusieurs élèves de cette classe portent ce nom. Recopiez son matricule d'origine.")
        elif not candidats:
            erreurs.append(
                f"Ligne {numero_ligne} : élève introuvable dans cette classe. Recopiez son matricule d'origine, tel qu'il est écrit dans le modèle."
            )
        elif candidats[0] in vues:
            erreurs.append(f"Ligne {numero_ligne} : même élève que la ligne {vues[candidats[0]]}.")
        else:
            vues[candidats[0]] = numero_ligne
            saisies[candidats[0]] = ligne["numero"]
    return saisies, erreurs


def modele_xlsx(classe, eleves, propres):
    """
    Classeur à remplir : les élèves de la classe (matricule d'origine, prénom, nom) et leur numéro actuel dans ce cycle (`propres` : `{id: numéro}`,
    vide s'il n'en ont pas). La colonne du numéro est au format texte : un numéro qui commence par 0 garde son 0.
    """
    classeur = nouveau_classeur()
    infos = [
        ("Classe", classe.nom), ("Cycle", classe.get_cycle_display()), ("Année scolaire", classe.annee_scolaire.libelle),
        ("Mode d'emploi", "Écrivez le numéro de chaque élève dans la dernière colonne, puis envoyez le fichier. Ne changez ni les titres ni les matricules d'origine."),
    ]
    lignes = [
        [eleve.matricule, eleve.prenom, eleve.nom, propres.get(eleve_id, "")]
        for eleve_id, eleve in sorted(eleves.items(), key=lambda element: (_normaliser(element[1].nom), _normaliser(element[1].prenom)))
    ]
    feuille = ajouter_feuille_tableau(
        classeur, "Numéros", f"Numéros du cycle - {classe.nom}", infos,
        ["Matricule d'origine", "Prénom", "Nom", "Numéro du cycle"], lignes,
    )
    premiere = 2 + len(infos) + 2  # titre, informations, ligne vide, titres : les élèves commencent juste dessous
    for rang in range(premiere, premiere + len(lignes)):
        feuille.cell(row=rang, column=4).number_format = "@"
    return classeur
