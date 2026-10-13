from django import template

from comptes.entretien import duree_conservation_messages

register = template.Library()


@register.simple_tag
def duree_conservation_messages_jours():
    """Nombre de jours avant l'effacement automatique des messages (0 : jamais), pour le rappeler aux utilisateurs."""
    return duree_conservation_messages()
