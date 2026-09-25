from django.db import migrations


def rattacher_annonces_existantes(apps, schema_editor):
    Annonce = apps.get_model("communication", "Annonce")
    for annonce in Annonce.objects.filter(etablissement__isnull=True, auteur__isnull=False).select_related("auteur"):
        if annonce.auteur.etablissement_id:
            annonce.etablissement_id = annonce.auteur.etablissement_id
            annonce.save(update_fields=["etablissement"])


class Migration(migrations.Migration):

    dependencies = [
        ("communication", "0003_annonce_etablissement"),
    ]

    operations = [
        migrations.RunPython(rattacher_annonces_existantes, migrations.RunPython.noop),
    ]
