import re
import zipfile

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


class ComplexiteMotDePasseValidator:
    """
    Exige au moins une majuscule, un chiffre et un caractère spécial,
    en complément des validateurs standards de Django (longueur, similarité
    avec l'utilisateur, mots de passe courants, mot de passe entièrement
    numérique).
    """

    MAJUSCULE = re.compile(r"[A-ZÀÂÄÉÈÊËÎÏÔÖÙÛÜŸÇ]")
    CHIFFRE = re.compile(r"[0-9]")
    SPECIAL = re.compile(r"[^A-Za-zÀ-ÿ0-9]")

    def validate(self, password, user=None):
        erreurs = []
        if not self.MAJUSCULE.search(password):
            erreurs.append(_("Le mot de passe doit contenir au moins une lettre majuscule."))
        if not self.CHIFFRE.search(password):
            erreurs.append(_("Le mot de passe doit contenir au moins un chiffre."))
        if not self.SPECIAL.search(password):
            erreurs.append(_("Le mot de passe doit contenir au moins un caractère spécial."))
        if erreurs:
            raise ValidationError(erreurs)

    def get_help_text(self):
        return _(
            "Votre mot de passe doit contenir au moins 10 caractères, "
            "dont une majuscule, un chiffre et un caractère spécial."
        )


def valider_taille_fichier_10mo(fichier):
    limite = 10 * 1024 * 1024
    if fichier.size > limite:
        raise ValidationError("Le fichier dépasse la taille maximale autorisée (10 Mo).")


def valider_taille_image_2mo(fichier):
    limite = 2 * 1024 * 1024
    if fichier.size > limite:
        raise ValidationError("L'image dépasse la taille maximale autorisée (2 Mo).")


EXTENSIONS_DOCUMENT_AUTORISEES = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".csv", ".jpg", ".jpeg", ".png", ".zip",
}


def valider_extension_document(fichier):
    """
    Empêche l'upload de types de fichiers dangereux (exécutables, scripts)
    déguisés en documents. Vérifie l'extension déclarée ; combinée à la
    limite de taille déjà en place, réduit la surface d'attaque des
    uploads sans bloquer les usages légitimes d'une bibliothèque scolaire.
    """
    nom = fichier.name.lower()
    if not any(nom.endswith(extension) for extension in EXTENSIONS_DOCUMENT_AUTORISEES):
        raise ValidationError(
            "Type de fichier non autorisé. Formats acceptés : "
            + ", ".join(sorted(EXTENSIONS_DOCUMENT_AUTORISEES))
        )


def valider_contenu_fichier(fichier):
    """Vérifie une signature minimale avant d'accepter un fichier uploadé."""
    if settings.DEBUG or getattr(fichier, "content_type", None) in {None, "application/octet-stream"}:
        return
    nom = fichier.name.lower()
    position = fichier.tell()
    try:
        debut = fichier.read(16)
        fichier.seek(0)
        if nom.endswith(".pdf") and not debut.startswith(b"%PDF-"):
            raise ValidationError("Le contenu du fichier PDF est invalide.")
        if nom.endswith((".jpg", ".jpeg")) and not debut.startswith(b"\xff\xd8\xff"):
            raise ValidationError("Le contenu de l'image JPEG est invalide.")
        if nom.endswith(".png") and not debut.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValidationError("Le contenu de l'image PNG est invalide.")
        if nom.endswith((".docx", ".xlsx", ".pptx", ".zip")):
            fichier.seek(0)
            if not zipfile.is_zipfile(fichier):
                raise ValidationError("Le contenu de l'archive est invalide.")
    finally:
        fichier.seek(position)
