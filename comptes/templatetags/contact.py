from django import template

from comptes.utils import lien_whatsapp

register = template.Library()


@register.simple_tag
def whatsapp(telephone, message):
    return lien_whatsapp(telephone, message)
