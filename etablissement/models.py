from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from comptes.langues import LANGUES
from comptes.uploads import chemin_upload_unique
from comptes.validators import valider_contenu_fichier, valider_taille_image_2mo


def chemin_upload_logo(instance, nom_fichier):
    return chemin_upload_unique("etablissement", instance.pk, nom_fichier)


def chemin_upload_signature(instance, nom_fichier):
    return chemin_upload_unique("etablissement_signature", instance.pk, nom_fichier)


def chemin_upload_cachet(instance, nom_fichier):
    return chemin_upload_unique("etablissement_cachet", instance.pk, nom_fichier)


class PlanEtablissement(models.TextChoices):
    """
    Formule d'abonnement d'un établissement : détermine les cycles dont les
    classes et les rôles de direction de cycle (y compris Censeur et
    Surveillant général, propres au Lycée) sont accessibles - sert à
    facturer différemment une école qui ne couvre que le 1er cycle d'une
    école qui va jusqu'au Lycée, sans qu'elle puisse s'auto-attribuer un
    cycle non souscrit (voir PlanEtablissement et scolarite.models.
    cycles_autorises_pour). LYCEE_SEUL et PROFESSIONNEL_SEUL existent pour
    les établissements qui n'ont ni 1er ni 2ème cycle (un lycée privé, une
    école professionnelle) : les trois premières formules sont cumulatives
    à partir du 1er cycle et ne peuvent pas les représenter.
    """
    PREMIER_CYCLE = "premier_cycle", "1er cycle"
    PREMIER_ET_DEUXIEME_CYCLE = "premier_et_deuxieme_cycle", "1er et 2ème cycle"
    TOUS_CYCLES = "tous_cycles", "Tous les cycles (1er, 2ème, Lycée)"
    LYCEE_SEUL = "lycee_seul", "Lycée seul"
    PROFESSIONNEL_SEUL = "professionnel_seul", "Enseignement professionnel seul"
    PRESCOLAIRE_SEUL = "prescolaire_seul", "Préscolaire seul"


class SituationFonctionnement(models.TextChoices):
    """Situation réelle de l'école sur le terrain, indépendante du compte (Etablissement.actif)."""
    OUVERT = "ouvert", "Ouvert"
    FERME = "ferme", "Fermé temporairement"
    RELOCALISE = "relocalise", "Relocalisé"


class MotifFermeture(models.TextChoices):
    INSECURITE = "insecurite", "Insécurité"
    INFRASTRUCTURE = "infrastructure", "Bâtiments endommagés ou inutilisables"
    ENSEIGNANTS = "enseignants", "Absence d'enseignants"
    AUTRE = "autre", "Autre motif"


class StatutEtablissement(models.TextChoices):
    PUBLIC = "public", "Public"
    COMMUNAUTAIRE = "communautaire", "Communautaire"
    PRIVE_LAIC = "prive_laic", "Privé laïc"
    PRIVE_CONFESSIONNEL = "prive_confessionnel", "Privé confessionnel"
    MEDERSA = "medersa", "Médersa (franco-arabe)"


class MilieuEtablissement(models.TextChoices):
    URBAIN = "urbain", "Urbain"
    RURAL = "rural", "Rural"


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
    nom_ar = models.CharField(
        "nom en arabe", max_length=200, blank=True,
        help_text="Nom de l'école écrit en arabe, affiché quand la langue est l'arabe. Vide : une proposition automatique est utilisée.",
    )
    devise = models.CharField(
        max_length=200, blank=True,
        help_text="Devise ou slogan affiché sous le nom (facultatif).",
    )
    devise_ar = models.CharField(
        "devise en arabe", max_length=200, blank=True,
        help_text="Devise écrite en arabe (facultatif).",
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
    coefficient_conduite = models.PositiveSmallIntegerField(
        "coefficient de la conduite", default=1,
        help_text="Poids de la note de conduite (de la 7ème à la 12ème année) dans la moyenne du bulletin : 1 = compte comme une "
                   "matière de coefficient 1 ; 0 = affichée sur le bulletin sans compter dans la moyenne.",
    )
    moyenne_passage_premier_cycle = models.DecimalField(
        "moyenne de passage du 1er cycle (sur 10)", max_digits=4, decimal_places=2, default=Decimal("5.00"),
        validators=[MinValueValidator(Decimal("0.50")), MaxValueValidator(Decimal("10"))],
        help_text="Moyenne annuelle sur 10 à partir de laquelle un élève de la 1ère à la 6ème année passe dans la classe supérieure (5 en général).",
    )
    logo = models.ImageField(
        upload_to=chemin_upload_logo, blank=True, null=True,
        validators=[valider_taille_image_2mo, valider_contenu_fichier],
        help_text="Logo affiché dans la barre latérale et sur la page de connexion. "
                   "Si aucun logo n'est fourni, l'initiale du nom est utilisée à la place. "
                   "Taille maximale : 2 Mo.",
    )
    # Documents officiels (certificats, attestations) : numéro, signataire, signature et cachet imprimés au choix.
    sigle = models.CharField(
        "sigle", max_length=15, blank=True,
        help_text="Abréviation qui figure dans le numéro des documents officiels (exemple : CSE). Vide : les initiales du nom de l'école.",
    )
    nom_signataire = models.CharField(
        "nom du signataire", max_length=120, blank=True,
        help_text="Personne qui signe les documents officiels (directeur, proviseur...).",
    )
    fonction_signataire = models.CharField(
        "fonction du signataire", max_length=100, blank=True, help_text="Exemple : Le Directeur, La Directrice, Le Proviseur.",
    )
    signature = models.ImageField(
        "signature", upload_to=chemin_upload_signature, blank=True, null=True,
        validators=[valider_taille_image_2mo, valider_contenu_fichier],
        help_text="Image de la signature (de préférence PNG sur fond transparent), imprimée sur les documents si on le demande. Taille maximale : 2 Mo.",
    )
    cachet = models.ImageField(
        "cachet", upload_to=chemin_upload_cachet, blank=True, null=True,
        validators=[valider_taille_image_2mo, valider_contenu_fichier],
        help_text="Image du cachet de l'école (de préférence PNG sur fond transparent), imprimée sur les documents si on le demande. Taille maximale : 2 Mo.",
    )
    email_facturation = models.EmailField(
        "email pour les factures d'abonnement", blank=True,
        help_text="Adresse à laquelle la plateforme envoie les factures d'abonnement de l'école et leurs rappels. Laissée vide, "
                   "elles vont aux comptes de direction de l'école (fondateur, administrateur général) ou, à défaut, à son développeur.",
    )
    telephone_facturation = models.CharField(
        "numéro WhatsApp pour les factures", max_length=20, blank=True,
        help_text="Numéro auquel le bouton WhatsApp de la liste des factures d'abonnement écrit (8 chiffres au Mali, ou format "
                   "international). Laissé vide, le numéro d'un compte de direction de l'école est utilisé s'il en a un.",
    )
    langue_par_defaut = models.CharField(
        "langue par défaut", max_length=2, choices=LANGUES, default="fr",
        help_text="Langue dans laquelle s'ouvrent les pages de l'école pour qui n'a pas choisi la sienne (bouton de langue). "
                   "Une école entièrement arabe choisit « العربية ».",
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
    inclut_professionnel = models.BooleanField(
        "inclut l'enseignement professionnel (CAP/BT)", default=False,
        help_text="Réglage indépendant de la formule ci-dessus : l'enseignement professionnel est une branche "
                   "parallèle au Lycée (accessible après le DEF), pas une suite du 1er/2ème cycle - un "
                   "établissement peut donc le cumuler avec n'importe quelle formule. Modifiable uniquement "
                   "depuis l'espace plateforme, comme la formule.",
    )
    inclut_prescolaire = models.BooleanField(
        "inclut le préscolaire (jardin d'enfants)", default=False,
        help_text="Réglage indépendant de la formule, comme l'enseignement professionnel : le préscolaire "
                   "précède le 1er cycle et peut se cumuler avec n'importe quelle formule. Modifiable "
                   "uniquement depuis l'espace plateforme.",
    )

    situation_fonctionnement = models.CharField(
        "situation de l'école", max_length=12, choices=SituationFonctionnement.choices,
        default=SituationFonctionnement.OUVERT,
        help_text="Descriptif (statistiques scolaires) : n'a aucun effet sur la connexion des comptes, qui "
                   "dépend uniquement de l'activation de l'établissement par l'espace plateforme.",
    )
    motif_fermeture = models.CharField(
        "motif de fermeture ou de relocalisation", max_length=20, choices=MotifFermeture.choices, blank=True,
    )
    date_situation = models.DateField(
        "depuis le", null=True, blank=True, help_text="Date de fermeture ou de relocalisation.",
    )

    code_etablissement = models.CharField(
        "code d'établissement", max_length=30, blank=True,
        help_text="Code officiel attribué par l'administration (recensement scolaire), s'il existe.",
    )
    statut_juridique = models.CharField(
        "statut", max_length=30, choices=StatutEtablissement.choices, blank=True,
        help_text="Public, communautaire, privé, médersa. À confirmer avec le questionnaire officiel.",
    )
    region = models.CharField("région", max_length=100, blank=True)
    cercle = models.CharField("cercle", max_length=100, blank=True)
    commune = models.CharField("commune", max_length=100, blank=True)
    milieu = models.CharField("milieu", max_length=10, choices=MilieuEtablissement.choices, blank=True)
    rattachement_administratif = models.CharField(
        "académie d'enseignement / CAP de rattachement", max_length=150, blank=True,
    )
    numero_agrement = models.CharField("n° d'autorisation ou d'agrément", max_length=60, blank=True)

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

    def clean(self):
        super().clean()
        # Une école ouverte n'a ni motif de fermeture ni date : on les efface plutôt que de les garder
        # comme restes d'une fermeture passée.
        if self.situation_fonctionnement == SituationFonctionnement.OUVERT:
            self.motif_fermeture = ""
            self.date_situation = None

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
    def sigle_effectif(self) -> str:
        """Le sigle saisi, sinon les initiales des mots du nom (« Groupe Scolaire Les Étoiles » -> « GSLE »), sinon « ECOLE »."""
        import re
        import unicodedata

        if self.sigle.strip():
            return self.sigle.strip().upper()
        sans_accent = unicodedata.normalize("NFKD", self.nom or "").encode("ascii", "ignore").decode("ascii")
        mots = [m for m in re.findall(r"[A-Za-z0-9]+", sans_accent) if len(m) > 2 or m[0].isupper()]
        initiales = "".join(m[0] for m in mots).upper()[:8]
        return initiales or "ECOLE"

    @property
    def initiale(self):
        from django.utils import translation

        if (translation.get_language() or "fr").startswith("ar"):  # arabe : la première lettre du nom arabe de l'école
            from comptes.arabisation import nom_d_ecole_arabe

            return ((self.nom_ar or nom_d_ecole_arabe(self.nom) or "؟").strip()[:1])
        return (self.nom or "?").strip()[:1].upper()


class FactureAbonnement(models.Model):
    """
    Facture de l'abonnement d'un établissement à la plateforme (propriétaire de la plateforme -> école), en FCFA.

    Une facture n'est jamais supprimée : elle est émise, puis payée ou annulée (avec un motif). Une facture payée ne
    s'annule pas (ce serait réécrire l'historique des encaissements). Les périodes facturées d'un même établissement
    ne se chevauchent pas (sauf facture annulée), pour ne jamais facturer deux fois la même période.
    """

    class Statut(models.TextChoices):
        EMISE = "emise", "Émise"
        PAYEE = "payee", "Payée"
        ANNULEE = "annulee", "Annulée"

    class ModeReglement(models.TextChoices):
        ESPECES = "especes", "Espèces"
        MOBILE_MONEY = "mobile_money", "Mobile Money"
        VIREMENT = "virement", "Virement bancaire"
        CHEQUE = "cheque", "Chèque"

    etablissement = models.ForeignKey(Etablissement, on_delete=models.PROTECT, related_name="factures_abonnement")
    numero = models.CharField(max_length=20, unique=True, editable=False)
    libelle = models.CharField(max_length=200)
    plan = models.CharField(
        "formule facturée", max_length=30, choices=PlanEtablissement.choices, blank=True,
        help_text="Formule de l'établissement au moment de l'émission (conservée même si elle change ensuite).",
    )
    periode_debut = models.DateField("début de la période")
    periode_fin = models.DateField("fin de la période")
    montant = models.PositiveIntegerField("montant (FCFA)")
    date_emission = models.DateField("émise le", default=timezone.localdate)
    date_echeance = models.DateField("à payer avant le")
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.EMISE)
    date_paiement = models.DateField("payée le", null=True, blank=True)
    mode_reglement = models.CharField(max_length=20, choices=ModeReglement.choices, blank=True)
    reference_reglement = models.CharField("référence du règlement", max_length=100, blank=True)
    motif_annulation = models.CharField(max_length=255, blank=True)
    envoyee_le = models.DateTimeField(
        "envoyée par email le", null=True, blank=True,
        help_text="Dernier envoi de la facture à l'école (hors rappels). Vide : jamais envoyée par la plateforme.",
    )
    nombre_rappels = models.PositiveSmallIntegerField("rappels envoyés", default=0)
    dernier_rappel_le = models.DateField("dernier rappel le", null=True, blank=True)
    cree_par = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "facture d'abonnement"
        verbose_name_plural = "factures d'abonnement"
        ordering = ["-date_emission", "-id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(periode_fin__gt=models.F("periode_debut")), name="facture_abonnement_periode_valide"),
            models.CheckConstraint(condition=models.Q(montant__gt=0), name="facture_abonnement_montant_positif"),
            models.CheckConstraint(
                condition=~models.Q(statut="payee") | models.Q(date_paiement__isnull=False),
                name="facture_abonnement_payee_a_une_date",
            ),
        ]

    def __str__(self):
        return f"{self.numero} - {self.etablissement.nom} - {self.montant} FCFA"

    def clean(self):
        super().clean()
        if self.periode_debut and self.periode_fin and self.periode_fin <= self.periode_debut:
            raise ValidationError("La fin de la période doit être postérieure à son début.")
        if self.montant is not None and self.montant <= 0:
            raise ValidationError("Le montant doit être strictement positif.")
        if self.date_echeance and self.date_emission and self.date_echeance < self.date_emission:
            raise ValidationError("L'échéance ne peut pas précéder la date d'émission.")
        if self.statut != self.Statut.ANNULEE and self.etablissement_id and self.periode_debut and self.periode_fin:
            chevauche = FactureAbonnement.objects.filter(
                etablissement_id=self.etablissement_id,
                periode_debut__lte=self.periode_fin, periode_fin__gte=self.periode_debut,
            ).exclude(statut=self.Statut.ANNULEE).exclude(pk=self.pk).first()
            if chevauche:
                raise ValidationError(
                    f"Cette période chevauche la facture {chevauche.numero} "
                    f"({chevauche.periode_debut:%d/%m/%Y} - {chevauche.periode_fin:%d/%m/%Y}) : une période ne se "
                    "facture qu'une fois (annulez d'abord l'autre facture si elle est erronée)."
                )

    @property
    def en_retard(self) -> bool:
        return self.statut == self.Statut.EMISE and self.date_echeance < timezone.localdate()

    @property
    def jours_de_retard(self) -> int:
        return (timezone.localdate() - self.date_echeance).days if self.en_retard else 0


class TarifCycle(models.Model):
    """
    Ce que le propriétaire de la plateforme facture à une école pour un cycle : un montant par élève et par an, ou un forfait par an pour le cycle
    (le choix dépend de l'école). Sert à proposer le montant d'une facture d'après les effectifs (espace_plateforme.effectifs) ; le propriétaire
    garde la main sur le montant qu'il émet.
    """

    class Mode(models.TextChoices):
        PAR_ELEVE = "par_eleve", "Par élève et par an"
        FORFAIT = "forfait", "Forfait par an"

    etablissement = models.ForeignKey(Etablissement, on_delete=models.CASCADE, related_name="tarifs_cycle")
    cycle = models.CharField(max_length=20, help_text="Un cycle de scolarite.models.Cycle (préscolaire, 1er cycle, 2ème cycle, lycée, professionnel).")
    mode = models.CharField(max_length=10, choices=Mode.choices)
    montant = models.PositiveIntegerField("montant (FCFA)", validators=[MinValueValidator(1), MaxValueValidator(2_000_000_000)])

    class Meta:
        verbose_name = "tarif par cycle"
        verbose_name_plural = "tarifs par cycle"
        ordering = ["etablissement", "cycle"]
        constraints = [models.UniqueConstraint(fields=["etablissement", "cycle"], name="un_tarif_par_cycle_et_par_ecole")]

    def __str__(self):
        return f"{self.etablissement} - {self.cycle} : {self.montant} ({self.get_mode_display()})"

    def clean(self):
        super().clean()
        from scolarite.models import Cycle

        if self.cycle not in Cycle.values:
            raise ValidationError({"cycle": "Cycle inconnu."})
