"""
Notifications sur le téléphone (Web Push) : chaque notification interne (comptes.Notification) est aussi envoyée aux appareils que la personne a activés.

- Éteint tant que les clés VAPID ne sont pas dans l'environnement (VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY) : aucun bouton, aucun envoi.
- Le contenu voyage chiffré de bout en bout entre le serveur et l'appareil (norme Web Push) : ni Google, ni Apple, ni Mozilla ne le lisent.
- L'envoi se fait dans un fil à part : la page de la personne qui a créé la notification n'attend jamais le service de notification du téléphone.
- Un appareil qui ne répond plus (désinstallé, désabonné) est retiré ; après 5 échecs de suite aussi.
"""
import json
import logging
import threading
from functools import lru_cache

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

logger = logging.getLogger(__name__)

ECHECS_MAXIMUM = 5
LONGUEUR_MAXIMALE_DU_MESSAGE = 160
ADRESSE_PAR_DEFAUT = "/comptes/notifications/"


def push_actif() -> bool:
    return bool(getattr(settings, "PUSH_ACTIF", False))


@lru_cache(maxsize=1)
def _cle_privee(brut: str):
    from py_vapid import Vapid

    return Vapid.from_raw(brut.encode("ascii"))


def adresse_sure(adresse: str) -> str:
    """Une adresse de notre site (qui commence par « / », jamais « // » ni un autre site) ; sinon la liste des notifications."""
    adresse = adresse or ""
    return adresse if adresse.startswith("/") and not adresse.startswith("//") else ADRESSE_PAR_DEFAUT


def charge_de(notification) -> str:
    return json.dumps({
        "titre": notification.titre[:80], "message": notification.message[:LONGUEUR_MAXIMALE_DU_MESSAGE],
        "url": adresse_sure(notification.url), "id": notification.pk,
    }, ensure_ascii=False)


def envoyer_a(abonnement, charge: str) -> bool:
    """Envoie la charge à un appareil ; renvoie True si le service de notification l'a acceptée."""
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info={"endpoint": abonnement.endpoint, "keys": {"p256dh": abonnement.cle_p256dh, "auth": abonnement.cle_auth}},
            data=charge, vapid_private_key=_cle_privee(settings.VAPID_PRIVATE_KEY), vapid_claims={"sub": f"mailto:{settings.VAPID_ADMIN_EMAIL}"},
            ttl=86400, timeout=10,
        )
    except WebPushException as erreur:
        statut = getattr(getattr(erreur, "response", None), "status_code", None)
        if statut in (404, 410):  # l'appareil s'est désabonné ou l'application a été désinstallée
            abonnement.delete()
        else:
            _compter_un_echec(abonnement)
        return False
    except Exception:  # noqa: BLE001 - un envoi raté ne doit jamais faire échouer la suite
        logger.exception("Notification téléphone non envoyée (appareil %s)", getattr(abonnement, "pk", None))
        _compter_un_echec(abonnement)
        return False
    type(abonnement).objects.filter(pk=abonnement.pk).update(dernier_succes=timezone.now(), echecs=0)
    return True


def _compter_un_echec(abonnement):
    modele = type(abonnement)
    modele.objects.filter(pk=abonnement.pk).update(echecs=abonnement.echecs + 1)
    if abonnement.echecs + 1 >= ECHECS_MAXIMUM:
        modele.objects.filter(pk=abonnement.pk).delete()


def envoyer_les_notifications(notifications) -> int:
    """Envoie chaque notification à tous les appareils de son destinataire. Renvoie le nombre d'envois acceptés."""
    from comptes.models import AbonnementPush

    acceptes = 0
    for notification in notifications:
        charge = charge_de(notification)
        for abonnement in AbonnementPush.objects.filter(utilisateur_id=notification.destinataire_id):
            acceptes += envoyer_a(abonnement, charge)
    return acceptes


def programmer_envoi(notifications):
    """Envoie les notifications aux appareils (dans un fil à part en production, tout de suite dans les tests). Sans clés : ne fait rien."""
    notifications = [notification for notification in notifications if notification.pk]
    if not push_actif() or not notifications:
        return

    def travail():
        try:
            envoyer_les_notifications(notifications)
        except Exception:  # noqa: BLE001
            logger.exception("Envoi des notifications sur téléphone interrompu")
        finally:
            close_old_connections()

    if getattr(settings, "PUSH_ASYNC", False):
        threading.Thread(target=travail, daemon=True, name="notifications-telephone").start()
    else:
        travail()


def notifier(destinataires, *, titre, message, url="", etablissement=None):
    """Une notification interne par destinataire (une seule requête) puis l'envoi sur leurs téléphones. Renvoie les notifications créées."""
    from comptes.models import Notification

    destinataires = list({destinataire.pk: destinataire for destinataire in destinataires}.values())
    creees = Notification.objects.bulk_create([
        Notification(destinataire=destinataire, etablissement=etablissement, titre=titre[:200], message=message, url=url[:500])
        for destinataire in destinataires
    ])
    programmer_envoi(creees)
    return creees
