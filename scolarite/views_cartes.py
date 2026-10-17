"""Cartes d'élève en PDF (planche A4, recto puis verso) : une classe entière ou un seul élève."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse

from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from comptes.excel import nom_fichier_sur
from comptes.pdf import creer_pdf
from permissions_matrix.modules import Module
from scolarite.cartes import construire_cartes, logo_en_donnees, planches
from scolarite.models import (
    ROLES_ETAT_CIVIL_ELEVE, Inscription, classes_visibles_pour, eleve_de_l_etablissement_ou_404, eleve_visible_pour,
)


def _verifier_droit(utilisateur):
    """Imprimer des cartes : le secrétariat et la direction, qui gèrent déjà les dossiers (jamais un enseignant, un parent ni un comptable)."""
    if utilisateur.role not in ROLES_ETAT_CIVIL_ELEVE:
        raise PermissionDenied("Vous n'avez pas le droit d'imprimer des cartes d'élève.")


def _reponse_pdf(request, inscriptions, nom_fichier, cible):
    cartes = construire_cartes(
        inscriptions, lambda jeton: request.build_absolute_uri(reverse("scolarite:verifier_document", kwargs={"jeton": jeton})),
    )
    if not cartes:
        return None
    html = render_to_string("scolarite/cartes_eleves_pdf.html", {
        "planches": planches(cartes), "logo": logo_en_donnees(request.user.etablissement),
        "arabe": getattr(request, "LANGUAGE_CODE", "fr") == "ar",
    }, request=request)
    reponse = HttpResponse(content_type="application/pdf")
    reponse["Content-Disposition"] = f'attachment; filename="{nom_fichier}.pdf"'
    if creer_pdf(html, reponse, request=request).err:
        return HttpResponse("Erreur lors de la génération du PDF.", status=500)
    enregistrer_action(
        acteur=request.user, action="impression_cartes_eleves", cible=cible, details={"cartes": len(cartes)}, request=request,
    )
    return reponse


@module_requis(Module.ELEVES)
def cartes_classe_pdf(request, classe_id):
    _verifier_droit(request.user)
    classe = get_object_or_404(classes_visibles_pour(request.user), id=classe_id)
    inscriptions = list(
        Inscription.objects.filter(classe=classe, statut=Inscription.Statut.EN_COURS)
        .select_related("eleve", "classe__annee_scolaire").order_by("eleve__nom", "eleve__prenom")
    )
    reponse = _reponse_pdf(request, inscriptions, nom_fichier_sur("cartes", classe.nom, classe.annee_scolaire.libelle), str(classe))
    if reponse is None:
        messages.error(request, "Aucun élève inscrit dans cette classe : aucune carte à imprimer.")
        return redirect(f"{reverse('scolarite:liste_eleves')}?classe={classe.pk}")
    return reponse


@module_requis(Module.ELEVES)
def carte_eleve_pdf(request, matricule):
    _verifier_droit(request.user)
    eleve = eleve_de_l_etablissement_ou_404(request.user, matricule)
    if not eleve_visible_pour(request.user, eleve):
        raise PermissionDenied("Vous n'avez pas accès à cet élève.")
    inscriptions = list(
        Inscription.objects.filter(eleve=eleve, statut=Inscription.Statut.EN_COURS).select_related("eleve", "classe__annee_scolaire")[:1]
    )
    reponse = _reponse_pdf(request, inscriptions, nom_fichier_sur("carte", eleve.matricule), eleve.matricule)
    if reponse is None:
        messages.error(request, "Aucune inscription en cours pour cet élève : aucune carte à imprimer.")
        return redirect("scolarite:dossier_eleve", matricule=eleve.matricule)
    return reponse
