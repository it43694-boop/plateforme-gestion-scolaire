import random
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from comptes.roles import Role, StatutCompte


class Sexe(models.TextChoices):
    MASCULIN = "M", "Masculin"
    FEMININ = "F", "Féminin"


class UtilisateurManager(BaseUserManager):
    """
    Manager personnalisé : l'identifiant de connexion est l'email
    (cf. cahier des charges - « Connexion : email et mot de passe suffisent »).
    """

    use_in_migrations = True

    def _creer_utilisateur(self, email, password, **extra_fields):
        if not email:
            raise ValueError("L'adresse email est obligatoire.")
        email = self.normalize_email(email)
        utilisateur = self.model(email=email, **extra_fields)
        utilisateur.set_password(password)
        utilisateur.full_clean(exclude=["password"])
        utilisateur.save(using=self._db)
        return utilisateur

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._creer_utilisateur(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", Role.DEVELOPPEUR)
        extra_fields.setdefault("statut", StatutCompte.ACTIF)
        extra_fields.setdefault("email_verifie", True)
        extra_fields.setdefault("is_active", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Un superutilisateur doit avoir is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Un superutilisateur doit avoir is_superuser=True.")
        return self._creer_utilisateur(email, password, **extra_fields)


def generer_matricule():
    """
    Matricule auto : année courante + 5 chiffres aléatoires. L'unicité est
    d'abord vérifiée par lecture (rapide, évite l'essai le plus fréquent),
    puis garantie in fine par la contrainte unique en base : en cas de
    course entre deux requêtes concurrentes, la seconde échoue avec une
    IntegrityError que l'appelant doit intercepter et réessayer (voir
    `creer_avec_matricule_unique` ci-dessous, utilisé par les points
    d'entrée qui créent un élève).
    """
    annee = timezone.now().year
    for _ in range(20):
        candidat = f"{annee}{random.randint(10000, 99999)}"
        if not Utilisateur.objects.filter(matricule=candidat).exists():
            return candidat
    raise RuntimeError("Impossible de générer un matricule unique - réessayez.")


def creer_avec_matricule_unique(construire_utilisateur, tentatives=5):
    """
    Exécute `construire_utilisateur()` (qui doit créer et sauvegarder
    l'Utilisateur élève) en réessayant automatiquement si la génération du
    matricule entre en collision avec une requête concurrente - la lecture
    préalable dans `generer_matricule` réduit le risque au minimum, mais ne
    l'élimine pas complètement sous forte charge simultanée.
    """
    from django.db import IntegrityError

    derniere_erreur = None
    for _ in range(tentatives):
        try:
            return construire_utilisateur()
        except IntegrityError as erreur:
            derniere_erreur = erreur
            continue
    raise RuntimeError("Impossible de créer le compte élève après plusieurs tentatives.") from derniere_erreur


class Utilisateur(AbstractBaseUser, PermissionsMixin):
    """
    Utilisateur unique pour tous les rôles de la plateforme (direction,
    personnel, enseignants, parents, élèves). Le rôle détermine le
    comportement et les accès, combiné à la matrice de permissions.
    """

    email = models.EmailField("adresse email", unique=True)
    prenom = models.CharField("prénom", max_length=100)
    nom = models.CharField("nom", max_length=100)

    role = models.CharField("rôle", max_length=40, choices=Role.choices)
    statut = models.CharField(
        "statut du compte", max_length=40,
        choices=StatutCompte.choices,
        default=StatutCompte.EN_ATTENTE_VERIFICATION_EMAIL,
    )

    # Téléphone : unique dans toute la base pour un compte parent (anti-doublon,
    # cf. cahier des charges). Optionnel pour les autres rôles.
    telephone = models.CharField(
        "téléphone", max_length=20, unique=True, null=True, blank=True,
    )
    profession = models.CharField("profession", max_length=150, blank=True)
    sexe = models.CharField(
        "sexe", max_length=1, choices=Sexe.choices, null=True, blank=True,
        help_text="Utilisé pour les statistiques par sexe (effectifs, taux de réussite).",
    )
    etablissement = models.ForeignKey(
        "etablissement.Etablissement", on_delete=models.PROTECT, null=True, blank=True,
        related_name="utilisateurs",
        help_text="Établissement auquel ce compte appartient. Détermine les données "
                   "(élèves, classes, finances...) visibles pour ce compte.",
    )

    # Élève uniquement
    matricule = models.CharField(
        "matricule", max_length=20, unique=True, null=True, blank=True,
    )
    date_naissance = models.DateField("date de naissance", null=True, blank=True)
    parents_lies = models.ManyToManyField(
        "self", symmetrical=False, related_name="enfants_lies",
        limit_choices_to={"role": Role.PARENT}, blank=True,
        verbose_name="parent(s) lié(s)",
    )

    # Vérification email (inscription)
    email_verifie = models.BooleanField("email vérifié", default=False)

    # Sécurité - verrouillage après tentatives échouées
    tentatives_connexion_echouees = models.PositiveSmallIntegerField(default=0)
    verrouille_jusqu_a = models.DateTimeField(null=True, blank=True)

    # Authentification à deux facteurs (TOTP, ex. Google/Microsoft Authenticator) -
    # activable par tout compte, recommandée pour les rôles à privilège élevé.
    # totp_secret n'est renseigné qu'à l'activation confirmée (un code valide a
    # été saisi) ; deux_facteurs_actif=False tant que ce n'est pas fait, même si
    # un secret a été généré puis abandonné en cours d'activation.
    totp_secret = models.CharField(max_length=32, blank=True, editable=False)
    deux_facteurs_actif = models.BooleanField("2FA activée", default=False)

    date_creation = models.DateTimeField("créé le", auto_now_add=True)
    derniere_modification = models.DateTimeField("modifié le", auto_now=True)

    is_active = models.BooleanField("actif", default=False)  # activé seulement au statut ACTIF
    is_staff = models.BooleanField("accès admin technique", default=False)

    objects = UtilisateurManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["prenom", "nom", "role"]

    class Meta:
        verbose_name = "utilisateur"
        verbose_name_plural = "utilisateurs"
        ordering = ["nom", "prenom"]

    def __str__(self):
        return f"{self.prenom} {self.nom} ({self.get_role_display()})"

    @property
    def nom_complet(self):
        return f"{self.prenom} {self.nom}"

    @property
    def telephone_effectif(self):
        """
        Téléphone à afficher/utiliser pour un élève : le sien s'il en a un,
        sinon celui du premier parent lié (cahier des charges : le téléphone
        de l'élève est « repris du parent »). Ce n'est PAS une copie stockée
        en base - cela évite tout conflit avec l'unicité du téléphone, qui
        s'applique en pratique aux comptes parents.
        """
        if self.telephone:
            return self.telephone
        if self.role == Role.ELEVE:
            premier_parent = self.parents_lies.exclude(telephone__isnull=True).first()
            return premier_parent.telephone if premier_parent else None
        return None

    def clean(self):
        super().clean()
        if self.role == Role.ELEVE and not self.matricule:
            self.matricule = generer_matricule()
        if self.role != Role.ELEVE and self.matricule:
            raise ValidationError("Seul un élève peut avoir un matricule.")

    def verrouille(self) -> bool:
        return bool(self.verrouille_jusqu_a and self.verrouille_jusqu_a > timezone.now())

    def enregistrer_echec_connexion(self):
        self.tentatives_connexion_echouees += 1
        if self.tentatives_connexion_echouees >= settings.NB_TENTATIVES_CONNEXION_AVANT_VERROUILLAGE:
            self.verrouille_jusqu_a = timezone.now() + timedelta(
                minutes=settings.DUREE_VERROUILLAGE_MINUTES
            )
        self.save(update_fields=["tentatives_connexion_echouees", "verrouille_jusqu_a"])

    def reinitialiser_tentatives_connexion(self):
        if self.tentatives_connexion_echouees or self.verrouille_jusqu_a:
            self.tentatives_connexion_echouees = 0
            self.verrouille_jusqu_a = None
            self.save(update_fields=["tentatives_connexion_echouees", "verrouille_jusqu_a"])

    @staticmethod
    def generer_secret_2fa() -> str:
        """Nouveau secret TOTP, à ne persister (totp_secret) qu'une fois confirmé par un code valide."""
        import pyotp
        return pyotp.random_base32()

    def uri_provisionnement_2fa(self, secret: str) -> str:
        """URI otpauth:// à encoder en QR code pour une app d'authentification (Google/Microsoft Authenticator...)."""
        import pyotp
        return pyotp.totp.TOTP(secret).provisioning_uri(name=self.email, issuer_name="Plateforme de gestion scolaire")

    def verifier_code_2fa(self, code: str, secret: str | None = None) -> bool:
        """
        Vérifie un code TOTP à 6 chiffres. `secret` permet de vérifier contre un
        secret pas encore enregistré (étape de confirmation à l'activation) ;
        sans argument, vérifie contre le secret déjà actif du compte.
        """
        import pyotp
        secret_a_verifier = secret or self.totp_secret
        if not secret_a_verifier or not code:
            return False
        return pyotp.TOTP(secret_a_verifier).verify(code.strip(), valid_window=1)


def _expiration_par_defaut():
    return timezone.now() + timedelta(minutes=settings.DUREE_VALIDITE_CODE_VERIFICATION_MINUTES)


class CodeVerificationEmail(models.Model):
    """Code à 6 chiffres, envoyé une seule fois à l'inscription, expire après 10 minutes."""

    utilisateur = models.ForeignKey(
        Utilisateur, on_delete=models.CASCADE, related_name="codes_verification",
    )
    code = models.CharField(max_length=6)
    cree_le = models.DateTimeField(auto_now_add=True)
    expire_le = models.DateTimeField(default=_expiration_par_defaut)
    utilise = models.BooleanField(default=False)
    tentatives_echouees = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "code de vérification email"
        verbose_name_plural = "codes de vérification email"

    def est_valide(self) -> bool:
        return not self.utilise and timezone.now() <= self.expire_le and self.tentatives_echouees < 5

    def enregistrer_echec(self):
        self.tentatives_echouees += 1
        if self.tentatives_echouees >= 5:
            self.utilise = True  # invalide définitivement ce code après 5 essais erronés
        self.save(update_fields=["tentatives_echouees", "utilise"])

    @staticmethod
    def generer_code() -> str:
        # secrets (non random) : ce code est un secret de sécurité envoyé par
        # email, pas un identifiant public comme le matricule.
        return f"{secrets.randbelow(1_000_000):06d}"

    def __str__(self):
        return f"Code pour {self.utilisateur.email} (expire le {self.expire_le:%d/%m/%Y %H:%M})"


class JournalAudit(models.Model):
    """
    Journal d'audit applicatif - traçabilité des actions sensibles
    (suppression de paiement, changement de rôle, modification de la
    matrice de permissions...). Voir cahier des charges, section Sécurité.
    Table volontairement en ajout seul (aucune vue d'édition/suppression
    n'est exposée dans l'application).
    """

    horodatage = models.DateTimeField(auto_now_add=True)
    acteur = models.ForeignKey(
        Utilisateur, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="actions_journalisees",
    )
    etablissement = models.ForeignKey(
        "etablissement.Etablissement", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="journal_audit",
    )
    action = models.CharField(max_length=100)
    cible = models.CharField(max_length=255, blank=True)
    details = models.JSONField(default=dict, blank=True)
    adresse_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name = "entrée du journal d'audit"
        verbose_name_plural = "journal d'audit"
        ordering = ["-horodatage"]

    def __str__(self):
        return f"[{self.horodatage:%d/%m/%Y %H:%M}] {self.acteur} - {self.action} - {self.cible}"


class EmailOutbox(models.Model):
    """Emails à envoyer hors requête lorsque EMAIL_ASYNC est activé."""

    sujet = models.CharField(max_length=255)
    contenu = models.TextField()
    expediteur = models.EmailField()
    destinataires = models.JSONField(default=list)
    cree_le = models.DateTimeField(auto_now_add=True)
    envoye_le = models.DateTimeField(null=True, blank=True)
    tentatives = models.PositiveSmallIntegerField(default=0)
    prochaine_tentative = models.DateTimeField(default=timezone.now)
    derniere_erreur = models.TextField(blank=True)
    verrouille_le = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["cree_le"]


class Notification(models.Model):
    """Notification interne indépendante de l'email ou du SMS."""

    destinataire = models.ForeignKey(Utilisateur, on_delete=models.CASCADE, related_name="notifications")
    etablissement = models.ForeignKey(
        "etablissement.Etablissement", on_delete=models.CASCADE, related_name="notifications",
        null=True, blank=True,
    )
    titre = models.CharField(max_length=200)
    message = models.TextField()
    url = models.CharField(max_length=500, blank=True)
    lue_le = models.DateTimeField(null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-cree_le"]
