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


def _moyenne_matiere(note_classe, note_composition):
    """
    Pratique malienne vérifiée sur des bulletins réels (lycée comme
    fondamental) : la composition trimestrielle compte double - elle est
    notée sur 40, pas 20, précisément pour ça. Moyenne = (classe +
    composition) / 3 (et non / 2), ce qui revient à donner un poids 1 à la
    note de classe et un poids 2 à la composition (40/20 = 2).
    Si une seule des deux est déjà saisie, elle sert seule de moyenne
    provisoire (ramenée sur 20 pour la composition) plutôt que d'attendre
    que les deux soient disponibles.
    """
    if note_classe is not None:
        note_classe = Decimal(str(note_classe))
    if note_composition is not None:
        note_composition = Decimal(str(note_composition))
    if note_classe is not None and note_composition is not None:
        return ((note_classe + note_composition) / 3).quantize(Decimal("0.01"))
    if note_classe is not None:
        return note_classe.quantize(Decimal("0.01"))
    return (note_composition / 2).quantize(Decimal("0.01"))


class Note(models.Model):
    """
    Note d'un élève pour une affectation (classe + matière + enseignant)
    donnée, sur un trimestre - jamais de doublon pour un même triplet
    (élève, affectation, trimestre).

    Conforme à la pratique malienne réelle (vérifiée sur des bulletins
    authentiques, lycée et fondamental) : deux notes distinctes par
    matière et par trimestre - la Note de Classe (contrôle continu, sur
    20) et la Note de Composition (examen trimestriel, sur 40). `valeur`
    (la moyenne de la matière, sur 20, affichée sur le bulletin) se
    calcule automatiquement - voir _moyenne_matiere.
    """

    eleve = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.CASCADE, related_name="notes",
        limit_choices_to={"role": Role.ELEVE},
    )
    affectation = models.ForeignKey(Affectation, on_delete=models.PROTECT, related_name="notes")
    trimestre = models.CharField(max_length=20, choices=Trimestre.choices)
    note_classe = models.DecimalField(
        "note de classe", max_digits=4, decimal_places=2, null=True, blank=True,
        help_text="Sur 20 (contrôle continu).",
    )
    note_composition = models.DecimalField(
        "note de composition", max_digits=5, decimal_places=2, null=True, blank=True,
        help_text="Sur 40 (examen trimestriel - compte double dans la moyenne).",
    )
    valeur = models.DecimalField(max_digits=4, decimal_places=2, help_text="Moyenne de la matière, sur 20 - calculée automatiquement.")

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
        if self.note_classe is None and self.note_composition is None:
            raise ValidationError("Au moins une des deux notes (classe ou composition) est requise.")
        if self.note_classe is not None and not (0 <= self.note_classe <= 20):
            raise ValidationError("La note de classe doit être comprise entre 0 et 20.")
        if self.note_composition is not None and not (0 <= self.note_composition <= 40):
            raise ValidationError("La note de composition doit être comprise entre 0 et 40.")
        if self.affectation_id and self.eleve_id:
            if self.eleve.etablissement_id != self.affectation.classe.annee_scolaire.etablissement_id:
                raise ValidationError("L'élève et l'affectation doivent appartenir au même établissement.")
            inscrit = Inscription.objects.filter(
                eleve_id=self.eleve_id, classe_id=self.affectation.classe_id,
            ).exists()
            if not inscrit:
                raise ValidationError("Cet élève n'est pas inscrit dans la classe de cette affectation.")


def saisir_note(*, eleve, affectation, trimestre, enseignant, note_classe=None, note_composition=None):
    """
    Enregistre ou corrige la Note de Classe et/ou la Note de Composition
    d'un élève, pour une affectation et un trimestre. Resaisir pour le
    même triplet (élève, affectation, trimestre) MET À JOUR uniquement la
    valeur fournie (ex. ajouter la composition une fois l'examen passé,
    sans toucher à la note de classe déjà saisie en cours de trimestre) -
    jamais de doublon. La moyenne de la matière (valeur) se recalcule
    automatiquement à chaque appel (voir _moyenne_matiere).
    """
    if enseignant.role in {Role.PARENT, Role.ELEVE}:
        raise ValidationError("Ce rôle ne peut pas saisir de note.")
    if enseignant.role == Role.ENSEIGNANT and affectation.enseignant_id != enseignant.id:
        raise ValidationError("Vous n'êtes pas l'enseignant affecté à cette matière pour cette classe.")
    if note_classe is None and note_composition is None:
        raise ValidationError("Au moins une des deux notes (classe ou composition) est requise.")

    with transaction.atomic():
        note = Note.objects.filter(eleve=eleve, affectation=affectation, trimestre=trimestre).first()
        ancienne_valeur = note.valeur if note else None
        if note is None:
            note = Note(eleve=eleve, affectation=affectation, trimestre=trimestre)
        if note_classe is not None:
            note.note_classe = note_classe
        if note_composition is not None:
            note.note_composition = note_composition
        note.enregistre_par = enseignant
        note.valeur = _moyenne_matiere(note.note_classe, note.note_composition)
        note.full_clean()
        note.save()
        if ancienne_valeur is not None and ancienne_valeur != note.valeur:
            NoteHistorique.objects.create(note=note, ancienne_valeur=ancienne_valeur, modifiee_par=enseignant)
        return note


class NoteHistorique(models.Model):
    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="historique")
    ancienne_valeur = models.DecimalField(max_digits=4, decimal_places=2)
    modifiee_par = models.ForeignKey("comptes.Utilisateur", on_delete=models.SET_NULL, null=True, related_name="corrections_notes")
    modifiee_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-modifiee_le"]


APPRECIATIONS_PAR_SEUIL = [
    (Decimal("17"), "Excellent"),
    (Decimal("16"), "Très Bien"),
    (Decimal("13"), "Bien"),
    (Decimal("10"), "Passable"),
]


def appreciation_pour(moyenne):
    """
    Échelle à 5 niveaux (Excellent/Très Bien/Bien/Passable/Insuffisant),
    seuils déduits de bulletins maliens réels (aucune échelle nationale
    publiée trouvée par ailleurs) - vérifiés exacts sur 13 notes de
    matières de deux bulletins différents (fondamental et lycée).
    """
    if moyenne is None:
        return ""
    for seuil, libelle in APPRECIATIONS_PAR_SEUIL:
        if moyenne >= seuil:
            return libelle
    return "Insuffisant"


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
