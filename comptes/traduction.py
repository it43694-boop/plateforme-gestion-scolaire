"""
Traduction des pages de la plateforme : un catalogue « français -> arabe » appliqué au HTML déjà produit.

Pourquoi à la sortie plutôt que dans chaque gabarit : l'application a été écrite en français, avec des milliers de textes dans ses
gabarits, ses formulaires, ses libellés de rôles et ses messages. Ce moteur les remplace à l'affichage, écran par écran, sans toucher à
chaque ligne de code ; un texte absent du catalogue reste en français (jamais de page cassée) et la liste de ce qui reste à traduire
sur une page s'obtient avec `manage.py audit_traduction`. Le catalogue est un simple fichier CSV (comptes/traductions/ar.csv) que
l'on peut corriger dans un tableur.

Ce qui est traduit : les textes des pages et les attributs lus par l'utilisateur (placeholder, aria-label, title, alt, boutons
d'envoi, message de confirmation). Ce qui ne l'est jamais : le contenu des <script>, <style>, <textarea> et commentaires, ni rien qui
ne figure pas EXACTEMENT au catalogue (un nom d'élève ou une annonce ne sont jamais « devinés »).

Phrases à trous : « {0} élèves inscrits » ; les valeurs captées restent telles quelles (ou sont traduites si elles figurent seules au catalogue).
Plusieurs textes collés par « · », « - », « — », « / » ou « | » sont traduits morceau par morceau.
"""
import csv
import html
import re
from functools import lru_cache
from pathlib import Path

DOSSIER_CATALOGUES = Path(__file__).resolve().parent / "traductions"
SEPARATEURS = (" · ", " — ", " - ", " / ", " | ")
PROFONDEUR_MAXIMALE = 3
LONGUEUR_MAXIMALE_DECOUPEE = 200  # un long paragraphe n'est jamais découpé en morceaux

TROU = re.compile(r"\{(\d+)\}")
JETONS = re.compile(
    r"(<!--.*?-->|<script\b.*?</script\s*>|<style\b.*?</style\s*>|<textarea\b.*?</textarea\s*>|<[^>]+>)", re.S | re.I,
)
ATTRIBUTS = re.compile(
    r'(?P<debut>(?<![\w-])(?:placeholder|aria-label|title|alt|data-confirmer)\s*=\s*")(?P<valeur>[^"]*)(?P<fin>")', re.I,
)
NOM_DE_BALISE = re.compile(r"<(/?)([a-zA-Z][\w:-]*)")
PROTEGE = re.compile(r'(?<![\w-])translate\s*=\s*"no"', re.I)
BALISES_SANS_FIN = {"input", "img", "br", "hr", "meta", "link", "area", "base", "col", "embed", "source", "track", "wbr"}
VALEUR_BOUTON = re.compile(r'(?P<debut>(?<![\w-])value\s*=\s*")(?P<valeur>[^"]*)(?P<fin>")', re.I)
TYPE_BOUTON = re.compile(r'(?<![\w-])type\s*=\s*"(?:submit|button|reset)"', re.I)

# Sens de lecture : dans une page de droite à gauche, un texte latin (nom, classe « 10ème CM1 (2026-2027) », référence, numéro avec « + »)
# est réordonné par le navigateur s'il n'est pas isolé. Les données ne se traduisent pas, mais on les enferme dans un isolat de direction
# automatique : <bdi> dans le texte, ou les caractères Unicode FSI / PDI là où une balise est interdite (liste déroulante, titre, SVG, attribut).
ISOLAT_DEBUT, ISOLAT_FIN = "\u2068", "\u2069"
A_ISOLER = re.compile(r"[A-Za-z\u00C0-\u024F]|(?<!\w)\+\s*\d")
PONCTUATION_DE_BORD = " \t\r\n-–—·:,;.!?،؛\"'«»"
ENTOURAGE = re.compile(rf"([{re.escape(PONCTUATION_DE_BORD)}]*)(.*?)([{re.escape(PONCTUATION_DE_BORD)}]*)", re.S)
BALISES_DE_TEXTE_BRUT = {"option", "title"}


def _isoler(texte: str) -> str:
    return f"{ISOLAT_DEBUT}{texte}{ISOLAT_FIN}" if A_ISOLER.search(texte) else texte


def _en_balises(texte_echappe: str, brut: bool) -> str:
    """Les isolats d'un texte déjà échappé deviennent <bdi>...</bdi>, sauf là où seul du texte est permis (brut)."""
    if brut:
        return texte_echappe
    return texte_echappe.replace(ISOLAT_DEBUT, "<bdi>").replace(ISOLAT_FIN, "</bdi>")


def normaliser(texte: str) -> str:
    """Espaces et sauts de ligne ramenés à une seule espace, apostrophe droite : la clé d'un texte du catalogue."""
    return " ".join(str(texte).replace("’", "'").split())


class Catalogue:
    """Textes exacts et phrases à trous d'une langue."""

    def __init__(self, entrees):
        self.exact = {}
        self.motifs = []
        for francais, traduction in entrees:
            cle = normaliser(francais)
            if not cle or not str(traduction).strip():
                continue
            if TROU.search(cle):
                self.motifs.append((self._motif(cle), traduction))
            else:
                self.exact[cle] = traduction
        self.motifs.sort(key=lambda motif: -len(motif[0].pattern))

    @staticmethod
    def _motif(cle):
        morceaux = TROU.split(cle)  # [texte, n, texte, n, ...]
        motif = "".join(
            f"(?P<g{morceau}>.+?)" if indice % 2 else re.escape(morceau) for indice, morceau in enumerate(morceaux)
        )
        return re.compile(motif, re.S)

    def __len__(self):
        return len(self.exact) + len(self.motifs)

    def traduire(self, texte, isoler=False):
        """La traduction d'un texte, ou None s'il n'y en a pas (le texte reste alors tel quel).

        isoler=True entoure d'un isolat de direction les valeurs non traduites (noms, classes...) qui se trouvent dans la phrase traduite.
        """
        return self._traduire(normaliser(texte), 0, isoler)

    def _traduire(self, cle, profondeur, isoler=False):
        if not cle:
            return None
        if cle in self.exact:
            return self.exact[cle]
        for motif, traduction in self.motifs:
            correspondance = motif.fullmatch(cle)
            if correspondance:
                valeurs = {
                    nom: self._traduire(normaliser(valeur), profondeur + 1, isoler) or (_isoler(valeur) if isoler else valeur)
                    for nom, valeur in correspondance.groupdict().items()
                }
                return TROU.sub(lambda trou: valeurs.get(f"g{trou.group(1)}", trou.group(0)), traduction)
        if profondeur >= PROFONDEUR_MAXIMALE or len(cle) > LONGUEUR_MAXIMALE_DECOUPEE:
            return None
        for separateur in SEPARATEURS:
            if separateur in cle:
                parties = cle.split(separateur)
                traduites = [self._traduire(partie, profondeur + 1, isoler) for partie in parties]
                if any(traduite is not None for traduite in traduites):
                    return separateur.join(
                        (_isoler(partie) if isoler else partie) if traduite is None else traduite for partie, traduite in zip(parties, traduites)
                    )
        return None


@lru_cache(maxsize=None)
def catalogue_pour(langue: str) -> Catalogue:
    """Le catalogue d'une langue (lu une fois) ; vide si la langue n'a pas de fichier."""
    chemin = DOSSIER_CATALOGUES / f"{langue}.csv"
    if not chemin.exists():
        return Catalogue([])
    return Catalogue(lire_csv(chemin))


def lire_csv(chemin):
    """Les couples (français, traduction) d'un fichier CSV : colonnes `francais`, `arabe`, `note` (la dernière est facultative)."""
    with open(chemin, encoding="utf-8-sig", newline="") as fichier:
        return [(ligne["francais"], ligne["arabe"]) for ligne in csv.DictReader(fichier) if ligne.get("francais")]


def vider_le_cache():
    catalogue_pour.cache_clear()


def _traduire_attributs(balise: str, catalogue: Catalogue) -> str:
    def remplacer(correspondance):
        traduction = catalogue.traduire(html.unescape(correspondance.group("valeur")))
        if traduction is None:
            return correspondance.group(0)
        return f"{correspondance.group('debut')}{html.escape(traduction, quote=True)}{correspondance.group('fin')}"

    balise = ATTRIBUTS.sub(remplacer, balise)
    if re.match(r"<(?:input|button)\b", balise, re.I) and TYPE_BOUTON.search(balise):
        balise = VALEUR_BOUTON.sub(remplacer, balise)
    return balise


def _traduire_texte(texte: str, catalogue: Catalogue, brut: bool = False) -> str:
    correspondance = re.fullmatch(r"(\s*)(.*?)(\s*)", texte, re.S)
    gauche, noyau, droite = correspondance.groups()
    if not noyau:
        return texte
    original = html.unescape(noyau)
    traduction = catalogue.traduire(original, isoler=True)
    if traduction is not None:
        return f"{gauche}{_en_balises(html.escape(traduction, quote=False), brut)}{droite}"
    debut, milieu, fin = ENTOURAGE.fullmatch(original).groups()  # ponctuation de bord : elle reste hors de l'isolat
    if not A_ISOLER.search(milieu):
        return texte
    isole = f"{html.escape(debut, quote=False)}{_en_balises(_isoler(html.escape(milieu, quote=False)), brut)}{html.escape(fin, quote=False)}"
    return f"{gauche}{isole}{droite}"


def traduire_html(contenu: str, catalogue: Catalogue) -> str:
    """Le HTML d'une page avec ses textes et ses attributs lisibles traduits ; tout le reste est rendu à l'identique."""
    if not len(catalogue):
        return contenu
    morceaux = JETONS.split(contenu)
    sortie = []
    protege = None  # [nom de la balise protégée, profondeur] : tout ce qu'elle contient reste tel quel (translate="no")
    precedente = ""  # nom de la balise ouvrante qui précède le texte
    dans_svg = 0
    for indice, morceau in enumerate(morceaux):
        if protege is not None:
            sortie.append(morceau)
            if indice % 2:
                balise = NOM_DE_BALISE.match(morceau)
                if balise and balise.group(2).lower() == protege[0]:
                    protege[1] += -1 if balise.group(1) else 1
                    if protege[1] <= 0:
                        protege = None
            continue
        if indice % 2 == 0:
            sortie.append(_traduire_texte(morceau, catalogue, brut=dans_svg > 0 or precedente in BALISES_DE_TEXTE_BRUT))
            continue
        balise_courante = NOM_DE_BALISE.match(morceau)
        if balise_courante:
            nom_courant, fermante = balise_courante.group(2).lower(), bool(balise_courante.group(1))
            precedente = "" if fermante else nom_courant
            if nom_courant == "svg":
                dans_svg = max(0, dans_svg - 1) if fermante else dans_svg + (0 if morceau.rstrip().endswith("/>") else 1)
        if not morceau.startswith(("<!--", "</")) and PROTEGE.search(morceau.partition(">")[0]):
            balise = NOM_DE_BALISE.match(morceau)
            sortie.append(morceau)
            if balise and balise.group(2).lower() not in BALISES_SANS_FIN and not morceau.rstrip().endswith("/>"):
                protege = [balise.group(2).lower(), 1]
            continue
        minuscule = morceau[:12].lower()
        if morceau.startswith("<!--") or minuscule.startswith(("<script", "<style")):
            sortie.append(morceau)
        elif minuscule.startswith("<textarea"):
            ouverture, _, reste = morceau.partition(">")  # seule l'ouverture (son placeholder) se traduit, jamais le contenu saisi
            sortie.append(_traduire_attributs(ouverture, catalogue) + ">" + reste)
        elif morceau.startswith("</"):
            sortie.append(morceau)
        else:
            sortie.append(_traduire_attributs(morceau, catalogue))
    return "".join(sortie)


def textes_de_la_page(contenu: str):
    """Les textes et attributs lisibles d'une page (sans doublon, dans l'ordre) : ce qu'il y a à traduire."""
    vus, resultat = set(), []
    for indice, morceau in enumerate(JETONS.split(contenu)):
        candidats = []
        if indice % 2 == 0:
            candidats.append(html.unescape(morceau))
        elif not morceau.startswith(("<!--", "</")) and not morceau[:12].lower().startswith(("<script", "<style")):
            candidats.extend(html.unescape(m.group("valeur")) for m in ATTRIBUTS.finditer(morceau.partition(">")[0] if morceau[:9].lower().startswith("<textarea") else morceau))
            if re.match(r"<(?:input|button)\b", morceau, re.I) and TYPE_BOUTON.search(morceau):
                candidats.extend(html.unescape(m.group("valeur")) for m in VALEUR_BOUTON.finditer(morceau))
        for candidat in candidats:
            cle = normaliser(candidat)
            if cle and cle not in vus:
                vus.add(cle)
                resultat.append(cle)
    return resultat


def chaines_non_traduites(contenu: str, catalogue: Catalogue):
    """Les textes de la page qui contiennent des lettres et n'ont pas de traduction (nombres, signes et déjà-arabe exclus)."""
    return [
        texte for texte in textes_de_la_page(contenu)
        if re.search(r"[^\W\d_]", texte) and not re.search(r"[؀-ۿ]", texte) and catalogue.traduire(texte) is None
    ]
