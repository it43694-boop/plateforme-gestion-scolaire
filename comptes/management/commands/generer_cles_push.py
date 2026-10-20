import base64

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from django.core.management.base import BaseCommand
from py_vapid import Vapid


def _b64(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode("ascii")


class Command(BaseCommand):
    help = "Génère une paire de clés pour les notifications sur téléphone (à copier dans les variables d'environnement, une seule fois pour la plateforme)."

    def handle(self, *args, **options):
        vapid = Vapid()
        vapid.generate_keys()
        privee = _b64(vapid.private_key.private_numbers().private_value.to_bytes(32, "big"))
        publique = _b64(vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))
        self.stdout.write("À mettre dans les variables d'environnement de Render (ne perdez pas la clé privée : changer de clés oblige chacun à réactiver ses notifications) :\n")
        self.stdout.write(f"VAPID_PUBLIC_KEY={publique}")
        self.stdout.write(f"VAPID_PRIVATE_KEY={privee}")
        self.stdout.write("VAPID_ADMIN_EMAIL=une adresse courriel de contact (celle de la plateforme)")
        self.stdout.write(self.style.WARNING("\nLa clé privée est un secret : ne la mettez ni dans le code, ni dans un message, ni dans le dépôt."))
