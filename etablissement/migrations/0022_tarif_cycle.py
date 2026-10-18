import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("etablissement", "0021_bulletin_mensuel_premier_cycle"),
    ]

    operations = [
        migrations.CreateModel(
            name="TarifCycle",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "cycle",
                    models.CharField(
                        help_text="Un cycle de scolarite.models.Cycle (préscolaire, 1er cycle, 2ème cycle, lycée, professionnel).", max_length=20,
                    ),
                ),
                ("mode", models.CharField(choices=[("par_eleve", "Par élève et par an"), ("forfait", "Forfait par an")], max_length=10)),
                (
                    "montant",
                    models.PositiveIntegerField(
                        validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(2000000000)],
                        verbose_name="montant (FCFA)",
                    ),
                ),
                (
                    "etablissement",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tarifs_cycle", to="etablissement.etablissement"),
                ),
            ],
            options={
                "verbose_name": "tarif par cycle",
                "verbose_name_plural": "tarifs par cycle",
                "ordering": ["etablissement", "cycle"],
            },
        ),
        migrations.AddConstraint(
            model_name="tarifcycle",
            constraint=models.UniqueConstraint(fields=("etablissement", "cycle"), name="un_tarif_par_cycle_et_par_ecole"),
        ),
    ]
