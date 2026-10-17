"""
Cartes d'élève : données d'une planche A4 de 8 cartes (2 colonnes, 4 lignes), recto puis verso.

Au verso, les deux cartes de chaque ligne sont permutées : une fois la feuille retournée sur son grand côté, le verso d'une carte tombe
exactement derrière son recto. Chaque carte porte un QR code qui ouvre la page publique de vérification (`scolarite.views.verifier_document`).
"""
import base64
from io import BytesIO

from scolarite.documents import logo_en_donnees  # noqa: F401 (réexporté : les cartes et les documents lisent le logo de la même façon)
from scolarite.models import Inscription, TypeDocumentVerifiable, VerificationDocument
from scolarite.photos import photo_en_donnees

CARTES_PAR_LIGNE = 2
LIGNES_PAR_PAGE = 4
CARTES_PAR_PAGE = CARTES_PAR_LIGNE * LIGNES_PAR_PAGE


def qr_en_donnees(adresse: str) -> str:
    try:
        import qrcode
    except ImportError:  # sans la bibliothèque, la carte s'imprime sans QR code plutôt que d'échouer
        return ""
    tampon = BytesIO()
    qrcode.make(adresse, box_size=4, border=1).save(tampon, format="PNG")
    return "data:image/png;base64," + base64.b64encode(tampon.getvalue()).decode("ascii")


def _verifications(inscriptions):
    """Un jeton de vérification par carte : celui qui existe déjà, sinon un nouveau (créés en une seule requête)."""
    existantes = {
        verification.inscription_id: verification
        for verification in VerificationDocument.objects.filter(
            type_document=TypeDocumentVerifiable.CARTE_ELEVE, inscription__in=inscriptions, actif=True,
        )
    }
    manquantes = [
        VerificationDocument(type_document=TypeDocumentVerifiable.CARTE_ELEVE, eleve=inscription.eleve, inscription=inscription)
        for inscription in inscriptions if inscription.pk not in existantes
    ]
    for verification in VerificationDocument.objects.bulk_create(manquantes):
        existantes[verification.inscription_id] = verification
    return existantes


def construire_cartes(inscriptions, adresse_de_verification) -> list[dict]:
    """
    Les cartes (dictionnaires prêts pour le gabarit) des inscriptions en cours données. `adresse_de_verification(jeton)` rend l'adresse
    complète que le QR code ouvre.
    """
    inscriptions = [i for i in inscriptions if i.statut == Inscription.Statut.EN_COURS]
    verifications = _verifications(inscriptions)
    cartes = []
    for inscription in inscriptions:
        eleve = inscription.eleve
        cartes.append({
            "eleve": eleve, "inscription": inscription, "classe": inscription.classe, "annee": inscription.classe.annee_scolaire,
            "photo": photo_en_donnees(eleve),
            "qr": qr_en_donnees(adresse_de_verification(verifications[inscription.pk].jeton)),
        })
    return cartes


def planches(cartes: list[dict]) -> list[dict]:
    """Les cartes rangées en pages de 8 : {"recto": [[carte, carte], ...], "verso": [[carte, carte], ...]} (verso permuté ligne par ligne)."""
    pages = []
    for debut in range(0, len(cartes), CARTES_PAR_PAGE):
        lot = cartes[debut:debut + CARTES_PAR_PAGE]
        lignes = [lot[i:i + CARTES_PAR_LIGNE] for i in range(0, len(lot), CARTES_PAR_LIGNE)]
        lignes = [ligne + [None] * (CARTES_PAR_LIGNE - len(ligne)) for ligne in lignes]
        pages.append({"recto": lignes, "verso": [list(reversed(ligne)) for ligne in lignes]})
    return pages
