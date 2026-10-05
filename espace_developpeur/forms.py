from django import forms

from comptes.forms import BootstrapFormMixin
from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role, StatutCompte
from etablissement.models import Etablissement
from scolarite.models import AnneeScolaire, role_autorise_pour_plan

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

    def __init__(self, *args, etablissement=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.etablissement = etablissement
        # Un rôle de direction propre à un cycle (Directeur du 2ème cycle/
        # Lycée, Censeur, Surveillant général) n'est proposé que si
        # l'abonnement de l'établissement couvre ce cycle - sinon l'école
        # pourrait s'attribuer un rôle pour un cycle qu'elle ne paie pas.
        self.fields["role"].choices = [
            (valeur, libelle) for valeur, libelle in ROLES_ATTRIBUABLES
            if role_autorise_pour_plan(valeur, etablissement)
        ]

    def clean_role(self):
        role = self.cleaned_data["role"]
        if not role_autorise_pour_plan(role, self.etablissement):
            raise forms.ValidationError("L'abonnement de votre établissement ne couvre pas ce rôle.")
        return role


class ParametresEtablissementForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Etablissement
        fields = ["nom", "devise", "logo", "code_devise", "pas_montant"]


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
