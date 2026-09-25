from django import forms

from comptes.forms import BootstrapFormMixin
from bibliotheque.models import Document


class AjouterDocumentForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Document
        fields = ["titre", "description", "fichier"]


class ImporterZipForm(BootstrapFormMixin, forms.Form):
    archive = forms.FileField(label="Archive ZIP")

    def clean_archive(self):
        archive = self.cleaned_data["archive"]
        if not archive.name.lower().endswith(".zip"):
            raise forms.ValidationError("Le fichier doit être une archive .zip.")
        return archive
