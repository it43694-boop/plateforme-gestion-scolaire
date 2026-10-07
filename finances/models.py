import datetime
from decimal import Decimal

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
    VERSEMENT = "versement", "Versement de scolarité"


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
    periodes_couvertes = models.JSONField(
        default=list, blank=True,
        help_text="Mois ou trimestres couverts par ce versement (ex. ['Janvier 2027', 'Février 2027']) - "
                   "une famille peut régler n'importe quelle combinaison de mois, pas forcément consécutifs. "
                   "Vide pour l'inscription ou un échéancier annuel.",
    )
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
        if self.periodes_couvertes and self.inscription_id:
            echeancier = getattr(self.inscription.classe, "echeancier", None)
            valides = set(echeancier.libelles_periodes()) if echeancier else set()
            invalides = [p for p in self.periodes_couvertes if p not in valides]
            if invalides:
                raise ValidationError(f"Période(s) invalide(s) pour cette classe : {', '.join(invalides)}.")

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
    montant = models.PositiveIntegerField(help_text="Montant net effectivement versé à l'employé.")
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.EN_ATTENTE)
    # Unique par établissement (voir Meta), pas globalement - même logique que Paiement.reference.
    reference = models.CharField(max_length=30, null=True, blank=True, editable=False)
    date_paiement = models.DateTimeField(null=True, blank=True)

    # Détail du bulletin de paie - facultatif (voir creer_bulletin_paie) :
    # un salaire saisi par la voie simple (saisir_salaire_vue) n'a que
    # `montant`, ces champs restent vides. Les parts employeur sont
    # purement informatives (coût réel pour l'établissement) et n'affectent
    # jamais `montant`, qui reste toujours le net versé à l'employé.
    salaire_brut = models.PositiveIntegerField(null=True, blank=True)
    cotisation_inps_salarie = models.PositiveIntegerField(null=True, blank=True)
    cotisation_inps_employeur = models.PositiveIntegerField(null=True, blank=True)
    cotisation_amo_salarie = models.PositiveIntegerField(null=True, blank=True)
    cotisation_amo_employeur = models.PositiveIntegerField(null=True, blank=True)
    its = models.PositiveIntegerField(
        "ITS (impôt sur salaires)", default=0, blank=True,
        help_text="Saisi manuellement - le barème officiel n'est pas calculé automatiquement par l'application.",
    )

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


class TypeContrat(models.TextChoices):
    CDI = "cdi", "CDI"
    CDD = "cdd", "CDD"


class Contrat(models.Model):
    """
    Contrat de travail d'un membre du personnel (poste, type, salaire de
    base). Un seul contrat actif à la fois par employé (voir clean()) -
    un renouvellement ou changement de poste clôture l'ancien (date_fin)
    plutôt que de le supprimer, pour garder l'historique complet.
    """

    employe = models.ForeignKey("comptes.Utilisateur", on_delete=models.PROTECT, related_name="contrats")
    etablissement = models.ForeignKey(
        "etablissement.Etablissement", on_delete=models.PROTECT, related_name="contrats", null=True, blank=True,
    )
    type_contrat = models.CharField(max_length=10, choices=TypeContrat.choices)
    poste = models.CharField(max_length=150)
    date_debut = models.DateField()
    date_fin = models.DateField(null=True, blank=True, help_text="Laisser vide pour un CDI toujours en cours.")
    salaire_base = models.PositiveIntegerField(help_text="Salaire brut mensuel de base.")

    cree_par = models.ForeignKey("comptes.Utilisateur", on_delete=models.PROTECT, related_name="contrats_crees")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "contrat"
        verbose_name_plural = "contrats"
        ordering = ["-date_debut"]

    def __str__(self):
        return f"{self.employe.nom_complet} - {self.get_type_contrat_display()} ({self.poste})"

    @property
    def est_actif(self):
        return self.date_fin is None or self.date_fin >= timezone.now().date()

    def clean(self):
        super().clean()
        if self.employe_id and self.etablissement_id and self.employe.etablissement_id != self.etablissement_id:
            raise ValidationError("L'employé et le contrat doivent appartenir au même établissement.")
        if self.type_contrat == TypeContrat.CDD and not self.date_fin:
            raise ValidationError("Un CDD doit avoir une date de fin.")
        if self.date_fin and self.date_debut and self.date_fin <= self.date_debut:
            raise ValidationError("La date de fin doit être postérieure à la date de début.")
        if self.employe_id and self.est_actif:
            conflit = Contrat.objects.filter(employe_id=self.employe_id).exclude(pk=self.pk).filter(
                models.Q(date_fin__isnull=True) | models.Q(date_fin__gte=timezone.now().date())
            )
            if conflit.exists():
                raise ValidationError(
                    "Cet employé a déjà un contrat actif - clôturez-le (date de fin) avant d'en créer un nouveau."
                )

    def save(self, *args, **kwargs):
        if not self.etablissement_id and self.employe_id:
            self.etablissement_id = self.employe.etablissement_id
        self.full_clean()
        super().save(*args, **kwargs)


def contrat_actif_pour(employe):
    """Le contrat en cours de cet employé, s'il en a un (voir Contrat.est_actif)."""
    return Contrat.objects.filter(employe=employe).filter(
        models.Q(date_fin__isnull=True) | models.Q(date_fin__gte=timezone.now().date())
    ).order_by("-date_debut").first()


class TypeConge(models.TextChoices):
    PAYE = "paye", "Congé payé"
    MALADIE = "maladie", "Congé maladie"
    MATERNITE = "maternite", "Congé maternité"
    AUTRE = "autre", "Autre"


class StatutConge(models.TextChoices):
    EN_ATTENTE = "en_attente", "En attente"
    APPROUVE = "approuve", "Approuvé"
    REFUSE = "refuse", "Refusé"


class DemandeConge(models.Model):
    """Congé d'un membre du personnel, enregistré par la direction/comptabilité."""

    employe = models.ForeignKey("comptes.Utilisateur", on_delete=models.PROTECT, related_name="demandes_conge")
    etablissement = models.ForeignKey(
        "etablissement.Etablissement", on_delete=models.PROTECT, related_name="demandes_conge", null=True, blank=True,
    )
    type_conge = models.CharField(max_length=20, choices=TypeConge.choices)
    date_debut = models.DateField()
    date_fin = models.DateField()
    motif = models.CharField(max_length=255, blank=True)
    statut = models.CharField(max_length=20, choices=StatutConge.choices, default=StatutConge.APPROUVE)

    enregistre_par = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.PROTECT, related_name="demandes_conge_enregistrees",
    )
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "congé"
        verbose_name_plural = "congés"
        ordering = ["-date_debut"]

    def __str__(self):
        return f"{self.employe.nom_complet} - {self.get_type_conge_display()} ({self.date_debut} au {self.date_fin})"

    @property
    def nombre_jours(self):
        """Jours ouvrables (dimanche exclu), inclusif des deux bornes."""
        jours = 0
        curseur = self.date_debut
        while curseur <= self.date_fin:
            if curseur.weekday() != 6:
                jours += 1
            curseur += datetime.timedelta(days=1)
        return jours

    def clean(self):
        super().clean()
        if self.employe_id and self.etablissement_id and self.employe.etablissement_id != self.etablissement_id:
            raise ValidationError("L'employé et le congé doivent appartenir au même établissement.")
        if self.date_debut and self.date_fin and self.date_fin < self.date_debut:
            raise ValidationError("La date de fin doit être postérieure ou égale à la date de début.")

    def save(self, *args, **kwargs):
        if not self.etablissement_id and self.employe_id:
            self.etablissement_id = self.employe.etablissement_id
        self.full_clean()
        super().save(*args, **kwargs)


JOURS_CONGES_PAYES_PAR_MOIS = Decimal("2.5")


def solde_conges_payes(employe, a_la_date=None):
    """
    Solde de congés payés disponible : jours acquis depuis le début du
    contrat en cours (2,5 jours ouvrables par mois complet travaillé,
    conforme au Code du travail malien) moins les jours de congé payé déjà
    approuvés. Simplification volontaire assumée : pas de remise à zéro
    annuelle (voir README) - renvoie 0 si l'employé n'a aucun contrat actif.
    """
    a_la_date = a_la_date or timezone.now().date()
    contrat = contrat_actif_pour(employe)
    if not contrat:
        return 0
    mois_travailles = (a_la_date.year - contrat.date_debut.year) * 12 + (a_la_date.month - contrat.date_debut.month)
    if a_la_date.day < contrat.date_debut.day:
        mois_travailles -= 1
    mois_travailles = max(mois_travailles, 0)
    acquis = JOURS_CONGES_PAYES_PAR_MOIS * mois_travailles

    conges_payes = DemandeConge.objects.filter(
        employe=employe, type_conge=TypeConge.PAYE, statut=StatutConge.APPROUVE, date_debut__gte=contrat.date_debut,
    )
    jours_pris = sum(conge.nombre_jours for conge in conges_payes)
    return float(acquis) - jours_pris


def creer_bulletin_paie(*, employe, periode, salaire_brut, its, enregistre_par):
    """
    Crée un Salaire avec le détail complet du bulletin (brut, cotisations
    INPS/AMO selon les taux configurés pour l'établissement, ITS saisi par
    l'appelant, net calculé). Le net calculé devient `montant` - c'est lui
    qui part en dépense de Caisse une fois le salaire marqué payé (voir
    marquer_salaire_paye), jamais le brut.
    """
    etablissement = employe.etablissement

    def _part(taux_pourcentage):
        return round(Decimal(salaire_brut) * Decimal(str(taux_pourcentage)) / Decimal("100"))

    inps_salarie = _part(etablissement.taux_inps_salarie) if etablissement else 0
    inps_employeur = _part(etablissement.taux_inps_employeur) if etablissement else 0
    amo_salarie = _part(etablissement.taux_amo_salarie) if etablissement else 0
    amo_employeur = _part(etablissement.taux_amo_employeur) if etablissement else 0
    net = salaire_brut - inps_salarie - amo_salarie - its
    if net <= 0:
        raise ValidationError("Le net calculé (brut moins retenues) doit être strictement positif.")

    return Salaire.objects.create(
        employe=employe, etablissement=etablissement, periode=periode, montant=net,
        salaire_brut=salaire_brut, its=its,
        cotisation_inps_salarie=inps_salarie, cotisation_inps_employeur=inps_employeur,
        cotisation_amo_salarie=amo_salarie, cotisation_amo_employeur=amo_employeur,
        enregistre_par=enregistre_par,
    )


# Comptes du plan SYSCOHADA utilisés par le journal de caisse (voir
# MouvementCaisse.compte_contrepartie et finances.views.journal_caisse_
# syscohada) - imputation fixe, puisque chaque mouvement de Caisse ne
# provient que d'exactement deux origines possibles (paiement ou salaire
# payé, voir la contrainte mouvement_caisse_origine_unique ci-dessous).
# Portée volontairement limitée à un journal de caisse exportable, PAS une
# comptabilité en partie double complète (plan de comptes, grand livre,
# bilan) - voir README.
COMPTE_SYSCOHADA_CAISSE = "571"
COMPTE_SYSCOHADA_PRODUITS_SCOLARITE = "706"
COMPTE_SYSCOHADA_CHARGES_PERSONNEL = "661"


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

    @property
    def compte_contrepartie(self):
        """Compte SYSCOHADA de contrepartie de la Caisse pour ce mouvement."""
        if self.type_mouvement == self.TypeMouvement.ENTREE:
            return COMPTE_SYSCOHADA_PRODUITS_SCOLARITE
        return COMPTE_SYSCOHADA_CHARGES_PERSONNEL

    @property
    def debit_caisse(self):
        return self.montant if self.type_mouvement == self.TypeMouvement.ENTREE else 0

    @property
    def credit_caisse(self):
        return self.montant if self.type_mouvement == self.TypeMouvement.SORTIE else 0

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

def enregistrer_paiement(*, eleve, inscription, tranche, montant, mode_paiement, enregistre_par, periodes_couvertes=None):
    """Crée un paiement de scolarité ET sa ligne de Caisse, de façon atomique."""
    with transaction.atomic():
        paiement = Paiement(
            eleve=eleve, inscription=inscription, tranche=tranche, montant=montant,
            mode_paiement=mode_paiement, enregistre_par=enregistre_par,
            periodes_couvertes=periodes_couvertes or [],
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
