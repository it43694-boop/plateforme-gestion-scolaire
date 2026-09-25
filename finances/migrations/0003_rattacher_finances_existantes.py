from django.db import migrations


def rattacher_finances_existantes(apps, schema_editor):
    Paiement = apps.get_model("finances", "Paiement")
    Salaire = apps.get_model("finances", "Salaire")
    MouvementCaisse = apps.get_model("finances", "MouvementCaisse")

    for paiement in Paiement.objects.filter(etablissement__isnull=True).select_related("eleve"):
        if paiement.eleve.etablissement_id:
            paiement.etablissement_id = paiement.eleve.etablissement_id
            paiement.save(update_fields=["etablissement"])

    for salaire in Salaire.objects.filter(etablissement__isnull=True).select_related("employe"):
        if salaire.employe.etablissement_id:
            salaire.etablissement_id = salaire.employe.etablissement_id
            salaire.save(update_fields=["etablissement"])

    for mouvement in MouvementCaisse.objects.filter(etablissement__isnull=True):
        source_etablissement_id = None
        if mouvement.paiement_id:
            source_etablissement_id = mouvement.paiement.etablissement_id
        elif mouvement.salaire_id:
            source_etablissement_id = mouvement.salaire.etablissement_id
        if source_etablissement_id:
            mouvement.etablissement_id = source_etablissement_id
            mouvement.save(update_fields=["etablissement"])


class Migration(migrations.Migration):

    dependencies = [
        ("finances", "0002_mouvementcaisse_etablissement_paiement_etablissement_and_more"),
    ]

    operations = [
        migrations.RunPython(rattacher_finances_existantes, migrations.RunPython.noop),
    ]
