from django.db import migrations


def rattacher_documents_existants(apps, schema_editor):
    Document = apps.get_model("bibliotheque", "Document")
    for document in Document.objects.filter(etablissement__isnull=True, ajoute_par__isnull=False).select_related("ajoute_par"):
        if document.ajoute_par.etablissement_id:
            document.etablissement_id = document.ajoute_par.etablissement_id
            document.save(update_fields=["etablissement"])


class Migration(migrations.Migration):

    dependencies = [
        ("bibliotheque", "0003_document_etablissement"),
    ]

    operations = [
        migrations.RunPython(rattacher_documents_existants, migrations.RunPython.noop),
    ]
