"""Formulaire public de pré-inscription : ouvert à tout visiteur, donc validé strictement et protégé contre les robots."""
import datetime

from django import forms

from comptes.forms import BootstrapFormMixin
from comptes.utils import numero_international
from tests_niveau.preinscription import classes_proposees

AGE_MINIMAL, AGE_MAXIMAL = 2, 25


class PreinscriptionForm(BootstrapFormMixin, forms.Form):
    prenom = forms.CharField(label="Prénom de l'enfant", max_length=100)
    nom = forms.CharField(label="Nom de l'enfant", max_length=100)
    date_naissance = forms.DateField(label="Date de naissance", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    sexe = forms.ChoiceField(label="Sexe", choices=[("F", "Féminin"), ("M", "Masculin")])
    classe_visee = forms.ModelChoiceField(label="Classe demandée", queryset=None)
    nom_parent = forms.CharField(label="Nom du parent ou tuteur", max_length=150)
    email = forms.EmailField(label="Adresse email du parent (pour recevoir la réponse)", required=False, max_length=254)
    telephone = forms.CharField(label="Téléphone du parent", required=False, max_length=20)
    message = forms.CharField(label="Message (facultatif)", required=False, max_length=500, widget=forms.Textarea(attrs={"rows": 3}))
    consentement = forms.BooleanField(
        label="J'accepte que ces informations soient utilisées par l'établissement pour traiter cette demande.",
        error_messages={"required": "Vous devez accepter pour envoyer la demande."},
    )
    # Piège à robots : caché aux personnes (voir le gabarit), un robot le remplit. Une demande où il est rempli est ignorée en silence.
    site_web = forms.CharField(label="Ne pas remplir", required=False, max_length=200)

    def __init__(self, *args, campagne, **kwargs):
        super().__init__(*args, **kwargs)
        self.campagne = campagne
        self.fields["classe_visee"].queryset = classes_proposees(campagne)
        self.fields["classe_visee"].label_from_instance = lambda classe: classe.nom
        self.fields["site_web"].widget.attrs.update({"tabindex": "-1", "autocomplete": "off"})

    @property
    def est_un_robot(self) -> bool:
        return bool(self.cleaned_data.get("site_web"))

    def clean_prenom(self):
        return " ".join(self.cleaned_data["prenom"].split())

    def clean_nom(self):
        return " ".join(self.cleaned_data["nom"].split())

    def clean_nom_parent(self):
        return " ".join(self.cleaned_data["nom_parent"].split())

    def clean_message(self):
        return " ".join((self.cleaned_data.get("message") or "").split())

    def clean_date_naissance(self):
        date = self.cleaned_data["date_naissance"]
        aujourdhui = datetime.date.today()
        age = (aujourdhui - date).days / 365.25
        if date > aujourdhui or not AGE_MINIMAL <= age <= AGE_MAXIMAL:
            raise forms.ValidationError("Cette date de naissance ne correspond pas à un enfant en âge d'être scolarisé.")
        return date

    def clean_telephone(self):
        valeur = (self.cleaned_data.get("telephone") or "").strip()
        if valeur and not numero_international(valeur)[0]:
            raise forms.ValidationError("Numéro invalide : 8 chiffres (Mali) ou un numéro international, par exemple +223 70 00 00 00.")
        return valeur

    def clean(self):
        donnees = super().clean()
        if not donnees.get("email") and not donnees.get("telephone") and not self.errors.get("email") and not self.errors.get("telephone"):
            self.add_error("telephone", "Donnez au moins une adresse email ou un numéro de téléphone pour que l'école puisse vous répondre.")
        return donnees


class CampagneForm(BootstrapFormMixin, forms.ModelForm):
    """La direction ouvre une campagne de pré-inscription."""

    class Meta:
        from tests_niveau.models import CampagnePreinscription

        model = CampagnePreinscription
        fields = ["titre", "annee_scolaire", "message_accueil", "date_ouverture", "date_cloture"]
        widgets = {
            "date_ouverture": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "date_cloture": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, etablissement, **kwargs):
        super().__init__(*args, **kwargs)
        from scolarite.models import AnneeScolaire

        self.etablissement = etablissement
        self.fields["annee_scolaire"].queryset = AnneeScolaire.objects.filter(etablissement=etablissement, est_archivee=False).order_by("-date_debut")
        self.fields["annee_scolaire"].label = "Année scolaire"

    def clean_titre(self):
        return " ".join(self.cleaned_data["titre"].split())

    def save(self, commit=True):
        campagne = super().save(commit=False)
        campagne.etablissement = self.etablissement
        if commit:
            campagne.save()
        return campagne


class ConvocationForm(BootstrapFormMixin, forms.Form):
    date_test = forms.DateField(label="Date du test", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))

    def clean_date_test(self):
        date = self.cleaned_data["date_test"]
        if date < datetime.date.today():
            raise forms.ValidationError("La date du test ne peut pas être dans le passé.")
        return date
