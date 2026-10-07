import re

from django import forms

from comptes.forms import BootstrapFormMixin
from comptes.models import Utilisateur
from comptes.roles import Role
from finances.models import (
    ModePaiement, Salaire, StatutConge, TypeConge, TypeContrat, TypeTranche, contrat_actif_pour,
)
from scolarite.models import Inscription


class ChoixLibreMultiple(forms.MultipleChoiceField):
    """
    Comme MultipleChoiceField, mais sans valider les valeurs contre
    `choices` (laissé vide ici) : les choix valides - les mois/trimestres
    de l'échéancier de la classe - ne sont connus qu'après avoir résolu
    l'élève choisi (recherche en direct, voir EnregistrerPaiementForm.clean),
    pas au moment où le formulaire est construit. Validé à la place dans
    clean(), une fois l'élève et son échéancier connus.
    """
    def valid_value(self, value):
        return True


class EnregistrerPaiementForm(BootstrapFormMixin, forms.Form):
    matricule_eleve = forms.CharField(label="Élève", widget=forms.HiddenInput())
    tranche = forms.ChoiceField(label="Tranche", choices=TypeTranche.choices)
    montant = forms.IntegerField(label="Montant", min_value=1)
    mode_paiement = forms.ChoiceField(label="Mode de paiement", choices=ModePaiement.choices)
    periodes = ChoixLibreMultiple(
        label="Mois couverts", required=False, widget=forms.CheckboxSelectMultiple,
        help_text="Cochez les mois (ou trimestres) exacts réglés par ce versement - inutile pour "
                   "l'inscription ou un échéancier annuel.",
    )

    def __init__(self, *args, etablissement=None, **kwargs):
        self.etablissement = etablissement
        super().__init__(*args, **kwargs)
        self.fields["montant"].label = f"Montant ({getattr(etablissement, 'code_devise', 'FCFA')})"

    def clean(self):
        cleaned = super().clean()
        matricule = cleaned.get("matricule_eleve")
        if not matricule:
            return cleaned
        try:
            eleve = Utilisateur.objects.get(matricule=matricule, role=Role.ELEVE, etablissement=self.etablissement)
        except Utilisateur.DoesNotExist:
            self.add_error("matricule_eleve", "Aucun élève trouvé avec ce matricule.")
            return cleaned

        inscription = Inscription.objects.filter(
            eleve=eleve, statut=Inscription.Statut.EN_COURS,
        ).order_by("-date_inscription").first()
        if not inscription:
            self.add_error("matricule_eleve", "Cet élève n'a pas d'inscription en cours.")
            return cleaned

        cleaned["eleve"] = eleve
        cleaned["inscription"] = inscription

        periodes = cleaned.get("periodes") or []
        if periodes:
            echeancier = getattr(inscription.classe, "echeancier", None)
            valides = set(echeancier.libelles_periodes()) if echeancier else set()
            invalides = [p for p in periodes if p not in valides]
            if invalides:
                self.add_error("periodes", f"Période(s) invalide(s) pour cette classe : {', '.join(invalides)}.")
        cleaned["periodes"] = periodes
        return cleaned


class CorrigerPaiementForm(BootstrapFormMixin, forms.Form):
    montant = forms.IntegerField(label="Montant", min_value=1)
    mode_paiement = forms.ChoiceField(label="Mode de paiement", choices=ModePaiement.choices)

    def __init__(self, *args, etablissement=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["montant"].label = f"Montant ({getattr(etablissement, 'code_devise', 'FCFA')})"


class SaisirSalaireForm(BootstrapFormMixin, forms.Form):
    email_employe = forms.EmailField(label="Employé", widget=forms.HiddenInput())
    periode = forms.CharField(
        label="Période", help_text="Format AAAA-MM, exemple : 2026-10",
        widget=forms.TextInput(attrs={"placeholder": "2026-10"}),
    )
    montant = forms.IntegerField(label="Montant", min_value=1)

    def __init__(self, *args, etablissement=None, **kwargs):
        self.etablissement = etablissement
        super().__init__(*args, **kwargs)
        self.fields["montant"].label = f"Montant ({getattr(etablissement, 'code_devise', 'FCFA')})"

    def clean_periode(self):
        periode = self.cleaned_data["periode"].strip()
        import re
        if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", periode):
            raise forms.ValidationError("Format attendu : AAAA-MM (exemple : 2026-10).")
        return periode

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get("email_employe")
        if not email:
            return cleaned
        try:
            employe = Utilisateur.objects.get(email__iexact=email, etablissement=self.etablissement)
        except Utilisateur.DoesNotExist:
            self.add_error("email_employe", "Aucun compte trouvé avec cet email dans votre établissement.")
            return cleaned
        if employe.role == Role.ELEVE:
            self.add_error("email_employe", "Un élève ne peut pas recevoir de salaire.")
            return cleaned
        periode = cleaned.get("periode")
        if periode and Salaire.objects.filter(employe=employe, periode=periode, est_supprime=False).exists():
            self.add_error("periode", "Un salaire existe déjà pour cet employé et cette période.")
            return cleaned
        cleaned["employe"] = employe
        return cleaned


def _resoudre_employe(etablissement, email):
    """Email -> (employe, message d'erreur ou None) - partagé par les formulaires RH ci-dessous."""
    try:
        employe = Utilisateur.objects.get(email__iexact=email, etablissement=etablissement)
    except Utilisateur.DoesNotExist:
        return None, "Aucun compte trouvé avec cet email dans votre établissement."
    if employe.role == Role.ELEVE:
        return None, "Un élève ne peut pas être employé."
    return employe, None


class CreerContratForm(BootstrapFormMixin, forms.Form):
    email_employe = forms.EmailField(label="Employé", widget=forms.HiddenInput())
    type_contrat = forms.ChoiceField(label="Type de contrat", choices=TypeContrat.choices)
    poste = forms.CharField(label="Poste", max_length=150)
    date_debut = forms.DateField(label="Date de début", widget=forms.DateInput(attrs={"type": "date"}))
    date_fin = forms.DateField(
        label="Date de fin", required=False, widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Requise pour un CDD ; laisser vide pour un CDI toujours en cours.",
    )
    salaire_base = forms.IntegerField(label="Salaire de base", min_value=1)

    def __init__(self, *args, etablissement=None, **kwargs):
        self.etablissement = etablissement
        super().__init__(*args, **kwargs)
        self.fields["salaire_base"].label = f"Salaire de base ({getattr(etablissement, 'code_devise', 'FCFA')})"

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get("email_employe")
        if not email:
            return cleaned
        employe, erreur = _resoudre_employe(self.etablissement, email)
        if erreur:
            self.add_error("email_employe", erreur)
            return cleaned
        if contrat_actif_pour(employe):
            self.add_error("email_employe", "Cet employé a déjà un contrat actif.")
            return cleaned
        if cleaned.get("type_contrat") == TypeContrat.CDD and not cleaned.get("date_fin"):
            self.add_error("date_fin", "Un CDD doit avoir une date de fin.")
            return cleaned
        cleaned["employe"] = employe
        return cleaned


class CloturerContratForm(BootstrapFormMixin, forms.Form):
    date_fin = forms.DateField(label="Date de fin du contrat", widget=forms.DateInput(attrs={"type": "date"}))


class EnregistrerCongeForm(BootstrapFormMixin, forms.Form):
    email_employe = forms.EmailField(label="Employé", widget=forms.HiddenInput())
    type_conge = forms.ChoiceField(label="Type de congé", choices=TypeConge.choices)
    date_debut = forms.DateField(label="Date de début", widget=forms.DateInput(attrs={"type": "date"}))
    date_fin = forms.DateField(label="Date de fin", widget=forms.DateInput(attrs={"type": "date"}))
    motif = forms.CharField(label="Motif", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    statut = forms.ChoiceField(label="Statut", choices=StatutConge.choices, initial=StatutConge.APPROUVE)

    def __init__(self, *args, etablissement=None, **kwargs):
        self.etablissement = etablissement
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get("email_employe")
        if not email:
            return cleaned
        employe, erreur = _resoudre_employe(self.etablissement, email)
        if erreur:
            self.add_error("email_employe", erreur)
            return cleaned
        date_debut, date_fin = cleaned.get("date_debut"), cleaned.get("date_fin")
        if date_debut and date_fin and date_fin < date_debut:
            self.add_error("date_fin", "La date de fin doit être postérieure ou égale à la date de début.")
            return cleaned
        cleaned["employe"] = employe
        return cleaned


class CreerBulletinPaieForm(BootstrapFormMixin, forms.Form):
    email_employe = forms.EmailField(label="Employé", widget=forms.HiddenInput())
    periode = forms.CharField(
        label="Période", help_text="Format AAAA-MM, exemple : 2026-10",
        widget=forms.TextInput(attrs={"placeholder": "2026-10"}),
    )
    salaire_brut = forms.IntegerField(label="Salaire brut", min_value=1)
    its = forms.IntegerField(
        label="ITS (impôt sur salaires)", min_value=0, initial=0,
        help_text="Montant saisi manuellement - le barème officiel n'est pas calculé automatiquement.",
    )

    def __init__(self, *args, etablissement=None, **kwargs):
        self.etablissement = etablissement
        super().__init__(*args, **kwargs)
        devise = getattr(etablissement, "code_devise", "FCFA")
        self.fields["salaire_brut"].label = f"Salaire brut ({devise})"
        self.fields["its"].label = f"ITS ({devise})"

    def clean_periode(self):
        periode = self.cleaned_data["periode"].strip()
        if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", periode):
            raise forms.ValidationError("Format attendu : AAAA-MM (exemple : 2026-10).")
        return periode

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get("email_employe")
        if not email:
            return cleaned
        employe, erreur = _resoudre_employe(self.etablissement, email)
        if erreur:
            self.add_error("email_employe", erreur)
            return cleaned
        periode = cleaned.get("periode")
        if periode and Salaire.objects.filter(employe=employe, periode=periode, est_supprime=False).exists():
            self.add_error("periode", "Un salaire existe déjà pour cet employé et cette période.")
            return cleaned
        salaire_brut, its = cleaned.get("salaire_brut"), cleaned.get("its") or 0
        if salaire_brut is not None and its >= salaire_brut:
            self.add_error("its", "L'ITS ne peut pas être supérieur ou égal au salaire brut.")
            return cleaned
        cleaned["employe"] = employe
        return cleaned
