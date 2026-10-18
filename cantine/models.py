"""
Cantine scolaire : les formules (tarifs), l'inscription des élèves, les repas servis et les paiements.

Deux façons de payer, au choix de l'école pour chaque formule :
- au mois : tout mois commencé est dû (de l'inscription jusqu'à la fin de l'inscription, ou jusqu'à aujourd'hui) ;
- au repas : chaque repas servi à l'appel du jour est dû.

Un paiement de cantine crée sa ligne de Caisse (comme un paiement de scolarité) ; une annulation ne supprime rien.
"""
from django.core.exceptions import ValidationError
from django.db import models

from comptes.roles import Role
from finances.models import ModePaiement


class ModeCantine(models.TextChoices):
    MENSUEL = "mensuel", "Au mois"
    REPAS = "repas", "Au repas"


class FormuleCantine(models.Model):
    """Un tarif de cantine : « Cantine du midi - 5 000 par mois », « Repas - 300 le repas »."""

    etablissement = models.ForeignKey("etablissement.Etablissement", on_delete=models.PROTECT, related_name="formules_cantine")
    libelle = models.CharField("formule", max_length=120, help_text="Le nom de la formule, tel que les parents le connaissent.")
    mode = models.CharField("paiement", max_length=10, choices=ModeCantine.choices, default=ModeCantine.MENSUEL)
    montant = models.PositiveIntegerField("tarif", help_text="Par mois ou par repas selon le paiement choisi.")
    active = models.BooleanField(default=True, help_text="Une formule désactivée ne se propose plus aux nouvelles inscriptions.")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "formule de cantine"
        verbose_name_plural = "formules de cantine"
        ordering = ["-active", "libelle", "pk"]
        unique_together = ("etablissement", "libelle")

    def __str__(self):
        return self.libelle

    def clean(self):
        super().clean()
        if self.montant is not None and self.montant <= 0:
            raise ValidationError("Le tarif doit être supérieur à zéro.")


class InscriptionCantine(models.Model):
    """
    Un élève inscrit à la cantine pour une année scolaire, avec sa formule. Une inscription se termine (date de fin) mais ne se supprime
    pas : ses repas et ses paiements restent. Un élève ne peut avoir qu'une inscription ouverte par année ; une nouvelle inscription
    reste possible après la fin de la précédente.
    """

    etablissement = models.ForeignKey("etablissement.Etablissement", on_delete=models.PROTECT, related_name="inscriptions_cantine")
    eleve = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.PROTECT, related_name="inscriptions_cantine", limit_choices_to={"role": Role.ELEVE},
    )
    annee_scolaire = models.ForeignKey("scolarite.AnneeScolaire", on_delete=models.PROTECT, related_name="inscriptions_cantine")
    formule = models.ForeignKey(FormuleCantine, on_delete=models.PROTECT, related_name="inscriptions")
    date_debut = models.DateField("à partir du")
    date_fin = models.DateField("jusqu'au", null=True, blank=True)
    cree_par = models.ForeignKey("comptes.Utilisateur", on_delete=models.SET_NULL, null=True, related_name="inscriptions_cantine_creees")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "inscription à la cantine"
        verbose_name_plural = "inscriptions à la cantine"
        ordering = ["eleve__nom", "eleve__prenom", "-date_debut", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["eleve", "annee_scolaire"], condition=models.Q(date_fin__isnull=True), name="cantine_une_inscription_ouverte_par_annee",
            ),
        ]

    def __str__(self):
        return f"{self.eleve.nom_complet} - {self.formule.libelle}"

    @property
    def ouverte(self) -> bool:
        return self.date_fin is None

    def active_le(self, date) -> bool:
        """L'élève mange à la cantine ce jour-là : inscription commencée et pas encore terminée."""
        return self.date_debut <= date and (self.date_fin is None or date <= self.date_fin)

    def clean(self):
        super().clean()
        if self.eleve_id and self.eleve.role != Role.ELEVE:
            raise ValidationError("Seul un élève peut être inscrit à la cantine.")
        if self.date_fin and self.date_debut and self.date_fin < self.date_debut:
            raise ValidationError("La date de fin ne peut pas précéder la date de début.")
        if self.eleve_id and self.eleve.etablissement_id != self.etablissement_id:
            raise ValidationError("L'élève doit appartenir à l'établissement.")
        if self.formule_id and self.formule.etablissement_id != self.etablissement_id:
            raise ValidationError("La formule doit appartenir à l'établissement.")
        if self.annee_scolaire_id and self.annee_scolaire.etablissement_id != self.etablissement_id:
            raise ValidationError("L'année scolaire doit appartenir à l'établissement.")


class RepasCantine(models.Model):
    """Un repas servi à un élève un jour donné (l'appel du jour). Un seul par élève et par jour."""

    inscription = models.ForeignKey(InscriptionCantine, on_delete=models.CASCADE, related_name="repas")
    date_repas = models.DateField()
    saisi_par = models.ForeignKey("comptes.Utilisateur", on_delete=models.SET_NULL, null=True, related_name="repas_cantine_saisis")

    class Meta:
        verbose_name = "repas de cantine"
        verbose_name_plural = "repas de cantine"
        ordering = ["-date_repas", "pk"]
        unique_together = ("inscription", "date_repas")


class PaiementCantine(models.Model):
    """
    Un paiement de cantine, avec son reçu numéroté (CAN-ANNÉE-NNNNNN). Il crée sa ligne de Caisse. L'annulation (direction seulement)
    garde le paiement et sa ligne de Caisse, marqués « annulés ».
    """

    etablissement = models.ForeignKey("etablissement.Etablissement", on_delete=models.PROTECT, related_name="paiements_cantine")
    inscription = models.ForeignKey(InscriptionCantine, on_delete=models.PROTECT, related_name="paiements")
    montant = models.PositiveIntegerField()
    mode_paiement = models.CharField(max_length=20, choices=ModePaiement.choices)
    reference = models.CharField(max_length=30, editable=False)
    date_paiement = models.DateTimeField(auto_now_add=True)
    enregistre_par = models.ForeignKey("comptes.Utilisateur", on_delete=models.SET_NULL, null=True, related_name="paiements_cantine_enregistres")
    annule = models.BooleanField(default=False)
    annule_par = models.ForeignKey("comptes.Utilisateur", on_delete=models.SET_NULL, null=True, blank=True, related_name="paiements_cantine_annules")
    annule_le = models.DateTimeField(null=True, blank=True)
    motif_annulation = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "paiement de cantine"
        verbose_name_plural = "paiements de cantine"
        ordering = ["-date_paiement", "-pk"]
        unique_together = ("etablissement", "reference")

    def __str__(self):
        return f"{self.reference} - {self.montant}"

    def clean(self):
        super().clean()
        if self.montant is not None and self.montant <= 0:
            raise ValidationError("Le montant du paiement doit être strictement positif.")
        if self.inscription_id and self.inscription.etablissement_id != self.etablissement_id:
            raise ValidationError("Le paiement et l'inscription doivent appartenir au même établissement.")
