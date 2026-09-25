from django import forms

from comptes.forms import BootstrapFormMixin
from communication.models import Annonce, Message, Portee


class PublierAnnonceForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Annonce
        fields = ["titre", "contenu", "piece_jointe", "portee", "classe_ciblee"]

    def __init__(self, *args, classes_disponibles=None, portees_disponibles=None, **kwargs):
        super().__init__(*args, **kwargs)
        if classes_disponibles is not None:
            self.fields["classe_ciblee"].queryset = classes_disponibles
        if portees_disponibles is not None:
            self.fields["portee"] = forms.ChoiceField(
                label="Portée", choices=[(p.value, p.label) for p in portees_disponibles],
                widget=forms.Select(attrs={"class": "form-control"}),
            )


class EnvoyerMessageForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Message
        fields = ["contenu"]
        widgets = {"contenu": forms.Textarea(attrs={"rows": 3, "placeholder": "Écrivez votre message..."})}
        labels = {"contenu": ""}
