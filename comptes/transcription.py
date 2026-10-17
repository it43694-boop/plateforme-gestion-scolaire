"""
Écriture en lettres arabes d'un nom de personne écrit en lettres latines (prénoms et noms maliens courants).

Deux étapes :
1. le dictionnaire `traductions/noms_ar.csv` (mot ou groupe de mots -> forme arabe usuelle : Mamadou -> محمدو, Fatoumata -> فاطمة, Traoré -> تراوري) ;
2. pour un mot inconnu, des règles de lecture à la française (ou -> و, é -> ي, dj -> ج, g -> غ...), qui donnent une écriture lisible mais PAS toujours
   celle que la famille choisirait.

C'est donc une PROPOSITION : l'école saisit l'écriture exacte de chaque personne (champs « prénom en arabe » et « nom en arabe »), qui passe
toujours avant cette transcription.
"""
import csv
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

FICHIER_NOMS = Path(__file__).resolve().parent / "traductions" / "noms_ar.csv"
MOT = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")

# Groupes de lettres lus d'un bloc, du plus long au plus court.
DIGRAPHES = (
    ("tch", "تش"), ("dj", "ج"), ("ch", "ش"), ("kh", "خ"), ("gh", "غ"), ("gn", "ني"), ("ng", "نغ"), ("ck", "ك"), ("qu", "ك"), ("ph", "ف"),
    ("th", "ت"), ("sh", "ش"), ("ou", "و"), ("oo", "و"), ("ai", "اي"), ("ay", "اي"), ("ei", "ي"), ("ey", "ي"), ("ee", "ي"), ("ii", "ي"),
    ("ie", "ي"), ("au", "او"),
)
LETTRES = {
    "a": "ا", "b": "ب", "d": "د", "f": "ف", "g": "غ", "h": "ه", "j": "ج", "k": "ك", "l": "ل", "m": "م", "n": "ن", "p": "ب", "q": "ق",
    "r": "ر", "s": "س", "t": "ت", "v": "ف", "w": "و", "x": "كس", "y": "ي", "z": "ز", "e": "ي", "i": "ي", "o": "و", "u": "و",
}
VOYELLES_ARABES = set("اويأإآ")
LETTRES_ARABES = re.compile(r"[؀-ۿݐ-ݿ]")


def cle(texte: str) -> str:
    """Forme de comparaison : minuscules, sans accents ni apostrophes (« Keïta » et « KEITA » donnent la même clé)."""
    texte = str(texte).casefold().replace("ç", "s").replace("’", "").replace("'", "")
    decompose = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in decompose if not unicodedata.combining(c))


@lru_cache(maxsize=1)
def dictionnaire() -> dict:
    with open(FICHIER_NOMS, encoding="utf-8-sig", newline="") as fichier:
        return {cle(ligne["latin"]): ligne["arabe"] for ligne in csv.DictReader(fichier) if ligne.get("latin") and ligne.get("arabe")}


def _mot_par_regles(mot: str) -> str:
    texte = cle(mot)
    resultat = []  # lettres arabes, avec leur nature (voyelle ou consonne) pour fondre les consonnes doubles
    i = 0
    while i < len(texte):
        debut = i == 0
        trouve = None
        for latin, arabe in DIGRAPHES:
            if texte.startswith(latin, i):
                trouve = (latin, arabe)
                break
        if trouve:
            latin, arabe = trouve
            if debut and latin == "ou":
                arabe = "أو"
            elif debut and latin in ("ai", "ay", "au"):
                arabe = "أ" + arabe[1:]
            i += len(latin)
        else:
            lettre = texte[i]
            if lettre == "c":
                arabe = "س" if texte[i + 1:i + 2] in ("e", "i", "y") else "ك"
            elif debut and lettre == "a" and len(texte) > 1:
                arabe = "أ"
            elif debut and lettre in ("i", "e") and len(texte) > 1:
                arabe = "إ" if lettre == "i" else "إي"
            elif debut and lettre == "o" and len(texte) > 1:
                arabe = "أو"
            else:
                arabe = LETTRES.get(lettre, lettre)
            i += 1
        if resultat and arabe == resultat[-1] and arabe not in VOYELLES_ARABES:
            continue  # consonne doublée (rr, ss, ll...) : une seule lettre
        resultat.append(arabe)
    return "".join(resultat)


def transcrire(texte: str) -> str:
    """L'écriture arabe d'un prénom ou d'un nom (un ou plusieurs mots ; les séparateurs - et espaces sont gardés)."""
    if not texte or not str(texte).strip():
        return ""
    if LETTRES_ARABES.search(texte):
        return str(texte)  # déjà en arabe
    mots = list(MOT.finditer(texte))
    entree = dictionnaire()
    morceaux, position, i = [], 0, 0
    while i < len(mots):
        # un groupe de mots connu (« Abdoul Karim ») passe avant les mots pris un à un
        for longueur in (3, 2):
            groupe = mots[i:i + longueur]
            if len(groupe) < longueur:
                continue
            if all(texte[a.end():b.start()] == " " for a, b in zip(groupe, groupe[1:])):
                traduction = entree.get(" ".join(cle(m.group()) for m in groupe))
                if traduction:
                    morceaux.append(texte[position:groupe[0].start()])
                    morceaux.append(traduction)
                    position = groupe[-1].end()
                    i += longueur
                    break
        else:
            mot = mots[i]
            morceaux.append(texte[position:mot.start()])
            morceaux.append(entree.get(cle(mot.group())) or _mot_par_regles(mot.group()))
            position = mot.end()
            i += 1
    morceaux.append(texte[position:])
    return "".join(morceaux)
