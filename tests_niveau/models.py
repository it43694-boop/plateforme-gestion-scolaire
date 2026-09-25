from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from scolarite.models import Classe, classes_visibles_pour


class Decision(models.TextChoices):
    EN_ATTENTE = "en_attente", "En attente"
    ADMIS = "admis", "Admis"
    REFUSE = "refuse", "Refusé"


class Candidat(models.Model):
    """
    Candidat à un test de niveau, en vue d'une admission dans une classe.
    Suivi des candidats et décision admis/refusé, cloisonné par cycle via
    la classe visée (cahier des charges, section Tests de niveau).
    """

    prenom = models.CharField(max_length=100)
    nom = models.CharField(max_length=100)
    date_naissance = models.DateField(null=True, blank=True)
    telephone_contact = models.CharField(max_length=20, blank=True, help_text="Téléphone d'un parent ou tuteur.")

    classe_visee = models.ForeignKey(Classe, on_delete=models.PROTECT, related_name="candidats")
    date_test = models.DateField(default=timezone.localdate)
    note_test = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)

    decision = models.CharField(max_length=20, choices=Decision.choices, default=Decision.EN_ATTENTE)
    decide_par = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.SET_NULL, null=True, blank=True, related_name="decisions_candidats",
    )
    decide_le = models.DateTimeField(null=True, blank=True)

    cree_par = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.SET_NULL, null=True, related_name="candidats_enregistres",
    )
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "candidat"
        verbose_name_plural = "candidats"
        ordering = ["-date_test"]

    def __str__(self):
        return f"{self.prenom} {self.nom} - {self.classe_visee} ({self.get_decision_display()})"

    @property
    def nom_complet(self):
        return f"{self.prenom} {self.nom}"

    def clean(self):
        super().clean()
        if self.note_test is not None and not (0 <= self.note_test <= 20):
            raise ValidationError("La note de test doit être comprise entre 0 et 20.")


def candidats_visibles_pour(utilisateur):
    """Cloisonnement par cycle : un candidat est visible via le cycle de sa classe visée."""
    return Candidat.objects.filter(classe_visee__in=classes_visibles_pour(utilisateur)).select_related(
        "classe_visee", "classe_visee__annee_scolaire",
    )


def decider_candidat(*, candidat, decision, acteur):
    if decision not in {Decision.ADMIS, Decision.REFUSE}:
        raise ValidationError("La décision doit être « admis » ou « refusé ».")
    candidat.decision = decision
    candidat.decide_par = acteur
    candidat.decide_le = timezone.now()
    candidat.full_clean()
    candidat.save()
    return candidat
