from django import forms
from django.core.exceptions import ValidationError

from comptes.forms import BootstrapFormMixin
from comptes.models import Utilisateur
from comptes.roles import ROLES_DIRECTION_GENERALE, Role
from django.utils import timezone

from etablissement.models import Etablissement, FactureAbonnement


class ModifierPlanEtablissementForm(BootstrapFormMixin, forms.ModelForm):
    """
    Formule d'abonnement (cycles couverts) d'un établissement - séparée de
    ParametresEtablissementForm à dessein : ce dernier est aussi utilisé par
    le développeur de l'établissement lui-même (espace_developpeur), qui ne
    doit jamais pouvoir s'auto-attribuer un cycle non souscrit.
    """

    class Meta:
        model = Etablissement
        fields = ["plan", "inclut_professionnel", "inclut_prescolaire"]


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


class EmettreFactureForm(BootstrapFormMixin, forms.Form):
    etablissement = forms.ModelChoiceField(label="Établissement", queryset=Etablissement.objects.order_by("nom"))
    periode_debut = forms.DateField(label="Début de la période", widget=forms.DateInput(attrs={"type": "date"}))
    periode_fin = forms.DateField(label="Fin de la période", widget=forms.DateInput(attrs={"type": "date"}))
    montant = forms.IntegerField(label="Montant (FCFA)", min_value=1, max_value=2_000_000_000)
    date_emission = forms.DateField(
        label="Date d'émission", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"), initial=timezone.localdate,
    )
    date_echeance = forms.DateField(
        label="À payer avant le", required=False, widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Laissez vide : 15 jours après l'émission.",
    )
    libelle = forms.CharField(
        label="Libellé", max_length=200, required=False,
        help_text="Laissez vide : « Abonnement <formule> - du ... au ... ».",
    )
    envoyer_par_email = forms.BooleanField(
        label="Envoyer la facture par email à l'école", required=False, initial=True,
        help_text="Le PDF part en pièce jointe à l'adresse de facturation de l'école ou, à défaut, à ses comptes de direction. "
                  "Si la facture n'est pas payée à l'échéance, des rappels partent ensuite tout seuls (voir la liste des factures).",
    )


class ReglementFactureForm(BootstrapFormMixin, forms.Form):
    date_paiement = forms.DateField(
        label="Date du règlement", widget=forms.DateInput(attrs={"type": "date"}), initial=timezone.localdate,
    )
    mode_reglement = forms.ChoiceField(label="Mode de règlement", choices=FactureAbonnement.ModeReglement.choices)
    reference = forms.CharField(
        label="Référence (facultatif)", max_length=100, required=False,
        help_text="Numéro de transaction Mobile Money, de virement ou de chèque.",
    )


# Les deux rôles à accès total qui ne sont pas dans la matrice de permissions et ne s'attribuent pas depuis l'espace
# développeur d'une école (un compte développeur compromis ne doit pas pouvoir s'en servir). Le développeur d'une école, lui,
# est créé avec l'école (CreerEtablissementForm).
ROLES_DIRECTION = tuple(role.value for role in ROLES_DIRECTION_GENERALE)


class CreerCompteDirectionForm(BootstrapFormMixin, forms.Form):
    role = forms.ChoiceField(
        label="Rôle", choices=[(valeur, dict(Role.choices)[valeur]) for valeur in ROLES_DIRECTION],
        help_text="Les deux ont le même accès complet à l'école. Ni l'un ni l'autre ne gère la matrice de permissions, les "
                  "comptes ou la suppression d'un élève : cela reste au développeur de l'école.",
    )
    prenom = forms.CharField(label="Prénom", max_length=100)
    nom = forms.CharField(label="Nom", max_length=100)
    email = forms.EmailField(label="Email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if Utilisateur.objects.filter(email__iexact=email).exists():
            raise ValidationError("Un compte existe déjà avec cet email.")
        return email
