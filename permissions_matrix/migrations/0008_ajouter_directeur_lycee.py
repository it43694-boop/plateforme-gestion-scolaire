from django.db import migrations


def ajouter_directeur_lycee(apps, schema_editor):
    """
    Nouveau rôle Directeur du lycée (cycle Lycée, 10ème à 12ème année),
    ajouté après la mise en place initiale de la matrice : les
    établissements déjà créés n'ont donc aucune ligne pour ce rôle tant
    qu'on ne les rattrape pas explicitement ici - contrairement à un
    établissement créé après ce correctif, qui le reçoit directement via
    PermissionMatrix.seed_pour().
    """
    from permissions_matrix.matrice_par_defaut import MATRICE_PAR_DEFAUT
    from permissions_matrix.modules import Module

    PermissionMatrix = apps.get_model("permissions_matrix", "PermissionMatrix")
    Etablissement = apps.get_model("etablissement", "Etablissement")

    modules_autorises = MATRICE_PAR_DEFAUT[next(
        r for r in MATRICE_PAR_DEFAUT if r.value == "directeur_lycee"
    )]
    lignes = [
        {"role": "directeur_lycee", "module": module.value, "autorise": module in modules_autorises}
        for module in Module
    ]

    objets = []
    for etablissement in Etablissement.objects.all():
        for ligne in lignes:
            objets.append(PermissionMatrix(etablissement=etablissement, **ligne))
    # Couvre aussi les éventuelles lignes historiques sans établissement
    # (installations mono-établissement antérieures au multi-tenant).
    for ligne in lignes:
        objets.append(PermissionMatrix(etablissement=None, **ligne))

    PermissionMatrix.objects.bulk_create(objets, ignore_conflicts=True)


def retirer_directeur_lycee(apps, schema_editor):
    PermissionMatrix = apps.get_model("permissions_matrix", "PermissionMatrix")
    PermissionMatrix.objects.filter(role="directeur_lycee").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("permissions_matrix", "0007_alter_permissionmatrix_role"),
        ("etablissement", "0004_generer_slugs_manquants"),
    ]

    operations = [
        migrations.RunPython(ajouter_directeur_lycee, retirer_directeur_lycee),
    ]
