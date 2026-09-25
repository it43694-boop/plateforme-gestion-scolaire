import io
import zipfile

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from comptes.validators import EXTENSIONS_DOCUMENT_AUTORISEES
from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from bibliotheque.forms import AjouterDocumentForm, ImporterZipForm
from bibliotheque.models import Document
from permissions_matrix.modules import Module

MAX_FICHIERS_PAR_IMPORT = 200
MAX_TAILLE_FICHIER_OCTETS = 10 * 1024 * 1024
MAX_TAILLE_TOTALE_OCTETS = 100 * 1024 * 1024


@module_requis(Module.BIBLIOTHEQUE)
def liste_documents(request):
    documents = Document.objects.filter(etablissement=request.user.etablissement)
    page_obj = Paginator(documents, 25).get_page(request.GET.get("page"))
    return render(request, "bibliotheque/liste_documents.html", {
        "page_obj": page_obj, "documents": page_obj.object_list,
        "formulaire_ajout": AjouterDocumentForm(),
        "formulaire_import": ImporterZipForm(),
    })


@module_requis(Module.BIBLIOTHEQUE)
@require_http_methods(["POST"])
def ajouter_document(request):
    formulaire = AjouterDocumentForm(request.POST, request.FILES)
    if formulaire.is_valid():
        document = formulaire.save(commit=False)
        document.ajoute_par = request.user
        document.etablissement = request.user.etablissement
        document.save()
        enregistrer_action(acteur=request.user, action="ajout_document", cible=document.titre, request=request)
        messages.success(request, f"Document « {document.titre} » ajouté.")
    else:
        messages.error(request, "Impossible d'ajouter le document : " + str(formulaire.errors))
    return redirect("bibliotheque:liste_documents")


@module_requis(Module.BIBLIOTHEQUE)
@require_http_methods(["POST"])
def importer_zip(request):
    formulaire = ImporterZipForm(request.POST, request.FILES)
    if not formulaire.is_valid():
        messages.error(request, "Import invalide : " + str(formulaire.errors))
        return redirect("bibliotheque:liste_documents")

    archive = formulaire.cleaned_data["archive"]
    nombre_importes = 0
    nombre_ignores = 0
    with zipfile.ZipFile(archive) as zip_fichier:
        infos = [info for info in zip_fichier.infolist() if not info.is_dir()]

        if len(infos) > MAX_FICHIERS_PAR_IMPORT:
            messages.error(
                request,
                f"L'archive contient trop de fichiers ({len(infos)}). "
                f"Maximum autorisé : {MAX_FICHIERS_PAR_IMPORT} par import.",
            )
            return redirect("bibliotheque:liste_documents")

        taille_totale = sum(info.file_size for info in infos)
        if taille_totale > MAX_TAILLE_TOTALE_OCTETS:
            messages.error(
                request,
                f"La taille totale décompressée de l'archive dépasse la limite autorisée "
                f"({MAX_TAILLE_TOTALE_OCTETS // (1024 * 1024)} Mo).",
            )
            return redirect("bibliotheque:liste_documents")

        for info in infos:
            if info.file_size > MAX_TAILLE_FICHIER_OCTETS:
                nombre_ignores += 1
                continue
            contenu = zip_fichier.read(info.filename)
            nom_simple = info.filename.split("/")[-1]
            if not nom_simple:
                nombre_ignores += 1
                continue
            if not any(nom_simple.lower().endswith(ext) for ext in EXTENSIONS_DOCUMENT_AUTORISEES):
                nombre_ignores += 1
                continue
            document = Document(titre=nom_simple, ajoute_par=request.user, etablissement=request.user.etablissement)
            document.fichier.save(nom_simple, ContentFile(contenu), save=False)
            try:
                document.full_clean()
            except ValidationError:
                nombre_ignores += 1
                document.fichier.delete(save=False)
                continue
            document.save()
            nombre_importes += 1

    enregistrer_action(
        acteur=request.user, action="import_zip_bibliotheque",
        cible=archive.name, details={"nombre_fichiers": nombre_importes, "ignores": nombre_ignores}, request=request,
    )
    message = f"{nombre_importes} document(s) importé(s) depuis l'archive."
    if nombre_ignores:
        message += f" {nombre_ignores} fichier(s) ignoré(s) (trop volumineux ou invalide(s))."
    messages.success(request, message)
    return redirect("bibliotheque:liste_documents")


@module_requis(Module.BIBLIOTHEQUE)
def exporter_zip(request):
    """
    Exporte toute la bibliothèque, ou une sélection (paramètre GET
    répété `id=`), en une seule archive zip.
    """
    ids_selection = request.GET.getlist("id")
    documents = Document.objects.filter(etablissement=request.user.etablissement)
    if ids_selection:
        documents = documents.filter(id__in=ids_selection)

    tampon = io.BytesIO()
    if documents.count() > 500:
        messages.error(request, "L'export est limité à 500 documents. Sélectionnez un sous-ensemble.")
        return redirect("bibliotheque:liste_documents")
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as zip_fichier:
        for document in documents:
            document.fichier.open("rb")
            zip_fichier.writestr(document.nom_fichier, document.fichier.read())
            document.fichier.close()
    tampon.seek(0)

    enregistrer_action(
        acteur=request.user, action="export_zip_bibliotheque",
        details={"nombre_fichiers": documents.count()}, request=request,
    )
    reponse = HttpResponse(tampon.getvalue(), content_type="application/zip")
    reponse["Content-Disposition"] = 'attachment; filename="bibliotheque.zip"'
    return reponse
