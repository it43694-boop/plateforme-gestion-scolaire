from django import forms

from comptes.forms import BootstrapFormMixin
from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role, StatutCompte
from etablissement.models import Etablissement

# Les rôles à accès total inconditionnel (développeur, fondateur,
# administrateur général) ne sont jamais attribuables depuis cette interface :
# un compte développeur compromis ne doit pas pouvoir s'en servir pour créer
# une porte dérobée permanente sur un autre compte. Leur attribution ne passe
# que par la console (shell Django / admin), jamais par le web.
ROLES_ATTRIBUABLES = [
    (valeur, libelle) for valeur, libelle in Role.choices
    if valeur not in {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL}
]


class ModifierCompteForm(BootstrapFormMixin, forms.Form):
    role = forms.ChoiceField(label="Rôle", choices=ROLES_ATTRIBUABLES)
    statut = forms.ChoiceField(label="Statut du compte", choices=StatutCompte.choices)


class ParametresEtablissementForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Etablissement
        fields = ["nom", "devise", "logo", "code_devise", "pas_montant"]
