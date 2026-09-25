from django.db import migrations
from django.utils.text import slugify


def generer_slugs_manquants(apps, schema_editor):
    Etablissement = apps.get_model("etablissement", "Etablissement")
    for etablissement in Etablissement.objects.filter(slug=""):
        base = slugify(etablissement.nom) or "etablissement"
        candidat = base
        suffixe = 2
        while Etablissement.objects.exclude(pk=etablissement.pk).filter(slug=candidat).exists():
            candidat = f"{base}-{suffixe}"
            suffixe += 1
        etablissement.slug = candidat
        etablissement.save(update_fields=["slug"])


class Migration(migrations.Migration):

    dependencies = [
        ("etablissement", "0003_alter_etablissement_options_etablissement_actif_and_more"),
    ]

    operations = [
        migrations.RunPython(generer_slugs_manquants, migrations.RunPython.noop),
    ]
