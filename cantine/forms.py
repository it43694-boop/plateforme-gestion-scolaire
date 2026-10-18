"""Formulaires de la cantine : formules, inscription d'élèves, paiement, fin d'inscription."""
from django import forms
from django.utils import timezone

from cantine.models import FormuleCantine
from comptes.forms import BootstrapFormMixin
from finances.models import ModePaiement


def _devise(etablissement) -> str:
    return getattr(etablissement, "code_devise", None) or "FCFA"


class FormuleForm(BootstrapFormMixin, forms.ModelForm):
    montant = forms.IntegerField(label="Tarif", min_value=1)

    class Meta:
        model = FormuleCantine
        fields = ["libelle", "mode", "montant"]

    def __init__(self, *args, etablissement, **kwargs):
        super().__init__(*args, **kwargs)
        self.etablissement = etablissement
        self.fields["montant"].label = f"Tarif ({_devise(etablissement)})"
        self.fields["montant"].help_text = "Par mois ou par repas selon le paiement choisi."

    def clean_libelle(self):
        libelle = " ".join(self.cleaned_data["libelle"].split())
        if FormuleCantine.objects.filter(etablissement=self.etablissement, libelle__iexact=libelle).exists():
            raise forms.ValidationError("Une formule porte déjà ce nom.")
        return libelle

    def save(self, commit=True):
        formule = super().save(commit=False)
        formule.etablissement = self.etablissement
        if commit:
            formule.save()
        return formule


class InscrireForm(BootstrapFormMixin, forms.Form):
    formule = forms.ModelChoiceField(
        label="Formule", queryset=FormuleCantine.objects.none(), widget=forms.RadioSelect, empty_label=None,
        error_messages={"required": "Choisissez la formule : au mois ou au repas."},
    )
    date_debut = forms.DateField(label="À partir du", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    eleves = forms.ModelMultipleChoiceField(
        label="Élèves à inscrire", queryset=None, widget=forms.CheckboxSelectMultiple,
        error_messages={"required": "Cochez au moins un élève."},
    )

    def __init__(self, *args, formules, eleves, **kwargs):
        kwargs.setdefault("initial", {"date_debut": timezone.localdate()})
        super().__init__(*args, **kwargs)
        self.fields["formule"].queryset = formules
        self.fields["eleves"].queryset = eleves
        self.fields["eleves"].label_from_instance = lambda eleve: f"{eleve.nom_complet} ({eleve.matricule})"


class PaiementCantineForm(BootstrapFormMixin, forms.Form):
    montant = forms.IntegerField(label="Montant", min_value=1)
    mode_paiement = forms.ChoiceField(label="Mode de paiement", choices=ModePaiement.choices)

    def __init__(self, *args, etablissement=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["montant"].label = f"Montant ({_devise(etablissement)})"


class TerminerForm(BootstrapFormMixin, forms.Form):
    date_fin = forms.DateField(label="Dernier jour à la cantine", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("initial", {"date_fin": timezone.localdate()})
        super().__init__(*args, **kwargs)


class AnnulationForm(BootstrapFormMixin, forms.Form):
    motif = forms.CharField(label="Motif de l'annulation", max_length=255, widget=forms.TextInput())
