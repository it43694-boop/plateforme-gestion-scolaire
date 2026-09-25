from django.db import migrations


def ajouter_module_absences(apps, schema_editor):
    PermissionMatrix = apps.get_model("permissions_matrix", "PermissionMatrix")
    PermissionMatrix.objects.filter(
        role__in=["parent", "eleve"], module="absences",
    ).update(autorise=True)


def revenir_en_arriere(apps, schema_editor):
    PermissionMatrix = apps.get_model("permissions_matrix", "PermissionMatrix")
    PermissionMatrix.objects.filter(
        role__in=["parent", "eleve"], module="absences",
    ).update(autorise=False)


class Migration(migrations.Migration):

    dependencies = [
        ("permissions_matrix", "0002_seed_matrice_par_defaut"),
    ]

    operations = [
        migrations.RunPython(ajouter_module_absences, revenir_en_arriere),
    ]
