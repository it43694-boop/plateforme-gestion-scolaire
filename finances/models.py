from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role


def _annee_courante():
    return timezone.now().year


class SequenceReference(models.Model):
    """
    Compteur séquentiel par établissement/préfixe/année pour les références
    de reçu et de dépense (PREFIXE-ANNEE-NNNNNN), incrémenté sous verrou de
    ligne (select_for_update) pour rester sans trou et sans collision même
    en cas d'écritures simultanées.

    Remplace un ancien tirage aléatoire dont la vérification d'unicité
    portait par erreur toujours sur la table MouvementCaisse, y compris pour
    les préfixes REC (paiement) et SAL (salaire) : une collision aurait pu
    lever une IntegrityError non rattrapée plutôt que de réessayer.
    """

    etablissement = models.ForeignKey(
        "etablissement.Etablissement", on_delete=models.PROTECT, related_name="sequences_reference",
        null=True, blank=True,
    )
    prefixe = models.CharField(max_length=10)
    annee = models.PositiveIntegerField()
    dernier_numero = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "séquence de référence"
        verbose_name_plural = "séquences de référence"
        unique_together = ("etablissement", "prefixe", "annee")

    def __str__(self):
        return f"{self.prefixe}-{self.annee} (dernier : {self.dernier_numero})"


def generer_reference(prefixe: str, etablissement) -> str:
    """
    Référence de reçu/dépense séquentielle, format PREFIXE-ANNEE-NNNNNN,
    propre à l'établissement. Doit être appelée à l'intérieur d'un bloc
    transaction.atomic() englobant (c'est le cas à tous les points d'appel) :
    select_for_update() ne verrouille effectivement qu'au sein d'une
    transaction.
    """
    annee = _annee_courante()
    sequence, _ = SequenceReference.objects.select_for_update().get_or_create(
        etablissement=etablissement, prefixe=prefixe, annee=annee,
    )
    sequence.dernier_numero += 1
    sequence.save(update_fields=["dernier_numero"])
    return f"{prefixe}-{annee}-{sequence.dernier_numero:06d}"


class ModePaiement(models.TextChoices):
    ESPECES = "especes", "Espèces"
    MOBILE_MONEY = "mobile_money", "Mobile Money"
    VIREMENT = "virement", "Virement bancaire"
    CHEQUE = "cheque", "Chèque"


class TypeTranche(models.TextChoices):
    INSCRIPTION = "inscription", "Inscription"
    TRANCHE_1 = "tranche_1", "Tranche 1"
    TRANCHE_2 = "tranche_2", "Tranche 2"


class Paiement(models.Model):
    """
    Paiement de scolarité par un élève, pour une tranche donnée de son
    échéancier de classe. Toute création déclenche automatiquement la
    ligne correspondante en Caisse (cahier des charges, section Finances).
    """

    eleve = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.PROTECT, related_name="paiements",
        limit_choices_to={"role": Role.ELEVE},
    )
    etablissement = models.ForeignKey(
        "etablissement.Etablissement", on_delete=models.PROTECT, related_name="paiements",
        null=True, blank=True,
    )
    inscription = models.ForeignKey(
        "scolarite.Inscription", on_delete=models.PROTECT, related_name="paiements",
    )
    tranche = models.CharField(max_length=20, choices=TypeTranche.choices)
    montant = models.PositiveIntegerField()
    mode_paiement = models.CharField(max_length=20, choices=ModePaiement.choices)
    # Unique par établissement (voir Meta), pas globalement : la numérotation
    # séquentielle repart de 1 pour chaque établissement, comme un registre
    # de reçus papier propre à chaque structure.
    reference = models.CharField(max_length=30, editable=False)
    date_paiement = models.DateTimeField(auto_now_add=True)
    enregistre_par = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.SET_NULL, null=True, related_name="paiements_enregistres",
    )

    est_supprime = models.BooleanField(default=False)
    supprime_par = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="paiements_supprimes",
    )
    supprime_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "paiement"
        verbose_name_plural = "paiements"
        ordering = ["-date_paiement"]
        unique_together = ("etablissement", "reference")

    def __str__(self):
        return f"{self.reference} - {self.eleve.nom_complet} - {self.get_tranche_display()}"

    def clean(self):
        super().clean()
        if self.eleve_id and self.eleve.role != Role.ELEVE:
            raise ValidationError("Seul un élève peut être associé à un paiement.")
        if self.inscription_id and self.eleve_id and self.inscription.eleve_id != self.eleve_id:
            raise ValidationError("L'inscription sélectionnée n'appartient pas à cet élève.")
        if self.inscription_id and self.etablissement_id:
            if self.inscription.classe.annee_scolaire.etablissement_id != self.etablissement_id:
                raise ValidationError("Le paiement et l'inscription doivent appartenir au même établissement.")
        if self.montant <= 0:
            raise ValidationError("Le montant du paiement doit être strictement positif.")

    def save(self, *args, **kwargs):
        if not self.etablissement_id and self.eleve_id:
            self.etablissement_id = self.eleve.etablissement_id
        self.full_clean()
        super().save(*args, **kwargs)


class Salaire(models.Model):
    """
    Salaire du personnel, saisi manuellement par période. Marquer un
    salaire « payé » crée automatiquement la dépense correspondante en
    Caisse (cahier des charges, section Finances/Caisse/Salaires).
    """

    class Statut(models.TextChoices):
        EN_ATTENTE = "en_attente", "En attente"
        PAYE = "paye", "Payé"

    employe = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.PROTECT, related_name="salaires",
    )
    etablissement = models.ForeignKey(
        "etablissement.Etablissement", on_delete=models.PROTECT, related_name="salaires",
        null=True, blank=True,
    )
    periode = models.CharField(
        max_length=7, help_text="Format AAAA-MM, exemple : 2026-10",
    )
    montant = models.PositiveIntegerField()
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.EN_ATTENTE)
    # Unique par établissement (voir Meta), pas globalement - même logique que Paiement.reference.
    reference = models.CharField(max_length=30, null=True, blank=True, editable=False)
    date_paiement = models.DateTimeField(null=True, blank=True)

    enregistre_par = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.SET_NULL, null=True, related_name="salaires_enregistres",
    )
    paye_par = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="salaires_payes",
    )

    est_supprime = models.BooleanField(default=False)
    supprime_par = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="salaires_supprimes",
    )
    supprime_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "salaire"
        verbose_name_plural = "salaires"
        unique_together = [("employe", "periode"), ("etablissement", "reference")]
        ordering = ["-periode"]

    def __str__(self):
        return f"{self.employe.nom_complet} - {self.periode} ({self.get_statut_display()})"

    def clean(self):
        super().clean()
        if self.employe_id and self.etablissement_id and self.employe.etablissement_id != self.etablissement_id:
            raise ValidationError("L'employé et le salaire doivent appartenir au même établissement.")
        if self.montant <= 0:
            raise ValidationError("Le montant du salaire doit être strictement positif.")

    def save(self, *args, **kwargs):
        if not self.etablissement_id and self.employe_id:
            self.etablissement_id = self.employe.etablissement_id
        self.full_clean()
        super().save(*args, **kwargs)


class MouvementCaisse(models.Model):
    """
    Registre unique de toute la trésorerie (cahier des charges, section
    Caisse). Toute ligne provient obligatoirement d'un paiement de
    scolarité (entrée) ou d'un salaire marqué payé (sortie) - aucune
    saisie manuelle libre, pour garantir que la Caisse reflète toujours
    exactement les paiements et salaires enregistrés.

    Une suppression de paiement/salaire par la direction n'efface jamais
    la ligne de Caisse : elle est annulée (conservée, marquée « annulée »)
    pour préserver l'intégrité du registre.
    """

    class TypeMouvement(models.TextChoices):
        ENTREE = "entree", "Entrée"
        SORTIE = "sortie", "Sortie"

    type_mouvement = models.CharField(max_length=10, choices=TypeMouvement.choices)
    etablissement = models.ForeignKey(
        "etablissement.Etablissement", on_delete=models.PROTECT, related_name="mouvements_caisse",
        null=True, blank=True,
    )
    montant = models.PositiveIntegerField()
    description = models.CharField(max_length=255)
    # Unique par établissement (voir Meta.constraints), pas globalement - même logique que Paiement.reference.
    reference = models.CharField(max_length=30)
    date_mouvement = models.DateTimeField(auto_now_add=True)

    paiement = models.OneToOneField(
        Paiement, on_delete=models.PROTECT, null=True, blank=True, related_name="mouvement_caisse",
    )
    salaire = models.OneToOneField(
        Salaire, on_delete=models.PROTECT, null=True, blank=True, related_name="mouvement_caisse",
    )

    annule = models.BooleanField(default=False)
    annule_par = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="mouvements_annules",
    )
    annule_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "mouvement de caisse"
        verbose_name_plural = "mouvements de caisse"
        ordering = ["-date_mouvement"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(paiement__isnull=False, salaire__isnull=True)
                    | models.Q(paiement__isnull=True, salaire__isnull=False)
                ),
                name="mouvement_caisse_origine_unique",
            ),
            models.UniqueConstraint(fields=["etablissement", "reference"], name="mouvement_caisse_reference_unique_par_etablissement"),
        ]

    def __str__(self):
        etat = " (annulé)" if self.annule else ""
        devise = getattr(self.etablissement, "code_devise", "FCFA")
        return f"{self.reference} - {self.get_type_mouvement_display()} - {self.montant} {devise}{etat}"

    def clean(self):
        super().clean()
        if bool(self.paiement_id) == bool(self.salaire_id):
            raise ValidationError(
                "Un mouvement de caisse doit provenir d'exactement un paiement OU un salaire."
            )
        origine = self.paiement or self.salaire
        if origine and self.etablissement_id != origine.etablissement_id:
            raise ValidationError("Le mouvement et son origine doivent appartenir au même établissement.")
        if self.montant <= 0:
            raise ValidationError("Le montant du mouvement doit être strictement positif.")

    def save(self, *args, **kwargs):
        if not self.etablissement_id:
            if self.paiement_id:
                self.etablissement_id = self.paiement.etablissement_id
            elif self.salaire_id:
                self.etablissement_id = self.salaire.etablissement_id
        self.full_clean()
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Opérations métier - chaque cascade est atomique (tout ou rien).
# ---------------------------------------------------------------------------

def enregistrer_paiement(*, eleve, inscription, tranche, montant, mode_paiement, enregistre_par):
    """Crée un paiement de scolarité ET sa ligne de Caisse, de façon atomique."""
    with transaction.atomic():
        paiement = Paiement(
            eleve=eleve, inscription=inscription, tranche=tranche, montant=montant,
            mode_paiement=mode_paiement, enregistre_par=enregistre_par,
            reference=generer_reference("REC", eleve.etablissement),
        )
        paiement.full_clean()
        paiement.save()

        MouvementCaisse.objects.create(
            type_mouvement=MouvementCaisse.TypeMouvement.ENTREE,
            montant=montant,
            description=f"Paiement scolarité - {eleve.nom_complet} - {paiement.get_tranche_display()}",
            reference=generer_reference("CAI", paiement.etablissement),
            paiement=paiement,
        )
        return paiement


def corriger_paiement(*, paiement, montant=None, mode_paiement=None, acteur):
    """Corrige un paiement existant et répercute le changement sur sa ligne de Caisse."""
    with transaction.atomic():
        if montant is not None:
            paiement.montant = montant
        if mode_paiement is not None:
            paiement.mode_paiement = mode_paiement
        paiement.full_clean()
        paiement.save()

        mouvement = getattr(paiement, "mouvement_caisse", None)
        if mouvement and not mouvement.annule:
            mouvement.montant = paiement.montant
            mouvement.description = (
                f"Paiement scolarité - {paiement.eleve.nom_complet} - {paiement.get_tranche_display()} "
                f"(corrigé)"
            )
            mouvement.full_clean()
            mouvement.save()
        return paiement


def supprimer_paiement(*, paiement, acteur):
    """Suppression réservée à la direction - annule le paiement ET sa ligne de Caisse (jamais effacées)."""
    if acteur.role not in {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL}:
        raise ValidationError("Seule la direction peut supprimer un paiement.")
    with transaction.atomic():
        paiement.est_supprime = True
        paiement.supprime_par = acteur
        paiement.supprime_le = timezone.now()
        paiement.save(update_fields=["est_supprime", "supprime_par", "supprime_le"])

        mouvement = getattr(paiement, "mouvement_caisse", None)
        if mouvement and not mouvement.annule:
            mouvement.annule = True
            mouvement.annule_par = acteur
            mouvement.annule_le = timezone.now()
            mouvement.save(update_fields=["annule", "annule_par", "annule_le"])


def marquer_salaire_paye(*, salaire, paye_par):
    """Marque un salaire comme payé ET crée la dépense correspondante en Caisse, de façon atomique."""
    if salaire.statut == Salaire.Statut.PAYE:
        raise ValidationError("Ce salaire est déjà marqué comme payé.")
    with transaction.atomic():
        salaire.statut = Salaire.Statut.PAYE
        salaire.date_paiement = timezone.now()
        salaire.paye_par = paye_par
        salaire.reference = generer_reference("SAL", salaire.etablissement)
        salaire.full_clean()
        salaire.save()

        MouvementCaisse.objects.create(
            type_mouvement=MouvementCaisse.TypeMouvement.SORTIE,
            montant=salaire.montant,
            description=f"Salaire - {salaire.employe.nom_complet} - {salaire.periode}",
            reference=generer_reference("CAI", salaire.etablissement),
            salaire=salaire,
        )
        return salaire


def supprimer_salaire(*, salaire, acteur):
    """Suppression réservée à la direction - annule le salaire ET sa ligne de Caisse si déjà payé."""
    if acteur.role not in {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL}:
        raise ValidationError("Seule la direction peut supprimer un salaire.")
    with transaction.atomic():
        salaire.est_supprime = True
        salaire.supprime_par = acteur
        salaire.supprime_le = timezone.now()
        salaire.save(update_fields=["est_supprime", "supprime_par", "supprime_le"])

        mouvement = getattr(salaire, "mouvement_caisse", None)
        if mouvement and not mouvement.annule:
            mouvement.annule = True
            mouvement.annule_par = acteur
            mouvement.annule_le = timezone.now()
            mouvement.save(update_fields=["annule", "annule_par", "annule_le"])
