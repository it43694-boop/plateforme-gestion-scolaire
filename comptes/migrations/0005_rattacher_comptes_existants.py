from django.db import migrations


def rattacher_comptes_existants(apps, schema_editor):
    """
    Mise à niveau depuis une installation mono-établissement : s'il
    n'existe qu'un seul établissement, tous les comptes sans établissement
    lui sont rattachés automatiquement. S'il en existe zéro ou plusieurs,
    impossible de deviner — les comptes concernés resteront à rattacher
    manuellement depuis l'espace développeur.
    """
    Utilisateur = apps.get_model("comptes", "Utilisateur")
    Etablissement = apps.get_model("etablissement", "Etablissement")

    if Etablissement.objects.count() == 1:
        etablissement = Etablissement.objects.first()
        Utilisateur.objects.filter(etablissement__isnull=True).update(etablissement=etablissement)


class Migration(migrations.Migration):

    dependencies = [
        ("comptes", "0004_utilisateur_etablissement"),
        ("etablissement", "0004_generer_slugs_manquants"),
    ]

    operations = [
        migrations.RunPython(rattacher_comptes_existants, migrations.RunPython.noop),
    ]
