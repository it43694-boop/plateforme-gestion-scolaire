from django import forms

from comptes.forms import BootstrapFormMixin
from comptes.models import Utilisateur
from comptes.roles import Role
from pedagogie.models import CreneauEmploiDuTemps, JourSemaine, Trimestre
from scolarite.models import Affectation


class SaisirNoteForm(BootstrapFormMixin, forms.Form):
    matricule_eleve = forms.CharField(label="Matricule de l'élève")
    trimestre = forms.ChoiceField(label="Trimestre", choices=Trimestre.choices)
    note_classe = forms.DecimalField(
        label="Note de classe / 20", min_value=0, max_value=20, decimal_places=2, required=False,
        help_text="Contrôle continu.",
    )
    note_composition = forms.DecimalField(
        label="Note de composition / 40", min_value=0, max_value=40, decimal_places=2, required=False,
        help_text="Examen trimestriel - compte double dans la moyenne.",
    )

    def __init__(self, *args, affectation, **kwargs):
        self.affectation = affectation
        super().__init__(*args, **kwargs)

    def clean_matricule_eleve(self):
        matricule = self.cleaned_data["matricule_eleve"]
        try:
            eleve = Utilisateur.objects.get(matricule=matricule, role=Role.ELEVE)
        except Utilisateur.DoesNotExist:
            raise forms.ValidationError("Aucun élève trouvé avec ce matricule.")
        if not eleve.inscriptions.filter(classe_id=self.affectation.classe_id).exists():
            raise forms.ValidationError("Cet élève n'est pas inscrit dans cette classe.")
        return matricule

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("note_classe") is None and cleaned.get("note_composition") is None:
            raise forms.ValidationError("Saisissez au moins une des deux notes (classe ou composition).")
        return cleaned


class SaisirAbsenceForm(BootstrapFormMixin, forms.Form):
    matricule_eleve = forms.CharField(label="Matricule de l'élève")
    date_absence = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}))
    justifiee = forms.BooleanField(label="Absence justifiée", required=False)
    motif = forms.CharField(label="Motif", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, classe, **kwargs):
        self.classe = classe
        super().__init__(*args, **kwargs)

    def clean_matricule_eleve(self):
        matricule = self.cleaned_data["matricule_eleve"]
        try:
            eleve = Utilisateur.objects.get(matricule=matricule, role=Role.ELEVE)
        except Utilisateur.DoesNotExist:
            raise forms.ValidationError("Aucun élève trouvé avec ce matricule.")
        if not eleve.inscriptions.filter(classe_id=self.classe.id).exists():
            raise forms.ValidationError("Cet élève n'est pas inscrit dans cette classe.")
        return matricule


class CreneauForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = CreneauEmploiDuTemps
        fields = ["affectation", "jour_semaine", "heure_debut", "heure_fin", "salle"]
        widgets = {
            "heure_debut": forms.TimeInput(attrs={"type": "time"}),
            "heure_fin": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, classe, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.classe = classe
        self.fields["affectation"].queryset = Affectation.objects.filter(classe=classe)
