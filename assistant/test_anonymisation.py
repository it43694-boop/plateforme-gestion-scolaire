"""
Ce que l'Assistant envoie à l'IA externe (Groq, hors du Mali) : jamais le nom ni le matricule de l'élève, et la
question libre est débarrassée des noms de l'élève, des emails et des longs numéros avant l'envoi.
"""
import datetime
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from assistant.services import anonymiser_question, serialiser_resultat
from comptes.models import Utilisateur
from comptes.roles import Role, StatutCompte
from finances.models import TypeTranche, enregistrer_paiement
from pedagogie.models import Trimestre, saisir_note
from scolarite.models import Affectation, AnneeScolaire, Classe, Cycle, Inscription


class AnonymiserQuestionTests(SimpleTestCase):
    def test_nom_et_prenom_de_l_eleve_remplaces_quelle_que_soit_la_casse(self):
        resultat = anonymiser_question("Awa Traoré a-t-elle payé ? AWA traoré est-elle absente ?", noms=["Awa", "Traoré"])
        self.assertNotIn("awa", resultat.lower())
        self.assertNotIn("traor", resultat.lower())
        self.assertIn("l'élève", resultat)

    def test_accents_ignores_dans_les_deux_sens(self):
        self.assertNotIn("issata", anonymiser_question("aissata a des absences ?", noms=["Aïssata"]).lower())
        self.assertNotIn("aïssata", anonymiser_question("Aïssata a des absences ?", noms=["Aissata"]).lower())

    def test_mot_entier_seulement(self):
        """Un prénom court ne doit pas abîmer les autres mots de la question."""
        self.assertEqual(anonymiser_question("Quel est le total des Awards ?", noms=["Awa"]), "Quel est le total des Awards ?")

    def test_prenom_compose(self):
        resultat = anonymiser_question("Marie Awa Keita est-elle inscrite ?", noms=["Marie Awa", "Keita"])
        self.assertNotIn("Marie", resultat)
        self.assertNotIn("Keita", resultat)

    def test_matricule_telephone_et_email_masques(self):
        resultat = anonymiser_question("Élève 202661497, tel 70123456, parent awa.traore@mail.com : solde ?")
        self.assertNotIn("202661497", resultat)
        self.assertNotIn("70123456", resultat)
        self.assertNotIn("@mail.com", resultat)
        self.assertIn("[numéro]", resultat)
        self.assertIn("[email]", resultat)

    def test_les_petits_nombres_et_les_questions_generales_ne_changent_pas(self):
        for question in ("Combien d'élèves sont inscrits en 2026 ?", "Quel est le solde de la caisse : 150000 FCFA ?", ""):
            self.assertEqual(anonymiser_question(question), question)

    def test_valeurs_vides_acceptees(self):
        self.assertEqual(anonymiser_question(None), "")
        self.assertEqual(anonymiser_question("Bonjour", noms=[None, "", " "]), "Bonjour")


class SerialiserResultatTests(SimpleTestCase):
    def test_aucune_identite_ni_reference_dans_les_donnees_envoyees(self):
        eleve = SimpleNamespace(nom_complet="Awa Traoré", matricule="202661497", prenom="Awa", nom="Traoré")
        paiement = SimpleNamespace(reference="REC-000123", get_tranche_display=lambda: "Versement", montant=20000)
        note = SimpleNamespace(
            affectation=SimpleNamespace(matiere="Maths"), get_trimestre_display=lambda: "1er trimestre", valeur=14,
        )
        donnees = serialiser_resultat({
            "eleve": eleve, "dossier_complet": True, "inscription": SimpleNamespace(classe="6A (2026-2027)"),
            "dernieres_notes": [note], "total_absences": 2, "derniers_paiements": [paiement],
        })
        brut = json.dumps(donnees, ensure_ascii=False)
        for interdit in ("Awa", "Traoré", "202661497", "REC-000123"):
            self.assertNotIn(interdit, brut)
        self.assertEqual(donnees["total_absences"], 2)  # les données utiles restent
        self.assertEqual(donnees["derniers_paiements"], [{"tranche": "Versement", "montant_fcfa": 20000}])
        self.assertEqual(donnees["dernieres_notes"][0]["valeur_sur_20"], 14.0)


@override_settings(GROQ_API_KEY="cle-de-test-factice")
class AssistantEnvoiAnonymeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        annee = AnneeScolaire.objects.create(
            libelle="2026-2027", date_debut=datetime.date(2026, 10, 1), date_fin=datetime.date(2027, 7, 31), est_active=True,
        )
        self.classe = Classe.objects.create(nom="4ème année B", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=annee)
        self.eleve = self.creer("eleve-anon@example.com", Role.ELEVE, prenom="Aminata", nom="Zqxcoulibaly")
        inscription = Inscription.objects.create(eleve=self.eleve, classe=self.classe)
        self.comptable = self.creer("comptable-anon@example.com", Role.COMPTABLE)
        self.enseignant = self.creer("prof-anon@example.com", Role.ENSEIGNANT)
        affectation = Affectation.objects.create(enseignant=self.enseignant, classe=self.classe, matiere="Anglais")
        saisir_note(
            eleve=self.eleve, affectation=affectation, trimestre=Trimestre.T1 if hasattr(Trimestre, "T1") else list(Trimestre)[0],
            note_classe=12, note_composition=28, enseignant=self.enseignant,
        )
        self.paiement = enregistrer_paiement(
            eleve=self.eleve, inscription=inscription, tranche=TypeTranche.VERSEMENT, montant=20000,
            mode_paiement="especes", enregistre_par=self.comptable,
        )

    @staticmethod
    def creer(email, role, **extra):
        compte = Utilisateur(
            email=email, prenom=extra.pop("prenom", "Test"), nom=extra.pop("nom", "Utilisateur"), role=role,
            statut=StatutCompte.ACTIF, is_active=True, **extra,
        )
        compte.set_password("MotDePasse#2026")
        compte.full_clean(exclude=["password"])
        compte.save()
        return compte

    def demander(self, utilisateur, question):
        with patch("assistant.views.repondre_avec_ia", return_value="Réponse simulée.") as ia:
            self.client.force_login(utilisateur)
            self.client.get(reverse("assistant:poser_question"), {"matricule": self.eleve.matricule, "question": question})
        self.assertTrue(ia.called)
        return ia.call_args.kwargs

    def test_ni_le_nom_ni_le_matricule_ni_la_reference_ne_partent_vers_l_ia(self):
        envoye = self.demander(self.comptable, "Aminata a-t-elle payé ?")
        brut = json.dumps(envoye["donnees_autorisees"], ensure_ascii=False, default=str)
        for interdit in ("Aminata", "Zqxcoulibaly", self.eleve.matricule, self.paiement.reference):
            self.assertNotIn(interdit, brut)
        self.assertIn("derniers_paiements", envoye["donnees_autorisees"])  # la réponse reste possible

    def test_la_question_tapee_est_anonymisee_avant_l_envoi(self):
        envoye = self.demander(
            self.comptable, f"Aminata Zqxcoulibaly (matricule {self.eleve.matricule}) a-t-elle payé ? écrire à p@mail.com",
        )
        question = envoye["question"]
        for interdit in ("Aminata", "Zqxcoulibaly", self.eleve.matricule, "p@mail.com"):
            self.assertNotIn(interdit, question)
        self.assertIn("a-t-elle payé", question)

    def test_la_reponse_affichee_reste_celle_de_l_ia(self):
        with patch("assistant.views.repondre_avec_ia", return_value="Le versement est enregistré.") as ia:
            self.client.force_login(self.comptable)
            reponse = self.client.get(reverse("assistant:poser_question"), {
                "matricule": self.eleve.matricule, "question": "Aminata a-t-elle payé ?",
            })
        self.assertTrue(ia.called)
        self.assertContains(reponse, "Le versement est enregistré.")
        self.assertContains(reponse, "Aminata")  # le dossier affiché à l'utilisateur, lui, garde le nom
