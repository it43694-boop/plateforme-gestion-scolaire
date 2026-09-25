from django.db import migrations


def retirer_suivi_des_cours_enseignant(apps, schema_editor):
    """
    Le cahier des charges décrit le module Suivi des cours comme une
    « vue d'ensemble direction » — pas un accès enseignant. Corrige le
    seed initial qui l'accordait par erreur au rôle enseignant.
    """
    PermissionMatrix = apps.get_model("permissions_matrix", "PermissionMatrix")
    PermissionMatrix.objects.filter(role="enseignant", module="suivi_des_cours").update(autorise=False)


def revenir_en_arriere(apps, schema_editor):
    PermissionMatrix = apps.get_model("permissions_matrix", "PermissionMatrix")
    PermissionMatrix.objects.filter(role="enseignant", module="suivi_des_cours").update(autorise=True)


class Migration(migrations.Migration):

    dependencies = [
        ("permissions_matrix", "0003_correction_absences_parent_eleve"),
    ]

    operations = [
        migrations.RunPython(retirer_suivi_des_cours_enseignant, revenir_en_arriere),
    ]
