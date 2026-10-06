from django import forms

from comptes.forms import BootstrapFormMixin
from comptes.models import Utilisateur
from comptes.roles import Role
from finances.models import ModePaiement, Salaire, TypeTranche
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
