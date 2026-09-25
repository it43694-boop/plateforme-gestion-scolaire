from datetime import timedelta

from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from comptes.models import EmailOutbox


class Command(BaseCommand):
    help = "Envoie les emails en attente et réessaie les échecs temporaires."

    def handle(self, *args, **options):
        maintenant = timezone.now()
        messages = EmailOutbox.objects.filter(
            envoye_le__isnull=True,
            prochaine_tentative__lte=maintenant,
            tentatives__lt=5,
        ).filter(
            Q(verrouille_le__isnull=True) | Q(verrouille_le__lt=maintenant - timedelta(minutes=15)),
        ).order_by("cree_le")[:100]
        for candidat in messages:
            with transaction.atomic():
                message = EmailOutbox.objects.select_for_update().filter(
                    pk=candidat.pk,
                    envoye_le__isnull=True,
                    tentatives__lt=5,
                ).filter(
                    Q(verrouille_le__isnull=True) | Q(verrouille_le__lt=maintenant - timedelta(minutes=15)),
                ).first()
                if message is None:
                    continue
                message.verrouille_le = maintenant
                message.save(update_fields=["verrouille_le"])
            try:
                send_mail(
                    message.sujet, message.contenu, message.expediteur,
                    message.destinataires, fail_silently=False,
                )
            except Exception as erreur:
                message.tentatives += 1
                message.derniere_erreur = str(erreur)[:2000]
                message.prochaine_tentative = maintenant + timedelta(minutes=2 ** message.tentatives)
                message.verrouille_le = None
                message.save(update_fields=["tentatives", "derniere_erreur", "prochaine_tentative", "verrouille_le"])
                self.stderr.write(f"Échec email {message.pk}: {erreur}")
            else:
                message.envoye_le = timezone.now()
                message.verrouille_le = None
                message.save(update_fields=["envoye_le", "verrouille_le"])