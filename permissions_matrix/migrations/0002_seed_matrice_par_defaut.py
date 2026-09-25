from django.db import migrations


def creer_matrice_par_defaut(apps, schema_editor):
    from permissions_matrix.matrice_par_defaut import generer_lignes

    PermissionMatrix = apps.get_model("permissions_matrix", "PermissionMatrix")
    lignes = generer_lignes()
    PermissionMatrix.objects.bulk_create(
        [PermissionMatrix(**ligne) for ligne in lignes],
        ignore_conflicts=True,
    )


def supprimer_matrice(apps, schema_editor):
    PermissionMatrix = apps.get_model("permissions_matrix", "PermissionMatrix")
    PermissionMatrix.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("permissions_matrix", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(creer_matrice_par_defaut, supprimer_matrice),
    ]
