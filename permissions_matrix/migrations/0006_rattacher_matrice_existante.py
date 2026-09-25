from django.db import migrations


def rattacher_matrice_existante(apps, schema_editor):
    """
    Mise à niveau depuis une installation mono-établissement : la matrice
    de permissions existante (créée avant l'introduction du multi-tenant)
    est rattachée à l'unique établissement, s'il n'y en a qu'un seul.
    """
    PermissionMatrix = apps.get_model("permissions_matrix", "PermissionMatrix")
    Etablissement = apps.get_model("etablissement", "Etablissement")

    if Etablissement.objects.count() == 1:
        etablissement = Etablissement.objects.first()
        PermissionMatrix.objects.filter(etablissement__isnull=True).update(etablissement=etablissement)


class Migration(migrations.Migration):

    dependencies = [
        ("permissions_matrix", "0005_alter_permissionmatrix_options_and_more"),
        ("etablissement", "0004_generer_slugs_manquants"),
    ]

    operations = [
        migrations.RunPython(rattacher_matrice_existante, migrations.RunPython.noop),
    ]
