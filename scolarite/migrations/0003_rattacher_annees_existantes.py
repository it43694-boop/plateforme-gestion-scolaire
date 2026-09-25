from django.db import migrations


def rattacher_annees_existantes(apps, schema_editor):
    AnneeScolaire = apps.get_model("scolarite", "AnneeScolaire")
    Etablissement = apps.get_model("etablissement", "Etablissement")
    if Etablissement.objects.count() == 1:
        etablissement = Etablissement.objects.first()
        AnneeScolaire.objects.filter(etablissement__isnull=True).update(etablissement=etablissement)


class Migration(migrations.Migration):

    dependencies = [
        ("scolarite", "0002_anneescolaire_etablissement_and_more"),
        ("etablissement", "0004_generer_slugs_manquants"),
    ]

    operations = [
        migrations.RunPython(rattacher_annees_existantes, migrations.RunPython.noop),
    ]
