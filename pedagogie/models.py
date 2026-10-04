import datetime
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction

from comptes.roles import Role
from scolarite.models import Affectation, Classe, Inscription


class Trimestre(models.TextChoices):
    T1 = "trimestre_1", "1er trimestre"
    T2 = "trimestre_2", "2ème trimestre"
    T3 = "trimestre_3", "3ème trimestre"


class Note(models.Model):
    """
    Note finale d'un élève pour une affectation (classe + matière +
    enseignant) donnée, sur un trimestre - jamais de doublon pour un même
    triplet (élève, affectation, trimestre).

    Calculée automatiquement à partir des évaluations saisies (devoirs,
    interrogations, bonus - voir Evaluation et _recalculer_note_trimestre),
    pondérées selon Affectation.poids_devoirs/poids_interrogations/
    poids_bonus : un enseignant ne modifie plus jamais ce champ
    directement, il saisit des évaluations individuelles.
    """

    eleve = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.CASCADE, related_name="notes",
        limit_choices_to={"role": Role.ELEVE},
    )
    affectation = models.ForeignKey(Affectation, on_delete=models.PROTECT, related_name="notes")
    trimestre = models.CharField(max_length=20, choices=Trimestre.choices)
    valeur = models.DecimalField(max_digits=4, decimal_places=2)

    enregistre_par = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.SET_NULL, null=True, related_name="notes_saisies",
    )
    saisie_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "note"
        verbose_name_plural = "notes"
        unique_together = ("eleve", "affectation", "trimestre")
        ordering = ["-modifie_le"]

    def __str__(self):
        return f"{self.eleve.nom_complet} - {self.affectation.matiere or 'Titulaire'} - {self.get_trimestre_display()} : {self.valeur}/20"

    def clean(self):
        super().clean()
        if self.eleve_id and self.eleve.role != Role.ELEVE:
            raise ValidationError("Seul un élève peut recevoir une note.")
        if not (0 <= self.valeur <= 20):
            raise ValidationError("La note doit être comprise entre 0 et 20.")
        if self.affectation_id and self.eleve_id:
            if self.eleve.etablissement_id != self.affectation.classe.annee_scolaire.etablissement_id:
                raise ValidationError("L'élève et l'affectation doivent appartenir au même établissement.")
            inscrit = Inscription.objects.filter(
                eleve_id=self.eleve_id, classe_id=self.affectation.classe_id,
            ).exists()
            if not inscrit:
                raise ValidationError("Cet élève n'est pas inscrit dans la classe de cette affectation.")


def saisir_note(*, eleve, affectation, trimestre, valeur, enseignant):
    """
    Enregistre ou corrige une note. Seul l'enseignant de l'affectation (ou
    un rôle à accès total) peut noter - vérifié en amont par la vue/le
    décorateur de module ; ici on vérifie explicitement l'affectation.
    """
    if enseignant.role == Role.ENSEIGNANT and affectation.enseignant_id != enseignant.id:
        raise ValidationError("Vous n'êtes pas l'enseignant affecté à cette matière pour cette classe.")

    with transaction.atomic():
        note = Note.objects.filter(
            eleve=eleve, affectation=affectation, trimestre=trimestre,
        ).first()
        ancienne_valeur = note.valeur if note else None
        if note is None:
            note = Note(
                eleve=eleve, affectation=affectation, trimestre=trimestre,
                valeur=valeur, enregistre_par=enseignant,
            )
        else:
            note.valeur = valeur
            note.enregistre_par = enseignant
        note.full_clean()
        note.save()
        if ancienne_valeur is not None and ancienne_valeur != valeur:
            NoteHistorique.objects.create(note=note, ancienne_valeur=ancienne_valeur, modifiee_par=enseignant)
        return note


class NoteHistorique(models.Model):
    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="historique")
    ancienne_valeur = models.DecimalField(max_digits=4, decimal_places=2)
    modifiee_par = models.ForeignKey("comptes.Utilisateur", on_delete=models.SET_NULL, null=True, related_name="corrections_notes")
    modifiee_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-modifiee_le"]


class TypeEvaluation(models.TextChoices):
    COMPOSITION = "composition", "Composition"
    DEVOIR = "devoir", "Devoir"
    INTERROGATION = "interrogation", "Interrogation"
    BONUS = "bonus", "Bonus"


class Evaluation(models.Model):
    """
    Note individuelle d'un devoir, d'une interrogation ou d'un bonus, pour
    un élève/affectation/trimestre. Plusieurs évaluations du même type
    peuvent coexister dans un trimestre (ex. deux devoirs) : elles sont
    moyennées entre elles, puis combinées aux autres types selon les poids
    de l'affectation (Affectation.poids_devoirs/poids_interrogations/
    poids_bonus) pour produire automatiquement la note finale du trimestre
    (voir _recalculer_note_trimestre, appelée à chaque ajout/suppression).
    """

    eleve = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.CASCADE, related_name="evaluations",
        limit_choices_to={"role": Role.ELEVE},
    )
    affectation = models.ForeignKey(Affectation, on_delete=models.PROTECT, related_name="evaluations")
    trimestre = models.CharField(max_length=20, choices=Trimestre.choices)
    type_evaluation = models.CharField(max_length=20, choices=TypeEvaluation.choices)
    libelle = models.CharField(max_length=100, blank=True, help_text="Exemple : « Devoir sur les fractions ». Facultatif.")
    valeur = models.DecimalField(max_digits=4, decimal_places=2)

    enregistre_par = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.SET_NULL, null=True, related_name="evaluations_saisies",
    )
    saisie_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "évaluation"
        verbose_name_plural = "évaluations"
        ordering = ["-saisie_le"]

    def __str__(self):
        libelle = self.libelle or self.get_type_evaluation_display()
        return f"{self.eleve.nom_complet} - {libelle} - {self.get_trimestre_display()} : {self.valeur}/20"

    def clean(self):
        super().clean()
        if self.eleve_id and self.eleve.role != Role.ELEVE:
            raise ValidationError("Seul un élève peut recevoir une évaluation.")
        if not (0 <= self.valeur <= 20):
            raise ValidationError("La note doit être comprise entre 0 et 20.")
        if self.affectation_id and self.eleve_id:
            if self.eleve.etablissement_id != self.affectation.classe.annee_scolaire.etablissement_id:
                raise ValidationError("L'élève et l'affectation doivent appartenir au même établissement.")
            inscrit = Inscription.objects.filter(
                eleve_id=self.eleve_id, classe_id=self.affectation.classe_id,
            ).exists()
            if not inscrit:
                raise ValidationError("Cet élève n'est pas inscrit dans la classe de cette affectation.")


def _recalculer_note_trimestre(*, eleve, affectation, trimestre, enregistre_par):
    """
    Recalcule la note finale du trimestre à partir de la moyenne, par type,
    des évaluations existantes, combinées selon les poids de l'affectation.
    Un type sans évaluation est exclu du calcul et les poids des types
    restants sont re-proportionnés entre eux - la note reflète ce qui a
    déjà été noté plutôt que de chuter artificiellement tant qu'un type
    (ex. bonus) n'a reçu aucune évaluation.
    """
    poids_par_type = {
        TypeEvaluation.COMPOSITION: affectation.poids_composition,
        TypeEvaluation.DEVOIR: affectation.poids_devoirs,
        TypeEvaluation.INTERROGATION: affectation.poids_interrogations,
        TypeEvaluation.BONUS: affectation.poids_bonus,
    }
    total_pondere, poids_total = Decimal("0"), 0
    for type_evaluation, poids in poids_par_type.items():
        if poids <= 0:
            continue
        valeurs = list(Evaluation.objects.filter(
            eleve=eleve, affectation=affectation, trimestre=trimestre, type_evaluation=type_evaluation,
        ).values_list("valeur", flat=True))
        if not valeurs:
            continue
        moyenne_type = sum(valeurs) / len(valeurs)
        total_pondere += moyenne_type * poids
        poids_total += poids

    if poids_total == 0:
        Note.objects.filter(eleve=eleve, affectation=affectation, trimestre=trimestre).delete()
        return None

    valeur_finale = (total_pondere / poids_total).quantize(Decimal("0.01"))
    return saisir_note(
        eleve=eleve, affectation=affectation, trimestre=trimestre,
        valeur=valeur_finale, enseignant=enregistre_par,
    )


def saisir_evaluation(*, eleve, affectation, trimestre, type_evaluation, valeur, libelle, enseignant):
    """
    Enregistre une nouvelle évaluation (devoir, interrogation ou bonus) et
    recalcule immédiatement la note finale du trimestre qui en découle.
    Contrairement à saisir_note, chaque appel ajoute une évaluation
    distincte plutôt que de corriger la précédente - plusieurs devoirs par
    trimestre sont attendus. Pour corriger une erreur de saisie, voir
    supprimer_evaluation.
    """
    if enseignant.role == Role.ENSEIGNANT and affectation.enseignant_id != enseignant.id:
        raise ValidationError("Vous n'êtes pas l'enseignant affecté à cette matière pour cette classe.")

    with transaction.atomic():
        evaluation = Evaluation(
            eleve=eleve, affectation=affectation, trimestre=trimestre,
            type_evaluation=type_evaluation, valeur=valeur, libelle=libelle, enregistre_par=enseignant,
        )
        evaluation.full_clean()
        evaluation.save()
        _recalculer_note_trimestre(eleve=eleve, affectation=affectation, trimestre=trimestre, enregistre_par=enseignant)
        return evaluation


def supprimer_evaluation(*, evaluation, enseignant):
    """Retire une évaluation et recalcule la note finale du trimestre qui en découlait."""
    if enseignant.role == Role.ENSEIGNANT and evaluation.affectation.enseignant_id != enseignant.id:
        raise ValidationError("Vous n'êtes pas l'enseignant affecté à cette matière pour cette classe.")

    eleve, affectation, trimestre = evaluation.eleve, evaluation.affectation, evaluation.trimestre
    with transaction.atomic():
        evaluation.delete()
        _recalculer_note_trimestre(eleve=eleve, affectation=affectation, trimestre=trimestre, enregistre_par=enseignant)

    class Meta:
        ordering = ["-modifiee_le"]


class VerificationBulletin(models.Model):
    eleve = models.ForeignKey("comptes.Utilisateur", on_delete=models.CASCADE, related_name="bulletins_verifiables")
    inscription = models.ForeignKey("scolarite.Inscription", on_delete=models.PROTECT, related_name="verifications_bulletin")
    jeton = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    cree_le = models.DateTimeField(auto_now_add=True)
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["-cree_le"]


class Absence(models.Model):
    """
    Absence quotidienne d'un élève, saisie par l'enseignant. Historique
    visible par l'élève, son parent, son enseignant et la direction
    (cahier des charges, section Absences).
    """

    eleve = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.CASCADE, related_name="absences",
        limit_choices_to={"role": Role.ELEVE},
    )
    classe = models.ForeignKey(Classe, on_delete=models.CASCADE, related_name="absences")
    date_absence = models.DateField()
    justifiee = models.BooleanField(default=False)
    motif = models.CharField(max_length=255, blank=True)

    enregistre_par = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.SET_NULL, null=True, related_name="absences_saisies",
    )
    saisie_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "absence"
        verbose_name_plural = "absences"
        unique_together = ("eleve", "date_absence")
        ordering = ["-date_absence"]

    def __str__(self):
        etat = "justifiée" if self.justifiee else "non justifiée"
        return f"{self.eleve.nom_complet} - {self.date_absence} ({etat})"

    def clean(self):
        super().clean()
        if self.eleve_id and self.eleve.role != Role.ELEVE:
            raise ValidationError("Seul un élève peut être marqué absent.")
        if self.date_absence and self.date_absence > datetime.date.today():
            raise ValidationError("Impossible de saisir une absence pour une date future.")
        if self.eleve_id and self.classe_id:
            if self.eleve.etablissement_id != self.classe.annee_scolaire.etablissement_id:
                raise ValidationError("L'élève et la classe doivent appartenir au même établissement.")
            if not Inscription.objects.filter(
                eleve_id=self.eleve_id, classe_id=self.classe_id,
            ).exists():
                raise ValidationError("Cet élève n'est pas inscrit dans cette classe.")

class JourSemaine(models.IntegerChoices):
    LUNDI = 0, "Lundi"
    MARDI = 1, "Mardi"
    MERCREDI = 2, "Mercredi"
    JEUDI = 3, "Jeudi"
    VENDREDI = 4, "Vendredi"
    SAMEDI = 5, "Samedi"


class StatutPresencePersonnel(models.TextChoices):
    PRESENT = "present", "Présent"
    ABSENT = "absent", "Absent"
    RETARD = "retard", "En retard"
    CONGE = "conge", "Congé"


class PresencePersonnel(models.Model):
    employe = models.ForeignKey("comptes.Utilisateur", on_delete=models.PROTECT, related_name="presences_personnel")
    etablissement = models.ForeignKey("etablissement.Etablissement", on_delete=models.PROTECT, related_name="presences_personnel")
    date = models.DateField()
    statut = models.CharField(max_length=20, choices=StatutPresencePersonnel.choices)
    heure_arrivee = models.TimeField(null=True, blank=True)
    heure_depart = models.TimeField(null=True, blank=True)
    motif = models.CharField(max_length=255, blank=True)
    saisi_par = models.ForeignKey("comptes.Utilisateur", on_delete=models.PROTECT, related_name="presences_saisies")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["employe", "date"], name="presence_personnel_unique_jour")]

    def clean(self):
        super().clean()
        if self.employe_id and self.employe.etablissement_id != self.etablissement_id:
            raise ValidationError("L'employé et la présence doivent appartenir au même établissement.")


class CreneauEmploiDuTemps(models.Model):
    """
    Créneau hebdomadaire d'une classe. Deux vérifications de cohérence :
    une classe ne peut pas avoir deux cours au même moment, et un
    enseignant ne peut pas être sur deux classes en même temps
    (cahier des charges, section Emploi du temps).
    """

    classe = models.ForeignKey(Classe, on_delete=models.CASCADE, related_name="creneaux")
    affectation = models.ForeignKey(Affectation, on_delete=models.CASCADE, related_name="creneaux")
    jour_semaine = models.IntegerField(choices=JourSemaine.choices)
    heure_debut = models.TimeField()
    heure_fin = models.TimeField()
    salle = models.CharField(max_length=50, blank=True)

    class Meta:
        verbose_name = "créneau d'emploi du temps"
        verbose_name_plural = "créneaux d'emploi du temps"
        ordering = ["jour_semaine", "heure_debut"]

    def __str__(self):
        return (
            f"{self.classe} - {self.get_jour_semaine_display()} "
            f"{self.heure_debut:%H:%M}-{self.heure_fin:%H:%M} - {self.affectation.matiere or 'Titulaire'}"
        )

    def clean(self):
        super().clean()
        if self.heure_fin <= self.heure_debut:
            raise ValidationError("L'heure de fin doit être postérieure à l'heure de début.")
        if self.affectation_id and self.classe_id and self.affectation.classe_id != self.classe_id:
            raise ValidationError("Cette affectation ne correspond pas à cette classe.")
        if self.affectation_id and self.classe_id and (
            self.affectation.classe.annee_scolaire.etablissement_id
            != self.classe.annee_scolaire.etablissement_id
        ):
            raise ValidationError("La classe et l'affectation doivent appartenir au même établissement.")

        chevauchement = models.Q(jour_semaine=self.jour_semaine) & models.Q(
            heure_debut__lt=self.heure_fin, heure_fin__gt=self.heure_debut,
        )

        # Une classe ne peut pas avoir deux créneaux qui se chevauchent.
        conflit_classe = CreneauEmploiDuTemps.objects.filter(
            chevauchement, classe_id=self.classe_id,
        ).exclude(pk=self.pk)
        if conflit_classe.exists():
            raise ValidationError("Cette classe a déjà un créneau à ce moment-là.")

        # Un enseignant ne peut pas être sur deux classes en même temps.
        if self.affectation_id:
            conflit_enseignant = CreneauEmploiDuTemps.objects.filter(
                chevauchement, affectation__enseignant_id=self.affectation.enseignant_id,
            ).exclude(pk=self.pk)
            if conflit_enseignant.exists():
                raise ValidationError("Cet enseignant a déjà un cours ailleurs à ce moment-là.")

        # Une salle (si renseignée) ne peut pas accueillir deux cours en même
        # temps - cloisonné par établissement : une salle "A1" à une école ne
        # doit jamais entrer en conflit avec une salle "A1" d'une autre école.
        if self.salle and self.classe_id:
            conflit_salle = CreneauEmploiDuTemps.objects.filter(
                chevauchement, salle=self.salle,
                classe__annee_scolaire__etablissement_id=self.classe.annee_scolaire.etablissement_id,
            ).exclude(pk=self.pk)
            if conflit_salle.exists():
                raise ValidationError(f"La salle « {self.salle} » est déjà occupée à ce moment-là.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
