"""
Les articles de la section « Ressources » (/ressources/) : des guides pratiques pour les directeurs d'école, écrits pour répondre à ce qu'ils cherchent sur Google.

Un article = un gabarit (templates/vitrine/articles/<nom>.html) + une ligne ici. Il apparaît tout seul dans la liste, dans « À lire aussi » et dans le plan du site
(sitemap.xml, avec sa date de dernière modification : mettez `modifie_le` à jour à chaque vraie modification du texte).

Règles d'écriture : des conseils utiles même sans Yelenova ; aucun chiffre, aucune statistique ni aucune loi que l'on ne puisse pas prouver ; la partie
« Comment Yelenova aide » ne décrit que ce que l'application fait réellement, avec ses limites.
"""
import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class Article:
    slug: str
    titre: str  # titre principal de la page et de la balise <title>
    description: str  # description pour Google et pour les partages (160 caractères au plus)
    sujet: str  # étiquette courte affichée dans la liste
    gabarit: str
    publie_le: datetime.date
    modifie_le: datetime.date


ARTICLES = (
    Article(
        slug="reduire-les-impayes-de-scolarite",
        titre="Impayés de scolarité : comment les réduire dans une école privée au Mali",
        description="Échéancier, reçus, relances, Orange Money : sept pratiques simples pour réduire les impayés de scolarité dans une école privée au Mali.",
        sujet="Finances",
        gabarit="vitrine/articles/impayes.html",
        publie_le=datetime.date(2026, 11, 5),
        modifie_le=datetime.date(2026, 11, 5),
    ),
    Article(
        slug="bulletin-scolaire-moyennes-coefficients-rangs",
        titre="Bulletin scolaire : calculer moyennes, coefficients et rangs sans erreur",
        description="Moyenne d'une matière, moyenne générale avec coefficients, rang : comment les calculer et éviter les erreurs de bulletin dans votre école.",
        sujet="Pédagogie",
        gabarit="vitrine/articles/bulletin.html",
        publie_le=datetime.date(2026, 11, 5),
        modifie_le=datetime.date(2026, 11, 5),
    ),
    Article(
        slug="payer-la-scolarite-orange-money-moov-money",
        titre="Payer la scolarité par Orange Money ou Moov Money : le guide pour l'école",
        description="Comment organiser le paiement de la scolarité par Orange Money ou Moov Money : les étapes pour les parents, la vérification, les erreurs à éviter.",
        sujet="Paiements",
        gabarit="vitrine/articles/mobile_money.html",
        publie_le=datetime.date(2026, 11, 5),
        modifie_le=datetime.date(2026, 11, 5),
    ),
)


def article_par_slug(slug):
    return next((article for article in ARTICLES if article.slug == slug), None)
