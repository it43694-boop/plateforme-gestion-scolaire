from django import forms

from comptes.forms import BootstrapFormMixin
from comptes.models import Utilisateur
from comptes.roles import Role
from pedagogie.models import CreneauEmploiDuTemps, JourSemaine, Trimestre
from scolarite.models import Affectation, Inscription
from scolarite.recherche import PLUSIEURS, options_de_saisie, trouver_eleve

# Un seul message pour « rien de tel dans cette classe », quelle qu'en soit la raison (matricule inexistant, élève d'une autre
# classe ou d'une autre école) : deux messages différents diraient à n'importe quel enseignant quels matricules existent dans
# les autres écoles (un matricule sert aussi d'identifiant de connexion à l'élève).
MESSAGE_ELEVE_INTROUVABLE_DANS_LA_CLASSE = "Aucun élève de cette classe ne porte ce nom ou ce matricule."
MESSAGE_PLUSIEURS_ELEVES = "Plusieurs élèves de cette classe portent ce nom : choisissez-en un dans la liste proposée."
ID_LISTE_ELEVES = "eleves-de-la-classe"


class EleveDeLaClasseMixin:
    """
    Champ « élève » d'une saisie faite pour UNE classe : le nom ou le matricule, au choix (personne ne retient le matricule de
    chacun). La liste des élèves de la classe est dans la page (suggestions du navigateur), donc la saisie par nom marche aussi
    sans réseau, et elle ne passe que par les élèves de cette classe : jamais une recherche sur toute l'école.
    """

    def preparer_champ_eleve(self, classe_id):
        self._classe_id = classe_id
        champ = self.fields["matricule_eleve"]
        champ.label = "Élève"
        champ.help_text = "Tapez le nom puis choisissez dans la liste, ou saisissez le matricule."
        champ.widget.attrs.update({"list": ID_LISTE_ELEVES, "autocomplete": "off", "placeholder": "Nom ou matricule"})

    def _eleves_de_la_classe(self):
        """Tous les élèves inscrits dans cette classe (comme avant : un élève sorti en cours d'année reste saisissable)."""
        if not hasattr(self, "_cache_eleves"):
            self._cache_eleves = list(Utilisateur.objects.filter(
                role=Role.ELEVE, inscriptions__classe_id=self._classe_id,
            ).distinct())
        return self._cache_eleves

    @property
    def options_eleves(self):
        """Les propositions de la liste : les élèves actuellement inscrits, « NOM Prénom », le matricule seulement pour les homonymes."""
        return options_de_saisie(Utilisateur.objects.filter(
            role=Role.ELEVE, inscriptions__classe_id=self._classe_id, inscriptions__statut=Inscription.Statut.EN_COURS,
        ).distinct())

    def clean_matricule_eleve(self):
        eleve, probleme = trouver_eleve(self.cleaned_data["matricule_eleve"], self._eleves_de_la_classe())
        if probleme == PLUSIEURS:
            raise forms.ValidationError(MESSAGE_PLUSIEURS_ELEVES)
        if eleve is None:
            raise forms.ValidationError(MESSAGE_ELEVE_INTROUVABLE_DANS_LA_CLASSE)
        return eleve.matricule  # toujours le matricule, quelle que soit la façon dont l'élève a été désigné


class SaisirNoteForm(EleveDeLaClasseMixin, BootstrapFormMixin, forms.Form):
    matricule_eleve = forms.CharField(label="Élève")
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
        self.preparer_champ_eleve(affectation.classe_id)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("note_classe") is None and cleaned.get("note_composition") is None:
            raise forms.ValidationError("Saisissez au moins une des deux notes (classe ou composition).")
        return cleaned


class SaisirAbsenceForm(EleveDeLaClasseMixin, BootstrapFormMixin, forms.Form):
    matricule_eleve = forms.CharField(label="Élève")
    date_absence = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}))
    justifiee = forms.BooleanField(label="Absence justifiée", required=False)
    motif = forms.CharField(label="Motif", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, classe, **kwargs):
        self.classe = classe
        super().__init__(*args, **kwargs)
        self.preparer_champ_eleve(classe.id)


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
