from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.core.exceptions import ValidationError

from comptes.models import Utilisateur
from comptes.roles import Role, StatutCompte


class BootstrapFormMixin:
    """Applique la classe Bootstrap `form-control` à tous les champs visibles."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for champ in self.fields.values():
            classe_existante = champ.widget.attrs.get("class", "")
            if not isinstance(champ.widget, (forms.CheckboxInput,)):
                champ.widget.attrs["class"] = (classe_existante + " form-control").strip()
            else:
                champ.widget.attrs["class"] = (classe_existante + " form-check-input").strip()

ROLES_AUTORISES_A_L_INSCRIPTION = [
    (Role.PARENT.value, Role.PARENT.label),
    (Role.PERSONNEL.value, Role.PERSONNEL.label),
    (Role.ENSEIGNANT.value, Role.ENSEIGNANT.label),
]
# Remarque : un compte élève est créé automatiquement lors de l'inscription
# scolaire (module Élèves, phase suivante) - il ne s'inscrit pas lui-même
# ici. Les rôles de direction/technique sont attribués uniquement par le
# développeur depuis l'espace développeur, jamais via ce formulaire public.


class InscriptionForm(BootstrapFormMixin, forms.ModelForm):
    role = forms.ChoiceField(choices=ROLES_AUTORISES_A_L_INSCRIPTION, label="Je m'inscris en tant que")
    mot_de_passe = forms.CharField(label="Mot de passe", widget=forms.PasswordInput, strip=False)
    confirmation_mot_de_passe = forms.CharField(
        label="Confirmer le mot de passe", widget=forms.PasswordInput, strip=False,
    )

    class Meta:
        model = Utilisateur
        fields = ["prenom", "nom", "email", "telephone", "profession", "role"]

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if Utilisateur.objects.filter(email=email).exists():
            raise ValidationError("Un compte existe déjà avec cet email.")
        return email

    def clean_telephone(self):
        telephone = self.cleaned_data.get("telephone", "").strip()
        role = self.data.get("role")
        if role == Role.PARENT.value and not telephone:
            raise ValidationError("Le téléphone est obligatoire pour un compte parent.")
        if telephone and Utilisateur.objects.filter(telephone=telephone).exists():
            raise ValidationError("Ce numéro de téléphone est déjà associé à un autre compte.")
        return telephone or None

    def clean(self):
        cleaned = super().clean()
        mdp = cleaned.get("mot_de_passe")
        confirmation = cleaned.get("confirmation_mot_de_passe")
        if mdp and confirmation and mdp != confirmation:
            self.add_error("confirmation_mot_de_passe", "Les deux mots de passe ne correspondent pas.")
        if mdp:
            password_validation.validate_password(mdp)
        role = cleaned.get("role")
        if role == Role.PARENT.value and not cleaned.get("profession"):
            self.add_error("profession", "La profession est obligatoire pour un compte parent.")
        return cleaned

    def save(self, commit=True):
        utilisateur = super().save(commit=False)
        utilisateur.set_password(self.cleaned_data["mot_de_passe"])
        utilisateur.statut = StatutCompte.EN_ATTENTE_VERIFICATION_EMAIL
        utilisateur.is_active = False
        if commit:
            utilisateur.save()
        return utilisateur


class VerificationEmailForm(BootstrapFormMixin, forms.Form):
    code = forms.CharField(
        label="Code de vérification", max_length=6, min_length=6,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code"}),
    )


class ConnexionForm(BootstrapFormMixin, forms.Form):
    email = forms.EmailField(label="Adresse email")
    mot_de_passe = forms.CharField(label="Mot de passe", widget=forms.PasswordInput, strip=False)


class MotDePasseOublieForm(BootstrapFormMixin, forms.Form):
    identifiant = forms.CharField(
        label="Email ou matricule",
        help_text="Un élève peut saisir son matricule à la place de son email.",
    )


class DefinirNouveauMotDePasseForm(BootstrapFormMixin, SetPasswordForm):
    """Réutilise la validation standard de Django (dont notre validateur de complexité)."""
    pass


class ChangerMotDePasseForm(BootstrapFormMixin, PasswordChangeForm):
    """Un utilisateur connecté change son propre mot de passe (ancien + nouveau)."""
    pass


class ChangerEmailForm(BootstrapFormMixin, forms.Form):
    """Un utilisateur connecté change sa propre adresse email (confirmée par son mot de passe)."""

    nouvel_email = forms.EmailField(label="Nouvelle adresse email")
    mot_de_passe = forms.CharField(label="Mot de passe actuel", widget=forms.PasswordInput, strip=False)

    def __init__(self, utilisateur, *args, **kwargs):
        self.utilisateur = utilisateur
        super().__init__(*args, **kwargs)

    def clean_nouvel_email(self):
        email = self.cleaned_data["nouvel_email"].strip().lower()
        if Utilisateur.objects.exclude(pk=self.utilisateur.pk).filter(email__iexact=email).exists():
            raise ValidationError("Cette adresse email est déjà utilisée par un autre compte.")
        return email

    def clean_mot_de_passe(self):
        mot_de_passe = self.cleaned_data["mot_de_passe"]
        if not self.utilisateur.check_password(mot_de_passe):
            raise ValidationError("Mot de passe incorrect.")
        return mot_de_passe
