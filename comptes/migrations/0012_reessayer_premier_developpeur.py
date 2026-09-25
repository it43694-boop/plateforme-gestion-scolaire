"""
Rejoue la création du premier compte développeur (voir 0011). Django ne
réexécute jamais une migration déjà appliquée, même si elle n'a rien fait la
première fois (ex. variables d'environnement pas encore définies au moment
du déploiement précédent) - cette migration, jamais encore appliquée, permet
un nouvel essai avec les valeurs actuelles de PREMIER_DEVELOPPEUR_EMAIL /
PREMIER_DEVELOPPEUR_MOT_DE_PASSE.
"""

import os

from django.contrib.auth.hashers import make_password
from django.db import migrations


def creer_premier_developpeur(apps, schema_editor):
    email = os.environ.get("PREMIER_DEVELOPPEUR_EMAIL")
    mot_de_passe = os.environ.get("PREMIER_DEVELOPPEUR_MOT_DE_PASSE")
    if not email or not mot_de_passe:
        print("PREMIER_DEVELOPPEUR_EMAIL/MOT_DE_PASSE absentes : aucun compte créé.")
        return

    Utilisateur = apps.get_model("comptes", "Utilisateur")
    if Utilisateur.objects.filter(is_superuser=True).exists():
        print("Un superutilisateur existe déjà : aucun compte créé.")
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
    print(f"Compte développeur créé : {email.strip().lower()}")


def inverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("comptes", "0011_creer_premier_developpeur"),
    ]
    operations = [
        migrations.RunPython(creer_premier_developpeur, inverse_noop),
    ]
