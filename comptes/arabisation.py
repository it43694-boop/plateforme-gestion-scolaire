"""
Arabe « pur » : chiffres arabes et données de l'école (noms de personnes, nom de l'école, classes) écrits en lettres arabes.

Quand la langue est l'arabe, la page produite ne doit contenir ni lettre latine ni chiffre occidental. Le catalogue (comptes/traduction.py) traduit
les textes de l'application ; ce module s'occupe de ce qui vient des DONNÉES de l'école :

- les chiffres : 0123456789 -> ٠١٢٣٤٥٦٧٨٩, virgule décimale -> ٫, % -> ٪ ;
- les noms : chaque prénom et nom de la base est remplacé par son écriture arabe, saisie par l'école (champs prenom_ar / nom_ar) ou, à défaut,
  proposée par comptes.transcription ; de même le nom de l'école, sa devise et les noms de classes.

Le remplacement se fait au moment de l'affichage, dans les textes de la page (jamais dans les adresses, les courriels, les valeurs de champs
de saisie, les scripts) : rien n'est modifié dans la base.
"""
import re
import time

from django.core.cache import cache

from comptes.transcription import MOT, cle, transcrire

VERS_ARABE = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
VERS_ASCII = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
CHIFFRE_ARABE = "٠-٩"
DUREE_CACHE = 600

ANALYSE = re.compile(
    r"(?P<protege>[\w.+-]+@[\w-]+(?:\.[\w-]+)+|https?://\S+|www\.\S+)|(?P<mot>[^\W_]+(?:['’][^\W_]+)*)",
)


def chiffres_arabes(texte: str) -> str:
    """Chiffres arabes (٠١٢...), virgule décimale arabe (٫) et signe pour cent arabe (٪)."""
    if not texte:
        return texte
    texte = texte.translate(VERS_ARABE)
    texte = re.sub(rf"(?<=[{CHIFFRE_ARABE}]),(?=[{CHIFFRE_ARABE}])", "٫", texte)
    return re.sub(rf"(?<=[{CHIFFRE_ARABE}])\s?%", "٪", texte)


# Mots latins qui peuvent rester dans un texte traduit ou saisi (sigles, formats de fichier, monnaie) -> leur écriture arabe.
LEXIQUE = {
    "FCFA": "فرنك سيفا", "CFA": "سيفا", "EUR": "يورو", "USD": "دولار", "Excel": "إكسل", "PDF": "بي دي إف", "CSV": "سي إس في",
    "ZIP": "زيب", "zip": "زيب", "xlsx": "إكسل", "SYSCOHADA": "سيسكوهادا", "OHADA": "أوهادا", "WhatsApp": "واتساب", "SMS": "رسالة نصية",
    "QR": "كيو آر", "Yelenova": "يلينوفا", "YELENOVA": "يلينوفا", "JPEG": "جي بي إي جي", "PNG": "بي إن جي", "WebP": "ويب بي",
}
LEXIQUE_ARABE = re.compile(r"(?<![\w@])\.?(" + "|".join(re.escape(m) for m in sorted(LEXIQUE, key=len, reverse=True)) + r")(?![\w@])")
# Préfixes des numéros (reçu REC-2026-000057, caisse CAI-..., banque BQ-..., salaire SAL-..., abonnement ABO-..., cantine CAN-..., tenues TEN-...) : un mot arabe devant les chiffres.
PREFIXES_DE_REFERENCE = {
    "REC": "إيصال", "CAI": "صندوق", "BQ": "بنك", "OD": "عمليات", "AN": "ترحيل", "SAL": "راتب", "ABO": "اشتراك", "CAN": "مطعم", "TEN": "زي",
}
REFERENCE = re.compile(r"(?<![\w])(" + "|".join(PREFIXES_DE_REFERENCE) + r")-(?=\d)")

# Dates écrites par Django (« 17 octobre 2026 », « 17 oct. 2026 », « lundi ») ou saisies par l'école : mois et jours en arabe.
MOIS = {
    "janvier": "يناير", "février": "فبراير", "mars": "مارس", "avril": "أبريل", "mai": "مايو", "juin": "يونيو", "juillet": "يوليو",
    "août": "أغسطس", "septembre": "سبتمبر", "octobre": "أكتوبر", "novembre": "نوفمبر", "décembre": "ديسمبر",
}
MOIS_ABREGES = {
    "janv": "يناير", "févr": "فبراير", "avr": "أبريل", "juil": "يوليو", "sept": "سبتمبر", "oct": "أكتوبر", "nov": "نوفمبر", "déc": "ديسمبر",
}
JOURS = {
    "lundi": "الاثنين", "mardi": "الثلاثاء", "mercredi": "الأربعاء", "jeudi": "الخميس", "vendredi": "الجمعة", "samedi": "السبت", "dimanche": "الأحد",
}
JOURS_ABREGES = {"lun": "الاثنين", "mar": "الثلاثاء", "mer": "الأربعاء", "jeu": "الخميس", "ven": "الجمعة", "sam": "السبت", "dim": "الأحد"}
NOMS_DE_DATES = re.compile(r"(?<![\w@])(" + "|".join(sorted({**MOIS, **JOURS}, key=len, reverse=True)) + r")(?![\w@])", re.I)
ABREVIATIONS_DE_DATES = re.compile(
    r"(?<![\w@])(" + "|".join(sorted({**MOIS_ABREGES, **JOURS_ABREGES}, key=len, reverse=True)) + r")\.(?![\w@])", re.I,
)
HEURE = re.compile(r"(?<![\w:])(\d{1,2}) ?h(?: ?(\d{2}))?(?![\w])")
DATE_ET_HEURE = re.compile(r"(?<=\d) à (?=\d)")


def _nom_de_date(nom: str) -> str:
    nom = nom.lower()
    return MOIS.get(nom) or JOURS.get(nom) or MOIS_ABREGES.get(nom) or JOURS_ABREGES[nom]


# Ce qui se recopie ou se tape tel quel ne change jamais : adresses de pages, courriels, identifiants de vérification d'un document.
PROTEGES = re.compile(
    r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|https?://\S+|www\.\S+|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


def finaliser_arabe(texte: str) -> str:
    """Dernière étape d'un texte arabe : numéros de référence, mots latins courants, mois et jours en arabe, puis chiffres arabes."""
    if not texte:
        return texte
    protegees = PROTEGES.findall(texte)
    if not protegees:
        return _finaliser_morceau(texte)
    morceaux = PROTEGES.split(texte)
    return "".join(_finaliser_morceau(morceau) + (protegees[i] if i < len(protegees) else "") for i, morceau in enumerate(morceaux))


def _finaliser_morceau(texte: str) -> str:
    if not texte:
        return texte
    texte = REFERENCE.sub(lambda m: PREFIXES_DE_REFERENCE[m.group(1)] + "-", texte)
    texte = LEXIQUE_ARABE.sub(lambda m: LEXIQUE[m.group(1)], texte)
    texte = NOMS_DE_DATES.sub(lambda m: _nom_de_date(m.group(1)), texte)
    texte = ABREVIATIONS_DE_DATES.sub(lambda m: _nom_de_date(m.group(1)), texte)
    texte = HEURE.sub(lambda m: f"{m.group(1)}:{m.group(2) or '00'}", texte)
    texte = DATE_ET_HEURE.sub(" الساعة ", texte)  # « 20/10/2026 à 15:54 »
    return chiffres_arabes(texte)


def chiffres_ascii(texte: str) -> str:
    """Ce qu'on tape avec des chiffres arabes (٠١٢...) est rendu en 0123... pour que les champs, les recherches et les matricules les comprennent."""
    return texte.translate(VERS_ASCII) if isinstance(texte, str) else texte


class Localisateur:
    """Remplace, dans un texte, les noms connus (personnes, école, classes) par leur écriture arabe."""

    def __init__(self, cles: dict, formes=()):
        self.cles = cles
        self.formes = set(formes)  # écritures exactes de la base : un nom saisi en minuscules (« keita ») est reconnu tel quel
        self.max_mots = max((c.count(" ") + 1 for c in cles), default=1)

    def __bool__(self):
        return bool(self.cles)

    def remplacer(self, texte: str) -> str:
        if not self.cles or not texte or not re.search(r"[^\W\d_]|\d[^\W\d_]", texte):
            return texte
        mots = [m for m in ANALYSE.finditer(texte) if m.group("mot")]
        if not mots:
            return texte
        sortie, position, i = [], 0, 0
        while i < len(mots):
            remplace = False
            for longueur in range(min(self.max_mots, len(mots) - i), 0, -1):
                groupe = mots[i:i + longueur]
                # un groupe de mots = des mots séparés par une seule espace (ordinaire ou insécable) ou un trait d'union
                if any(texte[a.end():b.start()] not in (" ", " ", "-") for a, b in zip(groupe, groupe[1:])):
                    continue
                premier = groupe[0].group()
                # un nom propre commence et finit par un mot à majuscule (ou un chiffre pour une classe) : « bien » n'est pas « Bien », « 7ème à »
                # n'est pas « 7ème A » ; les mots du milieu peuvent être en minuscules (« Groupe Scolaire Les Étoiles de Bamako »).
                if not all(m.group()[0].isupper() or m.group()[0].isdigit() or m.group() in self.formes for m in (groupe[0], groupe[-1])):
                    continue
                if longueur == 1 and len(cle(premier)) < 2:
                    continue
                traduction = self.cles.get(" ".join(cle(m.group()) for m in groupe))
                if traduction:
                    sortie.append(texte[position:groupe[0].start()])
                    sortie.append(traduction)
                    position = groupe[-1].end()
                    i += longueur
                    remplace = True
                    break
            if not remplace:
                i += 1
        sortie.append(texte[position:])
        return "".join(sortie)


# --- l'index des noms de l'école ----------------------------------------------------------------------------------------------

ORDINAUX = (
    "الأولى", "الثانية", "الثالثة", "الرابعة", "الخامسة", "السادسة", "السابعة", "الثامنة", "التاسعة", "العاشرة", "الحادية عشرة", "الثانية عشرة",
)
LETTRES_DE_CLASSE = {"A": "أ", "B": "ب", "C": "ج", "D": "د", "E": "هـ", "F": "و"}
SERIES = {
    "TSE": "العلوم الدقيقة", "TSEXP": "العلوم التجريبية", "TSECO": "العلوم الاقتصادية", "TLL": "الآداب واللغات", "TAL": "الآداب واللغات",
}
MOTS_DE_CLASSE = re.compile(
    r"^(?P<n>\d{1,2})\s?(?:ème|eme|ère|ere|e|è|°)?\s?(?:année|annee)?\s?(?P<lettre>[A-Fa-f])?$", re.IGNORECASE,
)
MOTS_D_ECOLE = {
    "groupe scolaire": "المجموعة المدرسية", "complexe scolaire": "المجمع المدرسي", "ecole": "مدرسة", "college": "إعدادية", "lycee": "ثانوية",
    "institut": "معهد", "centre": "مركز", "medersa": "مدرسة", "franco": "فرنسية", "arabe": "عربية", "prive": "الخاصة", "privee": "الخاصة",
    "moderne": "الحديثة", "etoiles": "نجوم", "horizon": "الأفق", "avenir": "المستقبل", "excellence": "التميز", "savoir": "العلم",
    "discipline": "الانضباط", "reussite": "النجاح", "saint": "القديس", "al": "ال", "nouvelle": "الجديدة", "universel": "العالمية",
    "bamako": "باماكو", "segou": "سيغو", "kayes": "كايس", "sikasso": "سيكاسو", "mopti": "موبتي", "koulikoro": "كوليكورو", "kati": "كاتي",
    "tombouctou": "تمبكتو", "gao": "غاو", "kidal": "كيدال", "koutiala": "كوتيالا", "djenne": "جني", "kita": "كيتا", "san": "سان",
}
MOTS_VIDES = {"de", "du", "des", "la", "le", "les", "d", "l", "et", "a"}


def nom_de_classe_arabe(nom: str) -> str:
    """« 6ème A » -> « السنة السادسة أ », « Terminale TSE » -> « السنة النهائية العلوم الدقيقة » ; vide si le nom n'a pas une forme connue."""
    nom = (nom or "").strip()
    correspondance = MOTS_DE_CLASSE.match(nom)
    if correspondance:
        rang = int(correspondance.group("n"))
        if 1 <= rang <= len(ORDINAUX):
            lettre = LETTRES_DE_CLASSE.get((correspondance.group("lettre") or "").upper(), "")
            return f"السنة {ORDINAUX[rang - 1]}" + (f" {lettre}" if lettre else "")
    mots = nom.split()
    if mots and cle(mots[0]) == "terminale":
        reste = " ".join(SERIES.get(m.upper(), m) for m in mots[1:])
        return "السنة النهائية" + (f" {reste}" if reste else "")
    return ""


def nom_d_ecole_arabe(nom: str) -> str:
    """Proposition pour le nom d'une école (mots courants traduits, noms de lieux et mots inconnus transcrits) ; l'école saisit le sien."""
    mots = [m for m in re.split(r"[\s'’]+", (nom or "").strip()) if m]
    resultat, i = [], 0
    while i < len(mots):
        deux = cle(" ".join(mots[i:i + 2]))
        if deux in MOTS_D_ECOLE:
            resultat.append(MOTS_D_ECOLE[deux])
            i += 2
            continue
        mot = cle(mots[i])
        if mot in MOTS_VIDES and i > 0:
            i += 1
            continue
        resultat.append(MOTS_D_ECOLE.get(mot) or transcrire(mots[i]))
        i += 1
    return " ".join(resultat)


MOTS_DE_MARQUE = {"yelenova", "education"}  # le nom de la plateforme (« YELENOVA ») est traduit par le catalogue, jamais pris pour un nom de personne


def _ajouter(index: dict, latin, arabe, *, saisi: bool):
    """Un nom de plus dans l'index : l'écriture saisie par l'école passe avant la transcription automatique."""
    cles = index["cles"]
    latin = " ".join(str(latin or "").split())
    if not latin:
        return
    texte_arabe = (arabe or "").strip() or (transcrire(latin) if not saisi else "")
    if not texte_arabe:
        return
    clef = " ".join(cle(mot) for mot in MOT.findall(latin))  # « Jean-Pierre » et « Jean Pierre » : même clé
    if len(clef) < 2 or clef in MOTS_DE_MARQUE:
        return
    index["formes"].update(MOT.findall(latin))
    if saisi or clef not in cles:
        cles[clef] = texte_arabe


def construire_index(etablissement_id) -> dict:
    """
    Index des noms : {"cles": {nom latin sans accents ni majuscules: nom arabe}, "formes": {écritures exactes de la base}} pour les personnes,
    l'école et les classes de l'établissement (ou de toute la plateforme).
    """
    from django.db.models import Q

    from comptes.models import Utilisateur
    from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL
    from etablissement.models import Etablissement
    from scolarite.models import Classe

    cles: dict = {"cles": {}, "formes": set()}
    ecoles = Etablissement.objects.all() if etablissement_id in (None, "public") else Etablissement.objects.filter(pk=etablissement_id)
    for nom, nom_ar, devise, devise_ar in ecoles.values_list("nom", "nom_ar", "devise", "devise_ar"):
        _ajouter(cles, nom, nom_ar or nom_d_ecole_arabe(nom), saisi=bool(nom_ar))
        _ajouter(cles, devise, devise_ar or nom_d_ecole_arabe(devise), saisi=bool(devise_ar))
    if etablissement_id == "public":
        # Les classes qu'une campagne de pré-inscription ouverte propose aux visiteurs : leurs noms s'écrivent sur une page publique.
        for nom, nom_ar in Classe.objects.filter(annee_scolaire__campagnes_preinscription__active=True).values_list("nom", "nom_ar").distinct():
            _ajouter(cles, nom, nom_ar or nom_de_classe_arabe(nom), saisi=bool(nom_ar))
        return cles
    if etablissement_id is None:
        # Le propriétaire de la plateforme voit les comptes de toutes les écoles (liste des comptes d'un établissement) et ses propres comptes.
        personnes = Utilisateur.objects.filter(
            Q(etablissement__isnull=False) | Q(role__in=[r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL])
        )
        classes = Classe.objects.all()
    else:
        personnes = Utilisateur.objects.filter(etablissement_id=etablissement_id)
        classes = Classe.objects.filter(annee_scolaire__etablissement_id=etablissement_id)
    for nom, nom_ar in classes.values_list("nom", "nom_ar").distinct():
        _ajouter(cles, nom, nom_ar or nom_de_classe_arabe(nom), saisi=bool(nom_ar))
    for prenom, nom, prenom_ar, nom_ar in personnes.values_list("prenom", "nom", "prenom_ar", "nom_ar"):
        _ajouter(cles, prenom, prenom_ar, saisi=bool(prenom_ar))
        _ajouter(cles, nom, nom_ar, saisi=bool(nom_ar))
    # Père, mère et personne à prévenir d'un élève : des noms de personnes sans compte, mot par mot (le nom de famille déjà saisi en arabe garde le dessus).
    # Lieux de naissance et écoles d'origine ou de destination saisis en lettres latines : un nom de lieu se transcrit, un nom d'école se
    # traduit mot à mot (« Lycée » -> الثانوية) puis se transcrit. L'adresse, libre, reste telle que saisie.
    from scolarite.models import TransfertEleve

    for lieu in personnes.exclude(lieu_naissance="").values_list("lieu_naissance", flat=True).distinct():
        _ajouter(cles, lieu, None, saisi=False)
    destinations = TransfertEleve.objects.exclude(destination_libelle="")
    if etablissement_id is not None:
        destinations = destinations.filter(inscription__classe__annee_scolaire__etablissement_id=etablissement_id)
    ecoles_citees = list(personnes.exclude(ecole_origine="").values_list("ecole_origine", flat=True).distinct())
    ecoles_citees += list(destinations.values_list("destination_libelle", flat=True).distinct())
    for nom_ecole in ecoles_citees:
        _ajouter(cles, nom_ecole, nom_d_ecole_arabe(nom_ecole), saisi=False)
    for nom_signataire in ecoles.exclude(nom_signataire="").values_list("nom_signataire", flat=True):
        for mot in MOT.findall(nom_signataire):
            _ajouter(cles, mot, None, saisi=False)
    for noms in personnes.exclude(nom_pere="", nom_mere="", contact_urgence_nom="").values_list("nom_pere", "nom_mere", "contact_urgence_nom").distinct():
        for nom_complet in noms:
            for mot in MOT.findall(nom_complet or ""):
                _ajouter(cles, mot, None, saisi=False)
    # Personnes qui n'ont pas (encore) de compte : candidats aux tests de niveau et parents annoncés à l'inscription d'un élève.
    # Aucune écriture saisie pour eux : la transcription automatique sert, et le nom d'une personne qui a un compte garde le dessus.
    from scolarite.models import ParentEnAttente
    from tests_niveau.models import Candidat

    if etablissement_id is None:
        candidats, parents = Candidat.objects.all(), ParentEnAttente.objects.all()
    else:
        candidats = Candidat.objects.filter(classe_visee__annee_scolaire__etablissement_id=etablissement_id)
        parents = ParentEnAttente.objects.filter(eleve__etablissement_id=etablissement_id)
    for modele in (candidats, parents):
        for prenom, nom in modele.values_list("prenom", "nom").distinct():
            _ajouter(cles, prenom, None, saisi=False)
            _ajouter(cles, nom, None, saisi=False)
    return cles


def _cle_version(identifiant) -> str:
    return f"arabisation:version:{identifiant}"


def invalider(identifiant=None):
    """À appeler quand un nom change : l'index de l'école (et celui de la plateforme) est reconstruit à la prochaine page."""
    for cible in {identifiant, None, "public"}:
        cache.set(_cle_version(cible), time.time_ns(), None)


def index_pour(identifiant) -> dict:
    version = cache.get(_cle_version(identifiant), 0)
    cle_cache = f"arabisation:index:{identifiant}:{version}"
    index = cache.get(cle_cache)
    if index is None:
        index = construire_index(identifiant)
        cache.set(cle_cache, index, DUREE_CACHE)
    return index


def localisateur_pour(request) -> Localisateur:
    """Le localisateur de la requête : celui de l'école du compte connecté, de la plateforme (propriétaire) ou des écoles publiques (visiteur)."""
    utilisateur = getattr(request, "user", None)
    if utilisateur is not None and getattr(utilisateur, "is_authenticated", False):
        identifiant = getattr(utilisateur, "etablissement_id", None)
    else:
        identifiant = "public"
    index = index_pour(identifiant)
    return Localisateur(index["cles"], index["formes"])


def arabe_de(prenom, prenom_ar="") -> str:
    """L'écriture arabe d'un prénom ou d'un nom : celle saisie, sinon la proposition automatique."""
    return (prenom_ar or "").strip() or transcrire(prenom or "")
