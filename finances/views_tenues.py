"""Vente de tenues : le stock, les ventes au comptoir et leurs reçus. Réservé au comptable et à la direction."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_http_methods, require_POST

from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from comptes.excel import nom_fichier_sur
from comptes.pdf import creer_pdf
from finances import tenues
from finances.forms_tenues import (
    AnnulationVenteForm, ApprovisionnerForm, ArticleTenueForm, CorrectionStockForm, VenteTenueForm,
)
from finances.models import ArticleTenue, MouvementStockTenue, VenteTenue
from finances.views import _est_direction, _peut_gerer_les_paiements
from permissions_matrix.modules import Module


def _ecole(request):
    if request.user.etablissement_id is None:
        raise Http404("Aucun établissement.")
    return request.user.etablissement


def _droit(request):
    if not _peut_gerer_les_paiements(request.user):
        raise PermissionDenied("Vous n'avez pas le droit de gérer la vente de tenues.")


def _article(request, article_id):
    return get_object_or_404(ArticleTenue, pk=article_id, etablissement=_ecole(request))


# ---------------------------------------------------------------------------
# Stock
# ---------------------------------------------------------------------------

@module_requis(Module.FINANCES)
@require_http_methods(["GET", "POST"])
def stock(request):
    _droit(request)
    ecole = _ecole(request)
    formulaire = ArticleTenueForm(request.POST or None, etablissement=ecole, initial={"actif": True, "seuil_alerte": 5})
    if request.method == "POST" and formulaire.is_valid():
        article = formulaire.save()
        enregistrer_action(acteur=request.user, action="creation_article_tenue", cible=article.nom_complet, details={"prix": article.prix}, request=request)
        messages.success(request, "Article ajouté. Enregistrez maintenant son premier arrivage pour qu'il puisse être vendu.")
        return redirect("finances:tenues")
    articles = list(ArticleTenue.objects.filter(etablissement=ecole))
    mouvements = MouvementStockTenue.objects.filter(article__etablissement=ecole).select_related("article", "cree_par")[:20]
    return render(request, "finances/tenues.html", {
        "formulaire": formulaire, "articles": articles, "mouvements": mouvements,
        "en_alerte": sum(1 for article in articles if article.actif and article.en_alerte),
        "formulaire_arrivage": ApprovisionnerForm(), "formulaire_correction": CorrectionStockForm(),
    })


@module_requis(Module.FINANCES)
@require_http_methods(["GET", "POST"])
def modifier_article(request, article_id):
    _droit(request)
    article = _article(request, article_id)
    formulaire = ArticleTenueForm(request.POST or None, instance=article, etablissement=article.etablissement)
    if request.method == "POST" and formulaire.is_valid():
        formulaire.save()
        enregistrer_action(acteur=request.user, action="modification_article_tenue", cible=article.nom_complet, request=request)
        messages.success(request, "Article modifié.")
        return redirect("finances:tenues")
    return render(request, "finances/tenues_article.html", {"formulaire": formulaire, "article": article})


@module_requis(Module.FINANCES)
@require_POST
def approvisionner(request, article_id):
    _droit(request)
    article = _article(request, article_id)
    formulaire = ApprovisionnerForm(request.POST)
    if formulaire.is_valid():
        try:
            tenues.approvisionner(article=article, quantite=formulaire.cleaned_data["quantite"], note=formulaire.cleaned_data["note"], acteur=request.user)
        except ValidationError as erreur:
            messages.error(request, erreur.messages[0])
        else:
            enregistrer_action(
                acteur=request.user, action="arrivage_tenue", cible=article.nom_complet, details={"quantite": formulaire.cleaned_data["quantite"]}, request=request,
            )
            messages.success(request, f"Arrivage enregistré : {formulaire.cleaned_data['quantite']} × {article.nom_complet}.")
    else:
        messages.error(request, "Indiquez une quantité reçue (un nombre entier supérieur à zéro).")
    return redirect("finances:tenues")


@module_requis(Module.FINANCES)
@require_POST
def corriger_stock(request, article_id):
    _droit(request)
    article = _article(request, article_id)
    formulaire = CorrectionStockForm(request.POST)
    if formulaire.is_valid():
        try:
            tenues.corriger_stock(
                article=article, nouveau_stock=formulaire.cleaned_data["nouveau_stock"], note=formulaire.cleaned_data["note"], acteur=request.user,
            )
        except ValidationError as erreur:
            messages.error(request, erreur.messages[0])
        else:
            enregistrer_action(
                acteur=request.user, action="correction_stock_tenue", cible=article.nom_complet,
                details={"stock": formulaire.cleaned_data["nouveau_stock"]}, request=request,
            )
            messages.success(request, f"Stock corrigé : {formulaire.cleaned_data['nouveau_stock']} × {article.nom_complet}.")
    else:
        messages.error(request, "Indiquez le stock réel compté et le motif de la correction.")
    return redirect("finances:tenues")


# ---------------------------------------------------------------------------
# Ventes
# ---------------------------------------------------------------------------

@module_requis(Module.FINANCES)
@require_http_methods(["GET", "POST"])
def vendre(request):
    _droit(request)
    ecole = _ecole(request)
    articles = ArticleTenue.objects.filter(etablissement=ecole, actif=True, stock__gt=0)
    formulaire = VenteTenueForm(request.POST or None, etablissement=ecole, articles=articles)
    if request.method == "POST" and formulaire.is_valid():
        donnees = formulaire.cleaned_data
        try:
            vente = tenues.vendre(
                etablissement=ecole, quantites=donnees["quantites"], eleve=donnees["eleve"], acheteur=donnees["acheteur"],
                mode_paiement=donnees["mode_paiement"], acteur=request.user,
            )
        except ValidationError as erreur:
            formulaire.add_error(None, erreur.messages[0])
        else:
            enregistrer_action(
                acteur=request.user, action="vente_tenues", cible=vente.reference,
                details={"total": vente.total, "articles": len(donnees["quantites"])}, request=request,
            )
            messages.success(request, f"Vente enregistrée : reçu {vente.reference}.")
            return redirect("finances:tenues_ventes")
    return render(request, "finances/tenues_vendre.html", {"formulaire": formulaire, "lignes": formulaire.lignes()})


@module_requis(Module.FINANCES)
def ventes(request):
    _droit(request)
    ecole = _ecole(request)
    recherche = request.GET.get("q", "").strip()
    liste = VenteTenue.objects.filter(etablissement=ecole).select_related("eleve", "enregistre_par").prefetch_related("lignes")
    if recherche:
        liste = liste.filter(
            Q(reference__icontains=recherche) | Q(acheteur__icontains=recherche) | Q(eleve__nom__icontains=recherche) | Q(eleve__prenom__icontains=recherche)
            | Q(eleve__matricule__icontains=recherche)
        )
    page_obj = Paginator(liste, 25).get_page(request.GET.get("page"))
    return render(request, "finances/tenues_ventes.html", {
        "page_obj": page_obj, "ventes": page_obj.object_list, "recherche": recherche, "peut_annuler": _est_direction(request.user),
    })


@module_requis(Module.FINANCES)
def recu_pdf(request, vente_id):
    _droit(request)
    vente = get_object_or_404(
        VenteTenue.objects.select_related("eleve", "enregistre_par", "etablissement").prefetch_related("lignes"),
        pk=vente_id, etablissement=_ecole(request),
    )
    html = render_to_string("finances/tenues_recu_pdf.html", {"vente": vente, "etablissement": vente.etablissement}, request=request)
    reponse = HttpResponse(content_type="application/pdf")
    reponse["Content-Disposition"] = f'attachment; filename="{nom_fichier_sur("recu", vente.reference)}.pdf"'
    if creer_pdf(html, reponse, request=request).err:
        return HttpResponse("Erreur lors de la génération du reçu.", status=500)
    return reponse


@module_requis(Module.FINANCES)
@require_POST
def annuler_vente(request, vente_id):
    if not _est_direction(request.user):
        raise PermissionDenied("Seule la direction peut annuler une vente.")
    vente = get_object_or_404(VenteTenue, pk=vente_id, etablissement=_ecole(request))
    formulaire = AnnulationVenteForm(request.POST)
    if not formulaire.is_valid():
        messages.error(request, "Indiquez le motif de l'annulation.")
    else:
        try:
            tenues.annuler_vente(vente=vente, motif=formulaire.cleaned_data["motif"], acteur=request.user)
        except ValidationError as erreur:
            messages.error(request, erreur.messages[0])
        else:
            enregistrer_action(acteur=request.user, action="annulation_vente_tenues", cible=vente.reference, request=request)
            messages.success(request, f"La vente {vente.reference} est annulée : les articles sont revenus en stock.")
    return redirect("finances:tenues_ventes")
