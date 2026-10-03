from django import forms

from comptes.forms import BootstrapFormMixin
from comptes.models import Sexe, Utilisateur
from comptes.roles import Role
from scolarite.models import PAS_MONTANT as PAS_MONTANT_PAR_DEFAUT
from scolarite.models import DEVISE_PAR_DEFAUT, AnneeScolaire, Classe, Cycle, EcheancierFrais, Serie


class CreerClasseForm(BootstrapFormMixin, forms.Form):
    nom = forms.CharField(label="Nom de la classe", max_length=60, help_text="Exemple : 3ème année A")
    cycle = forms.ChoiceField(label="Cycle", choices=Cycle.choices)
    serie = forms.ChoiceField(
        label="Série", choices=[("", "— Aucune (hors lycée, ou 10ème année) —")] + Serie.choices,
        required=False, help_text="Uniquement pour une classe de 11ème ou 12ème année.",
    )
    annee_scolaire = forms.ModelChoiceField(label="Année scolaire", queryset=AnneeScolaire.objects.none())
    montant_inscription = forms.IntegerField(label="Frais d'inscription", min_value=0)
    montant_tranche_1 = forms.IntegerField(label="Tranche 1", min_value=0)
    montant_tranche_2 = forms.IntegerField(label="Tranche 2", min_value=0)

    def __init__(self, *args, etablissement=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.etablissement = etablissement
        self.pas_montant = getattr(etablissement, "pas_montant", PAS_MONTANT_PAR_DEFAUT)
        self.devise = getattr(etablissement, "code_devise", DEVISE_PAR_DEFAUT)
        for champ in ["montant_inscription", "montant_tranche_1", "montant_tranche_2"]:
            self.fields[champ].label = f"{self.fields[champ].label} ({self.devise})"
        self.fields["montant_inscription"].help_text = f"Multiple de {self.pas_montant} {self.devise}."
        self.fields["annee_scolaire"].queryset = AnneeScolaire.objects.filter(etablissement=etablissement)
        self.fields["annee_scolaire"].initial = AnneeScolaire.active(etablissement)

    def clean(self):
        cleaned = super().clean()
        for champ in ["montant_inscription", "montant_tranche_1", "montant_tranche_2"]:
            valeur = cleaned.get(champ)
            if valeur is not None and valeur % self.pas_montant != 0:
                self.add_error(champ, f"Doit être un multiple de {self.pas_montant} {self.devise}.")
        nom = cleaned.get("nom")
        annee = cleaned.get("annee_scolaire")
        if nom and annee and Classe.objects.filter(nom=nom, annee_scolaire=annee).exists():
            self.add_error("nom", "Une classe porte déjà ce nom pour cette année scolaire.")
        if cleaned.get("serie") and cleaned.get("cycle") != Cycle.LYCEE:
            self.add_error("serie", "Une série ne s'applique qu'à une classe du cycle Lycée.")
        return cleaned

    def save(self):
        classe = Classe.objects.create(
            nom=self.cleaned_data["nom"], cycle=self.cleaned_data["cycle"],
            serie=self.cleaned_data["serie"], annee_scolaire=self.cleaned_data["annee_scolaire"],
        )
        EcheancierFrais.objects.create(
            classe=classe,
            montant_inscription=self.cleaned_data["montant_inscription"],
            montant_tranche_1=self.cleaned_data["montant_tranche_1"],
            montant_tranche_2=self.cleaned_data["montant_tranche_2"],
        )
        return classe


class AffecterEnseignantForm(BootstrapFormMixin, forms.Form):
    enseignant = forms.ModelChoiceField(
        label="Enseignant", queryset=Utilisateur.objects.filter(role=Role.ENSEIGNANT),
    )
    classe = forms.ModelChoiceField(label="Classe", queryset=Classe.objects.none())
    matiere = forms.CharField(
        label="Matière (optionnel)", max_length=100, required=False,
        help_text="Laissez vide pour un enseignant titulaire (toutes matières).",
    )
    coefficient = forms.IntegerField(
        label="Coefficient", min_value=1, initial=1, required=False,
        help_text="Poids de cette matière dans la moyenne du bulletin. 1 = compte comme les autres.",
    )

    def __init__(self, *args, etablissement=None, classes_disponibles=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["enseignant"].queryset = Utilisateur.objects.filter(
            role=Role.ENSEIGNANT, etablissement=etablissement,
        ).order_by("nom", "prenom")
        if classes_disponibles is not None:
            self.fields["classe"].queryset = classes_disponibles


class InscrireEleveForm(BootstrapFormMixin, forms.Form):
    prenom = forms.CharField(label="Prénom de l'élève", max_length=100)
    nom = forms.CharField(label="Nom de l'élève", max_length=100)
    matricule = forms.CharField(
        label="Matricule (optionnel)", max_length=20, required=False,
        help_text="Laissez vide pour générer automatiquement un matricule.",
    )
    sexe = forms.ChoiceField(label="Sexe", choices=Sexe.choices)
    date_naissance = forms.DateField(
        label="Date de naissance", required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    classe = forms.ModelChoiceField(label="Classe", queryset=Classe.objects.none())
    parent_email_1 = forms.EmailField(label="Email du 1er parent")
    parent_email_2 = forms.EmailField(label="Email du 2ème parent (optionnel)", required=False)

    def __init__(self, *args, classes_disponibles=None, etablissement=None, **kwargs):
        super().__init__(*args, **kwargs)
        if classes_disponibles is not None:
            self.fields["classe"].queryset = classes_disponibles
        self._etablissement = etablissement

    def _recuperer_parent(self, champ, email):
        if not email:
            return None
        try:
            # Cloisonné au même établissement que l'élève à inscrire : sans
            # ce filtre, un email appartenant à un parent d'un autre
            # établissement serait trouvé ici, pour échouer plus tard dans
            # lier_parent_a_eleve (après que l'élève a déjà été créé) - en
            # filtrant ici, le formulaire refuse proprement avant toute
            # écriture, avec le même message que « email inconnu » pour ne
            # pas révéler l'existence d'un compte dans un autre établissement.
            parent = Utilisateur.objects.get(email__iexact=email, etablissement=self._etablissement)
        except Utilisateur.DoesNotExist:
            self.add_error(champ, "Aucun compte trouvé avec cet email.")
            return None
        if parent.role != Role.PARENT:
            self.add_error(champ, "Ce compte n'a pas le rôle « parent ».")
            return None
        return parent

    def clean_matricule(self):
        matricule = self.cleaned_data["matricule"].strip()
        if matricule and Utilisateur.objects.filter(matricule=matricule).exists():
            raise forms.ValidationError("Ce matricule est déjà utilisé par un autre élève.")
        return matricule

    def clean(self):
        cleaned = super().clean()
        parent_1 = self._recuperer_parent("parent_email_1", cleaned.get("parent_email_1"))
        parent_2 = self._recuperer_parent("parent_email_2", cleaned.get("parent_email_2"))
        if parent_1 and parent_2 and parent_1.pk == parent_2.pk:
            self.add_error("parent_email_2", "Les deux parents doivent être des comptes différents.")
        cleaned["parent_1"] = parent_1
        cleaned["parent_2"] = parent_2
        return cleaned
