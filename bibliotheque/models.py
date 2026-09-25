import os

from django.db import models

from comptes.validators import valider_contenu_fichier, valider_extension_document, valider_taille_fichier_10mo


def chemin_upload_document(instance, nom_fichier):
    return f"bibliotheque/{nom_fichier}"


class Document(models.Model):
    """
    Document de la bibliothèque numérique. Ajout unitaire ou en masse via
    import zip (cahier des charges, section Bibliothèque).
    """

    titre = models.CharField(max_length=200)
    etablissement = models.ForeignKey(
        "etablissement.Etablissement", on_delete=models.PROTECT, related_name="documents",
        null=True, blank=True,
    )
    description = models.TextField(blank=True)
    fichier = models.FileField(
        upload_to=chemin_upload_document,
        validators=[valider_taille_fichier_10mo, valider_extension_document, valider_contenu_fichier],
    )
    taille_octets = models.PositiveIntegerField(default=0, editable=False)

    ajoute_par = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.SET_NULL, null=True, related_name="documents_ajoutes",
    )
    ajoute_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "document"
        verbose_name_plural = "documents"
        ordering = ["-ajoute_le"]

    def __str__(self):
        return self.titre

    def save(self, *args, **kwargs):
        if self.fichier and not self.taille_octets:
            self.taille_octets = self.fichier.size
        if not self.etablissement_id and self.ajoute_par_id:
            self.etablissement_id = self.ajoute_par.etablissement_id
        super().save(*args, **kwargs)

    @property
    def nom_fichier(self):
        return os.path.basename(self.fichier.name)
