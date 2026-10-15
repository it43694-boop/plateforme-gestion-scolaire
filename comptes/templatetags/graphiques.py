"""Balises de gabarit des graphiques (voir comptes.graphiques) : {% graphique_anneau %}, {% graphique_barres %}, {% graphique_colonnes %}."""
from django import template

from comptes import graphiques

register = template.Library()


@register.inclusion_tag("graphiques/anneau.html")
def graphique_anneau(parts, titre=""):
    return {"figure": graphiques.anneau(parts), "titre": titre}


@register.inclusion_tag("graphiques/barres.html")
def graphique_barres(lignes, titre="", unite=""):
    return {"figure": graphiques.barres(lignes, unite=unite), "titre": titre}


@register.inclusion_tag("graphiques/colonnes.html")
def graphique_colonnes(serie, titre="", unite=""):
    return {"figure": graphiques.colonnes(serie, unite=unite), "titre": titre}
