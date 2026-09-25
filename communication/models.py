from django.core.exceptions import ValidationError
from django.db import models

from comptes.roles import Role
from comptes.validators import valider_contenu_fichier, valider_extension_document, valider_taille_fichier_10mo


class Portee(models.TextChoices):
    TOUTE_ECOLE = "toute_ecole", "Toute l'école"
    MA_CLASSE = "ma_classe", "Une classe précise"


class Annonce(models.Model):
    """
    Annonce avec pièce jointe et notification email automatique. Portée
    limitée pour un enseignant : jamais de diffusion à toute l'école
    (cahier des charges, section Communication).
    """

    titre = models.CharField(max_length=200)
    etablissement = models.ForeignKey(
        "etablissement.Etablissement", on_delete=models.PROTECT, related_name="annonces",
        null=True, blank=True,
    )
    contenu = models.TextField()
    piece_jointe = models.FileField(
        upload_to="annonces/", blank=True, null=True,
        validators=[valider_taille_fichier_10mo, valider_extension_document, valider_contenu_fichier],
    )
    portee = models.CharField(max_length=20, choices=Portee.choices)
    classe_ciblee = models.ForeignKey(
        "scolarite.Classe", on_delete=models.CASCADE, null=True, blank=True, related_name="annonces",
    )

    auteur = models.ForeignKey("comptes.Utilisateur", on_delete=models.SET_NULL, null=True, related_name="annonces")
    date_publication = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "annonce"
        verbose_name_plural = "annonces"
        ordering = ["-date_publication"]

    def __str__(self):
        return self.titre

    def clean(self):
        super().clean()
        if self.portee == Portee.MA_CLASSE and not self.classe_ciblee_id:
            raise ValidationError("Une classe cible est requise pour une annonce limitée à une classe.")
        if self.portee == Portee.TOUTE_ECOLE and self.classe_ciblee_id:
            raise ValidationError("Une annonce « toute l'école » ne cible pas de classe précise.")
        if self.auteur_id and self.auteur.role == Role.ENSEIGNANT and self.portee == Portee.TOUTE_ECOLE:
            raise ValidationError("Un enseignant ne peut pas diffuser une annonce à toute l'école.")
        if self.classe_ciblee_id and self.etablissement_id:
            if self.classe_ciblee.annee_scolaire.etablissement_id != self.etablissement_id:
                raise ValidationError("L'annonce et la classe ciblée doivent appartenir au même établissement.")
        if self.auteur_id and self.etablissement_id and self.auteur.etablissement_id != self.etablissement_id:
            raise ValidationError("L'auteur et l'annonce doivent appartenir au même établissement.")

    def save(self, *args, **kwargs):
        if not self.etablissement_id and self.auteur_id:
            self.etablissement_id = self.auteur.etablissement_id
        self.full_clean()
        super().save(*args, **kwargs)


class Message(models.Model):
    """
    Messagerie directe entre un parent et un enseignant, à propos d'un
    élève précis - jamais entre deux comptes sans lien réel : le parent doit
    être lié à l'élève, l'enseignant doit réellement lui enseigner (même
    règle que la visibilité des notes/absences). Aucune conversation de
    groupe, aucun tiers : un fil = (parent, enseignant, élève).
    """

    etablissement = models.ForeignKey(
        "etablissement.Etablissement", on_delete=models.CASCADE, related_name="messages",
        null=True, blank=True,
    )
    eleve = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.CASCADE, related_name="messages_le_concernant",
        limit_choices_to={"role": Role.ELEVE},
    )
    expediteur = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.CASCADE, related_name="messages_envoyes",
    )
    destinataire = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.CASCADE, related_name="messages_recus",
    )
    contenu = models.TextField(max_length=2000)
    envoye_le = models.DateTimeField(auto_now_add=True)
    lu_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "message"
        verbose_name_plural = "messages"
        ordering = ["envoye_le"]

    def __str__(self):
        return f"{self.expediteur} -> {self.destinataire} ({self.eleve.nom_complet})"

    def clean(self):
        super().clean()
        if self.expediteur_id and self.destinataire_id and self.expediteur_id == self.destinataire_id:
            raise ValidationError("L'expéditeur et le destinataire doivent être différents.")
        if not (self.expediteur_id and self.destinataire_id and self.eleve_id):
            return
        roles = {self.expediteur.role, self.destinataire.role}
        if roles != {Role.PARENT, Role.ENSEIGNANT}:
            raise ValidationError("La messagerie n'est ouverte qu'entre un parent et un enseignant.")

        parent = self.expediteur if self.expediteur.role == Role.PARENT else self.destinataire
        enseignant = self.expediteur if self.expediteur.role == Role.ENSEIGNANT else self.destinataire

        if not self.eleve.parents_lies.filter(pk=parent.pk).exists():
            raise ValidationError("Ce parent n'est pas lié à cet élève.")

        from scolarite.models import Affectation, Inscription
        enseigne = Affectation.objects.filter(
            enseignant=enseignant, classe__inscriptions__eleve=self.eleve,
            classe__inscriptions__statut=Inscription.Statut.EN_COURS,
        ).exists()
        if not enseigne:
            raise ValidationError("Cet enseignant n'enseigne pas à cet élève.")

    def save(self, *args, **kwargs):
        if not self.etablissement_id and self.eleve_id:
            self.etablissement_id = self.eleve.etablissement_id
        self.full_clean()
        super().save(*args, **kwargs)
