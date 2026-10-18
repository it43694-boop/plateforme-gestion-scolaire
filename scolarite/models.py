import re
import secrets
import uuid

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role
from comptes.uploads import chemin_upload_unique
from comptes.validators import valider_contenu_fichier, valider_extension_document, valider_taille_fichier_10mo
from etablissement.models import PlanEtablissement


def chemin_upload_transfert(instance, nom_fichier):
    # Justificatif de transfert : donnée personnelle sensible, jamais un nom devinable.
    etablissement_id = instance.enregistre_par.etablissement_id if instance.enregistre_par_id else None
    return chemin_upload_unique("transferts", etablissement_id, nom_fichier)


class Cycle(models.TextChoices):
    """
    Cycles de l'enseignement malien (cf. cahier des charges pour le
    fondamental ; le lycée a été ajouté ensuite sur le même principe -
    seconde à terminale, menant au baccalauréat malien). PROFESSIONNEL
    n'est pas une suite du 2ème cycle mais une branche parallèle au Lycée :
    après le DEF, un élève part soit au Lycée général soit en enseignement
    technique et professionnel (CAP/BT) - jamais les deux à la suite l'un
    de l'autre. Voir FiliereProfessionnelle pour le détail CAP/BT.
    """
    PRESCOLAIRE = "prescolaire", "Préscolaire"
    PREMIER_CYCLE = "1er_cycle", "1er cycle"
    DEUXIEME_CYCLE = "2eme_cycle", "2ème cycle"
    LYCEE = "lycee", "Lycée"
    PROFESSIONNEL = "professionnel", "Enseignement professionnel"


class Niveau(models.TextChoices):
    """Année d'études structurée pour regrouper les sections d'un même niveau."""
    ANNEE_1 = "annee_1", "1ère année"
    ANNEE_2 = "annee_2", "2ème année"
    ANNEE_3 = "annee_3", "3ème année"
    ANNEE_4 = "annee_4", "4ème année"
    ANNEE_5 = "annee_5", "5ème année"
    ANNEE_6 = "annee_6", "6ème année"
    ANNEE_7 = "annee_7", "7ème année"
    ANNEE_8 = "annee_8", "8ème année"
    ANNEE_9 = "annee_9", "9ème année"
    ANNEE_10 = "annee_10", "10ème année"
    ANNEE_11 = "annee_11", "11ème année"
    ANNEE_12 = "annee_12", "12ème année"
    PRESCOLAIRE_PETITE = "presco_ps", "Petite section"
    PRESCOLAIRE_MOYENNE = "presco_ms", "Moyenne section"
    PRESCOLAIRE_GRANDE = "presco_gs", "Grande section"


NIVEAUX_PAR_CYCLE = {
    Cycle.PRESCOLAIRE: ["presco_ps", "presco_ms", "presco_gs"],
    Cycle.PREMIER_CYCLE: [f"annee_{annee}" for annee in range(1, 7)],
    Cycle.DEUXIEME_CYCLE: [f"annee_{annee}" for annee in range(7, 10)],
    Cycle.LYCEE: [f"annee_{annee}" for annee in range(10, 13)],
}


class DomaineProfessionnel(models.TextChoices):
    """Domaine de formation d'une classe CAP/BT : les statistiques officielles séparent industrie et tertiaire."""
    INDUSTRIEL = "industriel", "Industriel"
    TERTIAIRE = "tertiaire", "Tertiaire"


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


class FiliereProfessionnelle(models.TextChoices):
    """
    Les deux filières de l'enseignement secondaire professionnel malien -
    le métier/la spécialité exacte (électricité, couture, mécanique...)
    reste en texte libre dans le nom de la classe, comme pour les autres
    cycles ; seule la filière (durée, diplôme) est structurée ici.
    """
    CAP = "cap", "CAP - cycle court (2 ans)"
    BT = "bt", "BT - cycle long (4 ans)"


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
    # Formules « seul » : pour un lycée ou une école professionnelle sans
    # fondamental. Le lycée seul peut quand même cumuler le professionnel via
    # le réglage inclut_professionnel (cycles_autorises_pour).
    PlanEtablissement.LYCEE_SEUL.value: {Cycle.LYCEE.value},
    PlanEtablissement.PROFESSIONNEL_SEUL.value: {Cycle.PROFESSIONNEL.value},
    PlanEtablissement.PRESCOLAIRE_SEUL.value: {Cycle.PRESCOLAIRE.value},
}

def cycles_autorises_pour(etablissement) -> set:
    """
    Valeurs de cycle (chaînes) couvertes par l'abonnement d'un
    établissement (voir CYCLES_PAR_PLAN). L'enseignement professionnel est
    un réglage indépendant de la formule (Etablissement.inclut_
    professionnel) plutôt qu'une formule de plus : contrairement au 1er
    cycle/2ème cycle/Lycée qui forment une progression cumulative, le
    professionnel est une branche parallèle au Lycée que n'importe quelle
    formule peut inclure ou non (cf. recherche Mali - un même établissement
    peut cumuler fondamental, lycée ET professionnel).
    """
    if etablissement is None:
        return set(Cycle.values)
    cycles = set(CYCLES_PAR_PLAN.get(etablissement.plan, set(Cycle.values)))
    if getattr(etablissement, "inclut_professionnel", False):
        cycles.add(Cycle.PROFESSIONNEL.value)
    if getattr(etablissement, "inclut_prescolaire", False):
        cycles.add(Cycle.PRESCOLAIRE.value)
    return cycles


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
    nom_ar = models.CharField(
        "nom en arabe", max_length=60, blank=True,
        help_text="Nom de la classe écrit en arabe (facultatif) : vide, une proposition automatique est utilisée pour les noms usuels de classes.",
    )
    cycle = models.CharField(max_length=20, choices=Cycle.choices)
    serie = models.CharField(
        "série", max_length=20, choices=Serie.choices, blank=True,
        help_text="Uniquement pour une classe de 11ème ou 12ème année (lycée) - laisser vide sinon.",
    )
    filiere_professionnelle = models.CharField(
        "filière", max_length=20, choices=FiliereProfessionnelle.choices, blank=True,
        help_text="Uniquement pour une classe du cycle Enseignement professionnel - laisser vide sinon. "
                   "Le métier exact (électricité, couture...) se précise dans le nom de la classe.",
    )
    domaine_professionnel = models.CharField(
        "domaine", max_length=12, choices=DomaineProfessionnel.choices, blank=True,
        help_text="Uniquement pour une classe du cycle Enseignement professionnel : industriel ou tertiaire "
                   "(les statistiques officielles distinguent les deux). Facultatif.",
    )
    niveau = models.CharField(
        "niveau (année d'études)", max_length=10, choices=Niveau.choices, blank=True,
        help_text="Année d'études structurée (1ère à 12ème) pour regrouper les sections parallèles. Facultatif.",
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

    @property
    def examens_officiels(self):
        """Examens officiels que préparent les élèves de cette classe (liste vide si aucun)."""
        return examens_pour_classe(self)

    def clean(self):
        super().clean()
        if self.niveau and self.niveau not in NIVEAUX_PAR_CYCLE.get(self.cycle, []):
            raise ValidationError("Ce niveau ne correspond pas au cycle de la classe.")
        if self.serie and self.cycle != Cycle.LYCEE:
            raise ValidationError("Une série ne s'applique qu'à une classe du cycle Lycée.")
        if self.filiere_professionnelle and self.cycle != Cycle.PROFESSIONNEL:
            raise ValidationError("Une filière ne s'applique qu'à une classe du cycle Enseignement professionnel.")
        if self.domaine_professionnel and self.cycle != Cycle.PROFESSIONNEL:
            raise ValidationError("Un domaine ne s'applique qu'à une classe du cycle Enseignement professionnel.")
        if self.cycle == Cycle.PROFESSIONNEL and not self.filiere_professionnelle:
            raise ValidationError("Une classe du cycle Enseignement professionnel doit préciser sa filière (CAP ou BT).")
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
        ABANDON = "abandon", "Abandon"

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


def calculer_scolarite_nette(inscription, aides_actives=None):
    """
    Le net dû pour la scolarité seule (inscription + versements), après les aides actives de l'inscription.

    `aides_actives` : liste déjà chargée des aides actives de CETTE inscription, à fournir quand l'appelant boucle sur plusieurs inscriptions
    (ex. finances.views.suivi_paiements, assistant.alertes._familles_impayees) pour éviter une requête par élève.
    """
    echeancier = getattr(inscription.classe, "echeancier", None)
    brut = echeancier.total_annuel if echeancier else 0
    remise = 0
    aides = aides_actives if aides_actives is not None else inscription.aides_scolarite.filter(active=True)
    for aide in aides:
        remise += aide.montant or round(brut * aide.pourcentage / 100)
    return max(brut - remise, 0)


def total_frais_annexes(inscription) -> int:
    """La somme des frais annexes (de la classe et de toute l'école, pour l'année de l'inscription) que cette inscription doit en plus."""
    from django.db.models import Q, Sum

    from finances.models import FraisAnnexe

    classe = inscription.classe
    return FraisAnnexe.objects.filter(annee_scolaire_id=classe.annee_scolaire_id).filter(
        Q(classe__isnull=True) | Q(classe_id=classe.pk),
    ).aggregate(total=Sum("montant"))["total"] or 0


def calculer_total_du(inscription, aides_actives=None, annexes=None):
    """
    Le total dû par l'élève pour cette inscription : la scolarité nette des aides actives, plus les frais annexes (que les aides ne réduisent
    jamais).

    `aides_actives` et `annexes` : valeurs déjà chargées (liste des aides ; total des frais annexes), à fournir quand l'appelant boucle sur
    plusieurs inscriptions ; sans elles, une requête de plus est faite ici.
    """
    return calculer_scolarite_nette(inscription, aides_actives) + (total_frais_annexes(inscription) if annexes is None else annexes)


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
        upload_to=chemin_upload_transfert, blank=True,
        validators=[valider_taille_fichier_10mo, valider_extension_document, valider_contenu_fichier],
    )
    enregistre_par = models.ForeignKey("comptes.Utilisateur", on_delete=models.PROTECT, related_name="transferts_enregistres")
    cree_le = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        if not self.etablissement_destination_id and not self.destination_libelle:
            raise ValidationError(
                "Indiquez l'établissement de destination (sur la plateforme, ou en texte libre)."
            )


class Abandon(models.Model):
    """
    Élève qui a cessé de fréquenter l'établissement en cours d'année sans
    transfert formel vers une autre école (voir TransfertEleve pour ce
    second cas) - contrairement au transfert, pas de document ni
    d'établissement de destination à renseigner.
    """

    inscription = models.OneToOneField(Inscription, on_delete=models.PROTECT, related_name="abandon")
    date_abandon = models.DateField()
    motif = models.CharField(max_length=255)
    enregistre_par = models.ForeignKey("comptes.Utilisateur", on_delete=models.PROTECT, related_name="abandons_enregistres")
    cree_le = models.DateTimeField(auto_now_add=True)


def cloturer_inscription(*, inscription, decision, acteur, motif, date_evenement, destination_libelle="", justificatif=None):
    """
    Clôt l'inscription d'un élève en cours d'année scolaire - abandon ou
    transfert vers une autre école - indépendamment du passage de classe
    annuel (voir passer_eleve ci-dessus) qui lui traite la fin d'année
    pour toute une classe à la fois, avec une classe de destination dans
    le MÊME établissement. Ici l'élève quitte l'établissement : aucune
    nouvelle inscription n'est créée.
    """
    from django.db import transaction

    if decision not in {Inscription.Statut.ABANDON, Inscription.Statut.TRANSFERE}:
        raise ValidationError("Décision invalide : seuls abandon et transfert sont possibles ici.")
    if inscription.statut != Inscription.Statut.EN_COURS:
        raise ValidationError("Cette inscription a déjà fait l'objet d'une décision.")
    if not motif:
        raise ValidationError("Le motif est requis.")

    with transaction.atomic():
        inscription.statut = decision
        inscription.save(update_fields=["statut"])
        if decision == Inscription.Statut.TRANSFERE:
            transfert = TransfertEleve(
                inscription=inscription, destination_libelle=destination_libelle,
                date_transfert=date_evenement, motif=motif, enregistre_par=acteur,
            )
            if justificatif is not None:
                transfert.justificatif = justificatif
            transfert.full_clean()
            transfert.save()
        else:
            abandon = Abandon(
                inscription=inscription, date_abandon=date_evenement, motif=motif, enregistre_par=acteur,
            )
            abandon.full_clean()
            abandon.save()


class TypeDocumentVerifiable(models.TextChoices):
    ATTESTATION_SCOLARITE = "attestation_scolarite", "Attestation de scolarité"
    CARTE_ELEVE = "carte_eleve", "Carte d'élève"
    CERTIFICAT_SCOLARITE = "certificat_scolarite", "Certificat de scolarité"
    ATTESTATION_FREQUENTATION = "attestation_frequentation", "Attestation de fréquentation"
    CERTIFICAT_RADIATION = "certificat_radiation", "Certificat de radiation"


# Sans I, O, 0 ni 1 : un code recopié à la main depuis une carte imprimée ne se confond pas avec un autre.
ALPHABET_CODE_VERIFICATION = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def nouveau_code_verification() -> str:
    """Un code court qui se recopie à la main, de la forme XXXX-XXXX-XXXX (douze signes sur trente-deux : environ 60 bits, impossible à deviner)."""
    signes = "".join(secrets.choice(ALPHABET_CODE_VERIFICATION) for _ in range(12))
    return "-".join(signes[debut:debut + 4] for debut in (0, 4, 8))


def normaliser_code_verification(texte) -> str:
    """Le code tel qu'il est enregistré, depuis ce que la personne a tapé (minuscules, espaces ou tirets en trop) ; vide si ce n'est pas un code."""
    signes = re.sub(r"[^A-Z0-9]", "", (texte or "").upper())
    if len(signes) != 12 or any(signe not in ALPHABET_CODE_VERIFICATION for signe in signes):
        return ""
    return "-".join(signes[debut:debut + 4] for debut in (0, 4, 8))


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
    numero = models.CharField(
        "numéro du document", max_length=40, blank=True,
        help_text="Numéro d'ordre des documents officiels (exemple : 003/CSE/CERT/2026), attribué à la première émission.",
    )
    code = models.CharField(
        "code court", max_length=14, unique=True, null=True, blank=True, editable=False,
        help_text="Code imprimé sous le QR code (XXXX-XXXX-XXXX) : il se tape sur la page « Vérifier une carte » quand on ne peut pas scanner. "
                  "Vide pour les documents émis avant son introduction.",
    )
    cree_le = models.DateTimeField(auto_now_add=True)
    actif = models.BooleanField(default=True)

    class Meta:
        verbose_name = "document vérifiable"
        verbose_name_plural = "documents vérifiables"
        ordering = ["-cree_le"]

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = nouveau_code_verification()
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Calendrier scolaire
# ---------------------------------------------------------------------------

class TypeEvenement(models.TextChoices):
    RENTREE = "rentree", "Rentrée scolaire"
    VACANCES = "vacances", "Vacances"
    FERIE = "ferie", "Jour férié"
    EXAMEN = "examen", "Examen"
    REUNION = "reunion", "Réunion"
    AUTRE = "autre", "Autre"


class EvenementCalendrier(models.Model):
    """
    Une date (ou une période) du calendrier de l'école : rentrée, vacances, jours fériés, examens, réunions. Lisible par tous les comptes de
    l'école ; les dates « réservées au personnel » (conseil de classe, journée pédagogique...) ne le sont ni des parents ni des élèves.
    """

    etablissement = models.ForeignKey("etablissement.Etablissement", on_delete=models.CASCADE, related_name="evenements_calendrier")
    titre = models.CharField(max_length=200)
    type_evenement = models.CharField("type", max_length=10, choices=TypeEvenement.choices, default=TypeEvenement.AUTRE)
    date_debut = models.DateField("du")
    date_fin = models.DateField("au", null=True, blank=True, help_text="Laissez vide pour une seule journée.")
    description = models.CharField(max_length=255, blank=True)
    reserve_au_personnel = models.BooleanField("réservé au personnel", default=False, help_text="Invisible pour les parents et les élèves.")
    cree_par = models.ForeignKey("comptes.Utilisateur", on_delete=models.SET_NULL, null=True, blank=True, related_name="evenements_crees")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "évènement du calendrier"
        verbose_name_plural = "évènements du calendrier"
        ordering = ["date_debut", "date_fin", "pk"]
        indexes = [models.Index(fields=["etablissement", "date_debut"], name="calendrier_ecole_debut")]

    def __str__(self):
        return f"{self.titre} ({self.date_debut})"

    @property
    def fin(self):
        return self.date_fin or self.date_debut

    @property
    def est_une_periode(self) -> bool:
        return self.fin != self.date_debut

    def clean(self):
        super().clean()
        if self.date_debut and self.date_fin and self.date_fin < self.date_debut:
            raise ValidationError("La date de fin ne peut pas précéder la date de début.")
        if self.date_debut and self.date_fin and (self.date_fin - self.date_debut).days > 366:
            raise ValidationError("Un évènement ne peut pas durer plus d'un an.")


# ---------------------------------------------------------------------------
# Fonctions utilitaires - cloisonnement par cycle et dossier élève
# ---------------------------------------------------------------------------

def evenements_visibles_pour(utilisateur):
    """Les évènements du calendrier de l'école du compte ; sans ceux réservés au personnel pour un parent ou un élève."""
    evenements = EvenementCalendrier.objects.filter(etablissement_id=utilisateur.etablissement_id)
    if utilisateur.role in {Role.PARENT, Role.ELEVE}:
        evenements = evenements.filter(reserve_au_personnel=False)
    return evenements


def prochains_evenements(utilisateur, nombre=5, aujourdhui=None):
    """Les prochaines dates (en cours ou à venir), les plus proches d'abord."""
    import datetime

    from django.db.models import Q

    aujourdhui = aujourdhui or datetime.date.today()
    en_cours_ou_a_venir = Q(date_fin__gte=aujourdhui) | Q(date_fin__isnull=True, date_debut__gte=aujourdhui)
    return list(evenements_visibles_pour(utilisateur).filter(en_cours_ou_a_venir).order_by("date_debut", "pk")[:nombre])


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


def eleves_visibles_pour(utilisateur):
    """
    Les élèves qu'un utilisateur a le droit de consulter : exactement la règle de eleve_visible_pour, mais en UNE requête, pour
    proposer des noms dans une recherche au lieu de vérifier les élèves un par un. Toujours limité à son établissement.
    """
    from comptes.models import Utilisateur

    eleves = Utilisateur.objects.filter(role=Role.ELEVE, etablissement_id=utilisateur.etablissement_id)
    if utilisateur.role == Role.ELEVE:
        return eleves.filter(pk=utilisateur.pk)
    if utilisateur.role == Role.PARENT:
        return eleves.filter(parents_lies=utilisateur)
    if utilisateur.role == Role.ENSEIGNANT:
        classes_enseignees = Affectation.objects.filter(enseignant=utilisateur).values("classe_id")
        return eleves.filter(inscriptions__classe_id__in=classes_enseignees).distinct()
    if utilisateur.role not in ROLES_VOIENT_TOUT_ELEVE_DE_LETABLISSEMENT:
        return eleves.none()
    return eleves.filter(inscriptions__classe__in=classes_visibles_pour(utilisateur)).distinct()


def eleve_de_l_etablissement_ou_404(utilisateur, matricule):
    """
    Élève de l'établissement de l'utilisateur, identifié par son matricule - ou une page introuvable.

    Un matricule d'une AUTRE école doit être indiscernable d'un matricule qui n'existe pas : si l'un répondait
    « accès interdit » (403) et l'autre « introuvable » (404), n'importe quel utilisateur pourrait deviner quels
    matricules existent dans les autres écoles. Dans sa propre école, un élève qu'on ne peut pas voir reste en 403.
    """
    from django.shortcuts import get_object_or_404

    from comptes.models import Utilisateur

    return get_object_or_404(
        Utilisateur, matricule=matricule, role=Role.ELEVE, etablissement_id=utilisateur.etablissement_id,
    )


# Rôles de l'administration scolaire qui peuvent voir les renseignements sensibles d'un élève (état civil,
# handicap, déplacement) - jamais un enseignant, un comptable, le Censeur ni le Surveillant général.
ROLES_ETAT_CIVIL_ELEVE = {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL} | {
    Role.DIRECTEUR_1ER_CYCLE.value, Role.DIRECTEUR_2EME_CYCLE.value,
    Role.DIRECTEUR_LYCEE.value, Role.SECRETAIRE.value, Role.SUPER_ADMINISTRATEUR.value,
}


def peut_voir_etat_civil_eleve(utilisateur, eleve) -> bool:
    """État civil sensible visible par l'élève, ses parents et l'administration scolaire."""
    if utilisateur.pk == eleve.pk:
        return True
    if utilisateur.role == Role.PARENT:
        return eleve.parents_lies.filter(pk=utilisateur.pk).exists()
    return utilisateur.role in ROLES_ETAT_CIVIL_ELEVE and eleve_visible_pour(utilisateur, eleve)


def peut_corriger_dossier_eleve(utilisateur, eleve) -> bool:
    """
    Corriger les renseignements d'un élève (nom, naissance, parents en attente) : l'administration qui voit déjà
    son état civil, pour un élève qu'elle peut voir. Jamais un parent, l'élève lui-même, un enseignant, un comptable.
    """
    return utilisateur.role in ROLES_ETAT_CIVIL_ELEVE and eleve_visible_pour(utilisateur, eleve)


# ---------------------------------------------------------------------------
# Résultats aux examens officiels
# ---------------------------------------------------------------------------

class Examen(models.TextChoices):
    """Examens officiels dont les statistiques nationales publient le taux de réussite."""
    ENTREE_7E = "entree_7e", "Certificat d'entrée en 7ème année"
    DEF = "def", "Diplôme d'études fondamentales (DEF)"
    BAC = "bac", "Baccalauréat"
    CAP = "cap", "CAP"
    BT = "bt", "Brevet de technicien (BT)"


# Cycle de la classe dont les élèves se présentent à chaque examen.
CYCLE_PAR_EXAMEN = {
    Examen.ENTREE_7E.value: Cycle.PREMIER_CYCLE.value,
    Examen.DEF.value: Cycle.DEUXIEME_CYCLE.value,
    Examen.BAC.value: Cycle.LYCEE.value,
    Examen.CAP.value: Cycle.PROFESSIONNEL.value,
    Examen.BT.value: Cycle.PROFESSIONNEL.value,
}


class ResultatExamen(models.Model):
    """
    Résultat d'un élève à un examen officiel, rattaché à son inscription de l'année (donc à sa classe :
    la série du Bac, la filière CAP/BT et le domaine s'en déduisent, sans les ressaisir). Un seul résultat
    par inscription et par examen.
    """

    class Resultat(models.TextChoices):
        ADMIS = "admis", "Admis"
        AJOURNE = "ajourne", "Ajourné"
        ABSENT = "absent", "Absent"

    inscription = models.ForeignKey(Inscription, on_delete=models.CASCADE, related_name="resultats_examens")
    examen = models.CharField(max_length=20, choices=Examen.choices)
    resultat = models.CharField(max_length=10, choices=Resultat.choices)
    enregistre_par = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.SET_NULL, null=True, related_name="resultats_examens_saisis",
    )
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "résultat d'examen"
        verbose_name_plural = "résultats d'examen"
        unique_together = ("inscription", "examen")
        ordering = ["examen", "inscription__eleve__nom"]

    def __str__(self):
        return f"{self.get_examen_display()} - {self.get_resultat_display()}"

    def clean(self):
        super().clean()
        if not self.inscription_id or not self.examen:
            return
        classe = self.inscription.classe
        cycle_attendu = CYCLE_PAR_EXAMEN.get(self.examen)
        if cycle_attendu and classe.cycle != cycle_attendu:
            raise ValidationError(
                f"« {self.get_examen_display()} » concerne les classes du cycle "
                f"« {Cycle(cycle_attendu).label} » : la classe de cet élève est du cycle « {classe.get_cycle_display()} »."
            )
        if self.examen in {Examen.CAP.value, Examen.BT.value} and classe.filiere_professionnelle != self.examen:
            raise ValidationError("La filière de la classe (CAP ou BT) ne correspond pas à cet examen.")

    @property
    def classe(self):
        return self.inscription.classe


# ---------------------------------------------------------------------------
# Fiche d'infrastructures de l'école (une par année scolaire)
# ---------------------------------------------------------------------------

_MAX_EFFECTIF = MaxValueValidator(1_000_000)


class FicheInfrastructure(models.Model):
    """
    Infrastructures et équipements d'une école pour une année scolaire : salles, eau, latrines, électricité,
    mobilier, manuels, cantine. Renseignée par la direction de l'établissement ; sert à la fiche statistique
    annuelle (statistiques.fiche). Les rubriques suivent les priorités du plan décennal PRODEC 2 et de l'étude
    sur l'eau et l'assainissement dans les écoles (UNICEF/MEN, 2017) ; à comparer au questionnaire officiel de
    la CPS, qui n'a pas pu être consulté.
    """

    etablissement = models.ForeignKey(
        "etablissement.Etablissement", on_delete=models.CASCADE, related_name="fiches_infrastructure",
    )
    annee_scolaire = models.ForeignKey(
        AnneeScolaire, on_delete=models.CASCADE, related_name="fiches_infrastructure",
    )

    salles_classe = models.PositiveIntegerField("salles de classe (total)", default=0, validators=[_MAX_EFFECTIF])
    salles_bon_etat = models.PositiveIntegerField("dont en bon état", default=0, validators=[_MAX_EFFECTIF])
    salles_provisoires = models.PositiveIntegerField(
        "dont en matériaux provisoires (paillote, hangar, abri)", default=0, validators=[_MAX_EFFECTIF],
    )
    places_assises = models.PositiveIntegerField(
        "places assises (tables-bancs)", default=0, validators=[_MAX_EFFECTIF],
    )

    points_eau = models.PositiveIntegerField("points d'eau sur le site", default=0, validators=[_MAX_EFFECTIF])
    eau_potable_toute_annee = models.BooleanField("eau potable disponible toute l'année", default=False)
    latrines = models.PositiveIntegerField("latrines (nombre de cabines)", default=0, validators=[_MAX_EFFECTIF])
    latrines_fonctionnelles = models.PositiveIntegerField(
        "dont fonctionnelles", default=0, validators=[_MAX_EFFECTIF],
    )
    latrines_separees = models.BooleanField("latrines séparées filles / garçons", default=False)
    lavage_mains = models.BooleanField("dispositif de lavage des mains", default=False)
    electricite = models.BooleanField("électricité", default=False)

    manuels_lecture = models.PositiveIntegerField("manuels de lecture", default=0, validators=[_MAX_EFFECTIF])
    manuels_calcul = models.PositiveIntegerField("manuels de calcul", default=0, validators=[_MAX_EFFECTIF])
    cantine = models.BooleanField("cantine scolaire", default=False)
    cantine_beneficiaires = models.PositiveIntegerField(
        "élèves bénéficiaires de la cantine", default=0, validators=[_MAX_EFFECTIF],
    )

    modifie_par = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="fiches_infrastructure_modifiees",
    )
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "fiche d'infrastructures"
        verbose_name_plural = "fiches d'infrastructures"
        unique_together = ("etablissement", "annee_scolaire")

    def __str__(self):
        return f"Infrastructures {self.etablissement} - {self.annee_scolaire.libelle}"

    def clean(self):
        super().clean()
        if self.annee_scolaire_id and self.etablissement_id and self.annee_scolaire.etablissement_id != self.etablissement_id:
            raise ValidationError("L'année scolaire et l'établissement doivent correspondre.")
        erreurs = {}
        if self.salles_bon_etat > self.salles_classe:
            erreurs["salles_bon_etat"] = "Ne peut pas dépasser le nombre total de salles de classe."
        if self.salles_provisoires > self.salles_classe:
            erreurs["salles_provisoires"] = "Ne peut pas dépasser le nombre total de salles de classe."
        if self.latrines_fonctionnelles > self.latrines:
            erreurs["latrines_fonctionnelles"] = "Ne peut pas dépasser le nombre de latrines."
        if not self.cantine and self.cantine_beneficiaires:
            erreurs["cantine_beneficiaires"] = "Cochez « cantine scolaire » ou laissez ce nombre à 0."
        if erreurs:
            raise ValidationError(erreurs)


def examens_pour_classe(classe) -> list[str]:
    """Examens officiels auxquels les élèves de cette classe se présentent (selon son cycle et sa filière)."""
    resultat = []
    for examen, cycle in CYCLE_PAR_EXAMEN.items():
        if classe.cycle != cycle:
            continue
        if examen in {Examen.CAP.value, Examen.BT.value} and classe.filiere_professionnelle != examen:
            continue
        resultat.append(examen)
    return resultat
