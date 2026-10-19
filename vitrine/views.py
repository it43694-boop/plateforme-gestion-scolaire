import datetime

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django_ratelimit.core import ALL
from django_ratelimit.decorators import ratelimit

from comptes.langue import texte_pour_langue
from etablissement.models import Etablissement
from scolarite.recherche import filtrer
from vitrine import ecole_memorisee

# Jusqu'à ce nombre d'écoles, l'accueil montre la liste complète ; au-delà, seulement la recherche : personne ne parcourt la liste des clients de la plateforme,
# et une longue liste ne se lit plus.
SEUIL_LISTE_COMPLETE = 30
RESULTATS_MAX = 10
CHAMPS_DE_RECHERCHE = ("nom", "sigle", "commune", "cercle", "region")


def etablissements_de_l_annuaire():
    return Etablissement.objects.filter(actif=True, visible_dans_annuaire=True)


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

    etablissements = etablissements_de_l_annuaire()
    nombre = etablissements.count()

    if nombre == 0:
        return render(request, "vitrine/aucun_etablissement.html", {"nom_plateforme": settings.NOM_PLATEFORME})

    if nombre == 1:
        request.session["etablissement_id"] = etablissements.first().pk
        return render(request, "vitrine/accueil.html", {
            "nom_plateforme": settings.NOM_PLATEFORME, "etablissement": etablissements.first(), "mode_multi": False,
        })

    # Plusieurs écoles : l'école retenue au dernier passage en premier, sinon une recherche (et la liste complète tant qu'elle reste courte).
    terme = request.GET.get("q", "").strip()[:60]
    derniere = ecole_memorisee.lire(request)
    return render(request, "vitrine/accueil.html", {
        "nom_plateforme": settings.NOM_PLATEFORME, "etablissement": None, "mode_multi": True,
        "derniere_ecole": derniere if not terme else None,
        "terme": terme, "resultats": filtrer(etablissements, terme, *CHAMPS_DE_RECHERCHE, limite=RESULTATS_MAX) if terme else None,
        "etablissements": list(etablissements) if nombre <= SEUIL_LISTE_COMPLETE else None,
        "adresse_de_recherche": reverse("vitrine:rechercher_etablissement"),
    })


def choisir_etablissement(request, slug):
    etablissement = get_object_or_404(Etablissement, slug=slug, actif=True)
    request.session["etablissement_id"] = etablissement.pk
    reponse = redirect("comptes:connexion")
    ecole_memorisee.memoriser(reponse, etablissement)
    return reponse


def changer_ecole(request):
    """« Ce n'est pas mon école » : on oublie l'école retenue et on revient au choix."""
    reponse = redirect(reverse("vitrine:accueil") + "#choisir-etablissement")
    ecole_memorisee.oublier(reponse)
    request.session.pop("etablissement_id", None)
    return reponse


@ratelimit(key="ip", rate="60/m", method=ALL, block=False)
def rechercher_etablissement(request):
    """
    La recherche en direct de l'accueil : au plus dix écoles, après deux lettres. Limitée par adresse IP, pour que la liste des écoles ne soit pas
    aspirée d'un coup ; ne montre que les écoles actives de l'annuaire public.
    """
    terme = request.GET.get("q", "").strip()[:60]
    resultats = []
    if len(terme) >= 2 and not getattr(request, "limited", False):
        for ecole in filtrer(etablissements_de_l_annuaire(), terme, *CHAMPS_DE_RECHERCHE, limite=RESULTATS_MAX):
            resultats.append({
                "nom": ecole.nom, "lieu": ", ".join(lieu for lieu in (ecole.commune, ecole.region) if lieu),
                "logo": ecole.logo.url if ecole.logo else "", "initiale": ecole.initiale,
                "adresse": reverse("vitrine:choisir_etablissement", args=[ecole.slug]),
            })
    return JsonResponse({"resultats": resultats, "vide": texte_pour_langue(request, "Aucun établissement trouvé.")})


# ---------------------------------------------------------------------------
# Pages légales (publiques : visiteur anonyme comme utilisateur connecté)
# ---------------------------------------------------------------------------

# À mettre à jour à chaque modification des textes.
DATE_VERSION_LEGALE = datetime.date(2026, 10, 12)


def _contexte_legal():
    return {
        "editeur": {
            "nom": settings.EDITEUR_NOM, "statut": settings.EDITEUR_STATUT, "adresse": settings.EDITEUR_ADRESSE,
            "email": settings.EDITEUR_EMAIL, "telephone": settings.EDITEUR_TELEPHONE,
            "immatriculation": settings.EDITEUR_IMMATRICULATION, "directeur_publication": settings.DIRECTEUR_PUBLICATION,
        },
        "validee": settings.PAGES_LEGALES_VALIDEES,
        "date_version": DATE_VERSION_LEGALE,
        # Les prestataires facultatifs ne sont cités que s'ils sont réellement configurés.
        "ia_active": bool(settings.GROQ_API_KEY),
        "supervision_active": bool(settings.SENTRY_DSN),
    }


def mentions_legales(request):
    return render(request, "vitrine/mentions_legales.html", _contexte_legal())


def conditions_utilisation(request):
    return render(request, "vitrine/conditions_utilisation.html", _contexte_legal())


def confidentialite(request):
    return render(request, "vitrine/confidentialite.html", _contexte_legal())
