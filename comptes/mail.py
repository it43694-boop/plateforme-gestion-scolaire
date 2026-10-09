import logging
import smtplib

import sentry_sdk
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from comptes.models import EmailOutbox

logger = logging.getLogger(__name__)


def diagnostic_smtp() -> dict:
    """
    Réglages SMTP utiles pour comprendre un échec d'envoi (serveur, port,
    identifiant, forme du mot de passe) - JAMAIS le mot de passe lui-même ni un
    morceau de sa valeur : seulement sa longueur et des indicateurs de forme
    (espace ou saut de ligne caché, préfixe public des clés Brevo).
    """
    mot_de_passe = settings.EMAIL_HOST_PASSWORD or ""
    return {
        "hote": settings.EMAIL_HOST, "port": settings.EMAIL_PORT, "tls": settings.EMAIL_USE_TLS,
        "utilisateur": settings.EMAIL_HOST_USER,
        "longueur_mot_de_passe": len(mot_de_passe),
        "mot_de_passe_contient_un_espace_ou_saut_de_ligne": any(c.isspace() for c in mot_de_passe),
        "mot_de_passe_ressemble_a_une_cle_smtp_brevo": mot_de_passe.startswith("xsmtpsib-"),
        "mot_de_passe_ressemble_a_une_cle_api_brevo": mot_de_passe.startswith("xkeysib-"),
    }


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


# Un message à plusieurs destinataires est découpé en lots : les fournisseurs SMTP limitent
# le nombre de destinataires par message, et un seul envoi géant échouerait en bloc.
TAILLE_LOT_DESTINATAIRES = 50


def construire_message(sujet, contenu, expediteur, destinataires):
    """
    Message prêt à envoyer, avec son corps HTML de marque. Utilisé par l'envoi
    synchrone (ci-dessous) et par la file différée (commande envoyer_emails).

    Dès qu'il y a plusieurs destinataires, ils sont en COPIE CACHÉE : un champ « À »
    partagé montrerait à chacun l'adresse de tous les autres (parents et élèves d'une
    annonce à toute l'école). Un destinataire unique reste dans « À », comme avant.
    """
    destinataires = list(destinataires)
    if len(destinataires) > 1:
        email = EmailMultiAlternatives(sujet, contenu, expediteur, to=[expediteur], bcc=destinataires)
    else:
        email = EmailMultiAlternatives(sujet, contenu, expediteur, to=destinataires)
    email.attach_alternative(construire_corps_html(sujet, contenu), "text/html")
    return email


def envoyer_email(*, sujet, contenu, expediteur, destinataires):
    """
    Envoie immédiatement en développement ou met en file en production.

    L'envoi synchrone (EMAIL_ASYNC=False) ne doit jamais faire échouer la
    requête qui l'a déclenché (inscription, mot de passe oublié...) : un
    serveur SMTP lent ou injoignable ne doit produire qu'un email manquant
    (l'utilisateur peut toujours demander un renvoi), jamais un 502 - la
    création du compte, elle, a déjà été validée en base avant cet appel.

    Plusieurs destinataires : un message par lot de TAILLE_LOT_DESTINATAIRES, en copie
    cachée (voir construire_message). Au premier lot en échec on s'arrête : l'échec est
    presque toujours général (serveur injoignable, identifiants refusés) et réessayer
    chaque lot ferait attendre l'utilisateur plusieurs fois le délai d'expiration.
    """
    destinataires = list(destinataires)
    if not destinataires:
        return 0
    lots = [
        destinataires[i:i + TAILLE_LOT_DESTINATAIRES]
        for i in range(0, len(destinataires), TAILLE_LOT_DESTINATAIRES)
    ]
    if settings.EMAIL_ASYNC:
        creees = [
            EmailOutbox.objects.create(sujet=sujet, contenu=contenu, expediteur=expediteur, destinataires=lot)
            for lot in lots
        ]
        return creees[0]
    envoyes = 0
    for lot in lots:
        try:
            envoyes += construire_message(sujet, contenu, expediteur, lot).send()
        except (smtplib.SMTPException, TimeoutError, OSError) as erreur:
            diagnostic = diagnostic_smtp()
            # Dans Sentry (contexte « smtp ») et dans les logs de l'hébergeur : sans ces
            # lignes, un envoi qui échoue ne laisse aucune trace exploitable.
            logger.error(
                "Échec d'envoi d'email (%s) : %s | configuration : %s", type(erreur).__name__, erreur, diagnostic,
            )
            sentry_sdk.set_context("smtp", diagnostic)
            sentry_sdk.capture_exception()
            break
    return envoyes
