import uuid

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role
from comptes.validators import valider_contenu_fichier, valider_extension_document, valider_taille_fichier_10mo
from etablissement.models import PlanEtablissement


class Cycle(models.TextChoices):
    """
    Cycles de l'enseignement malien (cf. cahier des charges pour le
    fondamental ; le lycée a été ajouté ensuite sur le même principe -
    seconde à terminale, menant au baccalauréat malien).
    """
    PREMIER_CYCLE = "1er_cycle", "1er cycle"
    DEUXIEME_CYCLE = "2eme_cycle", "2ème cycle"
    LYCEE = "lycee", "Lycée"


class Serie(models.TextChoices):
    """
    Séries du baccalauréat malien, administrées par le CNECE (Centre
    national des examens et concours de l'éducation) - orientation des
    élèves à l'entrée en 11ème année, jusqu'au bac en 12ème (Terminale).
    La 10ème année (tronc commun) n'a pas encore de série.
    """
    SCIENCES_EXACTES = "tse", "Sciences Exactes (TSE)"
    SCIENCES_EXPERIMENTALES = "tsexp", "Sciences Expérimentales (TSExp)"
    SCIENCES_ECONOMIQUES = "tseco", "Sciences Économiques (TSEco)"
    SCIENCES_SOCIALES = "tss", "Sciences Sociales (TSS)"
    LANGUES_LITTERATURE = "tll", "Langues et Littérature (TLL)"
    ARTS_LETTRES = "tal", "Arts et Lettres (TAL)"


# Correspondance rôle de direction cloisonné -> cycle qu'il supervise. Donne
# aussi, via classes_visibles_pour et _peut_gerer_emploi_du_temps
# (pedagogie.views), le pouvoir administratif complet sur ce cycle (créer des
# classes, modifier l'emploi du temps) - à ne pas confondre avec
# CYCLE_PAR_ROLE_CLOISONNE ci-dessous, qui ne restreint que la VISIBILITÉ.
CYCLE_PAR_ROLE_DIRECTION = {
    Role.DIRECTEUR_1ER_CYCLE.value: Cycle.PREMIER_CYCLE.value,
    Role.DIRECTEUR_2EME_CYCLE.value: Cycle.DEUXIEME_CYCLE.value,
    Role.DIRECTEUR_LYCEE.value: Cycle.LYCEE.value,
}

# Rôles propres au Lycée (décret n°2011-234/P-RM du 12 mai 2011 portant
# organisation de l'Enseignement Secondaire Général : le Proviseur - ici
# DIRECTEUR_LYCEE - est assisté d'un Censeur et d'un Surveillant Général).
# Cloisonnés au Lycée pour la VISIBILITÉ des classes/élèves comme un
# directeur de cycle, mais volontairement absents de CYCLE_PAR_ROLE_DIRECTION :
# le Censeur est l'adjoint du proviseur (pédagogie et discipline), pas un
# administrateur de plein droit, et le Surveillant Général se limite au
# quotidien disciplinaire - ni l'un ni l'autre ne doit pouvoir créer une
# classe ou modifier l'emploi du temps (réservé à la direction).
CYCLE_PAR_ROLE_CLOISONNE = {
    **CYCLE_PAR_ROLE_DIRECTION,
    Role.CENSEUR.value: Cycle.LYCEE.value,
    Role.SURVEILLANT_GENERAL.value: Cycle.LYCEE.value,
}

# Cycles couverts par chaque formule d'abonnement (etablissement.models.
# PlanEtablissement) - détermine les cycles de classe créables et, via
# role_autorise_pour_plan ci-dessous, les rôles de direction de cycle
# attribuables. Un établissement sans plan reconnu (ne devrait pas arriver,
# le champ a un défaut) retombe sur tous les cycles plutôt que de bloquer
# silencieusement une école déjà en service.
CYCLES_PAR_PLAN = {
    PlanEtablissement.PREMIER_CYCLE.value: {Cycle.PREMIER_CYCLE.value},
    PlanEtablissement.PREMIER_ET_DEUXIEME_CYCLE.value: {Cycle.PREMIER_CYCLE.value, Cycle.DEUXIEME_CYCLE.value},
    PlanEtablissement.TOUS_CYCLES.value: {Cycle.PREMIER_CYCLE.value, Cycle.DEUXIEME_CYCLE.value, Cycle.LYCEE.value},
}

def cycles_autorises_pour(etablissement) -> set:
    """Valeurs de cycle (chaînes) couvertes par l'abonnement d'un établissement (voir CYCLES_PAR_PLAN)."""
    if etablissement is None:
        return set(Cycle.values)
    return CYCLES_PAR_PLAN.get(etablissement.plan, set(Cycle.values))


def role_autorise_pour_plan(role: str, etablissement) -> bool:
    """
    Un rôle de direction propre à un cycle (y compris Censeur/Surveillant
    général) n'est attribuable que si l'abonnement de l'établissement
    couvre ce cycle - empêche une école abonnée au 1er cycle seul de
    s'attribuer quand même un Directeur du Lycée ou un Censeur. Les rôles
    non cycle-spécifiques (secrétaire, comptable...) ne sont jamais
    concernés par cette restriction.
    """
    cycle_requis = CYCLE_PAR_ROLE_CLOISONNE.get(role)
    if cycle_requis is None:
        return True
    return cycle_requis in cycles_autorises_pour(etablissement)


class AnneeScolaire(models.Model):
    """
    Une année scolaire (ex. « 2026-2027 »), propre à un établissement.
    Les années passées restent consultables avec leurs propres effectifs
    et leurs propres frais, même si les tarifs ont changé depuis (cahier
    des charges, section Statistiques).
    """

    etablissement = models.ForeignKey(
        "etablissement.Etablissement", on_delete=models.PROTECT, related_name="annees_scolaires",
        null=True, blank=True,
    )
    libelle = models.CharField(max_length=20, help_text="Exemple : 2026-2027")
    date_debut = models.DateField()
    date_fin = models.DateField()
    est_active = models.BooleanField(
        default=False,
        help_text="Une seule année scolaire active à la fois par établissement.",
    )
    est_archivee = models.BooleanField(
        default=False,
        help_text="Une année archivée reste consultable mais ne reçoit plus de nouvelles écritures.",
    )

    class Meta:
        verbose_name = "année scolaire"
        verbose_name_plural = "années scolaires"
        unique_together = ("etablissement", "libelle")
        ordering = ["-date_debut"]

    def __str__(self):
        return self.libelle

    def clean(self):
        super().clean()
        if self.date_fin <= self.date_debut:
            raise ValidationError("La date de fin doit être postérieure à la date de début.")

    def verifier_mutable(self):
        if self.est_archivee:
            raise ValidationError("Cette année scolaire est archivée et ne peut plus être modifiée.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
        if self.est_active:
            # Une seule année active à la fois, PAR ÉTABLISSEMENT : on ne
            # désactive jamais celle d'un autre établissement.
            AnneeScolaire.objects.filter(etablissement=self.etablissement).exclude(pk=self.pk).update(est_active=False)

    @classmethod
    def active(cls, etablissement):
        return cls.objects.filter(etablissement=etablissement, est_active=True).first()


# Valeurs de repli quand aucun établissement n'est résolvable (ex. données
# de test construites sans établissement) : mêmes valeurs que le défaut du
# champ Etablissement.pas_montant, pour un comportement inchangé.
PAS_MONTANT = 5000
DEVISE_PAR_DEFAUT = "FCFA"

MOIS_FR = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]


def valider_multiple_de_5000(valeur):
    # Conservée pour les migrations historiques qui la référencent par son
    # chemin d'import (scolarite.models.valider_multiple_de_5000) - ne plus
    # utiliser sur un champ : la validation par pas se fait maintenant dans
    # EcheancierFrais.clean(), avec le pas propre à l'établissement de la
    # classe plutôt qu'une valeur globale figée.
    if valeur % PAS_MONTANT != 0:
        raise ValidationError(f"Le montant doit être un multiple de {PAS_MONTANT} {DEVISE_PAR_DEFAUT}.")


class Classe(models.Model):
    """
    Une classe est unique par nom ET par année scolaire (multi-années) :
    « 3ème année A » en 2026-2027 est un enregistrement distinct de
    « 3ème année A » en 2027-2028.
    """

    nom = models.CharField(max_length=60, help_text="Exemple : 3ème année A")
    cycle = models.CharField(max_length=20, choices=Cycle.choices)
    serie = models.CharField(
        "série", max_length=20, choices=Serie.choices, blank=True,
        help_text="Uniquement pour une classe de 11ème ou 12ème année (lycée) - laisser vide sinon.",
    )
    annee_scolaire = models.ForeignKey(
        AnneeScolaire, on_delete=models.PROTECT, related_name="classes",
    )
    classe_suivante = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="classes_precedentes",
        help_text="Classe vers laquelle les élèves admis de cette classe sont promus l'année suivante. "
                   "Mémorisée pour ne pas avoir à la ressaisir chaque année.",
    )

    class Meta:
        verbose_name = "classe"
        verbose_name_plural = "classes"
        unique_together = ("nom", "annee_scolaire")
        ordering = ["annee_scolaire", "cycle", "nom"]

    def __str__(self):
        return f"{self.nom} ({self.annee_scolaire.libelle})"

    def clean(self):
        super().clean()
        if self.serie and self.cycle != Cycle.LYCEE:
            raise ValidationError("Une série ne s'applique qu'à une classe du cycle Lycée.")
        if self.cycle and self.annee_scolaire_id:
            etablissement = self.annee_scolaire.etablissement
            if self.cycle not in cycles_autorises_pour(etablissement):
                raise ValidationError(
                    "L'abonnement de cet établissement ne couvre pas ce cycle - "
                    "contactez la plateforme pour le faire évoluer."
                )

    @property
    def effectif(self):
        return self.inscriptions.filter(statut=Inscription.Statut.EN_COURS).count()


class Periodicite(models.TextChoices):
    MENSUEL = "mensuel", "Mensuel"
    TRIMESTRIEL = "trimestriel", "Trimestriel"
    ANNUEL = "annuel", "Annuel"


# Nombre de versements (hors inscription) fixé par la périodicité - seul le
# mensuel se négocie école par école (9 ou 10 sur l'année scolaire) ;
# trimestriel et annuel découlent directement du calendrier scolaire.
NOMBRE_VERSEMENTS_FIXE = {
    Periodicite.TRIMESTRIEL: 3,
    Periodicite.ANNUEL: 1,
}


class EcheancierFrais(models.Model):
    """
    Frais de scolarité pour une classe donnée : des frais d'inscription
    (versés une fois) et un montant par période, répété sur l'année selon
    la périodicité choisie par l'établissement - les paiements se font en
    pratique par mois, par trimestre ou en une fois selon l'école.
    Saisie par pas de montant (5000 par défaut, configurable par
    établissement via Etablissement.pas_montant), sans plafond (chaque
    établissement fixe librement ses propres tarifs).
    """

    classe = models.OneToOneField(Classe, on_delete=models.CASCADE, related_name="echeancier")
    montant_inscription = models.PositiveIntegerField()
    periodicite = models.CharField(max_length=20, choices=Periodicite.choices, default=Periodicite.TRIMESTRIEL)
    montant_periode = models.PositiveIntegerField(
        help_text="Montant par mois, par trimestre ou pour l'année selon la périodicité choisie.",
    )
    nombre_versements = models.PositiveSmallIntegerField(
        default=3,
        help_text="Nombre de versements (hors inscription) sur l'année scolaire : 9 ou 10 pour le "
                   "mensuel ; fixé automatiquement à 3 pour le trimestriel et 1 pour l'annuel.",
    )

    class Meta:
        verbose_name = "échéancier de frais"
        verbose_name_plural = "échéanciers de frais"

    def __str__(self):
        return f"Frais - {self.classe}"

    def _pas_et_devise(self):
        etablissement = getattr(self.classe.annee_scolaire, "etablissement", None) if self.classe_id else None
        if etablissement is None:
            return PAS_MONTANT, DEVISE_PAR_DEFAUT
        return etablissement.pas_montant, etablissement.code_devise

    def clean(self):
        super().clean()
        if self.periodicite in NOMBRE_VERSEMENTS_FIXE:
            self.nombre_versements = NOMBRE_VERSEMENTS_FIXE[self.periodicite]
        elif self.periodicite == Periodicite.MENSUEL and self.nombre_versements not in (9, 10):
            raise ValidationError({"nombre_versements": "Un échéancier mensuel compte 9 ou 10 versements."})

        pas, devise = self._pas_et_devise()
        erreurs = {}
        for champ in ["montant_inscription", "montant_periode"]:
            valeur = getattr(self, champ, None)
            if valeur is not None and valeur % pas != 0:
                erreurs[champ] = f"Doit être un multiple de {pas} {devise}."
        if erreurs:
            raise ValidationError(erreurs)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def total_annuel(self):
        return self.montant_inscription + self.montant_periode * self.nombre_versements

    @property
    def libelle_periode(self):
        """Libellé d'un versement périodique (hors inscription), utilisé pour les reçus de paiement."""
        return {
            Periodicite.MENSUEL: "Mensualité",
            Periodicite.TRIMESTRIEL: "Trimestre",
            Periodicite.ANNUEL: "Année",
        }[self.periodicite]

    def libelles_periodes(self) -> list:
        """
        Libellés des mois (mensuel) ou trimestres (trimestriel) couverts
        par cet échéancier, dans l'ordre chronologique depuis le début de
        l'année scolaire - pour cocher exactement ceux qu'un versement
        règle (une famille peut payer n'importe quelle combinaison de
        mois, pas forcément consécutifs ni dans l'ordre). Vide pour
        l'annuel : un seul versement, aucun détail de période nécessaire.
        """
        if self.periodicite == Periodicite.ANNUEL:
            return []
        if self.periodicite == Periodicite.TRIMESTRIEL:
            return ["1er trimestre", "2ème trimestre", "3ème trimestre"]
        debut = self.classe.annee_scolaire.date_debut
        annee, mois = debut.year, debut.month
        libelles = []
        for _ in range(self.nombre_versements):
            libelles.append(f"{MOIS_FR[mois - 1]} {annee}")
            mois += 1
            if mois > 12:
                mois = 1
                annee += 1
        return libelles


class Affectation(models.Model):
    """Affectation d'un enseignant à une classe (et, en option, à une matière)."""

    enseignant = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.CASCADE, related_name="affectations",
        limit_choices_to={"role": Role.ENSEIGNANT},
    )
    classe = models.ForeignKey(Classe, on_delete=models.CASCADE, related_name="affectations")
    matiere = models.CharField(max_length=100, blank=True, help_text="Laisser vide si professeur titulaire.")
    coefficient = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1)],
        help_text="Poids de cette matière dans le calcul de la moyenne du bulletin. "
                   "1 par défaut (toutes les matières comptent également) ; augmentez pour une matière "
                   "à plus fort coefficient (ex. Mathématiques, Français).",
    )
    class Meta:
        verbose_name = "affectation d'enseignant"
        verbose_name_plural = "affectations d'enseignants"
        unique_together = ("enseignant", "classe", "matiere")

    def clean(self):
        super().clean()
        if self.enseignant_id and self.enseignant.role != Role.ENSEIGNANT:
            raise ValidationError("Seul un utilisateur avec le rôle « enseignant » peut être affecté.")
        if self.enseignant_id and self.classe_id and self.enseignant.etablissement_id != self.classe.annee_scolaire.etablissement_id:
            raise ValidationError("L'enseignant et la classe doivent appartenir au même établissement.")

    def __str__(self):
        libelle_matiere = self.matiere or "Titulaire"
        return f"{self.enseignant.nom_complet} - {self.classe} ({libelle_matiere})"


class Inscription(models.Model):
    """
    Lien entre un élève et une classe pour une année scolaire donnée
    (l'année scolaire est portée par la classe).
    """

    class Statut(models.TextChoices):
        EN_COURS = "en_cours", "En cours"
        ADMIS = "admis", "Admis (année suivante)"
        REDOUBLE = "redouble", "Redouble"
        TRANSFERE = "transfere", "Transféré / parti"

    eleve = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.CASCADE, related_name="inscriptions",
        limit_choices_to={"role": Role.ELEVE},
    )
    classe = models.ForeignKey(Classe, on_delete=models.PROTECT, related_name="inscriptions")
    date_inscription = models.DateField(auto_now_add=True)
    statut = models.CharField(max_length=20, choices=Statut.choices, default=Statut.EN_COURS)

    class Meta:
        verbose_name = "inscription"
        verbose_name_plural = "inscriptions"
        unique_together = ("eleve", "classe")
        ordering = ["-date_inscription"]

    def __str__(self):
        return f"{self.eleve.nom_complet} - {self.classe}"

    def clean(self):
        super().clean()
        if self.eleve_id and self.eleve.role != Role.ELEVE:
            raise ValidationError("Seul un utilisateur avec le rôle « élève » peut être inscrit.")
        if self.eleve_id and self.classe_id and self.eleve.etablissement_id != self.classe.annee_scolaire.etablissement_id:
            raise ValidationError("L'élève et la classe doivent appartenir au même établissement.")
        if self.classe_id:
            deja_inscrit = Inscription.objects.filter(
                eleve_id=self.eleve_id, classe__annee_scolaire=self.classe.annee_scolaire,
            ).exclude(pk=self.pk)
            if deja_inscrit.exists():
                raise ValidationError(
                    "Cet élève est déjà inscrit dans une classe pour cette année scolaire."
                )

    def save(self, *args, **kwargs):
        self.classe.annee_scolaire.verifier_mutable()
        self.full_clean()
        super().save(*args, **kwargs)


class ParentEnAttente(models.Model):
    """
    Email (et éventuellement nom/prénom/téléphone) d'un parent communiqué
    à l'inscription d'un élève, avant que ce parent n'ait lui-même créé de
    compte. Dès qu'un compte est créé et vérifié avec cet email (voir
    comptes.views.verifier_email -> lier_parents_en_attente), le lien
    élève-parent se fait automatiquement et cette ligne est supprimée -
    le secrétariat n'a plus besoin d'attendre que chaque parent se soit
    déjà inscrit avant de pouvoir inscrire son enfant.
    """

    eleve = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.CASCADE, related_name="parents_en_attente",
        limit_choices_to={"role": Role.ELEVE},
    )
    email = models.EmailField()
    nom = models.CharField(max_length=100, blank=True)
    prenom = models.CharField(max_length=100, blank=True)
    telephone = models.CharField(max_length=20, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "parent en attente"
        verbose_name_plural = "parents en attente"
        unique_together = ("eleve", "email")
        ordering = ["-cree_le"]

    def __str__(self):
        return f"{self.email} (en attente - {self.eleve.nom_complet})"


class TypeAideScolarite(models.TextChoices):
    BOURSE = "bourse", "Bourse"
    REDUCTION = "reduction", "Réduction"
    EXONERATION = "exoneration", "Exonération"


class AideScolarite(models.Model):
    inscription = models.ForeignKey(Inscription, on_delete=models.PROTECT, related_name="aides_scolarite")
    type_aide = models.CharField(max_length=20, choices=TypeAideScolarite.choices)
    montant = models.PositiveIntegerField(default=0)
    pourcentage = models.PositiveSmallIntegerField(default=0)
    motif = models.CharField(max_length=255)
    accordee_par = models.ForeignKey("comptes.Utilisateur", on_delete=models.PROTECT, related_name="aides_accordees")
    cree_le = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(default=True)

    def clean(self):
        super().clean()
        if self.montant and self.pourcentage:
            raise ValidationError("Une aide utilise soit un montant, soit un pourcentage.")
        if self.pourcentage > 100:
            raise ValidationError("Le pourcentage ne peut pas dépasser 100.")
        if self.inscription_id and self.accordee_par_id and self.inscription.classe.annee_scolaire.etablissement_id != self.accordee_par.etablissement_id:
            raise ValidationError("L'aide et l'inscription doivent appartenir au même établissement.")


def calculer_total_du(inscription, aides_actives=None):
    """
    Calcule le net dû en tenant compte des aides actives de l'inscription.

    `aides_actives` : liste déjà chargée des aides actives de CETTE
    inscription, à fournir quand l'appelant boucle sur plusieurs
    inscriptions (ex. finances.views.suivi_paiements,
    assistant.alertes._familles_impayees) pour éviter une requête par
    élève - sans ce paramètre, comportement inchangé (une requête ici).
    """
    echeancier = getattr(inscription.classe, "echeancier", None)
    brut = echeancier.total_annuel if echeancier else 0
    remise = 0
    aides = aides_actives if aides_actives is not None else inscription.aides_scolarite.filter(active=True)
    for aide in aides:
        remise += aide.montant or round(brut * aide.pourcentage / 100)
    return max(brut - remise, 0)


class TransfertEleve(models.Model):
    inscription = models.OneToOneField(Inscription, on_delete=models.PROTECT, related_name="transfert")
    etablissement_destination = models.ForeignKey(
        "etablissement.Etablissement", on_delete=models.PROTECT, null=True, blank=True,
        related_name="transferts_recus",
    )
    destination_libelle = models.CharField(max_length=255, blank=True)
    date_transfert = models.DateField()
    motif = models.CharField(max_length=255)
    justificatif = models.FileField(
        upload_to="transferts/", blank=True,
        validators=[valider_taille_fichier_10mo, valider_extension_document, valider_contenu_fichier],
    )
    enregistre_par = models.ForeignKey("comptes.Utilisateur", on_delete=models.PROTECT, related_name="transferts_enregistres")
    cree_le = models.DateTimeField(auto_now_add=True)


class TypeDocumentVerifiable(models.TextChoices):
    ATTESTATION_SCOLARITE = "attestation_scolarite", "Attestation de scolarité"


class VerificationDocument(models.Model):
    """
    Jeton de vérification publique pour un document officiel généré par la
    plateforme, hors bulletin (qui a son propre modèle historique,
    pedagogie.models.VerificationBulletin) - même principe : un QR code sur
    le PDF renvoie vers une page qui confirme l'authenticité du document
    sans en exposer le contenu complet. Un seul modèle générique ici plutôt
    qu'un nouveau modèle par type de document, puisque le besoin (jeton
    unique, élève, inscription, date d'émission) est identique pour tous.
    """

    type_document = models.CharField(max_length=30, choices=TypeDocumentVerifiable.choices)
    eleve = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.CASCADE, related_name="documents_verifiables",
    )
    inscription = models.ForeignKey(Inscription, on_delete=models.PROTECT, related_name="verifications_document")
    jeton = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    cree_le = models.DateTimeField(auto_now_add=True)
    actif = models.BooleanField(default=True)

    class Meta:
        verbose_name = "document vérifiable"
        verbose_name_plural = "documents vérifiables"
        ordering = ["-cree_le"]


# ---------------------------------------------------------------------------
# Fonctions utilitaires - cloisonnement par cycle et dossier élève
# ---------------------------------------------------------------------------

def classes_visibles_pour(utilisateur):
    """
    Retourne le queryset de classes visibles pour un utilisateur donné :
    toujours limité à SON établissement, puis, en plus, cloisonné par
    cycle pour les directeurs de cycle ainsi que pour le Censeur et le
    Surveillant général (propres au Lycée - voir CYCLE_PAR_ROLE_CLOISONNE).
    """
    queryset = Classe.objects.filter(
        annee_scolaire__etablissement=utilisateur.etablissement_id,
    ).select_related("annee_scolaire")
    cycle_impose = CYCLE_PAR_ROLE_CLOISONNE.get(utilisateur.role)
    if cycle_impose:
        return queryset.filter(cycle=cycle_impose)
    return queryset


def passer_eleve(*, inscription, decision, classe_destination=None):
    """
    Clôt une inscription (statut Admis/Redouble/Transféré) et, sauf
    transfert, crée la nouvelle inscription de l'élève dans la classe de
    destination pour l'année suivante. Utilisé par le passage de classe.
    """
    from django.core.exceptions import ValidationError
    from django.db import transaction

    if decision not in {Inscription.Statut.ADMIS, Inscription.Statut.REDOUBLE, Inscription.Statut.TRANSFERE}:
        raise ValidationError("Décision de passage invalide.")
    if decision != Inscription.Statut.TRANSFERE and classe_destination is None:
        raise ValidationError("Une classe de destination est requise, sauf en cas de transfert.")
    if classe_destination is not None:
        if classe_destination.annee_scolaire.etablissement_id != inscription.classe.annee_scolaire.etablissement_id:
            raise ValidationError("La classe de destination doit appartenir au même établissement.")
        if classe_destination.annee_scolaire.date_debut <= inscription.classe.annee_scolaire.date_debut:
            raise ValidationError("La classe de destination doit appartenir à une année ultérieure.")
    if inscription.statut != Inscription.Statut.EN_COURS:
        raise ValidationError("Cette inscription a déjà fait l'objet d'une décision.")

    with transaction.atomic():
        inscription.statut = decision
        inscription.save(update_fields=["statut"])
        if decision != Inscription.Statut.TRANSFERE:
            Inscription.objects.create(
                eleve=inscription.eleve, classe=classe_destination, statut=Inscription.Statut.EN_COURS,
            )


def lier_parent_a_eleve(eleve, parent):
    """
    Lie un parent à un élève (jusqu'à 2 parents maximum), et complète
    automatiquement le téléphone de l'élève à partir de celui du parent
    si l'élève n'en a pas encore (cahier des charges, section Comptes parents).
    """
    if eleve.role != Role.ELEVE:
        raise ValidationError("Seul un élève peut avoir des parents liés.")
    if parent.role != Role.PARENT:
        raise ValidationError("Seul un utilisateur avec le rôle « parent » peut être lié comme parent.")
    if eleve.parents_lies.exclude(pk=parent.pk).count() >= 2:
        raise ValidationError("Un élève ne peut pas avoir plus de 2 parents liés.")
    if eleve.etablissement_id != parent.etablissement_id:
        raise ValidationError("L'élève et le parent doivent appartenir au même établissement.")

    eleve.parents_lies.add(parent)


def lier_parents_en_attente(parent):
    """
    Appelée quand un compte parent vient d'être vérifié (voir
    comptes.views.verifier_email) : relie automatiquement tous les élèves
    de son établissement pour lesquels son email avait été enregistré
    avant qu'il n'ait de compte (voir ParentEnAttente). Une ligne dont le
    lien échoue (ex. élève ayant déjà 2 parents) est laissée en place pour
    une action manuelle plutôt que silencieusement perdue.
    """
    if parent.role != Role.PARENT:
        return
    for attente in ParentEnAttente.objects.filter(
        email__iexact=parent.email, eleve__etablissement_id=parent.etablissement_id,
    ).select_related("eleve"):
        try:
            lier_parent_a_eleve(attente.eleve, parent)
        except ValidationError:
            continue
        attente.delete()


def dossier_complet(eleve) -> bool:
    if eleve.role != Role.ELEVE:
        return False
    return bool(
        eleve.date_naissance and eleve.telephone_effectif and eleve.parents_lies.exists()
    )


# Rôles pour lesquels « voir n'importe quel élève de son établissement »
# (sous réserve du cloisonnement par cycle de classes_visibles_pour) est
# légitime : direction, secrétariat (gestion des dossiers), comptabilité
# (suivi des paiements par élève), pédagogie. Liste explicite plutôt qu'un
# repli implicite - un rôle non listé ici (bibliothécaire, personnel
# générique, ou un autre élève) n'a aucune raison de consulter le dossier
# d'un élève auquel il n'est pas directement lié.
ROLES_VOIENT_TOUT_ELEVE_DE_LETABLISSEMENT = {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL} | {
    Role.DIRECTEUR_1ER_CYCLE.value, Role.DIRECTEUR_2EME_CYCLE.value, Role.DIRECTEUR_LYCEE.value,
    Role.CENSEUR.value, Role.SURVEILLANT_GENERAL.value,
    Role.SUPER_ADMINISTRATEUR.value, Role.SECRETAIRE.value,
    Role.COMPTABLE.value, Role.RESPONSABLE_PEDAGOGIQUE.value,
}


def eleve_visible_pour(utilisateur, eleve) -> bool:
    """
    Règle de visibilité centrale d'un élève, utilisée par les notes, les
    absences, les documents officiels et l'Assistant : l'élève lui-même,
    son ou ses parents, un enseignant qui lui enseigne, ou un rôle de
    direction/gestion (avec cloisonnement par cycle pour les directeurs) -
    jamais un autre élève, ni un rôle sans lien direct avec les dossiers
    élèves (bibliothécaire, personnel générique).
    """
    if utilisateur.pk == eleve.pk:
        return True
    if utilisateur.role == Role.PARENT:
        return eleve.parents_lies.filter(pk=utilisateur.pk).exists()
    if utilisateur.role == Role.ENSEIGNANT:
        return Affectation.objects.filter(
            enseignant=utilisateur, classe__inscriptions__eleve=eleve,
        ).exists()
    if utilisateur.role not in ROLES_VOIENT_TOUT_ELEVE_DE_LETABLISSEMENT:
        return False
    classes_ok = classes_visibles_pour(utilisateur)
    return eleve.inscriptions.filter(classe__in=classes_ok).exists()
