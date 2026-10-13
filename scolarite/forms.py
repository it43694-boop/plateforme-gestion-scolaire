import datetime

from django import forms

from comptes.forms import BootstrapFormMixin
from comptes.models import SituationHandicap, StatutDeplacement
from comptes.models import Sexe, Utilisateur
from comptes.roles import Role
from comptes.validators import valider_contenu_fichier, valider_extension_document, valider_taille_fichier_10mo
from scolarite.models import PAS_MONTANT as PAS_MONTANT_PAR_DEFAUT
from scolarite.models import (
    DEVISE_PAR_DEFAUT, NOMBRE_VERSEMENTS_FIXE, AnneeScolaire, Classe, Cycle, DomaineProfessionnel, EcheancierFrais,
    FiliereProfessionnelle,
    Inscription, NIVEAUX_PAR_CYCLE, Niveau, ParentEnAttente, Periodicite, Serie, cycles_autorises_pour,
)


class CreerClasseForm(BootstrapFormMixin, forms.Form):
    nom = forms.CharField(label="Nom de la classe", max_length=60, help_text="Exemple : 3ème année A")
    cycle = forms.ChoiceField(label="Cycle", choices=Cycle.choices)
    niveau = forms.ChoiceField(
        label="Niveau (année d'études)", choices=[("", "— Non précisé —")] + list(Niveau.choices), required=False,
        help_text="Permet de relier les sections parallèles d'une même année d'études.",
    )
    serie = forms.ChoiceField(
        label="Série", choices=[("", "— Aucune (hors lycée, ou 10ème année) —")] + Serie.choices,
        required=False, help_text="Uniquement pour une classe de 11ème ou 12ème année.",
    )
    filiere_professionnelle = forms.ChoiceField(
        label="Filière", choices=[("", "— Aucune (hors enseignement professionnel) —")] + FiliereProfessionnelle.choices,
        required=False, help_text="Uniquement pour une classe du cycle Enseignement professionnel.",
    )
    domaine_professionnel = forms.ChoiceField(
        label="Domaine", choices=[("", "— Non précisé —")] + DomaineProfessionnel.choices, required=False,
        help_text="Uniquement pour une classe du cycle Enseignement professionnel : industriel ou tertiaire.",
    )
    annee_scolaire = forms.ModelChoiceField(label="Année scolaire", queryset=AnneeScolaire.objects.none())
    montant_inscription = forms.IntegerField(label="Frais d'inscription", min_value=0)
    periodicite = forms.ChoiceField(label="Périodicité des paiements", choices=Periodicite.choices)
    montant_periode = forms.IntegerField(label="Montant par période", min_value=0)
    nombre_versements = forms.IntegerField(
        label="Nombre de versements (mensuel uniquement)", min_value=1, required=False,
        help_text="Laisser vide sauf pour le mensuel : 9 ou 10 versements sur l'année scolaire. "
                   "Fixé automatiquement à 3 pour le trimestriel et 1 pour l'annuel.",
    )

    def __init__(self, *args, etablissement=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.etablissement = etablissement
        self.pas_montant = getattr(etablissement, "pas_montant", PAS_MONTANT_PAR_DEFAUT)
        self.devise = getattr(etablissement, "code_devise", DEVISE_PAR_DEFAUT)
        self.cycles_autorises = cycles_autorises_pour(etablissement)
        self.fields["cycle"].choices = [
            (valeur, libelle) for valeur, libelle in Cycle.choices if valeur in self.cycles_autorises
        ]
        for champ in ["montant_inscription", "montant_periode"]:
            self.fields[champ].label = f"{self.fields[champ].label} ({self.devise})"
        self.fields["montant_inscription"].help_text = f"Multiple de {self.pas_montant} {self.devise}."
        self.fields["montant_periode"].help_text = (
            f"Multiple de {self.pas_montant} {self.devise}. Par mois, par trimestre ou pour l'année "
            "selon la périodicité choisie ci-dessus."
        )
        self.fields["annee_scolaire"].queryset = AnneeScolaire.objects.filter(etablissement=etablissement)
        self.fields["annee_scolaire"].initial = AnneeScolaire.active(etablissement)

    def clean(self):
        cleaned = super().clean()
        cycle = cleaned.get("cycle")
        if cycle and cycle not in self.cycles_autorises:
            self.add_error("cycle", "L'abonnement de votre établissement ne couvre pas ce cycle.")
        for champ in ["montant_inscription", "montant_periode"]:
            valeur = cleaned.get(champ)
            if valeur is not None and valeur % self.pas_montant != 0:
                self.add_error(champ, f"Doit être un multiple de {self.pas_montant} {self.devise}.")
        nom = cleaned.get("nom")
        annee = cleaned.get("annee_scolaire")
        if nom and annee and Classe.objects.filter(nom=nom, annee_scolaire=annee).exists():
            self.add_error("nom", "Une classe porte déjà ce nom pour cette année scolaire.")
        if cleaned.get("niveau") and cleaned["niveau"] not in NIVEAUX_PAR_CYCLE.get(cycle, []):
            self.add_error("niveau", "Ce niveau ne correspond pas au cycle choisi.")
        if cleaned.get("serie") and cleaned.get("cycle") != Cycle.LYCEE:
            self.add_error("serie", "Une série ne s'applique qu'à une classe du cycle Lycée.")
        if cleaned.get("domaine_professionnel") and cleaned.get("cycle") != Cycle.PROFESSIONNEL:
            self.add_error("domaine_professionnel", "Un domaine ne s'applique qu'à une classe du cycle Enseignement professionnel.")
        if cleaned.get("filiere_professionnelle") and cleaned.get("cycle") != Cycle.PROFESSIONNEL:
            self.add_error("filiere_professionnelle", "Une filière ne s'applique qu'à une classe du cycle Enseignement professionnel.")
        if cleaned.get("cycle") == Cycle.PROFESSIONNEL and not cleaned.get("filiere_professionnelle"):
            self.add_error("filiere_professionnelle", "Précisez la filière (CAP ou BT) pour une classe du cycle Enseignement professionnel.")
        periodicite = cleaned.get("periodicite")
        if periodicite == Periodicite.MENSUEL and cleaned.get("nombre_versements") not in (9, 10):
            self.add_error("nombre_versements", "Un échéancier mensuel compte 9 ou 10 versements.")
        return cleaned

    def save(self):
        classe = Classe.objects.create(
            nom=self.cleaned_data["nom"], cycle=self.cleaned_data["cycle"],
            niveau=self.cleaned_data.get("niveau", ""),
            serie=self.cleaned_data["serie"], filiere_professionnelle=self.cleaned_data["filiere_professionnelle"],
            domaine_professionnel=self.cleaned_data.get("domaine_professionnel", ""),
            annee_scolaire=self.cleaned_data["annee_scolaire"],
        )
        periodicite = self.cleaned_data["periodicite"]
        EcheancierFrais.objects.create(
            classe=classe,
            montant_inscription=self.cleaned_data["montant_inscription"],
            periodicite=periodicite,
            montant_periode=self.cleaned_data["montant_periode"],
            nombre_versements=NOMBRE_VERSEMENTS_FIXE.get(periodicite) or self.cleaned_data["nombre_versements"],
        )
        return classe


class AffecterEnseignantForm(BootstrapFormMixin, forms.Form):
    enseignant = forms.ModelChoiceField(
        label="Enseignant", queryset=Utilisateur.objects.filter(role=Role.ENSEIGNANT),
    )
    classe = forms.ModelChoiceField(label="Classe", queryset=Classe.objects.none())
    matiere = forms.CharField(
        label="Matière (optionnel)", max_length=100, required=False,
        help_text="Laissez vide pour un enseignant titulaire (toutes matières).",
    )
    coefficient = forms.IntegerField(
        label="Coefficient", min_value=1, initial=1, required=False,
        help_text="Poids de cette matière dans la moyenne du bulletin. 1 = compte comme les autres.",
    )

    def __init__(self, *args, etablissement=None, classes_disponibles=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["enseignant"].queryset = Utilisateur.objects.filter(
            role=Role.ENSEIGNANT, etablissement=etablissement,
        ).order_by("nom", "prenom")
        if classes_disponibles is not None:
            self.fields["classe"].queryset = classes_disponibles


class InscrireEleveForm(BootstrapFormMixin, forms.Form):
    prenom = forms.CharField(label="Prénom de l'élève", max_length=100)
    nom = forms.CharField(label="Nom de l'élève", max_length=100)
    matricule = forms.CharField(
        label="Matricule (optionnel)", max_length=20, required=False,
        help_text="Laissez vide pour générer automatiquement un matricule.",
    )
    sexe = forms.ChoiceField(label="Sexe", choices=Sexe.choices)
    date_naissance = forms.DateField(
        label="Date de naissance", required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    lieu_naissance = forms.CharField(label="Lieu de naissance", max_length=120, required=False)
    numero_acte_naissance = forms.CharField(
        label="N° d'extrait d'acte de naissance", max_length=60, required=False,
    )
    handicap = forms.ChoiceField(
        label="Situation de handicap", choices=[("", "— Aucune —")] + SituationHandicap.choices, required=False,
    )
    statut_deplacement = forms.ChoiceField(
        label="Situation de déplacement", choices=[("", "— Aucune —")] + StatutDeplacement.choices, required=False,
    )
    classe = forms.ModelChoiceField(label="Classe", queryset=Classe.objects.none())
    parent_email_1 = forms.EmailField(label="Email du 1er parent")
    parent_nom_1 = forms.CharField(label="Nom du 1er parent", max_length=100, required=False)
    parent_prenom_1 = forms.CharField(label="Prénom du 1er parent", max_length=100, required=False)
    parent_telephone_1 = forms.CharField(label="Téléphone du 1er parent", max_length=20, required=False)
    parent_email_2 = forms.EmailField(label="Email du 2ème parent (optionnel)", required=False)
    parent_nom_2 = forms.CharField(label="Nom du 2ème parent", max_length=100, required=False)
    parent_prenom_2 = forms.CharField(label="Prénom du 2ème parent", max_length=100, required=False)
    parent_telephone_2 = forms.CharField(label="Téléphone du 2ème parent", max_length=20, required=False)

    def __init__(self, *args, classes_disponibles=None, etablissement=None, **kwargs):
        super().__init__(*args, **kwargs)
        if classes_disponibles is not None:
            self.fields["classe"].queryset = classes_disponibles
        self._etablissement = etablissement

    def _resoudre_parent(self, suffixe, email):
        """
        Si l'email correspond déjà à un compte parent de cet établissement,
        le lien se fait immédiatement. Sinon, l'email (et le nom/prénom/
        téléphone éventuellement fournis) est simplement mémorisé
        (ParentEnAttente) : le lien se fera automatiquement dès que ce
        parent créera et vérifiera son compte avec le même email - plus
        besoin qu'il soit déjà inscrit pour que son enfant le soit.
        """
        if not email:
            return None, None
        try:
            parent = Utilisateur.objects.get(email__iexact=email, etablissement=self._etablissement)
        except Utilisateur.DoesNotExist:
            return None, {
                "email": email,
                "nom": self.data.get(f"parent_nom_{suffixe}", "").strip(),
                "prenom": self.data.get(f"parent_prenom_{suffixe}", "").strip(),
                "telephone": self.data.get(f"parent_telephone_{suffixe}", "").strip(),
            }
        if parent.role != Role.PARENT:
            self.add_error(f"parent_email_{suffixe}", "Ce compte n'a pas le rôle « parent ».")
            return None, None
        return parent, None

    def clean_matricule(self):
        matricule = self.cleaned_data["matricule"].strip()
        if matricule and Utilisateur.objects.filter(matricule=matricule).exists():
            raise forms.ValidationError("Ce matricule est déjà utilisé par un autre élève.")
        return matricule

    def clean(self):
        cleaned = super().clean()
        email_1, email_2 = cleaned.get("parent_email_1"), cleaned.get("parent_email_2")
        if email_1 and email_2 and email_1.strip().lower() == email_2.strip().lower():
            self.add_error("parent_email_2", "Les deux parents doivent avoir des emails différents.")
            return cleaned
        parent_1, en_attente_1 = self._resoudre_parent("1", email_1)
        parent_2, en_attente_2 = self._resoudre_parent("2", email_2)
        if parent_1 and parent_2 and parent_1.pk == parent_2.pk:
            self.add_error("parent_email_2", "Les deux parents doivent être des comptes différents.")
        cleaned["parent_1"] = parent_1
        cleaned["parent_2"] = parent_2
        cleaned["parents_en_attente"] = [info for info in (en_attente_1, en_attente_2) if info]
        return cleaned


class CloturerInscriptionForm(BootstrapFormMixin, forms.Form):
    decision = forms.ChoiceField(
        label="Motif de sortie",
        choices=[
            (Inscription.Statut.ABANDON, "Abandon"),
            (Inscription.Statut.TRANSFERE, "Transfert vers une autre école"),
        ],
        widget=forms.RadioSelect,
    )
    date_evenement = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}))
    motif = forms.CharField(label="Motif", widget=forms.Textarea(attrs={"rows": 3}))
    destination_libelle = forms.CharField(
        label="Établissement de destination", required=False,
        help_text="Requis uniquement en cas de transfert.",
    )
    justificatif = forms.FileField(
        label="Justificatif (optionnel)", required=False,
        validators=[valider_taille_fichier_10mo, valider_extension_document, valider_contenu_fichier],
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") == Inscription.Statut.TRANSFERE and not cleaned.get("destination_libelle"):
            self.add_error("destination_libelle", "Indiquez l'établissement de destination.")
        return cleaned


class CorrigerDossierEleveForm(BootstrapFormMixin, forms.Form):
    """
    Les renseignements d'un élève qui peuvent se corriger après l'inscription. Jamais le matricule : il figure déjà
    sur les documents remis (bulletins, attestations) et sert de clé partout.
    """

    CHAMPS = (
        "prenom", "nom", "sexe", "date_naissance", "lieu_naissance", "numero_acte_naissance", "handicap",
        "statut_deplacement",
    )

    prenom = forms.CharField(label="Prénom", max_length=100)
    nom = forms.CharField(label="Nom", max_length=100)
    sexe = forms.ChoiceField(label="Sexe", choices=Sexe.choices)
    date_naissance = forms.DateField(
        label="Date de naissance", required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    lieu_naissance = forms.CharField(label="Lieu de naissance", max_length=120, required=False)
    numero_acte_naissance = forms.CharField(label="N° d'extrait d'acte de naissance", max_length=60, required=False)
    handicap = forms.ChoiceField(
        label="Situation de handicap", choices=[("", "— Aucune —")] + SituationHandicap.choices, required=False,
    )
    statut_deplacement = forms.ChoiceField(
        label="Situation de déplacement", choices=[("", "— Aucune —")] + StatutDeplacement.choices, required=False,
    )

    def __init__(self, *args, eleve, **kwargs):
        kwargs.setdefault("initial", {nom: getattr(eleve, nom) or "" for nom in self.CHAMPS})
        super().__init__(*args, **kwargs)

    def clean_date_naissance(self):
        date = self.cleaned_data.get("date_naissance")
        if date and date > datetime.date.today():
            raise forms.ValidationError("La date de naissance ne peut pas être dans le futur.")
        return date

    def appliquer(self, eleve) -> list[str]:
        """Écrit les valeurs corrigées sur l'élève et rend les NOMS des champs réellement modifiés (jamais les valeurs)."""
        modifies = []
        for nom in self.CHAMPS:
            valeur = self.cleaned_data.get(nom)
            if isinstance(valeur, str):
                valeur = valeur.strip()
            if (getattr(eleve, nom) or "") != (valeur or ""):
                setattr(eleve, nom, valeur)
                modifies.append(nom)
        if modifies:
            eleve.save(update_fields=modifies)
        return modifies


class ParentEnAttenteForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ParentEnAttente
        fields = ["email", "prenom", "nom", "telephone"]
        labels = {"email": "Email", "prenom": "Prénom", "nom": "Nom", "telephone": "Téléphone"}

    def __init__(self, *args, etablissement=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._etablissement = etablissement

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        compte = Utilisateur.objects.filter(email__iexact=email, etablissement=self._etablissement).first()
        if compte and compte.role != Role.PARENT:
            raise forms.ValidationError("Ce compte n'a pas le rôle « parent ».")
        return email


class BaseParentsEnAttenteFormSet(forms.BaseModelFormSet):
    def add_fields(self, form, index):
        super().add_fields(form, index)
        if "DELETE" in form.fields:
            form.fields["DELETE"].label = "Retirer ce parent"
            form.fields["DELETE"].widget.attrs["class"] = "form-check-input"

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        vus = set()
        for form in self.forms:
            email = (form.cleaned_data.get("email") or "").lower()
            if not email or form.cleaned_data.get("DELETE"):
                continue
            if email in vus:
                raise forms.ValidationError("Deux parents ont le même email.")
            vus.add(email)


MAX_PARENTS_PAR_ELEVE = 2


def formset_parents_en_attente(nb_parents_lies, nb_en_attente):
    """
    Un élève a au plus deux parents (comme à l'inscription) : on ne propose une ligne vide que s'il reste de la place,
    en comptant les parents qui ont déjà un compte lié.
    """
    places = max(0, MAX_PARENTS_PAR_ELEVE - nb_parents_lies)
    return forms.modelformset_factory(
        ParentEnAttente, form=ParentEnAttenteForm, formset=BaseParentsEnAttenteFormSet, can_delete=True,
        can_delete_extra=False, extra=1 if nb_en_attente < places else 0, max_num=max(places, nb_en_attente),
        validate_max=True,
    )
