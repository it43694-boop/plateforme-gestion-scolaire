import re

from django import forms
from django.utils import timezone

from comptabilite.models import CompteComptable, Journal
from comptes.forms import BootstrapFormMixin

NOMBRE_LIGNES_ECRITURE = 8


class ExerciceForm(BootstrapFormMixin, forms.Form):
    libelle = forms.CharField(label="Libellé", max_length=60, help_text="Par exemple « Exercice 2026 ».")
    date_debut = forms.DateField(label="Début", widget=forms.DateInput(attrs={"type": "date"}))
    date_fin = forms.DateField(label="Fin", widget=forms.DateInput(attrs={"type": "date"}))


class CompteForm(BootstrapFormMixin, forms.Form):
    numero = forms.CharField(label="Numéro", max_length=10, help_text="2 à 10 chiffres, en commençant par 1 à 8.")
    libelle = forms.CharField(label="Intitulé", max_length=200)


def _entier(valeur):
    """Montant saisi : vide = 0 ; accepte « 25 000 » (espaces ordinaires ou insécables) ; refuse le reste."""
    texte = (valeur or "").replace(" ", "").replace(" ", "").replace("\xa0", "").strip()
    if not texte:
        return 0
    if not texte.isdigit():
        raise ValueError(texte)
    return int(texte)


class EcritureLibreForm(BootstrapFormMixin, forms.Form):
    """Écriture à plusieurs lignes : on saisit le débit et le crédit de chaque compte, la somme doit être égale."""

    journal = forms.ChoiceField(
        label="Journal", choices=[(j.value, j.label) for j in Journal if j != Journal.A_NOUVEAUX],
        initial=Journal.OPERATIONS_DIVERSES,
    )
    date_ecriture = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}), initial=timezone.localdate)
    piece = forms.CharField(label="Pièce justificative", max_length=60, required=False, help_text="N° de facture, de reçu...")
    libelle = forms.CharField(label="Libellé", max_length=255)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lignes = []
        for numero in range(1, NOMBRE_LIGNES_ECRITURE + 1):
            champs = {}
            for nom, classe in (("compte", forms.CharField), ("libelle", forms.CharField), ("debit", forms.CharField), ("credit", forms.CharField)):
                champ = classe(required=False, max_length={"libelle": 255, "compte": 120}.get(nom, 20))
                champ.widget.attrs["class"] = "form-control form-control-sm"
                if nom == "compte":
                    champ.widget.attrs["list"] = "liste-comptes"
                    champ.widget.attrs["autocomplete"] = "off"
                if nom in ("debit", "credit"):
                    champ.widget.attrs["inputmode"] = "numeric"
                self.fields[f"{nom}_{numero}"] = champ
                champs[nom] = self[f"{nom}_{numero}"]
            self.lignes.append(champs)

    def clean(self):
        cleaned = super().clean()
        lignes = []
        for numero in range(1, NOMBRE_LIGNES_ECRITURE + 1):
            brut = (cleaned.get(f"compte_{numero}") or "").strip()
            numero_compte = re.match(r"\d+", brut)  # « 571 » ou « 571 - Caisse » (choix dans la liste)
            compte = numero_compte.group(0) if numero_compte else brut
            libelle = (cleaned.get(f"libelle_{numero}") or "").strip()
            try:
                debit, credit = _entier(cleaned.get(f"debit_{numero}")), _entier(cleaned.get(f"credit_{numero}"))
            except ValueError:
                self.add_error(f"debit_{numero}", "Montant invalide : chiffres seulement.")
                continue
            if not (compte or debit or credit or libelle):
                continue  # ligne vide
            if not compte:
                self.add_error(f"compte_{numero}", "Indiquez le compte.")
                continue
            lignes.append((compte, debit, credit, libelle))
        cleaned["lignes"] = lignes
        return cleaned


class OperationForm(BootstrapFormMixin, forms.Form):
    """Dépense ou recette en deux lignes : on indique ce qui a été payé ou encaissé, la plateforme trouve le débit et le crédit."""

    type_operation = forms.ChoiceField(label="Type", choices=[("depense", "Dépense (argent qui sort)"), ("recette", "Recette (argent qui entre)")])
    date_ecriture = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}), initial=timezone.localdate)
    montant = forms.IntegerField(label="Montant", min_value=1, max_value=2_000_000_000)
    compte = forms.ModelChoiceField(label="Compte", queryset=CompteComptable.objects.none(), help_text="Charge, produit, immobilisation, stock ou tiers.")
    mode = forms.ChoiceField(
        label="Réglé en / encaissé par",
        choices=[("especes", "Espèces (caisse)"), ("mobile_money", "Mobile Money"), ("virement", "Virement bancaire"), ("cheque", "Chèque")],
    )
    libelle = forms.CharField(label="Libellé", max_length=255)
    piece = forms.CharField(label="Pièce justificative", max_length=60, required=False)

    def __init__(self, *args, etablissement=None, **kwargs):
        super().__init__(*args, **kwargs)
        if etablissement is not None:
            self.fields["compte"].queryset = CompteComptable.objects.filter(etablissement=etablissement).exclude(
                numero__startswith="5",
            ).exclude(numero__startswith="8").order_by("numero")
            self.fields["compte"].label_from_instance = lambda compte: f"{compte.numero} - {compte.libelle}"
