"""
Cartes d'élève : chaque carte est une pièce d'un seul tenant, le recto à gauche et le verso à droite, que l'on découpe, plie sur le trait en
pointillé et plastifie. Quatre pièces par feuille A4. Chaque carte porte un QR code et un code court (XXXX-XXXX-XXXX) qui mènent à la page
publique « Vérifier un document » (`scolarite.views_verification`) ; les anciennes cartes, dont le QR code ouvre `scolarite.views.verifier_document`,
continuent de fonctionner.
"""
import base64
from io import BytesIO

from scolarite.documents import logo_en_donnees  # noqa: F401 (réexporté : les cartes et les documents lisent le logo de la même façon)
from scolarite.models import Inscription, TypeDocumentVerifiable, VerificationDocument, nouveau_code_verification
from scolarite.photos import photo_en_donnees

CARTES_PAR_PAGE = 4


def qr_en_donnees(adresse: str) -> str:
    try:
        import qrcode
    except ImportError:  # sans la bibliothèque, la carte s'imprime sans QR code plutôt que d'échouer
        return ""
    tampon = BytesIO()
    qrcode.make(adresse, box_size=4, border=1).save(tampon, format="PNG")
    return "data:image/png;base64," + base64.b64encode(tampon.getvalue()).decode("ascii")


def _verifications(inscriptions):
    """Une vérification (jeton et code court) par carte : celle qui existe déjà, sinon une nouvelle (créées en une seule requête)."""
    existantes = {
        verification.inscription_id: verification
        for verification in VerificationDocument.objects.filter(
            type_document=TypeDocumentVerifiable.CARTE_ELEVE, inscription__in=inscriptions, actif=True,
        )
    }
    # Une carte imprimée avant l'arrivée du code court en reçoit un maintenant : son QR code, lui, ne change pas.
    sans_code = [verification for verification in existantes.values() if not verification.code]
    for verification in sans_code:
        verification.code = nouveau_code_verification()
    if sans_code:
        VerificationDocument.objects.bulk_update(sans_code, ["code"])
    manquantes = [
        VerificationDocument(
            type_document=TypeDocumentVerifiable.CARTE_ELEVE, eleve=inscription.eleve, inscription=inscription, code=nouveau_code_verification(),
        )
        for inscription in inscriptions if inscription.pk not in existantes
    ]
    for verification in VerificationDocument.objects.bulk_create(manquantes):
        existantes[verification.inscription_id] = verification
    return existantes


def construire_cartes(inscriptions, adresse_de_verification) -> list[dict]:
    """
    Les cartes (dictionnaires prêts pour le gabarit) des inscriptions en cours données. `adresse_de_verification(code)` rend l'adresse
    complète que le QR code ouvre.
    """
    inscriptions = [i for i in inscriptions if i.statut == Inscription.Statut.EN_COURS]
    verifications = _verifications(inscriptions)
    cartes = []
    for inscription in inscriptions:
        eleve = inscription.eleve
        code = verifications[inscription.pk].code
        cartes.append({
            "eleve": eleve, "inscription": inscription, "classe": inscription.classe, "annee": inscription.classe.annee_scolaire,
            "photo": photo_en_donnees(eleve), "code": code, "qr": qr_en_donnees(adresse_de_verification(code)),
            "nom_long": len(eleve.nom) + len(eleve.prenom) > 24,  # un nom très long s'écrit plus petit plutôt que de passer sur deux lignes
        })
    return cartes


def pages(cartes: list[dict]) -> list[list[dict]]:
    """Les cartes rangées en feuilles de quatre pièces."""
    return [cartes[debut:debut + CARTES_PAR_PAGE] for debut in range(0, len(cartes), CARTES_PAR_PAGE)]
