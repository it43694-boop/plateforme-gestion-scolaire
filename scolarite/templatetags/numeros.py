from django import template

from scolarite.numeros_cycle import numero_du_cycle as numero

register = template.Library()


@register.filter
def numero_du_cycle(eleve, cycle):
    """`{{ eleve|numero_du_cycle:classe.cycle }}` : le numéro de l'élève dans ce cycle, sinon son matricule d'origine."""
    return numero(eleve, cycle)
