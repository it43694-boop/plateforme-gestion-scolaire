import datetime

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from comptes.models import Utilisateur
from comptes.roles import Role, StatutCompte
from pedagogie.models import Absence, CreneauEmploiDuTemps, JourSemaine, Note, Trimestre, saisir_note
from scolarite.models import Affectation, AnneeScolaire, Classe, Cycle, Inscription


def creer_utilisateur_actif(email, role, **kwargs):
    utilisateur = Utilisateur(email=email, prenom="Test", nom="Utilisateur", role=role, **kwargs)
    utilisateur.set_password("MotDePasse#2026")
    utilisateur.statut = StatutCompte.ACTIF
    utilisateur.is_active = True
    utilisateur.full_clean(exclude=["password"])
    utilisateur.save()
    return utilisateur


def creer_contexte_classe():
    annee = AnneeScolaire.objects.create(
        libelle="2026-2027", date_debut=datetime.date(2026, 10, 1),
        date_fin=datetime.date(2027, 7, 31), est_active=True,
    )
    classe = Classe.objects.create(nom="4ème année B", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=annee)
    return annee, classe


class SaisieNoteTests(TestCase):
    def setUp(self):
        self.annee, self.classe = creer_contexte_classe()
        self.enseignant = creer_utilisateur_actif("prof-note@example.com", Role.ENSEIGNANT)
        self.autre_enseignant = creer_utilisateur_actif("autre-prof@example.com", Role.ENSEIGNANT)
        self.affectation = Affectation.objects.create(
            enseignant=self.enseignant, classe=self.classe, matiere="Mathématiques",
        )
        self.eleve = creer_utilisateur_actif("eleve-note@example.com", Role.ELEVE)
        Inscription.objects.create(eleve=self.eleve, classe=self.classe)

    def test_enseignant_affecte_peut_noter(self):
        note = saisir_note(
            eleve=self.eleve, affectation=self.affectation, trimestre=Trimestre.T1,
            valeur=15.5, enseignant=self.enseignant,
        )
        self.assertEqual(note.valeur, 15.5)

    def test_autre_enseignant_ne_peut_pas_noter(self):
        with self.assertRaises(ValidationError):
            saisir_note(
                eleve=self.eleve, affectation=self.affectation, trimestre=Trimestre.T1,
                valeur=10, enseignant=self.autre_enseignant,
            )

    def test_resaisir_corrige_sans_creer_de_doublon(self):
        saisir_note(eleve=self.eleve, affectation=self.affectation, trimestre=Trimestre.T1, valeur=10, enseignant=self.enseignant)
        saisir_note(eleve=self.eleve, affectation=self.affectation, trimestre=Trimestre.T1, valeur=17, enseignant=self.enseignant)
        self.assertEqual(Note.objects.filter(eleve=self.eleve, affectation=self.affectation, trimestre=Trimestre.T1).count(), 1)
        note = Note.objects.get(eleve=self.eleve, affectation=self.affectation, trimestre=Trimestre.T1)
        self.assertEqual(note.valeur, 17)

    def test_note_hors_intervalle_refusee(self):
        with self.assertRaises(ValidationError):
            saisir_note(eleve=self.eleve, affectation=self.affectation, trimestre=Trimestre.T1, valeur=25, enseignant=self.enseignant)

    def test_eleve_non_inscrit_refuse(self):
        autre_eleve = creer_utilisateur_actif("hors-classe@example.com", Role.ELEVE)
        with self.assertRaises(ValidationError):
            saisir_note(eleve=autre_eleve, affectation=self.affectation, trimestre=Trimestre.T1, valeur=12, enseignant=self.enseignant)


class BulletinPondereTests(TestCase):
    """
    _calculer_bulletin pondère chaque note par le coefficient de sa matière
    (scolarite.models.Affectation.coefficient, 1 par défaut). Avec tous les
    coefficients à 1, le résultat reste une moyenne arithmétique simple -
    donc inchangé pour les données existantes.
    """

    def setUp(self):
        self.annee, self.classe = creer_contexte_classe()
        self.enseignant = creer_utilisateur_actif("prof-pondere@example.com", Role.ENSEIGNANT)
        self.eleve = creer_utilisateur_actif("eleve-pondere@example.com", Role.ELEVE)
        self.inscription = Inscription.objects.create(eleve=self.eleve, classe=self.classe)

    def test_coefficients_par_defaut_donnent_une_moyenne_simple(self):
        maths = Affectation.objects.create(enseignant=self.enseignant, classe=self.classe, matiere="Mathématiques")
        sport = Affectation.objects.create(enseignant=self.enseignant, classe=self.classe, matiere="Sport")
        saisir_note(eleve=self.eleve, affectation=maths, trimestre=Trimestre.T1, valeur=10, enseignant=self.enseignant)
        saisir_note(eleve=self.eleve, affectation=sport, trimestre=Trimestre.T1, valeur=20, enseignant=self.enseignant)

        from pedagogie.views import _calculer_bulletin
        resultat = _calculer_bulletin(self.eleve, self.inscription)
        self.assertEqual(resultat["moyenne_generale"], 15)

    def test_coefficient_plus_eleve_pese_davantage_sur_la_moyenne(self):
        maths = Affectation.objects.create(
            enseignant=self.enseignant, classe=self.classe, matiere="Mathématiques", coefficient=3,
        )
        sport = Affectation.objects.create(
            enseignant=self.enseignant, classe=self.classe, matiere="Sport", coefficient=1,
        )
        saisir_note(eleve=self.eleve, affectation=maths, trimestre=Trimestre.T1, valeur=10, enseignant=self.enseignant)
        saisir_note(eleve=self.eleve, affectation=sport, trimestre=Trimestre.T1, valeur=20, enseignant=self.enseignant)

        from pedagogie.views import _calculer_bulletin
        resultat = _calculer_bulletin(self.eleve, self.inscription)
        # (10*3 + 20*1) / (3+1) = 12.5, contre 15 en moyenne simple.
        self.assertEqual(resultat["moyenne_generale"], 12.5)


class ClassementTests(TestCase):
    def setUp(self):
        self.annee, self.classe = creer_contexte_classe()
        self.enseignant = creer_utilisateur_actif("prof-classement@example.com", Role.ENSEIGNANT)
        self.affectation = Affectation.objects.create(
            enseignant=self.enseignant, classe=self.classe, matiere="Mathématiques",
        )
        self.premier = creer_utilisateur_actif("premier@example.com", Role.ELEVE)
        self.second = creer_utilisateur_actif("second@example.com", Role.ELEVE)
        self.troisieme = creer_utilisateur_actif("troisieme@example.com", Role.ELEVE)
        self.inscription_premier = Inscription.objects.create(eleve=self.premier, classe=self.classe)
        self.inscription_second = Inscription.objects.create(eleve=self.second, classe=self.classe)
        self.inscription_troisieme = Inscription.objects.create(eleve=self.troisieme, classe=self.classe)

    def test_classement_ordonne_les_eleves_par_moyenne(self):
        saisir_note(eleve=self.premier, affectation=self.affectation, trimestre=Trimestre.T1, valeur=18, enseignant=self.enseignant)
        saisir_note(eleve=self.second, affectation=self.affectation, trimestre=Trimestre.T1, valeur=12, enseignant=self.enseignant)
        saisir_note(eleve=self.troisieme, affectation=self.affectation, trimestre=Trimestre.T1, valeur=8, enseignant=self.enseignant)

        from pedagogie.views import _calculer_bulletin
        self.assertEqual(_calculer_bulletin(self.premier, self.inscription_premier)["rang"], 1)
        self.assertEqual(_calculer_bulletin(self.second, self.inscription_second)["rang"], 2)
        resultat_troisieme = _calculer_bulletin(self.troisieme, self.inscription_troisieme)
        self.assertEqual(resultat_troisieme["rang"], 3)
        self.assertEqual(resultat_troisieme["effectif_classe"], 3)

    def test_classement_gere_les_ex_aequo(self):
        saisir_note(eleve=self.premier, affectation=self.affectation, trimestre=Trimestre.T1, valeur=15, enseignant=self.enseignant)
        saisir_note(eleve=self.second, affectation=self.affectation, trimestre=Trimestre.T1, valeur=15, enseignant=self.enseignant)
        saisir_note(eleve=self.troisieme, affectation=self.affectation, trimestre=Trimestre.T1, valeur=10, enseignant=self.enseignant)

        from pedagogie.views import _calculer_bulletin
        self.assertEqual(_calculer_bulletin(self.premier, self.inscription_premier)["rang"], 1)
        self.assertEqual(_calculer_bulletin(self.second, self.inscription_second)["rang"], 1)
        self.assertEqual(_calculer_bulletin(self.troisieme, self.inscription_troisieme)["rang"], 3)


class VisibiliteBulletinTests(TestCase):
    def setUp(self):
        self.annee, self.classe = creer_contexte_classe()
        self.enseignant = creer_utilisateur_actif("prof-bul@example.com", Role.ENSEIGNANT)
        self.affectation = Affectation.objects.create(enseignant=self.enseignant, classe=self.classe, matiere="Français")
        self.eleve = creer_utilisateur_actif("eleve-bul@example.com", Role.ELEVE)
        Inscription.objects.create(eleve=self.eleve, classe=self.classe)
        self.parent = creer_utilisateur_actif("parent-bul@example.com", Role.PARENT, telephone="70200001", profession="X")
        self.eleve.parents_lies.add(self.parent)
        saisir_note(eleve=self.eleve, affectation=self.affectation, trimestre=Trimestre.T1, valeur=14, enseignant=self.enseignant)

    def test_eleve_voit_son_propre_bulletin(self):
        self.client.force_login(self.eleve)
        reponse = self.client.get(reverse("pedagogie:bulletin_eleve", args=[self.eleve.matricule]))
        self.assertEqual(reponse.status_code, 200)

    def test_export_pdf_du_bulletin_renvoie_un_pdf(self):
        self.client.force_login(self.eleve)
        reponse = self.client.get(reverse("pedagogie:exporter_bulletin_pdf", args=[self.eleve.matricule]))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse["Content-Type"], "application/pdf")
        self.assertTrue(reponse.content.startswith(b"%PDF"))

    def test_export_pdf_avec_logo_etablissement_reussit(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from etablissement.models import Etablissement
        from permissions_matrix.models import PermissionMatrix

        png_1x1 = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00'
            b'\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        etablissement = Etablissement.objects.create(
            nom="École du Logo",
            logo=SimpleUploadedFile("logo.png", png_1x1, content_type="image/png"),
        )
        PermissionMatrix.seed_pour(etablissement)
        self.eleve.etablissement = etablissement
        self.eleve.save(update_fields=["etablissement"])

        self.client.force_login(self.eleve)
        reponse = self.client.get(reverse("pedagogie:exporter_bulletin_pdf", args=[self.eleve.matricule]))
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(reponse.content.startswith(b"%PDF"))

    def test_export_pdf_refuse_pour_eleve_non_visible(self):
        exterieur = creer_utilisateur_actif("exterieur-pdf@example.com", Role.ENSEIGNANT)
        self.client.force_login(exterieur)
        reponse = self.client.get(reverse("pedagogie:exporter_bulletin_pdf", args=[self.eleve.matricule]))
        self.assertEqual(reponse.status_code, 403)

    def test_parent_voit_le_bulletin_de_son_enfant(self):
        self.client.force_login(self.parent)
        reponse = self.client.get(reverse("pedagogie:bulletin_eleve", args=[self.eleve.matricule]))
        self.assertEqual(reponse.status_code, 200)

    def test_parent_ne_voit_pas_le_bulletin_dun_autre_eleve(self):
        autre_eleve = creer_utilisateur_actif("autre-eleve-bul@example.com", Role.ELEVE)
        Inscription.objects.create(eleve=autre_eleve, classe=self.classe)
        self.client.force_login(self.parent)
        reponse = self.client.get(reverse("pedagogie:bulletin_eleve", args=[autre_eleve.matricule]))
        self.assertEqual(reponse.status_code, 403)

    def test_enseignant_non_affecte_ne_voit_pas_le_bulletin(self):
        enseignant_exterieur = creer_utilisateur_actif("exterieur@example.com", Role.ENSEIGNANT)
        self.client.force_login(enseignant_exterieur)
        reponse = self.client.get(reverse("pedagogie:bulletin_eleve", args=[self.eleve.matricule]))
        self.assertEqual(reponse.status_code, 403)


class AbsenceTests(TestCase):
    def setUp(self):
        self.annee, self.classe = creer_contexte_classe()
        self.enseignant = creer_utilisateur_actif("prof-abs@example.com", Role.ENSEIGNANT)
        Affectation.objects.create(enseignant=self.enseignant, classe=self.classe, matiere="")
        self.eleve = creer_utilisateur_actif("eleve-abs@example.com", Role.ELEVE)
        Inscription.objects.create(eleve=self.eleve, classe=self.classe)

    def test_une_seule_absence_par_jour_resaisie_met_a_jour(self):
        self.client.force_login(self.enseignant)
        url = reverse("pedagogie:saisir_absence", args=[self.classe.id])
        self.client.post(url, {
            "matricule_eleve": self.eleve.matricule, "date_absence": "2026-11-10",
            "justifiee": "", "motif": "",
        })
        self.client.post(url, {
            "matricule_eleve": self.eleve.matricule, "date_absence": "2026-11-10",
            "justifiee": "on", "motif": "Maladie",
        })
        self.assertEqual(Absence.objects.filter(eleve=self.eleve).count(), 1)
        absence = Absence.objects.get(eleve=self.eleve)
        self.assertTrue(absence.justifiee)
        self.assertEqual(absence.motif, "Maladie")

    def test_absence_future_refusee(self):
        demain = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        absence = Absence(eleve=self.eleve, classe=self.classe, date_absence=demain, enregistre_par=self.enseignant)
        with self.assertRaises(ValidationError):
            absence.full_clean()

    def test_enseignant_non_affecte_ne_peut_pas_saisir(self):
        exterieur = creer_utilisateur_actif("exterieur-abs@example.com", Role.ENSEIGNANT)
        self.client.force_login(exterieur)
        reponse = self.client.get(reverse("pedagogie:saisir_absence", args=[self.classe.id]))
        self.assertEqual(reponse.status_code, 403)

    def test_parent_voit_historique_absence_de_son_enfant(self):
        Absence.objects.create(eleve=self.eleve, classe=self.classe, date_absence=datetime.date(2026, 11, 5), enregistre_par=self.enseignant)
        parent = creer_utilisateur_actif("parent-abs@example.com", Role.PARENT, telephone="70200002", profession="X")
        self.eleve.parents_lies.add(parent)
        self.client.force_login(parent)
        reponse = self.client.get(reverse("pedagogie:historique_absences", args=[self.eleve.matricule]))
        self.assertEqual(reponse.status_code, 200)


class SuiviDesCoursTests(TestCase):
    def setUp(self):
        self.annee, self.classe = creer_contexte_classe()
        self.classe_2eme = Classe.objects.create(nom="8ème année A", cycle=Cycle.DEUXIEME_CYCLE, annee_scolaire=self.annee)
        self.enseignant = creer_utilisateur_actif("prof-suivi@example.com", Role.ENSEIGNANT)
        self.affectation = Affectation.objects.create(enseignant=self.enseignant, classe=self.classe, matiere="Histoire")
        self.eleve = creer_utilisateur_actif("eleve-suivi@example.com", Role.ELEVE)
        Inscription.objects.create(eleve=self.eleve, classe=self.classe)
        saisir_note(eleve=self.eleve, affectation=self.affectation, trimestre=Trimestre.T1, valeur=12, enseignant=self.enseignant)
        Absence.objects.create(eleve=self.eleve, classe=self.classe, date_absence=datetime.date(2026, 11, 3), enregistre_par=self.enseignant)

    def test_compte_correctement_notes_et_absences_par_classe(self):
        direction = creer_utilisateur_actif("direction-suivi@example.com", Role.FONDATEUR)
        self.client.force_login(direction)
        reponse = self.client.get(reverse("pedagogie:suivi_des_cours"))
        ligne_classe = next(l for l in reponse.context["lignes"] if l["classe"] == self.classe)
        self.assertEqual(ligne_classe["nb_notes"], 1)
        self.assertEqual(ligne_classe["nb_absences"], 1)
        self.assertEqual(ligne_classe["nb_affectations"], 1)
        self.assertIsNotNone(ligne_classe["derniere_activite"])

    def test_directeur_de_cycle_ne_voit_pas_lautre_cycle(self):
        directeur_1er = creer_utilisateur_actif("dir1-suivi@example.com", Role.DIRECTEUR_1ER_CYCLE)
        self.client.force_login(directeur_1er)
        reponse = self.client.get(reverse("pedagogie:suivi_des_cours"))
        classes_listees = [l["classe"] for l in reponse.context["lignes"]]
        self.assertIn(self.classe, classes_listees)
        self.assertNotIn(self.classe_2eme, classes_listees)

    def test_enseignant_sans_acces_est_bloque(self):
        self.client.force_login(self.enseignant)
        reponse = self.client.get(reverse("pedagogie:suivi_des_cours"))
        self.assertEqual(reponse.status_code, 403)


class EmploiDuTempsTests(TestCase):
    def setUp(self):
        self.annee, self.classe = creer_contexte_classe()
        self.autre_classe = Classe.objects.create(nom="4ème année C", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        self.enseignant = creer_utilisateur_actif("prof-edt@example.com", Role.ENSEIGNANT)
        self.affectation = Affectation.objects.create(enseignant=self.enseignant, classe=self.classe, matiere="Sciences")
        self.affectation_autre_classe = Affectation.objects.create(
            enseignant=self.enseignant, classe=self.autre_classe, matiere="Sciences",
        )
        self.direction = creer_utilisateur_actif("direction-edt@example.com", Role.FONDATEUR)

    def test_creneau_valide_accepte(self):
        creneau = CreneauEmploiDuTemps(
            classe=self.classe, affectation=self.affectation, jour_semaine=JourSemaine.LUNDI,
            heure_debut=datetime.time(8, 0), heure_fin=datetime.time(9, 0),
        )
        creneau.full_clean()
        creneau.save()
        self.assertEqual(CreneauEmploiDuTemps.objects.count(), 1)

    def test_chevauchement_meme_classe_refuse(self):
        CreneauEmploiDuTemps.objects.create(
            classe=self.classe, affectation=self.affectation, jour_semaine=JourSemaine.LUNDI,
            heure_debut=datetime.time(8, 0), heure_fin=datetime.time(9, 0),
        )
        conflit = CreneauEmploiDuTemps(
            classe=self.classe, affectation=self.affectation, jour_semaine=JourSemaine.LUNDI,
            heure_debut=datetime.time(8, 30), heure_fin=datetime.time(9, 30),
        )
        with self.assertRaises(ValidationError):
            conflit.full_clean()

    def test_enseignant_ne_peut_pas_etre_sur_deux_classes_en_meme_temps(self):
        CreneauEmploiDuTemps.objects.create(
            classe=self.classe, affectation=self.affectation, jour_semaine=JourSemaine.MARDI,
            heure_debut=datetime.time(10, 0), heure_fin=datetime.time(11, 0),
        )
        conflit = CreneauEmploiDuTemps(
            classe=self.autre_classe, affectation=self.affectation_autre_classe, jour_semaine=JourSemaine.MARDI,
            heure_debut=datetime.time(10, 30), heure_fin=datetime.time(11, 30),
        )
        with self.assertRaises(ValidationError):
            conflit.full_clean()

    def test_export_pdf_renvoie_un_pdf(self):
        CreneauEmploiDuTemps.objects.create(
            classe=self.classe, affectation=self.affectation, jour_semaine=JourSemaine.LUNDI,
            heure_debut=datetime.time(8, 0), heure_fin=datetime.time(9, 0),
        )
        self.client.force_login(self.direction)
        reponse = self.client.get(reverse("pedagogie:exporter_emploi_du_temps_pdf", args=[self.classe.id]))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse["Content-Type"], "application/pdf")
        self.assertTrue(reponse.content.startswith(b"%PDF"))
