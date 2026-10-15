from django import forms

from comptes.forms import BootstrapFormMixin
from comptes.models import FormationPedagogique, Sexe, SituationHandicap, StatutDeplacement, StatutPersonnel
from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role, StatutCompte
from etablissement.models import Etablissement
from scolarite.models import AnneeScolaire, role_autorise_pour_plan

# Les rôles à accès total inconditionnel (développeur, fondateur,
# administrateur général) ne sont jamais attribuables depuis cette interface :
# un compte développeur compromis ne doit pas pouvoir s'en servir pour créer
# une porte dérobée permanente sur un autre compte. Seul le propriétaire de la
# plateforme les attribue : fondateur et administrateur général depuis sa page
# « Comptes » d'une école (espace_plateforme.views.creer_compte_direction), le
# développeur d'une école à la création de l'école, ou par la console.
ROLES_ATTRIBUABLES = [
    (valeur, libelle) for valeur, libelle in Role.choices
    if valeur not in {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL}
]


CHAMPS_PERSONNEL = (
    "statut_personnel", "diplome", "discipline", "formation_pedagogique", "date_prise_service", "heures_hebdomadaires",
    "sexe",
)
CHAMPS_ETAT_CIVIL_ELEVE = ("lieu_naissance", "numero_acte_naissance", "handicap", "statut_deplacement")
TOUS_CHAMPS_ADMINISTRATIFS = CHAMPS_PERSONNEL + CHAMPS_ETAT_CIVIL_ELEVE

# Jamais effacés à un changement de rôle : le sexe d'une personne ne dépend pas de son rôle (il sert aux
# statistiques par sexe), contrairement à une fiche de personnel ou à un état civil d'élève.
CHAMPS_CONSERVES = ("sexe",)

# Valeur d'un champ « effacé » : une date ou un nombre vide se stocke en NULL, un texte en chaîne vide.
VALEURS_VIDES = {"date_prise_service": None, "heures_hebdomadaires": None, "sexe": None}


def valeur_vide(nom):
    return VALEURS_VIDES.get(nom, "")


def est_vide(valeur) -> bool:
    return valeur is None or valeur == ""


def champs_applicables(role):
    if role == Role.ELEVE:
        return CHAMPS_ETAT_CIVIL_ELEVE
    if role == Role.PARENT:
        return ()
    return CHAMPS_PERSONNEL


class ModifierCompteForm(BootstrapFormMixin, forms.Form):
    role = forms.ChoiceField(
        label="Rôle", choices=ROLES_ATTRIBUABLES,
        help_text="Changer de rôle efface les informations administratives qui ne concernent plus le "
                   "nouveau rôle (fiche du personnel, état civil d'un élève).",
    )
    statut = forms.ChoiceField(label="Statut du compte", choices=StatutCompte.choices)

    statut_personnel = forms.ChoiceField(
        label="Situation administrative (personnel)", required=False,
        choices=[("", "---------")] + list(StatutPersonnel.choices),
    )
    diplome = forms.CharField(label="Diplôme le plus élevé (personnel)", required=False, max_length=120)
    discipline = forms.CharField(label="Discipline enseignée (personnel)", required=False, max_length=100)
    lieu_naissance = forms.CharField(label="Lieu de naissance (élève)", required=False, max_length=120)
    numero_acte_naissance = forms.CharField(
        label="N° d'extrait d'acte de naissance (élève)", required=False, max_length=60,
    )
    formation_pedagogique = forms.ChoiceField(
        label="Formation pédagogique (personnel)", required=False,
        choices=[("", "---------")] + list(FormationPedagogique.choices),
    )
    date_prise_service = forms.DateField(
        label="Date de prise de service (personnel)", required=False, widget=forms.DateInput(attrs={"type": "date"}),
    )
    heures_hebdomadaires = forms.IntegerField(
        label="Heures d'enseignement par semaine (personnel)", required=False, min_value=0, max_value=60,
    )
    sexe = forms.ChoiceField(
        label="Sexe (personnel)", required=False, choices=[("", "---------")] + list(Sexe.choices),
    )
    handicap = forms.ChoiceField(
        label="Situation de handicap (élève)", required=False,
        choices=[("", "---------")] + list(SituationHandicap.choices),
    )
    statut_deplacement = forms.ChoiceField(
        label="Situation de déplacement (élève)", required=False,
        choices=[("", "---------")] + list(StatutDeplacement.choices),
    )

    def __init__(self, *args, etablissement=None, compte=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.etablissement = etablissement
        self.compte = compte
        # Un rôle de direction propre à un cycle (Directeur du 2ème cycle/
        # Lycée, Censeur, Surveillant général) n'est proposé que si
        # l'abonnement de l'établissement couvre ce cycle - sinon l'école
        # pourrait s'attribuer un rôle pour un cycle qu'elle ne paie pas.
        self.fields["role"].choices = [
            (valeur, libelle) for valeur, libelle in ROLES_ATTRIBUABLES
            if role_autorise_pour_plan(valeur, etablissement)
        ]
        champs_a_garder = champs_applicables(getattr(compte, "role", None))
        for nom in TOUS_CHAMPS_ADMINISTRATIFS:
            if nom not in champs_a_garder:
                del self.fields[nom]

    def clean_role(self):
        role = self.cleaned_data["role"]
        if not role_autorise_pour_plan(role, self.etablissement):
            raise forms.ValidationError("L'abonnement de votre établissement ne couvre pas ce rôle.")
        return role

    def champs_administratifs(self):
        resultat = {}
        for nom in TOUS_CHAMPS_ADMINISTRATIFS:
            if nom not in self.fields:
                continue
            valeur = self.cleaned_data.get(nom)
            if isinstance(valeur, str):
                valeur = valeur.strip()
            resultat[nom] = valeur_vide(nom) if est_vide(valeur) else valeur
        return resultat


class ParametresEtablissementForm(BootstrapFormMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Facultatif : un envoi qui ne contient pas ce champ (ancien formulaire) conserve la situation
        # actuelle de l'école au lieu d'être refusé (ModelForm : champ omis + valeur par défaut = inchangé).
        self.fields["situation_fonctionnement"].required = False
        # Même principe pour le coefficient de la conduite : absent ou vide, il garde la valeur actuelle.
        self.fields["coefficient_conduite"].required = False
        self.fields["langue_par_defaut"].required = False

    def clean_langue_par_defaut(self):
        return self.cleaned_data.get("langue_par_defaut") or self.instance.langue_par_defaut or "fr"

    def clean_coefficient_conduite(self):
        valeur = self.cleaned_data.get("coefficient_conduite")
        return self.instance.coefficient_conduite if valeur is None else valeur

    def clean_telephone_facturation(self):
        from comptes.utils import numero_international

        valeur = (self.cleaned_data.get("telephone_facturation") or "").strip()
        if valeur and not numero_international(valeur)[0]:
            raise forms.ValidationError("Numéro invalide : 8 chiffres (Mali) ou un numéro international, par exemple +223 70 00 00 00.")
        return valeur

    def clean_code_etablissement(self):
        return " ".join(self.cleaned_data.get("code_etablissement", "").split()).upper()

    class Meta:
        model = Etablissement
        fields = [
            "nom", "devise", "logo", "code_devise", "pas_montant", "coefficient_conduite", "email_facturation", "telephone_facturation", "langue_par_defaut",
            "code_etablissement", "statut_juridique", "region", "cercle", "commune", "milieu",
            "rattachement_administratif", "numero_agrement",
            "situation_fonctionnement", "motif_fermeture", "date_situation",
            "taux_inps_salarie", "taux_inps_employeur", "taux_amo_salarie", "taux_amo_employeur",
        ]
        widgets = {"date_situation": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}


class CreerAnneeScolaireForm(BootstrapFormMixin, forms.Form):
    libelle = forms.CharField(label="Libellé", max_length=20, help_text="Exemple : 2026-2027")
    date_debut = forms.DateField(label="Date de début", widget=forms.DateInput(attrs={"type": "date"}))
    date_fin = forms.DateField(label="Date de fin", widget=forms.DateInput(attrs={"type": "date"}))
    est_active = forms.BooleanField(
        label="Année active", required=False,
        help_text="Les nouvelles classes s'y rattachent par défaut. Désactive automatiquement l'année "
                   "active précédente de cet établissement (une seule à la fois).",
    )

    def __init__(self, *args, etablissement=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.etablissement = etablissement

    def clean(self):
        cleaned = super().clean()
        date_debut, date_fin = cleaned.get("date_debut"), cleaned.get("date_fin")
        if date_debut and date_fin and date_fin <= date_debut:
            self.add_error("date_fin", "La date de fin doit être postérieure à la date de début.")
        libelle = cleaned.get("libelle")
        if libelle and AnneeScolaire.objects.filter(etablissement=self.etablissement, libelle=libelle).exists():
            self.add_error("libelle", "Une année scolaire porte déjà ce libellé pour cet établissement.")
        return cleaned

    def save(self):
        return AnneeScolaire.objects.create(
            etablissement=self.etablissement,
            libelle=self.cleaned_data["libelle"],
            date_debut=self.cleaned_data["date_debut"],
            date_fin=self.cleaned_data["date_fin"],
            est_active=self.cleaned_data["est_active"],
        )


class ConfirmerRetraitEleveForm(BootstrapFormMixin, forms.Form):
    """Le développeur retape le matricule : un clic distrait ne suffit pas pour effacer un élève."""

    confirmation = forms.CharField(label="Retapez le matricule pour confirmer", max_length=20)

    def __init__(self, *args, matricule, **kwargs):
        super().__init__(*args, **kwargs)
        self._matricule = matricule

    def clean_confirmation(self):
        saisi = self.cleaned_data["confirmation"].strip()
        if saisi != self._matricule:
            raise forms.ValidationError("Ce n'est pas le matricule de cet élève.")
        return saisi
