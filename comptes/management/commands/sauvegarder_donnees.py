import os
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

import boto3
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    """
    Sauvegarde de la base de données et des médias vers un dossier local.

    Le plan gratuit utilisé pour ce déploiement (Render) n'offre ni disque
    persistant, ni tâches planifiées (cron) : cette commande ne s'exécute
    donc jamais automatiquement côté serveur. Elle est conçue pour être
    lancée depuis un poste local (celui de l'administrateur), pointée vers
    la base et le bucket médias de production via les mêmes variables
    d'environnement (DATABASE_URL, AWS_*) que celles déjà utilisées pour
    configurer Render - jamais de secret codé en dur ici.

    La fréquence n'est pas gérée par ce fichier : c'est le planificateur du
    système d'exploitation (Tâches planifiées sous Windows, cron sous
    Linux/macOS) qui décide quand relancer cette commande, à l'intervalle
    choisi par l'administrateur.
    """

    help = "Sauvegarde la base de données et les médias vers un dossier local, à planifier soi-même."

    def add_arguments(self, parser):
        parser.add_argument(
            "--destination", required=True,
            help="Dossier local où écrire la sauvegarde (créé automatiquement si besoin).",
        )
        parser.add_argument(
            "--garder-jours", type=int, default=30,
            help="Supprime dans ce dossier les sauvegardes plus anciennes que N jours (défaut 30).",
        )

    def handle(self, *args, **options):
        dossier_parent = Path(options["destination"]).expanduser()
        dossier_parent.mkdir(parents=True, exist_ok=True)

        horodatage = timezone.now().strftime("%Y%m%d_%H%M%S")
        dossier = dossier_parent / f"sauvegarde_{horodatage}"
        dossier.mkdir()

        self._sauvegarder_base_de_donnees(dossier)
        self._sauvegarder_medias(dossier)
        self._purger_anciennes_sauvegardes(dossier_parent, options["garder_jours"])

        self.stdout.write(self.style.SUCCESS(f"Sauvegarde terminée : {dossier}"))

    def _sauvegarder_base_de_donnees(self, dossier):
        config = settings.DATABASES["default"]

        if config["ENGINE"] == "django.db.backends.sqlite3":
            source = Path(config["NAME"])
            if not source.exists():
                self.stdout.write(self.style.WARNING("Base SQLite introuvable, ignorée."))
                return
            shutil.copy2(source, dossier / "base_de_donnees.sqlite3")
            self.stdout.write(self.style.SUCCESS("Base de données (SQLite) copiée."))
            return

        cible = dossier / "base_de_donnees.sql"
        commande = [
            "pg_dump",
            "--host", config["HOST"] or "localhost",
            "--port", str(config["PORT"] or 5432),
            "--username", config["USER"],
            "--format", "plain",
            "--no-owner", "--no-privileges",
            "--file", str(cible),
            config["NAME"],
        ]
        environnement = os.environ.copy()
        if config.get("PASSWORD"):
            environnement["PGPASSWORD"] = config["PASSWORD"]

        try:
            subprocess.run(commande, check=True, env=environnement, capture_output=True, text=True)
        except FileNotFoundError:
            raise CommandError(
                "pg_dump est introuvable sur ce poste. Installez les outils client "
                "PostgreSQL (https://www.postgresql.org/download/), assurez-vous que "
                "pg_dump est accessible depuis une invite de commande, puis relancez "
                "cette commande."
            )
        except subprocess.CalledProcessError as erreur:
            raise CommandError(f"Échec de pg_dump : {erreur.stderr}")
        self.stdout.write(self.style.SUCCESS("Base de données (PostgreSQL) exportée."))

    def _sauvegarder_medias(self, dossier):
        destination_medias = dossier / "medias"
        bucket = os.environ.get("AWS_STORAGE_BUCKET_NAME", "")

        if bucket:
            self._telecharger_bucket_s3(bucket, destination_medias)
            return

        source = Path(settings.MEDIA_ROOT)
        if source.exists() and any(source.iterdir()):
            shutil.copytree(source, destination_medias)
            self.stdout.write(self.style.SUCCESS("Médias (dossier local) copiés."))
        else:
            self.stdout.write(self.style.WARNING("Aucun média local à sauvegarder."))

    def _telecharger_bucket_s3(self, bucket, destination_medias):
        client = boto3.client(
            "s3",
            endpoint_url=os.environ.get("AWS_S3_ENDPOINT_URL") or None,
            region_name=os.environ.get("AWS_S3_REGION_NAME") or None,
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID") or None,
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY") or None,
        )
        destination_medias.mkdir(parents=True, exist_ok=True)

        compte = 0
        paginateur = client.get_paginator("list_objects_v2")
        for page in paginateur.paginate(Bucket=bucket):
            for objet in page.get("Contents", []):
                cle = objet["Key"]
                cible = destination_medias / cle
                cible.parent.mkdir(parents=True, exist_ok=True)
                client.download_file(bucket, cle, str(cible))
                compte += 1
        self.stdout.write(self.style.SUCCESS(f"Médias : {compte} fichier(s) téléchargé(s) depuis « {bucket} »."))

    def _purger_anciennes_sauvegardes(self, dossier_parent, garder_jours):
        limite = timezone.now() - timedelta(days=garder_jours)
        supprimees = 0
        for enfant in dossier_parent.iterdir():
            if not enfant.is_dir() or not enfant.name.startswith("sauvegarde_"):
                continue
            modifie_le = timezone.datetime.fromtimestamp(enfant.stat().st_mtime, tz=timezone.get_current_timezone())
            if modifie_le < limite:
                shutil.rmtree(enfant)
                supprimees += 1
        if supprimees:
            self.stdout.write(self.style.SUCCESS(
                f"{supprimees} ancienne(s) sauvegarde(s) supprimée(s) (plus de {garder_jours} jour(s))."
            ))
