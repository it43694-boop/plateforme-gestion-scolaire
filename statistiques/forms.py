from django import forms

from comptes.forms import BootstrapFormMixin
from scolarite.models import FicheInfrastructure


class FicheInfrastructureForm(BootstrapFormMixin, forms.ModelForm):
    """Fiche d'infrastructures d'une école pour une année : l'établissement et l'année sont fixés par la vue."""

    class Meta:
        model = FicheInfrastructure
        exclude = ["etablissement", "annee_scolaire", "modifie_par", "modifie_le"]
