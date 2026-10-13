from django import template
from django.contrib.humanize.templatetags.humanize import intcomma

register = template.Library()


@register.filter
def montant(valeur):
    """
    Montant lisible : 75000 s'affiche « 75 000 » (espace insécable, séparateur des milliers français), 1460000 s'affiche
    « 1 460 000 ». Une valeur vide reste vide, une valeur qui n'est pas un nombre est rendue telle quelle.
    """
    if valeur is None or valeur == "":
        return ""
    return intcomma(valeur)
