"""
Photos des élèves : affichage (toujours après vérification des droits), envoi, suppression, import d'une archive ZIP pour une classe.

La photo d'un enfant n'a jamais d'adresse publique : elle ne sort que par `photo_eleve`, qui applique la même règle de visibilité que le
dossier de l'élève (`eleve_visible_pour`).
"""
from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from comptes.forms import BootstrapFormMixin
from permissions_matrix.modules import Module
from scolarite.models import (
    ROLES_ETAT_CIVIL_ELEVE, classes_visibles_pour, eleve_de_l_etablissement_ou_404, eleve_visible_pour, peut_corriger_dossier_eleve,
)
from scolarite.photos import LIMITE_FICHIERS_ARCHIVE, enregistrer_photo, importer_archive, supprimer_photo

TAILLE_MAXIMALE_ARCHIVE = 60 * 1024 * 1024


class PhotoForm(forms.Form):
    photo = forms.FileField(label="Photo")


class ArchivePhotosForm(BootstrapFormMixin, forms.Form):
    archive = forms.FileField(
        label="Archive ZIP des photos",
        help_text=f"Un fichier JPEG, PNG ou WebP par élève, nommé avec son matricule ou avec son nom (au plus {LIMITE_FICHIERS_ARCHIVE} photos, 60 Mo).",
    )

    def clean_archive(self):
        archive = self.cleaned_data["archive"]
        if archive.size > TAILLE_MAXIMALE_ARCHIVE:
            raise forms.ValidationError("L'archive dépasse la taille maximale autorisée (60 Mo).")
        if not archive.name.lower().endswith(".zip"):
            raise forms.ValidationError("Envoyez un fichier .zip.")
        return archive


@module_requis(Module.ELEVES)
def photo_eleve(request, matricule):
    """La photo de l'élève, pour qui a le droit de voir son dossier (l'élève, ses parents, l'école)."""
    eleve = eleve_de_l_etablissement_ou_404(request.user, matricule)
    if not eleve_visible_pour(request.user, eleve):
        raise PermissionDenied("Vous n'avez pas accès à cet élève.")
    if not eleve.photo:
        raise Http404("Pas de photo.")
    try:
        fichier = eleve.photo.open("rb")
    except (OSError, ValueError):
        raise Http404("Photo introuvable.") from None
    return FileResponse(fichier, content_type="image/jpeg")


@module_requis(Module.ELEVES)
@require_POST
def envoyer_photo_eleve(request, matricule):
    eleve = eleve_de_l_etablissement_ou_404(request.user, matricule)
    if not peut_corriger_dossier_eleve(request.user, eleve):
        raise PermissionDenied("Vous n'avez pas le droit de modifier la photo de cet élève.")
    formulaire = PhotoForm(request.POST, request.FILES)
    if formulaire.is_valid():
        try:
            enregistrer_photo(eleve, formulaire.cleaned_data["photo"].read())
        except ValidationError as erreur:
            messages.error(request, erreur.messages[0])
        else:
            enregistrer_action(acteur=request.user, action="photo_eleve", cible=eleve.matricule, details={"operation": "envoi"}, request=request)
            messages.success(request, f"Photo de {eleve.nom_complet} enregistrée.")
    else:
        messages.error(request, "Choisissez une image à envoyer.")
    return redirect("scolarite:dossier_eleve", matricule=eleve.matricule)


@module_requis(Module.ELEVES)
@require_POST
def supprimer_photo_eleve(request, matricule):
    eleve = eleve_de_l_etablissement_ou_404(request.user, matricule)
    if not peut_corriger_dossier_eleve(request.user, eleve):
        raise PermissionDenied("Vous n'avez pas le droit de modifier la photo de cet élève.")
    if supprimer_photo(eleve):
        enregistrer_action(acteur=request.user, action="photo_eleve", cible=eleve.matricule, details={"operation": "suppression"}, request=request)
        messages.success(request, f"Photo de {eleve.nom_complet} supprimée.")
    return redirect("scolarite:dossier_eleve", matricule=eleve.matricule)


@module_requis(Module.ELEVES)
@require_http_methods(["GET", "POST"])
def importer_photos_classe(request, classe_id):
    """Un ZIP de photos pour toute une classe : chaque fichier est rattaché à l'élève dont il porte le matricule ou le nom."""
    if request.user.role not in ROLES_ETAT_CIVIL_ELEVE:
        raise PermissionDenied("Vous n'avez pas le droit d'importer des photos.")
    classe = get_object_or_404(classes_visibles_pour(request.user), id=classe_id)
    formulaire = ArchivePhotosForm(request.POST or None, request.FILES or None)
    bilan = None
    if request.method == "POST" and formulaire.is_valid():
        try:
            bilan = importer_archive(classe, formulaire.cleaned_data["archive"])
        except ValidationError as erreur:
            formulaire.add_error("archive", erreur.messages[0])
        else:
            enregistrer_action(
                acteur=request.user, action="import_photos_classe", cible=str(classe),
                details={"importees": len(bilan.importees), "ignorees": len(bilan.ignorees)}, request=request,
            )
    return render(request, "scolarite/importer_photos.html", {"classe": classe, "formulaire": formulaire, "bilan": bilan})
