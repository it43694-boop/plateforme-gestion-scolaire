"""
Crée le tout premier compte développeur à partir de variables d'environnement,
pour les hébergements sans accès shell (ex. plan gratuit Render) où
`python manage.py createsuperuser` n'est pas exécutable.

Ne fait rien si PREMIER_DEVELOPPEUR_EMAIL / PREMIER_DEVELOPPEUR_MOT_DE_PASSE
ne sont pas définies, ou si un superutilisateur existe déjà (idempotent :
un redéploiement ultérieur ne recrée jamais le compte ni ne réinitialise son
mot de passe). Ces deux variables peuvent être retirées de l'hébergeur une
fois le compte créé - elles ne sont plus utilisées ensuite.
"""

import os

from django.contrib.auth.hashers import make_password
from django.db import migrations


def creer_premier_developpeur(apps, schema_editor):
    email = os.environ.get("PREMIER_DEVELOPPEUR_EMAIL")
    mot_de_passe = os.environ.get("PREMIER_DEVELOPPEUR_MOT_DE_PASSE")
    if not email or not mot_de_passe:
        return

    Utilisateur = apps.get_model("comptes", "Utilisateur")
    if Utilisateur.objects.filter(is_superuser=True).exists():
        return

    Utilisateur.objects.create(
        email=email.strip().lower(),
        prenom="Admin",
        nom="Principal",
        role="developpeur",
        statut="actif",
        email_verifie=True,
        is_active=True,
        is_staff=True,
        is_superuser=True,
        password=make_password(mot_de_passe),
    )


def inverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("comptes", "0010_utilisateur_deux_facteurs_actif_and_more"),
    ]
    operations = [
        migrations.RunPython(creer_premier_developpeur, inverse_noop),
    ]
