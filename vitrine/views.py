from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render

from etablissement.models import Etablissement


def accueil(request):
    """
    Page publique racine — une seule mise en page, dans tous les cas.
    En mono-établissement, la marque et les boutons pointent directement
    vers cette école. Dès que plusieurs établissements existent, la même
    page s'affiche avec l'identité générique de la plateforme, et la zone
    de boutons devient une liste d'établissements à choisir - jamais un
    design entièrement différent.
    """
    if request.user.is_authenticated:
        return redirect("comptes:redirection_tableau_de_bord")

    etablissements = Etablissement.objects.filter(actif=True, visible_dans_annuaire=True)
    nombre = etablissements.count()

    if nombre == 0:
        return render(request, "vitrine/aucun_etablissement.html", {"nom_plateforme": settings.NOM_PLATEFORME})

    if nombre == 1:
        request.session["etablissement_id"] = etablissements.first().pk
        return render(request, "vitrine/accueil.html", {
            "nom_plateforme": settings.NOM_PLATEFORME, "etablissement": etablissements.first(), "mode_multi": False,
        })

    return render(request, "vitrine/accueil.html", {
        "nom_plateforme": settings.NOM_PLATEFORME, "etablissement": None,
        "etablissements": etablissements, "mode_multi": True,
    })


def choisir_etablissement(request, slug):
    etablissement = get_object_or_404(Etablissement, slug=slug, actif=True)
    request.session["etablissement_id"] = etablissement.pk
    return redirect("comptes:connexion")
