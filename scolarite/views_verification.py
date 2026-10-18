"""Page publique « Vérifier un document » : on y tape le code court imprimé sous le QR code d'une carte (ou on y arrive en scannant le QR code)."""
from django.shortcuts import render
from django_ratelimit.core import ALL
from django_ratelimit.decorators import ratelimit

from scolarite.models import VerificationDocument, normaliser_code_verification


@ratelimit(key="ip", rate="20/m", method=ALL, block=False)
def verifier(request):
    """
    Sans limite, la page permettrait d'essayer des codes en masse. Elle ne dit rien de plus que le QR code : ce que le document imprimé montre déjà
    (type, élève, matricule, classe, école, date), jamais le dossier.
    """
    code_saisi = (request.POST.get("code") or request.GET.get("code") or "").strip()[:40]
    contexte = {"code_saisi": code_saisi, "resultat": None, "refus": ""}
    if getattr(request, "limited", False):
        contexte["refus"] = "limite"
    elif code_saisi:
        code = normaliser_code_verification(code_saisi)
        verification = (
            VerificationDocument.objects.select_related("eleve", "inscription__classe__annee_scolaire__etablissement")
            .filter(code=code, actif=True).first() if code else None
        )
        if verification is None:
            contexte["refus"] = "inconnu"
        else:
            contexte["resultat"] = {
                "type_document": verification.get_type_document_display(), "eleve": verification.eleve.nom_complet,
                "matricule": verification.eleve.matricule, "classe": verification.inscription.classe,
                "etablissement": verification.inscription.classe.annee_scolaire.etablissement.nom, "emis_le": verification.cree_le,
                "code": verification.code,
            }
    return render(request, "scolarite/verifier_document.html", contexte)
