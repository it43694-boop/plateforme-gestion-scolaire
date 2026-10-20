import datetime

from django import forms
from django.utils import timezone

from comptes.forms import BootstrapFormMixin
from comptes.models import Utilisateur
from comptes.roles import Role
from comptes.validators import valider_contenu_fichier, valider_taille_image_2mo
from finances.declarations import une_transaction_deja_declaree
from finances.models import OperateurMobileMoney, normaliser_reference_transaction
from scolarite.models import Inscription

LONGUEUR_MINIMALE_DE_TRANSACTION = 6
JOURS_MAXIMUM_DEPUIS_LE_PAIEMENT = 366


class DeclarerPaiementForm(BootstrapFormMixin, forms.Form):
    """Ce qu'un parent déclare après avoir payé par Mobile Money : ses enfants seulement, le numéro de transaction du SMS de l'opérateur."""

    eleve = forms.ModelChoiceField(label="Enfant", queryset=Utilisateur.objects.none(), empty_label=None)
    operateur = forms.ChoiceField(label="Opérateur", choices=OperateurMobileMoney.choices)
    montant = forms.IntegerField(label="Montant payé", min_value=1, max_value=100_000_000)
    reference_transaction = forms.CharField(
        label="Numéro de transaction", max_length=40, help_text="Il figure dans le SMS de confirmation de l'opérateur.",
    )
    date_du_paiement = forms.DateField(label="Date du paiement", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    telephone_payeur = forms.CharField(label="Numéro utilisé pour payer", max_length=20, required=False)
    capture = forms.ImageField(
        label="Capture d'écran", required=False, validators=[valider_taille_image_2mo, valider_contenu_fichier],
        help_text="Facultative : la capture du SMS ou de l'application. 2 Mo au plus.",
    )

    def __init__(self, *args, parent, etablissement, **kwargs):
        kwargs.setdefault("initial", {"date_du_paiement": timezone.localdate(), "telephone_payeur": getattr(parent, "telephone", "") or ""})
        super().__init__(*args, **kwargs)
        self.etablissement = etablissement
        self.devise = getattr(etablissement, "code_devise", "FCFA")
        enfants = Utilisateur.objects.filter(
            parents_lies=parent, role=Role.ELEVE, etablissement=etablissement, inscriptions__statut=Inscription.Statut.EN_COURS,
        ).distinct().order_by("nom", "prenom")
        self.fields["eleve"].queryset = enfants
        self.fields["eleve"].label_from_instance = lambda eleve: eleve.nom_complet
        self.fields["montant"].label = f"Montant payé ({self.devise})"

    def clean_reference_transaction(self):
        reference = normaliser_reference_transaction(self.cleaned_data["reference_transaction"])
        if len(reference) < LONGUEUR_MINIMALE_DE_TRANSACTION:
            raise forms.ValidationError("Ce numéro de transaction est trop court : recopiez-le tel qu'il est écrit dans le SMS.")
        return reference

    def clean_date_du_paiement(self):
        date = self.cleaned_data["date_du_paiement"]
        aujourd_hui = timezone.localdate()
        if date > aujourd_hui:
            raise forms.ValidationError("La date du paiement ne peut pas être dans le futur.")
        if (aujourd_hui - date).days > JOURS_MAXIMUM_DEPUIS_LE_PAIEMENT:
            raise forms.ValidationError("Ce paiement date de plus d'un an : adressez-vous à l'école.")
        return date

    def clean(self):
        donnees = super().clean()
        reference, operateur = donnees.get("reference_transaction"), donnees.get("operateur")
        if reference and operateur and une_transaction_deja_declaree(self.etablissement, operateur, reference):
            self.add_error("reference_transaction", "Ce numéro de transaction a déjà été déclaré.")
        return donnees


class RefuserDeclarationForm(BootstrapFormMixin, forms.Form):
    motif = forms.CharField(
        label="Motif du refus", max_length=200, widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Le parent le lit : par exemple « transaction introuvable » ou « montant différent de celui reçu ».",
    )
