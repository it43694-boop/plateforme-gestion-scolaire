import datetime
import json

from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils.html import escape
from django_ratelimit.core import ALL
from django_ratelimit.decorators import ratelimit

from comptes.langue import texte_pour_langue
from etablissement.models import Etablissement
from scolarite.recherche import filtrer
from vitrine import ecole_memorisee
from vitrine.articles import ARTICLES, article_par_slug

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


TITRE_PRESENTATION = "Logiciel de gestion scolaire pour les écoles du Mali"
DESCRIPTION_PRESENTATION = (
    "Logiciel de gestion scolaire pour les écoles du Mali : notes, bulletins, paiements, cantine, cartes d'élève "
    "et portail des parents. En français et en arabe."
)


def presentation(request):
    """
    Page de présentation publique, écrite pour être lue par les moteurs de recherche autant que par les directeurs d'école :
    un seul titre principal, des sous-titres qui reprennent ce que l'on cherche (bulletins, paiements Mobile Money, cantine...),
    une foire aux questions et les données structurées de l'éditeur. Elle n'affiche aucune donnée d'école ni de personne et reste
    la même pour tout le monde ; le contact n'apparaît que s'il est configuré dans l'environnement.
    """
    adresse = settings.URL_PUBLIQUE + reverse("vitrine:presentation")
    logo = settings.URL_PUBLIQUE + static("img/logo-yelenova.png")
    donnees = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization", "@id": settings.URL_PUBLIQUE + "/#organisation", "name": settings.NOM_PLATEFORME,
                "url": settings.URL_PUBLIQUE + "/", "logo": logo, "slogan": settings.SLOGAN_PLATEFORME,
            },
            {
                "@type": "SoftwareApplication", "name": settings.NOM_PLATEFORME, "url": adresse,
                "applicationCategory": "EducationalApplication", "operatingSystem": "Web",
                "inLanguage": ["fr", "ar"], "description": DESCRIPTION_PRESENTATION,
                "publisher": {"@id": settings.URL_PUBLIQUE + "/#organisation"},
            },
        ],
    }
    return render(request, "vitrine/presentation.html", {
        "titre_presentation": TITRE_PRESENTATION, "description_presentation": DESCRIPTION_PRESENTATION,
        "adresse_canonique": adresse, "url_publique": settings.URL_PUBLIQUE, "logo_de_partage": logo,
        # « < » est échappé : une donnée ne peut pas refermer la balise <script> qui la contient.
        "donnees_structurees": json.dumps(donnees, ensure_ascii=False).replace("<", "\\u003c"),
    })


# Pages que l'on veut voir sur Google : le plan du site (sitemap.xml) ne liste que celles-ci et les articles (vitrine/articles.py). Les pages légales portent
# « noindex » et n'y figurent pas. Une future page publique s'ajoute ici.
PAGES_A_REFERENCER = ("vitrine:accueil", "vitrine:presentation", "vitrine:ressources")

# Parties de l'application que les moteurs de recherche n'ont pas à parcourir : comptes, données des écoles, outils du propriétaire, pages techniques,
# vérification de documents (/verifier/) et choix d'école. La plupart demandent déjà une connexion ; « /static/ », la présentation et les pages légales
# restent ouvertes (Google a besoin du style pour juger la page, et du « noindex » des pages légales pour les écarter).
PREFIXES_NON_PARCOURUS = (
    "/admin/", "/comptes/", "/scolarite/", "/finances/", "/comptabilite/", "/pedagogie/", "/tests-de-niveau/", "/cantine/", "/assistant/",
    "/plateforme/", "/bibliotheque/", "/communication/", "/statistiques/", "/espace-developpeur/", "/e/", "/ecole/", "/verifier/",
    "/healthz", "/sw.js", "/manifest.webmanifest",
)


def robots(request):
    """robots.txt : ce que les moteurs de recherche ne parcourent pas, et l'adresse du plan du site (toujours celle de l'adresse publique)."""
    lignes = ["User-agent: *"] + [f"Disallow: {prefixe}" for prefixe in PREFIXES_NON_PARCOURUS]
    lignes += ["", f"Sitemap: {settings.URL_PUBLIQUE}/sitemap.xml", ""]
    return HttpResponse("\n".join(lignes), content_type="text/plain; charset=utf-8")


def sitemap(request):
    """sitemap.xml : la liste des pages publiques à faire connaître, avec l'adresse publique principale (jamais celle de l'hébergeur)."""
    pages = [(reverse(nom), None) for nom in PAGES_A_REFERENCER]
    pages += [(reverse("vitrine:article", kwargs={"slug": article.slug}), article.modifie_le) for article in ARTICLES]
    corps = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for chemin, modifie_le in pages:
        date = f"<lastmod>{modifie_le.isoformat()}</lastmod>" if modifie_le else ""  # la date d'un article est celle de sa dernière vraie modification
        corps += f"  <url><loc>{escape(settings.URL_PUBLIQUE + chemin)}</loc>{date}</url>\n"
    corps += "</urlset>\n"
    return HttpResponse(corps, content_type="application/xml; charset=utf-8")


TITRE_RESSOURCES = "Ressources pour les directeurs d'école au Mali"
DESCRIPTION_RESSOURCES = (
    "Guides pratiques pour mieux gérer une école au Mali : réduire les impayés de scolarité, calculer les bulletins, "
    "organiser le paiement par Orange Money ou Moov Money."
)


def ressources(request):
    """La liste des articles : les guides pratiques écrits pour les directeurs d'école (vitrine/articles.py)."""
    adresse = settings.URL_PUBLIQUE + reverse("vitrine:ressources")
    return render(request, "vitrine/ressources.html", {
        "titre_ressources": TITRE_RESSOURCES, "description_ressources": DESCRIPTION_RESSOURCES,
        "adresse_canonique": adresse, "url_publique": settings.URL_PUBLIQUE, "articles": ARTICLES,
        "logo_de_partage": settings.URL_PUBLIQUE + static("img/logo-yelenova.png"),
    })


def article(request, slug):
    """Un article : texte en français (le corps n'est jamais traduit), données structurées « Article » et fil d'Ariane pour Google."""
    courant = article_par_slug(slug)
    if courant is None:
        raise Http404("Article introuvable.")
    adresse = settings.URL_PUBLIQUE + reverse("vitrine:article", kwargs={"slug": courant.slug})
    organisation = {"@id": settings.URL_PUBLIQUE + "/#organisation"}
    donnees = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Article", "headline": courant.titre, "description": courant.description, "inLanguage": "fr",
                "datePublished": courant.publie_le.isoformat(), "dateModified": courant.modifie_le.isoformat(),
                "mainEntityOfPage": {"@type": "WebPage", "@id": adresse},
                "author": {"@type": "Organization", "name": settings.NOM_PLATEFORME, "url": settings.URL_PUBLIQUE + "/"},
                "publisher": organisation,
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Accueil", "item": settings.URL_PUBLIQUE + "/"},
                    {"@type": "ListItem", "position": 2, "name": "Ressources", "item": settings.URL_PUBLIQUE + reverse("vitrine:ressources")},
                    {"@type": "ListItem", "position": 3, "name": courant.titre, "item": adresse},
                ],
            },
        ],
    }
    return render(request, courant.gabarit, {
        "article": courant, "autres_articles": [a for a in ARTICLES if a.slug != courant.slug],
        "adresse_canonique": adresse, "url_publique": settings.URL_PUBLIQUE, "logo_de_partage": settings.URL_PUBLIQUE + static("img/logo-yelenova.png"),
        "donnees_structurees": json.dumps(donnees, ensure_ascii=False).replace("<", "\\u003c"),
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
