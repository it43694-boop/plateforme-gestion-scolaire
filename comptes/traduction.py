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
SEPARATEURS = (" · ", " — ", " - ", " / ", " | ", ", ")
SEPARATEURS_FORTS = (" · ", " — ", " - ", " | ")
SEPARATEUR_DE_SORTIE = {", ": "، "}  # la virgule française devient la virgule arabe
PROFONDEUR_MAXIMALE = 6
LONGUEUR_MAXIMALE_DECOUPEE = 200  # un long paragraphe n'est jamais découpé en morceaux

TROU = re.compile(r"\{(\d+)\}")
SEPARATEURS_DE_MORCEAUX = re.compile(r"( · | — | \| )")
PARENTHESE_FINALE = re.compile(r"(.+?) \(([^()]+)\)")
FIN_DE_PHRASE = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÀ-ÖØ-ÞŒ«\"(])")
LONGUEUR_MAXIMALE_PAR_PHRASES = 800  # un message de plusieurs phrases collées (« Élève inscrit. Matricule : 5. Dossier complet. »)
JETONS = re.compile(
    r"(<!--.*?-->|<script\b.*?</script\s*>|<style\b.*?</style\s*>|<textarea\b.*?</textarea\s*>|<[^>]+>)", re.S | re.I,
)
ATTRIBUTS = re.compile(
    r'(?P<debut>(?<![\w-])(?:placeholder|aria-label|title|alt|data-confirmer-bouton|data-confirmer)\s*=\s*")(?P<valeur>[^"]*)(?P<fin>")', re.I,
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
A_ISOLER = re.compile(r"[A-Za-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u024F]|(?<!\w)\+\s*\d")
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
        motifs = []
        for francais, traduction in entrees:
            cle = normaliser(francais)
            if not cle or not str(traduction).strip():
                continue
            if TROU.search(cle):
                motifs.append((len(TROU.sub("", cle)), self._motif(cle), traduction, cle))
            else:
                self.exact[cle] = traduction
        # La phrase qui contient le plus de texte fixe passe en premier : « Adresse : {0} » avant le très général « {0} : {1} ».
        motifs.sort(key=lambda motif: -motif[0])
        self.motifs = [(motif, traduction) for _, motif, traduction, _ in motifs]
        self._litteraux = {motif: cle for _, motif, _, cle in motifs}  # le texte français de chaque phrase à trous

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

    def _par_phrases(self, cle, profondeur, isoler):
        """Plusieurs phrases collées : chaque groupe de phrases connu du catalogue est traduit (le plus long d'abord), le reste est laissé tel quel."""
        phrases = FIN_DE_PHRASE.split(cle)
        if not 2 <= len(phrases) <= 12:
            return None
        morceaux, trouve, debut = [], False, 0
        while debut < len(phrases):
            for fin in range(len(phrases) if debut else len(phrases) - 1, debut, -1):
                groupe = " ".join(phrases[debut:fin])
                if fin - debut > 1:  # plusieurs phrases ensemble : seulement si le catalogue les connaît telles quelles
                    traduction = self._direct(groupe, profondeur + 1, isoler)
                else:
                    traduction = self._traduire(groupe, profondeur + 1, isoler, par_phrases=False)
                if traduction is None and fin - debut == 1 and groupe.endswith("."):  # « Dossier complet. » : le point final se remet après
                    sans_point = self._traduire(groupe[:-1], profondeur + 1, isoler, par_phrases=False)
                    traduction = f"{sans_point}." if sans_point is not None else traduction
                if traduction is not None and traduction != groupe:  # un modèle très général (« {0} : {1} ») peut rendre le texte tel quel
                    morceaux.append(traduction)
                    trouve, debut = True, fin
                    break
            else:
                morceaux.append(_isoler(phrases[debut]) if isoler else phrases[debut])
                debut += 1
        return " ".join(morceaux) if trouve else None

    def _direct(self, cle, profondeur, isoler):
        """Le texte exact du catalogue ou sa phrase à trous précise (jamais un joint général comme « {0} : {1} »), sans aucun découpage."""
        if cle in self.exact:
            return self.exact[cle]
        for motif, traduction in self.motifs:
            correspondance = motif.fullmatch(cle)
            if correspondance and len(TROU.sub("", self._litteraux[motif]).strip()) > 4:
                if any(FIN_DE_PHRASE.search(valeur) for valeur in correspondance.groupdict().values()):
                    continue  # un trou ne doit pas avaler plusieurs phrases
                return self._remplir(correspondance, traduction, profondeur, isoler)
        return None

    def _remplir(self, correspondance, traduction, profondeur, isoler):
        valeurs = {
            nom: self._traduire(normaliser(valeur), profondeur + 1, isoler) or (_isoler(valeur) if isoler else valeur)
            for nom, valeur in correspondance.groupdict().items()
        }
        return TROU.sub(lambda trou: valeurs.get(f"g{trou.group(1)}", trou.group(0)), traduction)

    def _traduire(self, cle, profondeur, isoler=False, par_phrases=True):
        if not cle:
            return None
        if cle in self.exact:
            return self.exact[cle]
        if cle[0].islower() and (avec_majuscule := cle[0].upper() + cle[1:]) in self.exact:
            return self.exact[avec_majuscule]  # « handicap moteur » (|lower dans un gabarit) : l'arabe n'a pas de majuscule
        reserve = None
        for motif, traduction in self.motifs:
            correspondance = motif.fullmatch(cle)
            if correspondance:
                # « Modifier {0} » capte aussi « Modifier un compte - École X » : si une valeur contient un séparateur absent de la phrase,
                # on découpe d'abord ; la phrase à trous ne sert qu'en dernier recours.
                litteral = self._litteraux[motif]
                if len(TROU.sub("", litteral).strip()) <= 4 and FIN_DE_PHRASE.search(cle):
                    # « {0} : {1} » est un simple joint : sur plusieurs phrases collées il ne vaut qu'en dernier recours, et jamais pour un groupe
                    # de phrases déjà examiné une à une.
                    if par_phrases:
                        reserve = reserve or (correspondance, traduction)
                    continue
                valeurs = correspondance.groupdict().values()
                if profondeur < PROFONDEUR_MAXIMALE and any(s in v and s not in litteral for s in SEPARATEURS_FORTS for v in valeurs):
                    reserve = reserve or (correspondance, traduction)
                    continue
                return self._remplir(correspondance, traduction, profondeur, isoler)
        if profondeur >= PROFONDEUR_MAXIMALE:
            return self._remplir(*reserve, profondeur, isoler) if reserve else None
        if par_phrases and len(cle) <= LONGUEUR_MAXIMALE_PAR_PHRASES:
            traduit = self._par_phrases(cle, profondeur, isoler)
            if traduit is not None:
                return traduit
        if len(cle) > LONGUEUR_MAXIMALE_DECOUPEE:
            return self._remplir(*reserve, profondeur, isoler) if reserve else None
        # « Nom (Enseignant) », « 6ème A (Mathématiques) », « handicap visuel (1). » : le mot entre parenthèses se traduit à part.
        point = "." if cle.endswith(").") else ""
        parenthese = PARENTHESE_FINALE.fullmatch(cle[:-1] if point else cle)
        # Une tête qui est déjà une phrase du catalogue (« CAP - cycle court (2 ans) (industriel) ») ne se découpe pas aux séparateurs.
        if parenthese and self._connu(parenthese.group(1)):
            traduit = self._avec_parenthese(parenthese, point, profondeur, isoler)
            if traduit is not None:
                return traduit
        for separateur in SEPARATEURS:
            if separateur in cle:
                parties = cle.split(separateur)
                traduites = [self._traduire(partie, profondeur + 1, isoler) for partie in parties]
                if any(traduite is not None for traduite in traduites):
                    return SEPARATEUR_DE_SORTIE.get(separateur, separateur).join(
                        (_isoler(partie) if isoler else partie) if traduite is None else traduite for partie, traduite in zip(parties, traduites)
                    )
        if parenthese:
            traduit = self._avec_parenthese(parenthese, point, profondeur, isoler)
            if traduit is not None:
                return traduit
        return self._remplir(*reserve, profondeur, isoler) if reserve else None

    def _connu(self, cle):
        return cle in self.exact or (cle[:1].islower() and cle[0].upper() + cle[1:] in self.exact)

    def _avec_parenthese(self, parenthese, point, profondeur, isoler):
        tete, queue = parenthese.groups()
        tete_traduite = self._traduire(tete, profondeur + 1, isoler)
        queue_traduite = self._traduire(queue, profondeur + 1, isoler)
        if tete_traduite is None and queue_traduite is None:
            return None
        tete_finale = tete_traduite if tete_traduite is not None else (_isoler(tete) if isoler else tete)
        queue_finale = queue_traduite if queue_traduite is not None else (_isoler(queue) if isoler else queue)
        return f"{tete_finale} ({queue_finale}){point}"


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


def _avec_noms_en_arabe(texte: str, catalogue: Catalogue, localisateur) -> str:
    """
    Le texte dont les noms (personnes, école, classes) sont écrits en arabe, SAUF si le texte entier est une phrase du catalogue : « Plan comptable »
    reste « Plan comptable » même si une personne s'appelle « Comptable », « Sciences Exactes (TSE) » reste le nom d'une série même si une classe
    s'appelle « TSE ».
    """
    if localisateur is None or normaliser(texte) in catalogue.exact:
        return texte
    # Un texte fait de morceaux collés (« Lycée — Sciences Exactes (TSE) — CAP - cycle court ») : chaque morceau qui est déjà une phrase du catalogue
    # est laissé tel quel, les noms ne sont remplacés que dans les autres.
    morceaux = SEPARATEURS_DE_MORCEAUX.split(texte)
    if len(morceaux) == 1:
        return localisateur.remplacer(texte)
    return "".join(
        morceau if indice % 2 or normaliser(morceau) in catalogue.exact else localisateur.remplacer(morceau) for indice, morceau in enumerate(morceaux)
    )


def _traduire_attributs(balise: str, catalogue: Catalogue, localisateur=None, chiffres=None) -> str:
    def remplacer(correspondance):
        valeur = html.unescape(correspondance.group("valeur"))
        final = _avec_noms_en_arabe(valeur, catalogue, localisateur)
        traduction = catalogue.traduire(final)
        if traduction is not None:
            final = traduction
        if chiffres:
            final = chiffres(final)
        if final == valeur:
            return correspondance.group(0)
        return f"{correspondance.group('debut')}{html.escape(final, quote=True)}{correspondance.group('fin')}"

    balise = ATTRIBUTS.sub(remplacer, balise)
    if re.match(r"<(?:input|button)\b", balise, re.I) and TYPE_BOUTON.search(balise):
        balise = VALEUR_BOUTON.sub(remplacer, balise)
    return balise


def _traduire_texte(texte: str, catalogue: Catalogue, brut: bool = False, localisateur=None, chiffres=None) -> str:
    correspondance = re.fullmatch(r"(\s*)(.*?)(\s*)", texte, re.S)
    gauche, noyau, droite = correspondance.groups()
    if not noyau:
        return texte
    source = html.unescape(noyau)
    original = _avec_noms_en_arabe(source, catalogue, localisateur)  # noms de personnes, d'école et de classes -> arabe
    traduction = catalogue.traduire(original, isoler=True)
    if traduction is not None:
        final = traduction
    else:
        debut, milieu, fin = ENTOURAGE.fullmatch(original).groups()  # ponctuation de bord : elle reste hors de l'isolat
        final = original
        traduit_au_centre = catalogue.traduire(milieu, isoler=True) if milieu and (debut.strip() or fin.strip()) else None
        if traduit_au_centre is not None:  # « Libellé: » (deux-points collé par Django), « Aucun élève. » : le texte du centre est au catalogue
            final = f"{debut}{traduit_au_centre}{fin}"
        elif A_ISOLER.search(milieu):
            final = f"{debut}{_isoler(milieu)}{fin}"
    if chiffres:
        final = chiffres(final)
    if final == source:
        return texte  # rien n'a changé : la page garde exactement son texte d'origine
    return f"{gauche}{_en_balises(html.escape(final, quote=False), brut)}{droite}"


def traduire_html(contenu: str, catalogue: Catalogue, localisateur=None, chiffres=None) -> str:
    """
    Le HTML d'une page avec ses textes et ses attributs lisibles traduits ; tout le reste est rendu à l'identique.
    `localisateur` remplace les noms de l'école par leur écriture arabe, `chiffres` convertit les chiffres (voir comptes.arabisation).
    """
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
            sortie.append(_traduire_texte(
                morceau, catalogue, brut=dans_svg > 0 or precedente in BALISES_DE_TEXTE_BRUT, localisateur=localisateur, chiffres=chiffres,
            ))
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
            sortie.append(_traduire_attributs(ouverture, catalogue, localisateur, chiffres) + ">" + reste)
        elif morceau.startswith("</"):
            sortie.append(morceau)
        else:
            sortie.append(_traduire_attributs(morceau, catalogue, localisateur, chiffres))
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


ADRESSES = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|https?://\S+|www\.\S+")
LETTRE_OU_CHIFFRE_LATIN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ɏ0-9]")  # sans les signes × et ÷


def restes_latins(contenu: str):
    """Les textes d'une page déjà en arabe qui contiennent encore une lettre latine ou un chiffre occidental (les adresses email et les liens exceptés)."""
    return [texte for texte in textes_de_la_page(contenu) if LETTRE_OU_CHIFFRE_LATIN.search(ADRESSES.sub("", texte))]
