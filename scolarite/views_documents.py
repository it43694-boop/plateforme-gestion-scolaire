"""
Documents officiels d'un élève en PDF : certificat de scolarité, attestation de fréquentation, certificat de radiation.

Options (adresse de la page) : `bilingue=1` (version française et version arabe dans le même fichier), `signature=1` et `cachet=1`
(imprimés seulement si l'école a téléversé l'image). Sans option, le document est écrit dans la langue de la personne qui l'édite.
"""
import base64
from io import BytesIO

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from comptes.excel import nom_fichier_sur
from comptes.pdf import creer_pdf
from permissions_matrix.modules import Module
from scolarite.documents import (
    TYPES, emettre, fusionner_pdf, image_en_donnees, inscription_concernee, logo_en_donnees, ville_de_l_ecole,
)
from scolarite.models import (
    ROLES_ETAT_CIVIL_ELEVE, Inscription, eleve_de_l_etablissement_ou_404, eleve_visible_pour,
)


def _qr(adresse: str) -> str:
    try:
        import qrcode
    except ImportError:
        return ""
    tampon = BytesIO()
    qrcode.make(adresse).save(tampon, format="PNG")
    return "data:image/png;base64," + base64.b64encode(tampon.getvalue()).decode("ascii")


def _contexte(request, eleve, inscription, verification, type_document, *, signature, cachet):
    etablissement = inscription.classe.annee_scolaire.etablissement
    adresse = request.build_absolute_uri(reverse("scolarite:verifier_document", kwargs={"jeton": verification.jeton}))
    contexte = {
        "logo": logo_en_donnees(etablissement), "type_document": type_document, "eleve": eleve, "inscription": inscription, "classe": inscription.classe,
        "annee": inscription.classe.annee_scolaire, "verification": verification, "verification_url": adresse.rstrip("/"), "qr_code": _qr(adresse),
        "ville": ville_de_l_ecole(etablissement), "aujourdhui": timezone.localdate(),
        "signature": image_en_donnees(etablissement.signature) if signature else "",
        "cachet": image_en_donnees(etablissement.cachet) if cachet else "",
        "en_cours": inscription.statut == Inscription.Statut.EN_COURS,
    }
    if type_document.abreviation == "RAD":
        transfert = getattr(inscription, "transfert", None) if inscription.statut == Inscription.Statut.TRANSFERE else None
        abandon = getattr(inscription, "abandon", None) if inscription.statut == Inscription.Statut.ABANDON else None
        contexte["radie_le"] = transfert.date_transfert if transfert else (abandon.date_abandon if abandon else None)
        contexte["destination"] = (
            (transfert.destination_libelle or (transfert.etablissement_destination.nom if transfert.etablissement_destination_id else "")) if transfert else ""
        )
        contexte["transfert"] = transfert is not None
    return contexte


@module_requis(Module.ELEVES)
def document_officiel(request, matricule, code):
    if request.user.role not in ROLES_ETAT_CIVIL_ELEVE:
        raise PermissionDenied("Vous n'avez pas le droit d'éditer des documents officiels.")
    type_document = TYPES.get(code)
    if type_document is None:
        raise Http404("Document inconnu.")
    eleve = eleve_de_l_etablissement_ou_404(request.user, matricule)
    if not eleve_visible_pour(request.user, eleve):
        raise PermissionDenied("Vous n'avez pas accès à cet élève.")
    inscription = inscription_concernee(eleve, type_document)
    if inscription is None:
        messages.error(request, {
            "RAD": "Cet élève n'a pas été radié (ni transfert, ni abandon) : aucun certificat de radiation à éditer.",
            "ATTEST": "Cet élève n'a pas d'inscription en cours : aucune attestation de fréquentation à éditer.",
        }.get(type_document.abreviation, "Cet élève n'a aucune inscription : aucun certificat à éditer."))
        return redirect("scolarite:dossier_eleve", matricule=eleve.matricule)

    verification = emettre(inscription, type_document)
    etablissement = inscription.classe.annee_scolaire.etablissement
    signature = request.GET.get("signature") == "1" and bool(etablissement.signature)
    cachet = request.GET.get("cachet") == "1" and bool(etablissement.cachet)
    contexte = _contexte(request, eleve, inscription, verification, type_document, signature=signature, cachet=cachet)

    langue_page = getattr(request, "LANGUAGE_CODE", "fr")
    if request.GET.get("bilingue") == "1":
        langues = ["ar", "fr"] if langue_page == "ar" else ["fr", "ar"]  # la langue de la personne d'abord
    else:
        langues = [langue_page]

    pdfs = []
    for langue in langues:
        html = render_to_string("scolarite/document_officiel_pdf.html", {**contexte, "etablissement": etablissement}, request=request)
        sortie = BytesIO()
        if creer_pdf(html, sortie, request=request, langue=langue).err:
            return HttpResponse("Erreur lors de la génération du PDF.", status=500)
        pdfs.append(sortie.getvalue())
    contenu = pdfs[0] if len(pdfs) == 1 else fusionner_pdf(*pdfs)

    enregistrer_action(
        acteur=request.user, action="generation_document_officiel", cible=eleve.matricule,
        details={"type": type_document.abreviation, "numero": verification.numero, "bilingue": len(langues) > 1, "signature": signature, "cachet": cachet},
        request=request,
    )
    reponse = HttpResponse(contenu, content_type="application/pdf")
    reponse["Content-Disposition"] = f'attachment; filename="{nom_fichier_sur(type_document.abreviation.lower(), eleve.matricule)}.pdf"'
    return reponse
