import secrets

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from scolarite.models import Classe, classes_visibles_pour


class Decision(models.TextChoices):
    EN_ATTENTE = "en_attente", "En attente"
    ADMIS = "admis", "Admis"
    REFUSE = "refuse", "Refusé"


class StatutDemande(models.TextChoices):
    """Où en est la demande d'un candidat venu de la pré-inscription en ligne (un candidat saisi à la main est « traité »)."""

    RECUE = "recue", "Demande reçue"
    CONVOQUE = "convoque", "Convoqué au test"
    REFUSEE = "refusee", "Demande refusée"
    TRAITEE = "traitee", "Traité"


def nouveau_jeton_de_campagne() -> str:
    return secrets.token_urlsafe(18)


class CampagnePreinscription(models.Model):
    """
    Une période de pré-inscription en ligne : la direction l'ouvre, partage son lien (jeton impossible à deviner), puis la ferme. Les familles
    qui ouvrent le lien déposent leur demande, qui arrive dans la liste des candidats ; le secrétariat convoque au test ou refuse.
    """

    etablissement = models.ForeignKey("etablissement.Etablissement", on_delete=models.CASCADE, related_name="campagnes_preinscription")
    titre = models.CharField(max_length=150)
    annee_scolaire = models.ForeignKey(
        "scolarite.AnneeScolaire", on_delete=models.PROTECT, related_name="campagnes_preinscription",
        help_text="Les familles choisissent parmi les classes de cette année.",
    )
    message_accueil = models.CharField(
        "message d'accueil", max_length=500, blank=True, help_text="Affiché en haut du formulaire public (conditions, pièces à apporter...).",
    )
    date_ouverture = models.DateField("ouverte à partir du", null=True, blank=True)
    date_cloture = models.DateField("fermée après le", null=True, blank=True)
    active = models.BooleanField(default=True, help_text="Décochez pour fermer tout de suite le formulaire public.")
    jeton = models.CharField(max_length=40, unique=True, default=nouveau_jeton_de_campagne, editable=False)
    cree_par = models.ForeignKey("comptes.Utilisateur", on_delete=models.SET_NULL, null=True, blank=True, related_name="campagnes_creees")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "campagne de pré-inscription"
        verbose_name_plural = "campagnes de pré-inscription"
        ordering = ["-cree_le"]

    def __str__(self):
        return self.titre

    def clean(self):
        super().clean()
        if self.date_ouverture and self.date_cloture and self.date_cloture < self.date_ouverture:
            raise ValidationError("La date de fermeture ne peut pas précéder la date d'ouverture.")
        if self.annee_scolaire_id and self.etablissement_id and self.annee_scolaire.etablissement_id != self.etablissement_id:
            raise ValidationError("L'année scolaire n'appartient pas à cet établissement.")

    def est_ouverte(self, aujourdhui=None) -> bool:
        aujourdhui = aujourdhui or timezone.localdate()
        if not self.active or self.annee_scolaire.est_archivee:
            return False
        return not (
            (self.date_ouverture and aujourdhui < self.date_ouverture) or (self.date_cloture and aujourdhui > self.date_cloture)
        )


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
    date_test = models.DateField(default=timezone.localdate, null=True, blank=True)  # vide tant qu'une demande en ligne n'est pas convoquée
    note_test = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)

    # Demande déposée en ligne par la famille (pré-inscription).
    campagne = models.ForeignKey(CampagnePreinscription, on_delete=models.SET_NULL, null=True, blank=True, related_name="demandes")
    statut_demande = models.CharField(max_length=10, choices=StatutDemande.choices, default=StatutDemande.TRAITEE)
    sexe = models.CharField(max_length=1, blank=True)
    nom_parent = models.CharField(max_length=150, blank=True)
    email_contact = models.EmailField(blank=True, help_text="Adresse où la famille reçoit les réponses.")
    message = models.CharField(max_length=500, blank=True)
    langue = models.CharField(max_length=2, blank=True, help_text="Langue de la famille, pour ses courriels.")
    demande_le = models.DateTimeField(null=True, blank=True)

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
        ordering = ["-date_test", "-pk"]

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
    candidat.full_clean(exclude=["cree_par"])  # une demande déposée en ligne n'a pas d'auteur dans l'école
    candidat.save()
    return candidat
