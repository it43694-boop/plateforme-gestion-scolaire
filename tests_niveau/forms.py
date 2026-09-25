from django import forms

from comptes.forms import BootstrapFormMixin
from tests_niveau.models import Candidat


class AjouterCandidatForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Candidat
        fields = ["prenom", "nom", "date_naissance", "telephone_contact", "classe_visee", "date_test", "note_test"]
        widgets = {
            "date_naissance": forms.DateInput(attrs={"type": "date"}),
            "date_test": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, classes_disponibles=None, **kwargs):
        super().__init__(*args, **kwargs)
        if classes_disponibles is not None:
            self.fields["classe_visee"].queryset = classes_disponibles
