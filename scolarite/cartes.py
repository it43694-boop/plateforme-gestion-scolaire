"""
Cartes d'élève : chaque carte est une pièce d'un seul tenant, le recto à gauche et le verso à droite, que l'on découpe, plie sur le trait en
pointillé et plastifie. Quatre pièces par feuille A4. Chaque carte porte un QR code et un code court (XXXX-XXXX-XXXX) qui mènent à la page
publique « Vérifier un document » (`scolarite.views_verification`) ; les anciennes cartes, dont le QR code ouvre `scolarite.views.verifier_document`,
continuent de fonctionner.
"""
import base64
from io import BytesIO

from PIL import Image

from scolarite.documents import image_en_donnees, logo_en_donnees  # noqa: F401 (logo réexporté : les cartes et les documents le lisent de la même façon)
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


def cachet_en_donnees(champ) -> str:
    """
    Le cachet en adresse « data: » pour le PDF, recadré dans un carré transparent : rond, ovale ou rectangulaire, il garde ses proportions
    dans la case carrée que la carte lui réserve. Vide si le cachet est absent ou illisible.
    """
    if not champ:
        return ""
    try:
        with champ.open("rb") as fichier:
            contenu = fichier.read(2 * 1024 * 1024 + 1)
        if not contenu or len(contenu) > 2 * 1024 * 1024:
            return ""
        with Image.open(BytesIO(contenu)) as source:
            image = source.convert("RGBA")
        image.thumbnail((400, 400))
        carre = Image.new("RGBA", (max(image.size),) * 2, (0, 0, 0, 0))
        carre.paste(image, ((carre.width - image.width) // 2, (carre.height - image.height) // 2), image)
        tampon = BytesIO()
        carre.save(tampon, format="PNG")
    except (OSError, ValueError, Image.DecompressionBombError):
        return ""
    return "data:image/png;base64," + base64.b64encode(tampon.getvalue()).decode("ascii")


def signataires_par_cycle(etablissement, cycles) -> dict:
    """
    Qui signe la carte, et quel cachet elle porte, pour chacun des cycles donnés : `{cycle: {"nom", "fonction", "signature", "cachet"}}`
    (images en adresses « data: » pour le PDF), ou `None` pour un cycle où rien n'est renseigné.

    - Le signataire d'un cycle (nom, fonction, signature) est celui que l'école a saisi pour ce cycle (`SignataireCycle`) ; si elle n'a saisi aucun
      des trois pour ce cycle, c'est celui de l'école entière. Jamais un mélange : la signature d'un directeur n'accompagne pas le nom d'un autre.
    - Le cachet est celui du cycle, sinon celui de l'école.
    """
    from etablissement.models import SignataireCycle

    propres = {signataire.cycle: signataire for signataire in SignataireCycle.objects.filter(etablissement=etablissement)}
    images = {}  # une image n'est lue et encodée qu'une fois, même si plusieurs cycles s'en servent

    def donnees(champ, lecteur=image_en_donnees):
        if not champ:
            return ""
        if (lecteur, champ.name) not in images:
            images[(lecteur, champ.name)] = lecteur(champ)
        return images[(lecteur, champ.name)]

    resultat = {}
    for cycle in cycles:
        propre = propres.get(cycle)
        if propre is not None and (propre.nom_signataire or propre.fonction_signataire or propre.signature):
            nom, fonction, signature = propre.nom_signataire, propre.fonction_signataire, donnees(propre.signature)
        else:
            nom, fonction, signature = etablissement.nom_signataire, etablissement.fonction_signataire, donnees(etablissement.signature)
        champ_cachet = propre.cachet if propre is not None and propre.cachet else etablissement.cachet
        cachet = donnees(champ_cachet, cachet_en_donnees)
        resultat[cycle] = {"nom": nom, "fonction": fonction, "signature": signature, "cachet": cachet} if (nom or fonction or signature or cachet) else None
    return resultat


def ajouter_les_signataires(cartes: list[dict], etablissement) -> None:
    """Joint à chaque carte le signataire (et le cachet) du cycle de sa classe."""
    signataires = signataires_par_cycle(etablissement, {carte["classe"].cycle for carte in cartes})
    for carte in cartes:
        carte["signataire"] = signataires[carte["classe"].cycle]


def pages(cartes: list[dict]) -> list[list[dict]]:
    """Les cartes rangées en feuilles de quatre pièces."""
    return [cartes[debut:debut + CARTES_PAR_PAGE] for debut in range(0, len(cartes), CARTES_PAR_PAGE)]
