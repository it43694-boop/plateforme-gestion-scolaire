from django.db import migrations


def ajouter_censeur_surveillant_general(apps, schema_editor):
    """
    Nouveaux rôles Censeur et Surveillant général (propres au Lycée, décret
    n°2011-234/P-RM), ajoutés après la mise en place initiale de la
    matrice : les établissements déjà créés n'ont donc aucune ligne pour
    ces deux rôles tant qu'on ne les rattrape pas explicitement ici -
    contrairement à un établissement créé après ce correctif, qui les
    reçoit directement via PermissionMatrix.seed_pour() (même principe que
    la migration 0008_ajouter_directeur_lycee).
    """
    from permissions_matrix.matrice_par_defaut import MATRICE_PAR_DEFAUT
    from permissions_matrix.modules import Module

    PermissionMatrix = apps.get_model("permissions_matrix", "PermissionMatrix")
    Etablissement = apps.get_model("etablissement", "Etablissement")

    lignes = []
    for role_enum in MATRICE_PAR_DEFAUT:
        if role_enum.value not in {"censeur", "surveillant_general"}:
            continue
        modules_autorises = MATRICE_PAR_DEFAUT[role_enum]
        for module in Module:
            lignes.append({
                "role": role_enum.value, "module": module.value, "autorise": module in modules_autorises,
            })

    objets = []
    for etablissement in Etablissement.objects.all():
        for ligne in lignes:
            objets.append(PermissionMatrix(etablissement=etablissement, **ligne))
    # Couvre aussi les éventuelles lignes historiques sans établissement
    # (installations mono-établissement antérieures au multi-tenant).
    for ligne in lignes:
        objets.append(PermissionMatrix(etablissement=None, **ligne))

    PermissionMatrix.objects.bulk_create(objets, ignore_conflicts=True)


def retirer_censeur_surveillant_general(apps, schema_editor):
    PermissionMatrix = apps.get_model("permissions_matrix", "PermissionMatrix")
    PermissionMatrix.objects.filter(role__in=["censeur", "surveillant_general"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("permissions_matrix", "0010_alter_permissionmatrix_role"),
    ]

    operations = [
        migrations.RunPython(ajouter_censeur_surveillant_general, retirer_censeur_surveillant_general),
    ]
