from django.db import migrations


def retirer_classes_enseignant(apps, schema_editor):
    """
    Le module Classes donne accès à la création de classes, à
    l'affectation d'enseignants (y compris soi-même) et au passage de
    classe - des actions d'administration de toute l'école, pas du
    périmètre d'un enseignant. Son accès à ses propres classes ("Mes
    classes", saisie de notes/absences) reste inchangé, couvert par les
    modules Notes/bulletins et Absences.

    Ne touche que les lignes encore à la valeur par défaut d'origine
    (autorise=True) : un établissement qui aurait déjà personnalisé cette
    case depuis l'espace développeur pour la repasser à True volontairement
    n'est pas écrasé par ce correctif.
    """
    PermissionMatrix = apps.get_model("permissions_matrix", "PermissionMatrix")
    PermissionMatrix.objects.filter(role="enseignant", module="classes", autorise=True).update(autorise=False)


def restaurer_classes_enseignant(apps, schema_editor):
    PermissionMatrix = apps.get_model("permissions_matrix", "PermissionMatrix")
    PermissionMatrix.objects.filter(role="enseignant", module="classes").update(autorise=True)


class Migration(migrations.Migration):

    dependencies = [
        ("permissions_matrix", "0008_ajouter_directeur_lycee"),
    ]

    operations = [
        migrations.RunPython(retirer_classes_enseignant, restaurer_classes_enseignant),
    ]
