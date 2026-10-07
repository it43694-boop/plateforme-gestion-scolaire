from decimal import Decimal

from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from comptes.validators import valider_contenu_fichier, valider_taille_image_2mo


class PlanEtablissement(models.TextChoices):
    """
    Formule d'abonnement d'un établissement : détermine les cycles dont les
    classes et les rôles de direction de cycle (y compris Censeur et
    Surveillant général, propres au Lycée) sont accessibles - sert à
    facturer différemment une école qui ne couvre que le 1er cycle d'une
    école qui va jusqu'au Lycée, sans qu'elle puisse s'auto-attribuer un
    cycle non souscrit (voir PlanEtablissement et scolarite.models.
    cycles_autorises_pour).
    """
    PREMIER_CYCLE = "premier_cycle", "1er cycle"
    PREMIER_ET_DEUXIEME_CYCLE = "premier_et_deuxieme_cycle", "1er et 2ème cycle"
    TOUS_CYCLES = "tous_cycles", "Tous les cycles (1er, 2ème, Lycée)"


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
    plan = models.CharField(
        "formule d'abonnement", max_length=30, choices=PlanEtablissement.choices,
        default=PlanEtablissement.TOUS_CYCLES,
        help_text="Cycles couverts par l'abonnement - restreint les cycles de classe créables et les rôles "
                   "de direction de cycle attribuables. Modifiable uniquement depuis l'espace plateforme, "
                   "jamais par l'établissement lui-même.",
    )

    # Taux de cotisations sociales maliennes (INPS, AMO/CANAM), utilisés par
    # le bulletin de paie détaillé (finances.models.creer_bulletin_paie).
    # Valeurs par défaut conformes aux taux en vigueur au moment de l'écriture
    # (INPS part salarié 3,6 % ; AMO part salarié/employeur 3,06 %/3,5 %,
    # décret n°578/P-RM du 26/10/2010) - la part employeur de l'INPS varie
    # en réalité de 18,9 % à 21,9 % selon la classe de risque ATMP de
    # l'établissement, d'où un champ modifiable plutôt qu'une valeur codée en
    # dur : ces taux évoluent par décret, à vérifier/ajuster périodiquement.
    taux_inps_salarie = models.DecimalField(
        "taux INPS (part salarié)", max_digits=5, decimal_places=2, default=Decimal("3.6"),
        help_text="Pourcentage du salaire brut retenu sur le bulletin de paie au titre de l'INPS.",
    )
    taux_inps_employeur = models.DecimalField(
        "taux INPS (part employeur)", max_digits=5, decimal_places=2, default=Decimal("20.0"),
        help_text="Pourcentage du salaire brut à la charge de l'établissement (information uniquement, "
                   "n'affecte pas le net payé à l'employé) - varie de 18,9 % à 21,9 % selon la classe de "
                   "risque ATMP, à ajuster selon votre situation réelle.",
    )
    taux_amo_salarie = models.DecimalField(
        "taux AMO (part salarié)", max_digits=5, decimal_places=2, default=Decimal("3.06"),
        help_text="Pourcentage du salaire brut retenu sur le bulletin de paie au titre de l'AMO (CANAM).",
    )
    taux_amo_employeur = models.DecimalField(
        "taux AMO (part employeur)", max_digits=5, decimal_places=2, default=Decimal("3.5"),
        help_text="Pourcentage du salaire brut à la charge de l'établissement au titre de l'AMO "
                   "(information uniquement, n'affecte pas le net payé à l'employé).",
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
