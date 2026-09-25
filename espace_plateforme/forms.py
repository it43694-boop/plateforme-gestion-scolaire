from django import forms
from django.core.exceptions import ValidationError

from comptes.forms import BootstrapFormMixin
from comptes.models import Utilisateur
from etablissement.models import Etablissement


class CreerEtablissementForm(BootstrapFormMixin, forms.Form):
    nom = forms.CharField(label="Nom de l'établissement", max_length=200)
    devise = forms.CharField(label="Devise (facultatif)", max_length=200, required=False)

    prenom_developpeur = forms.CharField(label="Prénom du premier administrateur")
    nom_developpeur = forms.CharField(label="Nom du premier administrateur")
    email_developpeur = forms.EmailField(label="Email du premier administrateur")
    mot_de_passe_developpeur = forms.CharField(
        label="Mot de passe initial", widget=forms.PasswordInput, strip=False,
        help_text="10 caractères minimum, une majuscule, un chiffre, un caractère spécial.",
    )

    def clean_email_developpeur(self):
        email = self.cleaned_data["email_developpeur"].strip().lower()
        if Utilisateur.objects.filter(email__iexact=email).exists():
            raise ValidationError("Un compte existe déjà avec cet email.")
        return email

    def clean_mot_de_passe_developpeur(self):
        from django.contrib.auth.password_validation import validate_password
        mot_de_passe = self.cleaned_data["mot_de_passe_developpeur"]
        validate_password(mot_de_passe)
        return mot_de_passe
