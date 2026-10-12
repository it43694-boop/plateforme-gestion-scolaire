from django.core.exceptions import ValidationError
from django.db import models

from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role
from comptes.uploads import chemin_upload_unique
from comptes.validators import valider_contenu_fichier, valider_extension_document, valider_taille_fichier_10mo


def chemin_upload_annonce(instance, nom_fichier):
    return chemin_upload_unique("annonces", instance.etablissement_id, nom_fichier)


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
        upload_to=chemin_upload_annonce, blank=True, null=True,
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
        if self.auteur_id and self.auteur.role in {Role.PARENT, Role.ELEVE}:
            raise ValidationError("Un parent ou un élève ne peut pas publier d'annonce.")
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


class PorteeEquipe(models.TextChoices):
    CLASSE = "classe", "Classe"
    NIVEAU = "niveau", "Niveau (toutes les sections)"
    MATIERE_NIVEAU = "matiere_niveau", "Matière dans un niveau"


def normaliser_matiere(texte: str) -> str:
    return " ".join((texte or "").split()).casefold()


class FilEquipe(models.Model):
    etablissement = models.ForeignKey(
        "etablissement.Etablissement", on_delete=models.CASCADE, related_name="fils_equipe",
    )
    annee_scolaire = models.ForeignKey(
        "scolarite.AnneeScolaire", on_delete=models.CASCADE, related_name="fils_equipe",
    )
    portee = models.CharField(max_length=20, choices=PorteeEquipe.choices)
    classe = models.ForeignKey(
        "scolarite.Classe", on_delete=models.CASCADE, null=True, blank=True, related_name="fils_equipe",
    )
    niveau = models.CharField(max_length=10, blank=True)
    matiere = models.CharField("matière (forme normalisée)", max_length=100, blank=True)
    matiere_affichee = models.CharField("matière", max_length=100, blank=True)
    cle = models.CharField(max_length=250, unique=True, editable=False)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "fil d'équipe"
        verbose_name_plural = "fils d'équipe"
        ordering = ["portee", "niveau", "matiere"]

    def __str__(self):
        return self.libelle

    @staticmethod
    def construire_cle(annee_id, portee, classe_id, niveau, matiere_normalisee):
        return f"{annee_id}|{portee}|{classe_id or ''}|{niveau}|{matiere_normalisee}"

    @property
    def libelle(self):
        from scolarite.models import Niveau
        libelle_niveau = dict(Niveau.choices).get(self.niveau, self.niveau)
        if self.portee == PorteeEquipe.CLASSE:
            return f"Classe {self.classe.nom}" if self.classe_id else "Classe"
        if self.portee == PorteeEquipe.NIVEAU:
            return f"{libelle_niveau} - toutes les sections"
        return f"{self.matiere_affichee} - {libelle_niveau}"

    def clean(self):
        super().clean()
        if self.portee == PorteeEquipe.CLASSE:
            if not self.classe_id or self.niveau or self.matiere:
                raise ValidationError("Un fil de classe cible une classe, sans niveau ni matière.")
            if self.classe.annee_scolaire_id != self.annee_scolaire_id:
                raise ValidationError("La classe doit appartenir à l'année scolaire du fil.")
        elif self.portee == PorteeEquipe.NIVEAU:
            if self.classe_id or not self.niveau or self.matiere:
                raise ValidationError("Un fil de niveau cible un niveau, sans classe ni matière.")
        elif self.portee == PorteeEquipe.MATIERE_NIVEAU:
            if self.classe_id or not self.niveau or not self.matiere:
                raise ValidationError("Un fil de matière cible un niveau et une matière, sans classe.")
        if self.annee_scolaire_id and self.annee_scolaire.etablissement_id != self.etablissement_id:
            raise ValidationError("L'année scolaire et le fil doivent appartenir au même établissement.")

    def save(self, *args, **kwargs):
        self.cle = self.construire_cle(
            self.annee_scolaire_id, self.portee, self.classe_id, self.niveau, self.matiere,
        )
        self.full_clean(exclude=["cle"])
        super().save(*args, **kwargs)


class MessageEquipe(models.Model):
    fil = models.ForeignKey(FilEquipe, on_delete=models.CASCADE, related_name="messages")
    auteur = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.SET_NULL, null=True, related_name="messages_equipe",
    )
    contenu = models.TextField(max_length=2000)
    envoye_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "message d'équipe"
        verbose_name_plural = "messages d'équipe"
        ordering = ["envoye_le"]

    def clean(self):
        super().clean()
        if self.auteur_id:
            roles_autorises = {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL} | {
                Role.ENSEIGNANT.value, Role.DIRECTEUR_1ER_CYCLE.value, Role.DIRECTEUR_2EME_CYCLE.value,
                Role.DIRECTEUR_LYCEE.value, Role.CENSEUR.value, Role.RESPONSABLE_PEDAGOGIQUE.value,
                Role.SUPER_ADMINISTRATEUR.value,
            }
            if self.auteur.role not in roles_autorises:
                raise ValidationError("Ce rôle ne peut pas écrire dans un fil d'équipe pédagogique.")
            if self.auteur.etablissement_id != self.fil.etablissement_id:
                raise ValidationError("L'auteur et le fil doivent appartenir au même établissement.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
