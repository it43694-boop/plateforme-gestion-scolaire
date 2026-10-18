"""Formulaires de la vente de tenues : article, arrivage, correction de stock, vente, annulation."""
from django import forms

from comptes.forms import BootstrapFormMixin
from comptes.models import Utilisateur
from comptes.roles import Role
from finances.models import ArticleTenue, ModePaiement

QUANTITE_MAXIMALE = 999


class ArticleTenueForm(BootstrapFormMixin, forms.ModelForm):
    prix = forms.IntegerField(label="Prix de vente", min_value=1)

    class Meta:
        model = ArticleTenue
        fields = ["libelle", "taille", "prix", "seuil_alerte", "actif"]

    def __init__(self, *args, etablissement, **kwargs):
        super().__init__(*args, **kwargs)
        self.etablissement = etablissement
        self.fields["prix"].label = f"Prix de vente ({getattr(etablissement, 'code_devise', None) or 'FCFA'})"

    def clean(self):
        donnees = super().clean()
        libelle, taille = " ".join((donnees.get("libelle") or "").split()), " ".join((donnees.get("taille") or "").split())
        if libelle:
            donnees["libelle"], donnees["taille"] = libelle, taille
            doublons = ArticleTenue.objects.filter(etablissement=self.etablissement, libelle__iexact=libelle, taille__iexact=taille)
            if self.instance.pk:
                doublons = doublons.exclude(pk=self.instance.pk)
            if doublons.exists():
                self.add_error("libelle", "Cet article existe déjà dans cette taille.")
        return donnees

    def save(self, commit=True):
        article = super().save(commit=False)
        article.etablissement = self.etablissement
        if commit:
            article.save()
        return article


class ApprovisionnerForm(BootstrapFormMixin, forms.Form):
    quantite = forms.IntegerField(label="Quantité reçue", min_value=1, max_value=100000)
    note = forms.CharField(label="Note (facultatif)", required=False, max_length=255, help_text="Fournisseur, numéro de bon de livraison...")


class CorrectionStockForm(BootstrapFormMixin, forms.Form):
    nouveau_stock = forms.IntegerField(label="Stock réel compté", min_value=0, max_value=100000)
    note = forms.CharField(label="Motif de la correction", max_length=255)


class AnnulationVenteForm(BootstrapFormMixin, forms.Form):
    motif = forms.CharField(label="Motif de l'annulation", max_length=255)


class VenteTenueForm(BootstrapFormMixin, forms.Form):
    """Une vente : l'acheteur (un élève, ou un nom), le mode de paiement et une quantité par article en vente."""

    matricule_eleve = forms.CharField(label="Élève", required=False, widget=forms.HiddenInput())
    acheteur = forms.CharField(label="Acheteur (s'il n'est pas élève)", required=False, max_length=120)
    mode_paiement = forms.ChoiceField(label="Mode de paiement", choices=ModePaiement.choices)

    def __init__(self, *args, etablissement, articles, **kwargs):
        super().__init__(*args, **kwargs)
        self.etablissement = etablissement
        self.articles = list(articles)
        for article in self.articles:
            self.fields[f"qte_{article.pk}"] = forms.IntegerField(
                label=article.nom_complet, required=False, min_value=0, max_value=QUANTITE_MAXIMALE, initial=0,
                widget=forms.NumberInput(attrs={"min": 0, "max": QUANTITE_MAXIMALE, "class": "form-control form-control-sm text-end"}),
            )

    def lignes(self):
        """[(article, champ de quantité)] pour l'affichage, dans l'ordre des articles."""
        return [(article, self[f"qte_{article.pk}"]) for article in self.articles]

    def clean(self):
        donnees = super().clean()
        quantites = {article.pk: donnees.get(f"qte_{article.pk}") or 0 for article in self.articles}
        if not any(quantites.values()):
            raise forms.ValidationError("Indiquez la quantité d'au moins un article.")
        donnees["quantites"] = {pk: quantite for pk, quantite in quantites.items() if quantite}
        matricule = (donnees.get("matricule_eleve") or "").strip()
        donnees["eleve"] = None
        if matricule:
            eleve = Utilisateur.objects.filter(matricule=matricule, role=Role.ELEVE, etablissement=self.etablissement).first()
            if eleve is None:
                self.add_error("matricule_eleve", "Aucun élève trouvé avec ce matricule.")
            donnees["eleve"] = eleve
        return donnees
