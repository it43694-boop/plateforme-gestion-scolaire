from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from comptes.roles import Role


class Cycle(models.TextChoices):
    """Cycles de l'enseignement fondamental malien (cf. cahier des charges)."""
    PREMIER_CYCLE = "1er_cycle", "1er cycle (1ère à 6ème année)"
    DEUXIEME_CYCLE = "2eme_cycle", "2ème cycle (7ème à 9ème année)"


# Correspondance rôle de direction cloisonné -> cycle qu'il supervise.
CYCLE_PAR_ROLE_DIRECTION = {
    Role.DIRECTEUR_1ER_CYCLE.value: Cycle.PREMIER_CYCLE.value,
    Role.DIRECTEUR_2EME_CYCLE.value: Cycle.DEUXIEME_CYCLE.value,
}

# Rôles ayant une vue sur tous les cycles sans restriction (matrice de
# permissions mise à part - voir permissions_matrix pour l'accès au module).
ROLES_VISION_TOUS_CYCLES = {
    Role.DEVELOPPEUR.value, Role.FONDATEUR.value, Role.ADMINISTRATEUR_GENERAL.value,
    Role.SUPER_ADMINISTRATEUR.value, Role.COMPTABLE.value, Role.SECRETAIRE.value,
    Role.RESPONSABLE_PEDAGOGIQUE.value,
}


class AnneeScolaire(models.Model):
    """
    Une année scolaire (ex. « 2026-2027 »), propre à un établissement.
    Les années passées restent consultables avec leurs propres effectifs
    et leurs propres frais, même si les tarifs ont changé depuis (cahier
    des charges, section Statistiques).
    """

    etablissement = models.ForeignKey(
        "etablissement.Etablissement", on_delete=models.PROTECT, related_name="annees_scolaires",
        null=True, blank=True,
    )
    libelle = models.CharField(max_length=20, help_text="Exemple : 2026-2027")
    date_debut = models.DateField()
    date_fin = models.DateField()
    est_active = models.BooleanField(
        default=False,
        help_text="Une seule année scolaire active à la fois par établissement.",
    )
    est_archivee = models.BooleanField(
        default=False,
        help_text="Une année archivée reste consultable mais ne reçoit plus de nouvelles écritures.",
    )

    class Meta:
        verbose_name = "année scolaire"
        verbose_name_plural = "années scolaires"
        unique_together = ("etablissement", "libelle")
        ordering = ["-date_debut"]

    def __str__(self):
        return self.libelle

    def clean(self):
        super().clean()
        if self.date_fin <= self.date_debut:
            raise ValidationError("La date de fin doit être postérieure à la date de début.")

    def verifier_mutable(self):
        if self.est_archivee:
            raise ValidationError("Cette année scolaire est archivée et ne peut plus être modifiée.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
        if self.est_active:
            # Une seule année active à la fois, PAR ÉTABLISSEMENT : on ne
            # désactive jamais celle d'un autre établissement.
            AnneeScolaire.objects.filter(etablissement=self.etablissement).exclude(pk=self.pk).update(est_active=False)

    @classmethod
    def active(cls, etablissement):
        return cls.objects.filter(etablissement=etablissement, est_active=True).first()


# Valeurs de repli quand aucun établissement n'est résolvable (ex. données
# de test construites sans établissement) : mêmes valeurs que le défaut du
# champ Etablissement.pas_montant, pour un comportement inchangé.
PAS_MONTANT = 5000
DEVISE_PAR_DEFAUT = "FCFA"


def valider_multiple_de_5000(valeur):
    # Conservée pour les migrations historiques qui la référencent par son
    # chemin d'import (scolarite.models.valider_multiple_de_5000) - ne plus
    # utiliser sur un champ : la validation par pas se fait maintenant dans
    # EcheancierFrais.clean(), avec le pas propre à l'établissement de la
    # classe plutôt qu'une valeur globale figée.
    if valeur % PAS_MONTANT != 0:
        raise ValidationError(f"Le montant doit être un multiple de {PAS_MONTANT} {DEVISE_PAR_DEFAUT}.")


class Classe(models.Model):
    """
    Une classe est unique par nom ET par année scolaire (multi-années) :
    « 3ème année A » en 2026-2027 est un enregistrement distinct de
    « 3ème année A » en 2027-2028.
    """

    nom = models.CharField(max_length=60, help_text="Exemple : 3ème année A")
    cycle = models.CharField(max_length=20, choices=Cycle.choices)
    annee_scolaire = models.ForeignKey(
        AnneeScolaire, on_delete=models.PROTECT, related_name="classes",
    )
    classe_suivante = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="classes_precedentes",
        help_text="Classe vers laquelle les élèves admis de cette classe sont promus l'année suivante. "
                   "Mémorisée pour ne pas avoir à la ressaisir chaque année.",
    )

    class Meta:
        verbose_name = "classe"
        verbose_name_plural = "classes"
        unique_together = ("nom", "annee_scolaire")
        ordering = ["annee_scolaire", "cycle", "nom"]

    def __str__(self):
        return f"{self.nom} ({self.annee_scolaire.libelle})"

    @property
    def effectif(self):
        return self.inscriptions.filter(statut=Inscription.Statut.EN_COURS).count()


class EcheancierFrais(models.Model):
    """
    Frais de scolarité en 3 tranches pour une classe donnée.
    Saisie par pas de montant (5000 par défaut, configurable par
    établissement via Etablissement.pas_montant), sans plafond (chaque
    établissement fixe librement ses propres tarifs).
    """

    classe = models.OneToOneField(Classe, on_delete=models.CASCADE, related_name="echeancier")
    montant_inscription = models.PositiveIntegerField()
    montant_tranche_1 = models.PositiveIntegerField()
    montant_tranche_2 = models.PositiveIntegerField()

    class Meta:
        verbose_name = "échéancier de frais"
        verbose_name_plural = "échéanciers de frais"

    def __str__(self):
        return f"Frais - {self.classe}"

    def _pas_et_devise(self):
        etablissement = getattr(self.classe.annee_scolaire, "etablissement", None) if self.classe_id else None
        if etablissement is None:
            return PAS_MONTANT, DEVISE_PAR_DEFAUT
        return etablissement.pas_montant, etablissement.code_devise

    def clean(self):
        super().clean()
        pas, devise = self._pas_et_devise()
        erreurs = {}
        for champ in ["montant_inscription", "montant_tranche_1", "montant_tranche_2"]:
            valeur = getattr(self, champ, None)
            if valeur is not None and valeur % pas != 0:
                erreurs[champ] = f"Doit être un multiple de {pas} {devise}."
        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def total_annuel(self):
        return self.montant_inscription + self.montant_tranche_1 + self.montant_tranche_2


class Affectation(models.Model):
    """Affectation d'un enseignant à une classe (et, en option, à une matière)."""

    enseignant = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.CASCADE, related_name="affectations",
        limit_choices_to={"role": Role.ENSEIGNANT},
    )
    classe = models.ForeignKey(Classe, on_delete=models.CASCADE, related_name="affectations")
    matiere = models.CharField(max_length=100, blank=True, help_text="Laisser vide si professeur titulaire.")
    coefficient = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1)],
        help_text="Poids de cette matière dans le calcul de la moyenne du bulletin. "
                   "1 par défaut (toutes les matières comptent également) ; augmentez pour une matière "
                   "à plus fort coefficient (ex. Mathématiques, Français).",
    )

    class Meta:
        verbose_name = "affectation d'enseignant"
        verbose_name_plural = "affectations d'enseignants"
        unique_together = ("enseignant", "classe", "matiere")

    def clean(self):
        super().clean()
        if self.enseignant_id and self.enseignant.role != Role.ENSEIGNANT:
            raise ValidationError("Seul un utilisateur avec le rôle « enseignant » peut être affecté.")
        if self.enseignant_id and self.classe_id and self.enseignant.etablissement_id != self.classe.annee_scolaire.etablissement_id:
            raise ValidationError("L'enseignant et la classe doivent appartenir au même établissement.")

    def __str__(self):
        libelle_matiere = self.matiere or "Titulaire"
        return f"{self.enseignant.nom_complet} - {self.classe} ({libelle_matiere})"


class Inscription(models.Model):
    """
    Lien entre un élève et une classe pour une année scolaire donnée
    (l'année scolaire est portée par la classe).
    """

    class Statut(models.TextChoices):
        EN_COURS = "en_cours", "En cours"
        ADMIS = "admis", "Admis (année suivante)"
        REDOUBLE = "redouble", "Redouble"
        TRANSFERE = "transfere", "Transféré / parti"

    eleve = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.CASCADE, related_name="inscriptions",
        limit_choices_to={"role": Role.ELEVE},
    )
    classe = models.ForeignKey(Classe, on_delete=models.PROTECT, related_name="inscriptions")
    date_inscription = models.DateField(auto_now_add=True)
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.EN_COURS)

    class Meta:
        verbose_name = "inscription"
        verbose_name_plural = "inscriptions"
        unique_together = ("eleve", "classe")
        ordering = ["-date_inscription"]

    def __str__(self):
        return f"{self.eleve.nom_complet} - {self.classe}"

    def clean(self):
        super().clean()
        if self.eleve_id and self.eleve.role != Role.ELEVE:
            raise ValidationError("Seul un utilisateur avec le rôle « élève » peut être inscrit.")
        if self.eleve_id and self.classe_id and self.eleve.etablissement_id != self.classe.annee_scolaire.etablissement_id:
            raise ValidationError("L'élève et la classe doivent appartenir au même établissement.")
        if self.classe_id:
            deja_inscrit = Inscription.objects.filter(
                eleve_id=self.eleve_id, classe__annee_scolaire=self.classe.annee_scolaire,
            ).exclude(pk=self.pk)
            if deja_inscrit.exists():
                raise ValidationError(
                    "Cet élève est déjà inscrit dans une classe pour cette année scolaire."
                )

    def save(self, *args, **kwargs):
        self.classe.annee_scolaire.verifier_mutable()
        self.full_clean()
        super().save(*args, **kwargs)


class TypeAideScolarite(models.TextChoices):
    BOURSE = "bourse", "Bourse"
    REDUCTION = "reduction", "Réduction"
    EXONERATION = "exoneration", "Exonération"


class AideScolarite(models.Model):
    inscription = models.ForeignKey(Inscription, on_delete=models.PROTECT, related_name="aides_scolarite")
    type_aide = models.CharField(max_length=20, choices=TypeAideScolarite.choices)
    montant = models.PositiveIntegerField(default=0)
    pourcentage = models.PositiveSmallIntegerField(default=0)
    motif = models.CharField(max_length=255)
    accordee_par = models.ForeignKey("comptes.Utilisateur", on_delete=models.PROTECT, related_name="aides_accordees")
    cree_le = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(default=True)

    def clean(self):
        super().clean()
        if self.montant and self.pourcentage:
            raise ValidationError("Une aide utilise soit un montant, soit un pourcentage.")
        if self.pourcentage > 100:
            raise ValidationError("Le pourcentage ne peut pas dépasser 100.")
        if self.inscription_id and self.accordee_par_id and self.inscription.classe.annee_scolaire.etablissement_id != self.accordee_par.etablissement_id:
            raise ValidationError("L'aide et l'inscription doivent appartenir au même établissement.")


def calculer_total_du(inscription):
    """Calcule le net dû en tenant compte des aides actives de l'inscription."""
    echeancier = getattr(inscription.classe, "echeancier", None)
    brut = echeancier.total_annuel if echeancier else 0
    remise = 0
    for aide in inscription.aides_scolarite.filter(active=True):
        remise += aide.montant or round(brut * aide.pourcentage / 100)
    return max(brut - remise, 0)


class TransfertEleve(models.Model):
    inscription = models.OneToOneField(Inscription, on_delete=models.PROTECT, related_name="transfert")
    etablissement_destination = models.ForeignKey(
        "etablissement.Etablissement", on_delete=models.PROTECT, null=True, blank=True,
        related_name="transferts_recus",
    )
    destination_libelle = models.CharField(max_length=255, blank=True)
    date_transfert = models.DateField()
    motif = models.CharField(max_length=255)
    justificatif = models.FileField(upload_to="transferts/", blank=True)
    enregistre_par = models.ForeignKey("comptes.Utilisateur", on_delete=models.PROTECT, related_name="transferts_enregistres")
    cree_le = models.DateTimeField(auto_now_add=True)


# ---------------------------------------------------------------------------
# Fonctions utilitaires - cloisonnement par cycle et dossier élève
# ---------------------------------------------------------------------------

def classes_visibles_pour(utilisateur):
    """
    Retourne le queryset de classes visibles pour un utilisateur donné :
    toujours limité à SON établissement, puis, en plus, cloisonné par
    cycle pour les directeurs de cycle.
    """
    queryset = Classe.objects.filter(
        annee_scolaire__etablissement=utilisateur.etablissement_id,
    ).select_related("annee_scolaire")
    cycle_impose = CYCLE_PAR_ROLE_DIRECTION.get(utilisateur.role)
    if cycle_impose:
        return queryset.filter(cycle=cycle_impose)
    return queryset


def passer_eleve(*, inscription, decision, classe_destination=None):
    """
    Clôt une inscription (statut Admis/Redouble/Transféré) et, sauf
    transfert, crée la nouvelle inscription de l'élève dans la classe de
    destination pour l'année suivante. Utilisé par le passage de classe.
    """
    from django.core.exceptions import ValidationError
    from django.db import transaction

    if decision not in {Inscription.Statut.ADMIS, Inscription.Statut.REDOUBLE, Inscription.Statut.TRANSFERE}:
        raise ValidationError("Décision de passage invalide.")
    if decision != Inscription.Statut.TRANSFERE and classe_destination is None:
        raise ValidationError("Une classe de destination est requise, sauf en cas de transfert.")
    if classe_destination is not None:
        if classe_destination.annee_scolaire.etablissement_id != inscription.classe.annee_scolaire.etablissement_id:
            raise ValidationError("La classe de destination doit appartenir au même établissement.")
        if classe_destination.annee_scolaire.date_debut <= inscription.classe.annee_scolaire.date_debut:
            raise ValidationError("La classe de destination doit appartenir à une année ultérieure.")
    if inscription.statut != Inscription.Statut.EN_COURS:
        raise ValidationError("Cette inscription a déjà fait l'objet d'une décision.")

    with transaction.atomic():
        inscription.statut = decision
        inscription.save(update_fields=["statut"])
        if decision != Inscription.Statut.TRANSFERE:
            Inscription.objects.create(
                eleve=inscription.eleve, classe=classe_destination, statut=Inscription.Statut.EN_COURS,
            )


def lier_parent_a_eleve(eleve, parent):
    """
    Lie un parent à un élève (jusqu'à 2 parents maximum), et complète
    automatiquement le téléphone de l'élève à partir de celui du parent
    si l'élève n'en a pas encore (cahier des charges, section Comptes parents).
    """
    if eleve.role != Role.ELEVE:
        raise ValidationError("Seul un élève peut avoir des parents liés.")
    if parent.role != Role.PARENT:
        raise ValidationError("Seul un utilisateur avec le rôle « parent » peut être lié comme parent.")
    if eleve.parents_lies.exclude(pk=parent.pk).count() >= 2:
        raise ValidationError("Un élève ne peut pas avoir plus de 2 parents liés.")
    if eleve.etablissement_id != parent.etablissement_id:
        raise ValidationError("L'élève et le parent doivent appartenir au même établissement.")

    eleve.parents_lies.add(parent)


def dossier_complet(eleve) -> bool:
    if eleve.role != Role.ELEVE:
        return False
    return bool(
        eleve.date_naissance and eleve.telephone_effectif and eleve.parents_lies.exists()
    )


def eleve_visible_pour(utilisateur, eleve) -> bool:
    """
    Règle de visibilité centrale d'un élève, utilisée par les notes, les
    absences et l'Assistant : l'élève lui-même, son ou ses parents, un
    enseignant qui lui enseigne, ou la direction (avec cloisonnement par
    cycle pour les directeurs).
    """
    if utilisateur.pk == eleve.pk:
        return True
    if utilisateur.role == Role.PARENT:
        return eleve.parents_lies.filter(pk=utilisateur.pk).exists()
    if utilisateur.role == Role.ENSEIGNANT:
        return Affectation.objects.filter(
            enseignant=utilisateur, classe__inscriptions__eleve=eleve,
        ).exists()
    classes_ok = classes_visibles_pour(utilisateur)
    return eleve.inscriptions.filter(classe__in=classes_ok).exists()
