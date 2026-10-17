"""
Documents officiels d'un élève : certificat de scolarité, attestation de fréquentation, certificat de radiation.

Chaque document porte un numéro d'ordre « 003/SIGLE/CERT/2026 » : un compteur par école, par type et par année (jamais deux fois le même
numéro, même avec deux émissions simultanées), attribué à la PREMIÈRE émission. Éditer de nouveau le même document pour la même inscription
redonne le même numéro et le même QR code de vérification.
"""
import base64
import io
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from finances.models import SequenceReference
from scolarite.models import Inscription, TypeDocumentVerifiable, VerificationDocument


@dataclass(frozen=True)
class TypeDeDocument:
    code: str  # dans l'adresse de la page
    type_verifiable: str
    abreviation: str  # dans le numéro : CERT, ATTEST, RAD
    titre: str


TYPES = {
    "certificat-scolarite": TypeDeDocument("certificat-scolarite", TypeDocumentVerifiable.CERTIFICAT_SCOLARITE, "CERT", "Certificat de scolarité"),
    "attestation-frequentation": TypeDeDocument(
        "attestation-frequentation", TypeDocumentVerifiable.ATTESTATION_FREQUENTATION, "ATTEST", "Attestation de fréquentation",
    ),
    "certificat-radiation": TypeDeDocument("certificat-radiation", TypeDocumentVerifiable.CERTIFICAT_RADIATION, "RAD", "Certificat de radiation"),
}
STATUTS_RADIES = (Inscription.Statut.TRANSFERE, Inscription.Statut.ABANDON)
STATUTS_SCOLARISES = (Inscription.Statut.EN_COURS, Inscription.Statut.ADMIS, Inscription.Statut.REDOUBLE)


def inscription_concernee(eleve, type_document: TypeDeDocument):
    """
    L'inscription que le document atteste, ou None s'il n'y en a pas :
    - fréquentation : l'inscription en cours ;
    - scolarité : l'inscription en cours, sinon la plus récente menée à son terme (admis, redoublement) ;
    - radiation : la plus récente inscription close par un transfert ou un abandon.
    """
    inscriptions = Inscription.objects.filter(eleve=eleve).select_related(
        "classe__annee_scolaire__etablissement", "eleve",
    ).order_by("-classe__annee_scolaire__date_debut", "-pk")
    if type_document.abreviation == "RAD":
        return inscriptions.filter(statut__in=STATUTS_RADIES).first()
    en_cours = inscriptions.filter(statut=Inscription.Statut.EN_COURS).first()
    if en_cours or type_document.abreviation == "ATTEST":
        return en_cours
    return inscriptions.filter(statut__in=STATUTS_SCOLARISES).first()


def format_numero(numero_ordre: int, etablissement, type_document: TypeDeDocument, annee: int) -> str:
    return f"{numero_ordre:03d}/{etablissement.sigle_effectif}/{type_document.abreviation}/{annee}"


def _numero_suivant(etablissement, type_document: TypeDeDocument, annee: int) -> int:
    """Le prochain numéro d'ordre (verrouillé : deux émissions en même temps n'obtiennent jamais le même)."""
    sequence, _ = SequenceReference.objects.select_for_update().get_or_create(
        etablissement=etablissement, prefixe=f"DOC-{type_document.abreviation}"[:10], annee=annee,
    )
    sequence.dernier_numero += 1
    sequence.save(update_fields=["dernier_numero"])
    return sequence.dernier_numero


def emettre(inscription, type_document: TypeDeDocument) -> VerificationDocument:
    """Le document déjà émis pour cette inscription (même numéro, même QR code), sinon un nouveau, numéroté."""
    etablissement = inscription.classe.annee_scolaire.etablissement
    with transaction.atomic():
        existant = VerificationDocument.objects.filter(
            type_document=type_document.type_verifiable, inscription=inscription, actif=True,
        ).order_by("pk").first()
        if existant is not None and existant.numero:
            return existant
        annee = timezone.localdate().year
        numero = format_numero(_numero_suivant(etablissement, type_document, annee), etablissement, type_document, annee)
        if existant is not None:  # émis avant la numérotation : il reçoit son numéro maintenant
            existant.numero = numero
            existant.save(update_fields=["numero"])
            return existant
        return VerificationDocument.objects.create(
            type_document=type_document.type_verifiable, eleve=inscription.eleve, inscription=inscription, numero=numero,
        )


def image_en_donnees(champ) -> str:
    """Une image enregistrée (signature, cachet) en adresse « data: » pour un PDF ; vide si absente ou illisible."""
    if not champ:
        return ""
    try:
        with champ.open("rb") as fichier:
            contenu = fichier.read(2 * 1024 * 1024 + 1)
    except (OSError, ValueError):
        return ""
    if not contenu or len(contenu) > 2 * 1024 * 1024:
        return ""
    type_mime = "image/png" if contenu.startswith(b"\x89PNG") else "image/jpeg"
    return f"data:{type_mime};base64," + base64.b64encode(contenu).decode("ascii")


def logo_en_donnees(etablissement) -> str:
    """Le logo de l'école en adresse « data: » : le générateur de PDF ne sait pas aller chercher une adresse relative (/media/...)."""
    return image_en_donnees(etablissement.logo)


def ville_de_l_ecole(etablissement) -> str:
    return etablissement.commune or etablissement.cercle or etablissement.region or ""


def fusionner_pdf(*contenus: bytes) -> bytes:
    """Plusieurs PDF mis bout à bout dans un seul (version française puis version arabe d'un document bilingue)."""
    from pypdf import PdfReader, PdfWriter

    auteur = PdfWriter()
    for contenu in contenus:
        auteur.append(PdfReader(io.BytesIO(contenu)))
    sortie = io.BytesIO()
    auteur.write(sortie)
    return sortie.getvalue()
