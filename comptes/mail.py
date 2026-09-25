from django.conf import settings
from django.core.mail import send_mail

from comptes.models import EmailOutbox


def envoyer_email(*, sujet, contenu, expediteur, destinataires):
    """Envoie immédiatement en développement ou met en file en production."""
    if settings.EMAIL_ASYNC:
        return EmailOutbox.objects.create(
            sujet=sujet,
            contenu=contenu,
            expediteur=expediteur,
            destinataires=list(destinataires),
        )
    return send_mail(sujet, contenu, expediteur, list(destinataires))