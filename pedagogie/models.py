import datetime
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
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
    from pedagogie.clotures import verifier_periode_ouverte

    verifier_periode_ouverte(affectation.classe, trimestre)

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
    (Decimal("18"), "Excellent"),
    (Decimal("16"), "Très Bien"),
    (Decimal("14"), "Bien"),
    (Decimal("12"), "Assez Bien"),
    (Decimal("10"), "Passable"),
]


def appreciation_pour(moyenne):
    """
    Échelle à 6 niveaux : Excellent (18 et plus), Très Bien (16), Bien (14), Assez Bien (12), Passable (10),
    Insuffisant (en dessous de 10). Elle sert aux notes de matières, à la note de conduite et à la moyenne du
    trimestre. L'ancienne échelle, relevée sur un seul bulletin, n'avait pas « Assez Bien » : une note de 13
    sortait « Bien ».
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


# ---------------------------------------------------------------------------
# Conduite : une note sur 20 par trimestre, hors des matières, de la 7ème à la 12ème année
# ---------------------------------------------------------------------------

NIVEAUX_AVEC_CONDUITE = frozenset(f"annee_{numero}" for numero in range(7, 13))


def classe_note_la_conduite(classe) -> bool:
    """La conduite se note de la 7ème à la 12ème année : jamais en primaire, ni dans une classe dont le niveau n'est pas défini."""
    return classe.niveau in NIVEAUX_AVEC_CONDUITE


class NoteConduite(models.Model):
    """
    Note de conduite d'un élève pour un trimestre, saisie par la vie scolaire ou la direction. Ce n'est pas une matière : pas
    d'affectation d'enseignant, pas de composition. Voir pedagogie.conduite pour la saisie et le calcul de la moyenne.
    """

    eleve = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.CASCADE, related_name="notes_conduite", limit_choices_to={"role": Role.ELEVE},
    )
    classe = models.ForeignKey(Classe, on_delete=models.PROTECT, related_name="notes_conduite")
    trimestre = models.CharField(max_length=20, choices=Trimestre.choices)
    valeur = models.DecimalField(
        "note de conduite", max_digits=4, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(20)],
        help_text="Sur 20.",
    )
    enregistre_par = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.SET_NULL, null=True, blank=True, related_name="notes_conduite_saisies",
    )
    saisie_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "note de conduite"
        verbose_name_plural = "notes de conduite"
        unique_together = ("eleve", "classe", "trimestre")
        ordering = ["classe", "eleve__nom", "trimestre"]

    def __str__(self):
        return f"Conduite {self.valeur}/20 - {self.eleve} - {self.get_trimestre_display()}"

    def clean(self):
        super().clean()
        if self.eleve_id and self.eleve.role != Role.ELEVE:
            raise ValidationError("Seul un élève peut recevoir une note de conduite.")
        if self.classe_id:
            if not classe_note_la_conduite(self.classe):
                raise ValidationError("La conduite ne se note qu'à partir de la 7ème année.")
            if self.eleve_id:
                if self.eleve.etablissement_id != self.classe.annee_scolaire.etablissement_id:
                    raise ValidationError("L'élève et la classe doivent appartenir au même établissement.")
                if not Inscription.objects.filter(eleve_id=self.eleve_id, classe_id=self.classe_id).exists():
                    raise ValidationError("Cet élève n'est pas inscrit dans cette classe.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
class TypeMesureDiscipline(models.TextChoices):
    RETARD = "retard", "Retard"
    AVERTISSEMENT = "avertissement", "Avertissement"
    BLAME = "blame", "Blâme"
    CONVOCATION = "convocation", "Convocation des parents"
    EXCLUSION = "exclusion", "Exclusion"


class MesureDiscipline(models.Model):
    """
    Une ligne du registre de discipline : un retard, un avertissement, un blâme, une convocation des parents ou une exclusion.
    Visible par l'élève, ses parents et l'administration qui le suit ; les parents sont prévenus par courriel (voir pedagogie.discipline).
    """

    eleve = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.CASCADE, related_name="mesures_discipline", limit_choices_to={"role": Role.ELEVE},
    )
    classe = models.ForeignKey(Classe, on_delete=models.CASCADE, related_name="mesures_discipline")
    date_mesure = models.DateField("date")
    type_mesure = models.CharField("mesure", max_length=20, choices=TypeMesureDiscipline.choices)
    motif = models.CharField(max_length=255, blank=True)
    enregistre_par = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.SET_NULL, null=True, blank=True, related_name="mesures_discipline_saisies",
    )
    saisie_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "mesure de discipline"
        verbose_name_plural = "mesures de discipline"
        ordering = ["-date_mesure", "-pk"]
        indexes = [models.Index(fields=["eleve", "date_mesure"], name="discipline_eleve_date")]

    def __str__(self):
        return f"{self.get_type_mesure_display()} - {self.eleve} - {self.date_mesure}"

    def clean(self):
        super().clean()
        if self.eleve_id and self.eleve.role != Role.ELEVE:
            raise ValidationError("Seul un élève peut faire l'objet d'une mesure de discipline.")
        if self.date_mesure and self.date_mesure > datetime.date.today():
            raise ValidationError("Impossible d'enregistrer une mesure pour une date future.")
        if self.type_mesure != TypeMesureDiscipline.RETARD and not (self.motif or "").strip():
            raise ValidationError("Indiquez le motif de la mesure.")
        if self.eleve_id and self.classe_id:
            if self.eleve.etablissement_id != self.classe.annee_scolaire.etablissement_id:
                raise ValidationError("L'élève et la classe doivent appartenir au même établissement.")
            if not Inscription.objects.filter(eleve_id=self.eleve_id, classe_id=self.classe_id).exists():
                raise ValidationError("Cet élève n'est pas inscrit dans cette classe.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
class PeriodeCloturee(models.Model):
    """
    Un trimestre dont les notes sont clôturées pour toute une année scolaire : plus aucune note de matière ni de conduite ne s'y ajoute ni
    ne s'y corrige, tant que la direction ne l'a pas rouvert. Une année archivée est toujours clôturée (voir pedagogie.clotures).
    """

    annee_scolaire = models.ForeignKey("scolarite.AnneeScolaire", on_delete=models.CASCADE, related_name="periodes_cloturees")
    trimestre = models.CharField(max_length=20, choices=Trimestre.choices)
    cloturee_par = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.SET_NULL, null=True, blank=True, related_name="periodes_cloturees",
    )
    cloturee_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "période clôturée"
        verbose_name_plural = "périodes clôturées"
        constraints = [models.UniqueConstraint(fields=["annee_scolaire", "trimestre"], name="periode_cloturee_unique")]

    def __str__(self):
        return f"{self.get_trimestre_display()} - {self.annee_scolaire}"


class SeanceCahier(models.Model):
    """
    Une ligne du cahier de textes d'une classe : ce qui a été fait pendant une séance de cours (matière de l'affectation), le travail à faire et
    la date de remise. Les parents et les élèves de la classe voient les devoirs ; l'enseignant et la direction tiennent le cahier.
    """

    affectation = models.ForeignKey(Affectation, on_delete=models.CASCADE, related_name="seances_cahier")
    date_seance = models.DateField("date de la séance")
    contenu = models.CharField("séance", max_length=500, help_text="Ce qui a été fait ou étudié.")
    travail_a_faire = models.CharField("travail à faire", max_length=500, blank=True)
    date_remise = models.DateField("à rendre pour le", null=True, blank=True)
    cree_par = models.ForeignKey("comptes.Utilisateur", on_delete=models.SET_NULL, null=True, blank=True, related_name="seances_cahier_saisies")
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "séance du cahier de textes"
        verbose_name_plural = "séances du cahier de textes"
        ordering = ["-date_seance", "-pk"]
        indexes = [models.Index(fields=["affectation", "date_seance"], name="cahier_affectation_date")]

    def __str__(self):
        return f"{self.affectation} - {self.date_seance}"

    def clean(self):
        super().clean()
        if self.date_seance and self.date_seance > datetime.date.today():
            raise ValidationError("Une séance se note le jour même ou après : pas de date future.")
        if self.date_remise and self.date_seance and self.date_remise < self.date_seance:
            raise ValidationError("La date de remise ne peut pas précéder la séance.")
        if self.date_remise and not (self.travail_a_faire or "").strip():
            raise ValidationError("Indiquez le travail à faire pour la date de remise.")


class ChapitreProgramme(models.Model):
    """Un chapitre du programme d'une matière dans une classe : où l'on en est (en %), la date prévue pour le finir, les difficultés rencontrées."""

    affectation = models.ForeignKey(Affectation, on_delete=models.CASCADE, related_name="chapitres")
    titre = models.CharField(max_length=200)
    ordre = models.PositiveSmallIntegerField(default=0)
    date_prevue = models.DateField("à terminer pour le", null=True, blank=True)
    pourcentage = models.PositiveSmallIntegerField("avancement (%)", default=0, validators=[MaxValueValidator(100)])
    difficultes = models.CharField("difficultés rencontrées", max_length=255, blank=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "chapitre du programme"
        verbose_name_plural = "chapitres du programme"
        ordering = ["ordre", "pk"]
        constraints = [models.CheckConstraint(condition=models.Q(pourcentage__lte=100), name="chapitre_pourcentage_max_100")]

    def __str__(self):
        return f"{self.titre} ({self.pourcentage} %)"

    @property
    def en_retard(self) -> bool:
        """Un chapitre non terminé dont la date prévue est passée."""
        return bool(self.date_prevue and self.pourcentage < 100 and self.date_prevue < datetime.date.today())
