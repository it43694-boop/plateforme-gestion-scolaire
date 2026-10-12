"""
Comptabilité en partie double selon le plan SYSCOHADA révisé : plan comptable, exercices, journaux, écritures.

Principes (comme un vrai livre comptable) :
- chaque écriture est équilibrée (total des débits = total des crédits), vérifié à la création ;
- une écriture n'est jamais modifiée ni supprimée : une erreur se corrige par une écriture de contre-passation ;
- tout est cloisonné par établissement ; une écriture ne peut porter que sur les comptes de son établissement ;
- un exercice clôturé n'accepte plus aucune écriture.
Les montants sont des entiers (FCFA, sans décimales).
"""
import datetime

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class CompteComptable(models.Model):
    """Un compte du plan comptable de l'établissement (SYSCOHADA : classes 1 à 8)."""

    etablissement = models.ForeignKey("etablissement.Etablissement", on_delete=models.PROTECT, related_name="comptes_comptables")
    numero = models.CharField("numéro", max_length=10)
    libelle = models.CharField("intitulé", max_length=200)
    systeme = models.BooleanField(
        "compte du plan SYSCOHADA", default=False,
        help_text="Les comptes du plan de base ne se renomment ni ne se retirent ; vous pouvez ajouter vos propres sous-comptes.",
    )

    class Meta:
        verbose_name = "compte comptable"
        verbose_name_plural = "comptes comptables"
        ordering = ["numero"]
        constraints = [models.UniqueConstraint(fields=["etablissement", "numero"], name="compte_comptable_numero_unique_par_etablissement")]

    def __str__(self):
        return f"{self.numero} - {self.libelle}"

    @property
    def classe(self) -> int:
        return int(self.numero[0])

    def clean(self):
        super().clean()
        if not self.numero.isdigit() or not (2 <= len(self.numero) <= 10) or self.numero[0] not in "12345678":
            raise ValidationError("Le numéro de compte comporte 2 à 10 chiffres et commence par 1 à 8 (classe SYSCOHADA).")


class Exercice(models.Model):
    """Exercice comptable (douze mois en principe). Les exercices d'un établissement ne se chevauchent pas."""

    etablissement = models.ForeignKey("etablissement.Etablissement", on_delete=models.PROTECT, related_name="exercices_comptables")
    libelle = models.CharField("libellé", max_length=60)
    date_debut = models.DateField("début")
    date_fin = models.DateField("fin")
    cloture = models.BooleanField("clôturé", default=False)
    cloture_le = models.DateTimeField(null=True, blank=True)
    cloture_par = models.ForeignKey("comptes.Utilisateur", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        verbose_name = "exercice comptable"
        verbose_name_plural = "exercices comptables"
        ordering = ["-date_debut"]
        constraints = [
            models.UniqueConstraint(fields=["etablissement", "libelle"], name="exercice_libelle_unique_par_etablissement"),
            models.CheckConstraint(condition=models.Q(date_fin__gt=models.F("date_debut")), name="exercice_dates_valides"),
        ]

    def __str__(self):
        return f"{self.libelle} ({self.date_debut:%d/%m/%Y} - {self.date_fin:%d/%m/%Y})"

    def clean(self):
        super().clean()
        if self.date_debut and self.date_fin:
            if self.date_fin <= self.date_debut:
                raise ValidationError("La fin de l'exercice doit être postérieure à son début.")
            if (self.date_fin - self.date_debut).days > 731:
                raise ValidationError("Un exercice ne dépasse pas deux ans (douze mois en principe).")
            if self.etablissement_id:
                chevauche = Exercice.objects.filter(
                    etablissement_id=self.etablissement_id, date_debut__lte=self.date_fin, date_fin__gte=self.date_debut,
                ).exclude(pk=self.pk).first()
                if chevauche:
                    raise ValidationError(f"Cet exercice chevauche « {chevauche.libelle} » : les exercices ne se chevauchent pas.")


class Journal(models.TextChoices):
    CAISSE = "CAI", "Journal de caisse"
    BANQUE = "BQ", "Journal de banque et de monnaie électronique"
    OPERATIONS_DIVERSES = "OD", "Opérations diverses"
    A_NOUVEAUX = "AN", "À-nouveaux (report des soldes)"


class Ecriture(models.Model):
    """En-tête d'une écriture comptable ; ses lignes (LigneEcriture) sont équilibrées. Jamais modifiée ni supprimée."""

    class Origine(models.TextChoices):
        MANUELLE = "manuelle", "Saisie manuelle"
        AUTOMATIQUE = "automatique", "Générée depuis la caisse (paiements, salaires)"
        CONTREPASSATION = "contrepassation", "Contre-passation"
        CLOTURE = "cloture", "Clôture de l'exercice"
        REPORT = "report", "Report à nouveau"

    etablissement = models.ForeignKey("etablissement.Etablissement", on_delete=models.PROTECT, related_name="ecritures_comptables")
    exercice = models.ForeignKey(Exercice, on_delete=models.PROTECT, related_name="ecritures")
    journal = models.CharField(max_length=3, choices=Journal.choices)
    numero = models.CharField("n° d'écriture", max_length=30)
    date_ecriture = models.DateField("date")
    piece = models.CharField("pièce justificative", max_length=60, blank=True)
    libelle = models.CharField("libellé", max_length=255)
    origine = models.CharField(max_length=16, choices=Origine.choices, default=Origine.MANUELLE)

    mouvement_caisse = models.ForeignKey(
        "finances.MouvementCaisse", on_delete=models.PROTECT, null=True, blank=True, related_name="ecritures_comptables",
    )
    contrepasse_de = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="contrepassation",
        help_text="Écriture que celle-ci annule (une écriture ne se contre-passe qu'une fois).",
    )
    report_de = models.ForeignKey(
        Exercice, on_delete=models.PROTECT, null=True, blank=True, related_name="reports_vers_exercice_suivant",
        help_text="Exercice dont cette écriture reporte les soldes (à-nouveaux).",
    )
    cree_par = models.ForeignKey("comptes.Utilisateur", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "écriture comptable"
        verbose_name_plural = "écritures comptables"
        ordering = ["date_ecriture", "id"]
        constraints = [models.UniqueConstraint(fields=["etablissement", "numero"], name="ecriture_numero_unique_par_etablissement")]

    def __str__(self):
        return f"{self.numero} - {self.libelle}"

    @property
    def total(self) -> int:
        return sum(ligne.debit for ligne in self.lignes.all())


class LigneEcriture(models.Model):
    ecriture = models.ForeignKey(Ecriture, on_delete=models.CASCADE, related_name="lignes")
    compte = models.ForeignKey(CompteComptable, on_delete=models.PROTECT, related_name="lignes")
    libelle = models.CharField(max_length=255, blank=True)
    debit = models.BigIntegerField(default=0)
    credit = models.BigIntegerField(default=0)

    class Meta:
        verbose_name = "ligne d'écriture"
        verbose_name_plural = "lignes d'écriture"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(debit__gte=0) & models.Q(credit__gte=0), name="ligne_ecriture_montants_positifs"),
            models.CheckConstraint(condition=models.Q(debit=0) | models.Q(credit=0), name="ligne_ecriture_debit_ou_credit"),
            models.CheckConstraint(condition=models.Q(debit__gt=0) | models.Q(credit__gt=0), name="ligne_ecriture_non_nulle"),
        ]

    def __str__(self):
        return f"{self.compte.numero} D{self.debit} C{self.credit}"
