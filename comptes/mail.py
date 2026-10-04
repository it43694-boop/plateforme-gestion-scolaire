import smtplib

import sentry_sdk
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from comptes.models import EmailOutbox


def construire_corps_html(sujet, contenu):
    """
    Habille un email en texte brut dans le gabarit de marque de la
    plateforme - utilisé à la fois par l'envoi synchrone (ci-dessous) et
    par la file différée (comptes/management/commands/envoyer_emails.py),
    pour que les deux chemins produisent le même rendu.
    """
    return render_to_string("emails/base_email.html", {
        "sujet": sujet, "contenu": contenu, "nom_plateforme": getattr(settings, "NOM_PLATEFORME", ""),
    })


def envoyer_email(*, sujet, contenu, expediteur, destinataires):
    """
    Envoie immédiatement en développement ou met en file en production.

    L'envoi synchrone (EMAIL_ASYNC=False) ne doit jamais faire échouer la
    requête qui l'a déclenché (inscription, mot de passe oublié...) : un
    serveur SMTP lent ou injoignable ne doit produire qu'un email manquant
    (l'utilisateur peut toujours demander un renvoi), jamais un 502 - la
    création du compte, elle, a déjà été validée en base avant cet appel.
    """
    if settings.EMAIL_ASYNC:
        return EmailOutbox.objects.create(
            sujet=sujet,
            contenu=contenu,
            expediteur=expediteur,
            destinataires=list(destinataires),
        )
    email = EmailMultiAlternatives(sujet, contenu, expediteur, list(destinataires))
    email.attach_alternative(construire_corps_html(sujet, contenu), "text/html")
    try:
        return email.send()
    except (smtplib.SMTPException, TimeoutError, OSError):
        sentry_sdk.capture_exception()
        return 0