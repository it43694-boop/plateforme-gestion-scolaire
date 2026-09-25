from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from comptes.validators import valider_contenu_fichier, valider_taille_image_2mo


class Etablissement(models.Model):
    """
    Un établissement utilisant la plateforme. Plusieurs établissements
    peuvent coexister sur une même installation (multi-établissement) :
    chacun a sa propre identité (nom, logo, devise, monnaie), et - via le champ
    `etablissement` ajouté aux comptes et aux données métier - ses propres
    élèves, classes, finances, etc., isolés des autres établissements.

    `actif=False` bloque la connexion de tous les comptes de cet
    établissement, sans les désactiver individuellement (utile pour
    suspendre un établissement entier, ex. impayé d'abonnement, sans
    perdre ses données).
    """

    nom = models.CharField(
        max_length=200,
        help_text="Nom affiché partout dans l'application (barre latérale, emails, connexion).",
    )
    slug = models.SlugField(max_length=220, unique=True, blank=True, editable=False)
    devise = models.CharField(
        max_length=200, blank=True,
        help_text="Devise ou slogan affiché sous le nom (facultatif).",
    )
    code_devise = models.CharField(
        "monnaie", max_length=10, default="FCFA",
        help_text="Code ou symbole monétaire affiché sur les montants (paiements, salaires, bulletins financiers, "
                   "reçus). Exemples : FCFA, EUR, USD.",
    )
    pas_montant = models.PositiveIntegerField(
        "pas de saisie des frais", default=5000,
        help_text="Les frais de scolarité (inscription, tranches) doivent être saisis par multiple de ce montant. "
                   "5000 correspond à la plus petite coupure courante en FCFA ; ajustez pour une autre monnaie.",
    )
    logo = models.ImageField(
        upload_to="etablissement/", blank=True, null=True,
        validators=[valider_taille_image_2mo, valider_contenu_fichier],
        help_text="Logo affiché dans la barre latérale et sur la page de connexion. "
                   "Si aucun logo n'est fourni, l'initiale du nom est utilisée à la place. "
                   "Taille maximale : 2 Mo.",
    )
    actif = models.BooleanField(
        "établissement actif", default=True,
        help_text="Désactiver bloque la connexion de tous les comptes de cet établissement, "
                   "sans supprimer ni modifier leurs comptes individuellement.",
    )
    visible_dans_annuaire = models.BooleanField(
        "visible dans l'annuaire public", default=True,
        help_text="Si désactivé, cet établissement n'apparaît pas sur la page d'accueil publique "
                   "(les comptes existants peuvent toujours s'y connecter via un lien direct).",
    )
    cree_le = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = "établissement"
        verbose_name_plural = "établissements"
        ordering = ["nom"]

    def __str__(self):
        return self.nom

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.nom) or "etablissement"
            candidat = base
            suffixe = 2
            while Etablissement.objects.exclude(pk=self.pk).filter(slug=candidat).exists():
                candidat = f"{base}-{suffixe}"
                suffixe += 1
            self.slug = candidat
        super().save(*args, **kwargs)

    @property
    def initiale(self):
        return (self.nom or "?").strip()[:1].upper()
