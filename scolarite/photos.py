"""
Photos d'élèves : préparation d'une image (redressée, réduite, en JPEG) et import d'une archive ZIP pour toute une classe.

Une photo d'enfant est une donnée sensible : elle n'est jamais enregistrée telle qu'elle arrive. Chaque image est ouverte et vérifiée avec Pillow
(un fichier qui n'est pas une vraie image est refusé, quelle que soit son extension), redressée selon l'orientation de l'appareil, réduite à
480 pixels au plus et réécrite en JPEG : les informations cachées dans le fichier d'origine (lieu, appareil, date) disparaissent.
"""
import base64
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

from comptes.models import Utilisateur
from comptes.roles import Role
from scolarite.models import Inscription

COTE_MAXIMAL = 480
QUALITE_JPEG = 85
FORMATS_ACCEPTES = {"JPEG", "PNG", "WEBP", "MPO"}  # MPO : photo de téléphone (JPEG à plusieurs images)
EXTENSIONS_IMAGE = (".jpg", ".jpeg", ".png", ".webp")
PIXELS_MAXIMAUX = 40_000_000  # refuse une « bombe de décompression » : petit fichier, image gigantesque
LIMITE_FICHIERS_ARCHIVE = 120  # une classe à la fois : le traitement doit tenir dans le délai d'une requête
LIMITE_TAILLE_PHOTO = 10 * 1024 * 1024
LIMITE_TAILLE_ARCHIVE_DECOMPRESSEE = 200 * 1024 * 1024
MESSAGE_IMAGE_INVALIDE = "Cette image est illisible ou son format n'est pas accepté (JPEG, PNG ou WebP)."


def preparer_photo(contenu: bytes) -> ContentFile:
    """L'image du fichier, redressée, réduite et réécrite en JPEG ; ValidationError si ce n'est pas une image acceptable."""
    if not contenu or len(contenu) > LIMITE_TAILLE_PHOTO:
        raise ValidationError("L'image dépasse la taille maximale autorisée (10 Mo).")
    try:
        image = Image.open(io.BytesIO(contenu))
        if image.format not in FORMATS_ACCEPTES:
            raise ValidationError(MESSAGE_IMAGE_INVALIDE)
        if image.width * image.height > PIXELS_MAXIMAUX:
            raise ValidationError("Cette image est trop grande (plus de 40 millions de pixels).")
        if image.format == "JPEG":
            image.draft("RGB", (COTE_MAXIMAL * 2, COTE_MAXIMAL * 2))  # décodage à taille réduite : beaucoup plus rapide pour une photo de téléphone
        image.load()
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as erreur:
        raise ValidationError(MESSAGE_IMAGE_INVALIDE) from erreur
    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA", "P"):
        fond = Image.new("RGB", image.size, (255, 255, 255))  # une transparence devient du blanc
        image = image.convert("RGBA")
        fond.paste(image, mask=image.split()[-1])
        image = fond
    else:
        image = image.convert("RGB")
    image.thumbnail((COTE_MAXIMAL, COTE_MAXIMAL))
    sortie = io.BytesIO()
    image.save(sortie, format="JPEG", quality=QUALITE_JPEG, optimize=True)  # aucune métadonnée d'origine n'est recopiée
    return ContentFile(sortie.getvalue())


def enregistrer_photo(eleve, contenu: bytes) -> None:
    """Remplace la photo de l'élève (l'ancienne est supprimée du stockage une fois la nouvelle écrite)."""
    nouveau = preparer_photo(contenu)
    ancienne = eleve.photo.name if eleve.photo else ""
    eleve.photo.save("photo.jpg", nouveau, save=False)  # nom neutre : ni le matricule ni le nom de l'enfant dans l'adresse de stockage
    eleve.save(update_fields=["photo"])
    if ancienne and ancienne != eleve.photo.name:
        eleve.photo.storage.delete(ancienne)


def supprimer_photo(eleve) -> bool:
    if not eleve.photo:
        return False
    eleve.photo.delete(save=False)
    eleve.photo = None
    eleve.save(update_fields=["photo"])
    return True


def photo_en_donnees(eleve) -> str:
    """La photo en adresse « data: » à mettre dans un PDF (le générateur de PDF ne va pas chercher d'adresse externe) ; vide s'il n'y en a pas."""
    if not eleve.photo:
        return ""
    try:
        with eleve.photo.open("rb") as fichier:
            return "data:image/jpeg;base64," + base64.b64encode(fichier.read()).decode("ascii")
    except (OSError, ValueError):
        return ""  # fichier absent du stockage : la carte s'imprime sans photo plutôt que d'échouer


# ---------------------------------------------------------------------------
# Import d'une archive ZIP : un fichier par élève, nommé par son matricule ou par son nom
# ---------------------------------------------------------------------------

def normaliser_nom(texte: str) -> str:
    """Minuscules, sans accent, séparateurs ramenés à une espace : « Traoré_Aminata.JPG » et « aminata traore » se rejoignent."""
    sans_accent = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", sans_accent.lower()).split())


@dataclass
class BilanImportPhotos:
    importees: list = field(default_factory=list)  # (élève, nom du fichier)
    ignorees: list = field(default_factory=list)  # (nom du fichier, raison)

    @property
    def total(self):
        return len(self.importees) + len(self.ignorees)


def eleves_de_la_classe(classe):
    return list(
        Utilisateur.objects.filter(
            role=Role.ELEVE, inscriptions__classe=classe, inscriptions__statut=Inscription.Statut.EN_COURS,
        ).distinct()
    )


def _index_des_eleves(eleves):
    """Clés de recherche d'un fichier : le matricule, puis « prénom nom » et « nom prénom » (sans accent, sans casse)."""
    par_matricule, par_nom = {}, {}
    for eleve in eleves:
        par_matricule[normaliser_nom(eleve.matricule or "")] = eleve
        for cle in (f"{eleve.prenom} {eleve.nom}", f"{eleve.nom} {eleve.prenom}"):
            par_nom.setdefault(normaliser_nom(cle), []).append(eleve)
    return par_matricule, par_nom


def importer_archive(classe, archive) -> BilanImportPhotos:
    """
    Enregistre chaque photo d'une archive ZIP pour l'élève de la classe qu'elle désigne. Le rapport dit ce qui a été importé et pourquoi
    le reste ne l'a pas été. L'archive n'est jamais décompressée sur le disque (aucun chemin de fichier n'est suivi).
    Lève ValidationError si l'archive elle-même est refusée (illisible, trop de fichiers, trop volumineuse).
    """
    try:
        zip_ = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError, ValueError) as erreur:
        raise ValidationError("Ce fichier n'est pas une archive ZIP valide.") from erreur
    with zip_:
        entrees = [entree for entree in zip_.infolist() if not entree.is_dir()]
        if len(entrees) > LIMITE_FICHIERS_ARCHIVE:
            raise ValidationError(f"L'archive contient trop de fichiers (plus de {LIMITE_FICHIERS_ARCHIVE}).")
        if sum(entree.file_size for entree in entrees) > LIMITE_TAILLE_ARCHIVE_DECOMPRESSEE:
            raise ValidationError("L'archive est trop volumineuse une fois décompressée (plus de 200 Mo).")
        par_matricule, par_nom = _index_des_eleves(eleves_de_la_classe(classe))
        bilan = BilanImportPhotos()
        deja_pris = set()
        for entree in entrees:
            nom_complet = entree.filename.replace("\\", "/")
            nom = nom_complet.rsplit("/", 1)[-1]
            if nom.startswith(".") or nom_complet.startswith("__MACOSX/") or not nom.lower().endswith(EXTENSIONS_IMAGE):
                continue  # fichiers cachés ou étrangers (métadonnées de Mac, Thumbs.db...) : on les passe sans bruit
            cle = normaliser_nom(nom.rsplit(".", 1)[0])
            eleve = par_matricule.get(cle)
            if eleve is None:
                candidats = par_nom.get(cle, [])
                if len(candidats) > 1:
                    bilan.ignorees.append((nom, "Plusieurs élèves portent ce nom : nommez la photo avec le matricule."))
                    continue
                eleve = candidats[0] if candidats else None
            if eleve is None:
                bilan.ignorees.append((nom, "Aucun élève de cette classe ne correspond à ce nom de fichier."))
                continue
            if eleve.pk in deja_pris:
                bilan.ignorees.append((nom, "Cet élève a déjà une photo dans cette archive."))
                continue
            if entree.file_size > LIMITE_TAILLE_PHOTO:
                bilan.ignorees.append((nom, "L'image dépasse la taille maximale autorisée (10 Mo)."))
                continue
            try:
                enregistrer_photo(eleve, zip_.read(entree))
            except (ValidationError, zipfile.BadZipFile, OSError, RuntimeError):
                bilan.ignorees.append((nom, MESSAGE_IMAGE_INVALIDE))
                continue
            deja_pris.add(eleve.pk)
            bilan.importees.append((eleve, nom))
    return bilan
