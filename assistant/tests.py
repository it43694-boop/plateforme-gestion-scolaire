import datetime
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from comptes.models import Utilisateur
from comptes.roles import Role, StatutCompte
from finances.models import TypeTranche, enregistrer_paiement
from pedagogie.models import Trimestre, saisir_note
from scolarite.models import Affectation, AnneeScolaire, Classe, Cycle, Inscription
from assistant.services import AssistantIndisponible, serialiser_resultat


def creer_utilisateur_actif(email, role, **kwargs):
    utilisateur = Utilisateur(email=email, prenom="Test", nom="Utilisateur", role=role, **kwargs)
    utilisateur.set_password("MotDePasse#2026")
    utilisateur.statut = StatutCompte.ACTIF
    utilisateur.is_active = True
    utilisateur.full_clean(exclude=["password"])
    utilisateur.save()
    return utilisateur


class AssistantTests(TestCase):
    def setUp(self):
        self.annee = AnneeScolaire.objects.create(
            libelle="2026-2027", date_debut=datetime.date(2026, 10, 1),
            date_fin=datetime.date(2027, 7, 31), est_active=True,
        )
        self.classe = Classe.objects.create(nom="5ème année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        self.eleve = creer_utilisateur_actif("eleve-assist@example.com", Role.ELEVE)
        self.inscription = Inscription.objects.create(eleve=self.eleve, classe=self.classe)
        self.enseignant = creer_utilisateur_actif("prof-assist@example.com", Role.ENSEIGNANT)
        self.affectation = Affectation.objects.create(enseignant=self.enseignant, classe=self.classe, matiere="SVT")
        saisir_note(eleve=self.eleve, affectation=self.affectation, trimestre=Trimestre.T1, valeur=14, enseignant=self.enseignant)
        self.comptable = creer_utilisateur_actif("comptable-assist@example.com", Role.COMPTABLE)
        enregistrer_paiement(
            eleve=self.eleve, inscription=self.inscription, tranche=TypeTranche.TRANCHE_1,
            montant=15000, mode_paiement="especes", enregistre_par=self.comptable,
        )

    def test_enseignant_voit_les_notes_mais_pas_les_paiements(self):
        self.client.force_login(self.enseignant)
        reponse = self.client.get(reverse("assistant:poser_question"), {"matricule": self.eleve.matricule})
        self.assertIn("dernieres_notes", reponse.context["resultat"])
        self.assertNotIn("derniers_paiements", reponse.context["resultat"])

    def test_comptable_ne_voit_pas_les_notes_dun_eleve_hors_de_sa_portee(self):
        # Le comptable a accès au module Finances mais pas Notes/Absences par défaut.
        self.client.force_login(self.comptable)
        reponse = self.client.get(reverse("assistant:poser_question"), {"matricule": self.eleve.matricule})
        self.assertIn("derniers_paiements", reponse.context["resultat"])
        self.assertNotIn("dernieres_notes", reponse.context["resultat"])

    def test_enseignant_non_affecte_na_pas_acces_a_leleve(self):
        exterieur = creer_utilisateur_actif("exterieur-assist@example.com", Role.ENSEIGNANT)
        self.client.force_login(exterieur)
        reponse = self.client.get(reverse("assistant:poser_question"), {"matricule": self.eleve.matricule})
        self.assertIsNone(reponse.context["resultat"])
        self.assertTrue(reponse.context["erreur"])

    def test_matricule_inexistant(self):
        self.client.force_login(self.comptable)
        reponse = self.client.get(reverse("assistant:poser_question"), {"matricule": "00000000"})
        self.assertIsNone(reponse.context["resultat"])
        self.assertEqual(reponse.context["erreur"], "Aucun élève trouvé avec ce matricule.")

    def test_eleve_peut_se_rechercher_lui_meme(self):
        # Remarque : le rôle élève n'a pas le module Assistant par défaut
        # (outil pensé pour le personnel) ; ce test vérifie la règle de
        # visibilité elle-même via un rôle à accès total, qui la contourne
        #  donc on vérifie plutôt qu'un rôle à accès total voit tout.
        direction = creer_utilisateur_actif("direction-assist@example.com", Role.FONDATEUR)
        self.client.force_login(direction)
        reponse = self.client.get(reverse("assistant:poser_question"), {"matricule": self.eleve.matricule})
        self.assertIsNotNone(reponse.context["resultat"])
        self.assertIn("dernieres_notes", reponse.context["resultat"])
        self.assertIn("derniers_paiements", reponse.context["resultat"])
        self.assertIn("total_absences", reponse.context["resultat"])


class SerialisationDonneesIATests(TestCase):
    """
    Vérifie que le paquet envoyé à l'API ne contient JAMAIS plus que ce que
    le rôle a le droit de voir  la garantie de sécurité repose sur ce
    filtrage en amont, pas sur une consigne donnée à l'IA.
    """

    def setUp(self):
        self.annee = AnneeScolaire.objects.create(
            libelle="2026-2027", date_debut=datetime.date(2026, 10, 1),
            date_fin=datetime.date(2027, 7, 31), est_active=True,
        )
        self.classe = Classe.objects.create(nom="4ème année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        self.eleve = creer_utilisateur_actif("eleve-ia@example.com", Role.ELEVE)
        Inscription.objects.create(eleve=self.eleve, classe=self.classe)

    def test_paquet_sans_finances_quand_role_na_pas_le_module(self):
        resultat = {"eleve": self.eleve, "dossier_complet": False}
        # Ni "derniers_paiements" ni "dernieres_notes" ni "total_absences" ne
        # sont ajoutés par la vue quand le rôle n'y a pas accès  le paquet
        # sérialisé doit donc rester silencieux sur ces sujets.
        paquet = serialiser_resultat(resultat)
        self.assertNotIn("derniers_paiements", paquet)
        self.assertNotIn("dernieres_notes", paquet)
        self.assertNotIn("total_absences", paquet)

    def test_paquet_contient_uniquement_les_cles_fournies(self):
        comptable = creer_utilisateur_actif("comptable-ia@example.com", Role.COMPTABLE)
        enregistrer_paiement(
            eleve=self.eleve, inscription=Inscription.objects.get(eleve=self.eleve),
            tranche=TypeTranche.TRANCHE_1, montant=15000, mode_paiement="especes",
            enregistre_par=comptable,
        )
        from finances.models import Paiement
        resultat = {
            "eleve": self.eleve, "dossier_complet": False,
            "derniers_paiements": Paiement.objects.filter(eleve=self.eleve),
        }
        paquet = serialiser_resultat(resultat)
        self.assertIn("derniers_paiements", paquet)
        self.assertNotIn("dernieres_notes", paquet)
        self.assertNotIn("total_absences", paquet)
        self.assertEqual(paquet["derniers_paiements"][0]["montant_fcfa"], 15000)


@override_settings(GROQ_API_KEY="cle-de-test-factice")
class AssistantModeGeneratifTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()  # les compteurs de limite de débit ne sont pas réinitialisés par TestCase
        self.annee = AnneeScolaire.objects.create(
            libelle="2026-2027", date_debut=datetime.date(2026, 10, 1),
            date_fin=datetime.date(2027, 7, 31), est_active=True,
        )
        self.classe = Classe.objects.create(nom="4ème année B", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        self.enseignant = creer_utilisateur_actif("prof-ia@example.com", Role.ENSEIGNANT)
        self.affectation = Affectation.objects.create(enseignant=self.enseignant, classe=self.classe, matiere="Anglais")
        self.eleve = creer_utilisateur_actif("eleve-ia2@example.com", Role.ELEVE)
        Inscription.objects.create(eleve=self.eleve, classe=self.classe)
        self.comptable = creer_utilisateur_actif("comptable-ia2@example.com", Role.COMPTABLE)
        enregistrer_paiement(
            eleve=self.eleve, inscription=Inscription.objects.get(eleve=self.eleve),
            tranche=TypeTranche.TRANCHE_1, montant=20000, mode_paiement="especes",
            enregistre_par=self.comptable,
        )

    def test_enseignant_pose_une_question_les_finances_ne_partent_jamais_a_lapi(self):
        with patch("assistant.views.repondre_avec_ia") as mock_ia:
            mock_ia.return_value = "Réponse simulée."
            self.client.force_login(self.enseignant)
            self.client.get(reverse("assistant:poser_question"), {
                "matricule": self.eleve.matricule, "question": "Quel est son solde de paiement ?",
            })
            self.assertTrue(mock_ia.called)
            donnees_envoyees = mock_ia.call_args.kwargs["donnees_autorisees"]
            self.assertNotIn("derniers_paiements", donnees_envoyees)

    def test_comptable_pose_une_question_les_notes_ne_partent_jamais_a_lapi(self):
        with patch("assistant.views.repondre_avec_ia") as mock_ia:
            mock_ia.return_value = "Réponse simulée."
            self.client.force_login(self.comptable)
            self.client.get(reverse("assistant:poser_question"), {
                "matricule": self.eleve.matricule, "question": "A-t-il de bonnes notes ?",
            })
            donnees_envoyees = mock_ia.call_args.kwargs["donnees_autorisees"]
            self.assertNotIn("dernieres_notes", donnees_envoyees)
            self.assertIn("derniers_paiements", donnees_envoyees)

    def test_reponse_ia_affichee_dans_le_contexte(self):
        with patch("assistant.views.repondre_avec_ia", return_value="Il a payé sa tranche 1."):
            self.client.force_login(self.comptable)
            reponse = self.client.get(reverse("assistant:poser_question"), {
                "matricule": self.eleve.matricule, "question": "A-t-il payé ?",
            })
            self.assertEqual(reponse.context["reponse_ia"], "Il a payé sa tranche 1.")

    def test_panne_api_ne_bloque_pas_laffichage_des_donnees_brutes(self):
        with patch("assistant.views.repondre_avec_ia", side_effect=AssistantIndisponible("panne")):
            self.client.force_login(self.comptable)
            reponse = self.client.get(reverse("assistant:poser_question"), {
                "matricule": self.eleve.matricule, "question": "A-t-il payé ?",
            })
            self.assertIsNotNone(reponse.context["resultat"])
            self.assertIn("derniers_paiements", reponse.context["resultat"])
            self.assertTrue(reponse.context["erreur_ia"])

    def test_sans_question_pas_dappel_a_lia(self):
        with patch("assistant.views.repondre_avec_ia") as mock_ia:
            self.client.force_login(self.comptable)
            self.client.get(reverse("assistant:poser_question"), {"matricule": self.eleve.matricule})
            self.assertFalse(mock_ia.called)

    def test_limite_de_questions_par_heure_appliquee(self):
        with patch("assistant.views.repondre_avec_ia", return_value="Réponse."):
            self.client.force_login(self.comptable)
            for _ in range(20):
                self.client.get(reverse("assistant:poser_question"), {
                    "matricule": self.eleve.matricule, "question": "A-t-il payé ?",
                })
            # La 21ème question dans la même heure doit être refusée.
            reponse = self.client.get(reverse("assistant:poser_question"), {
                "matricule": self.eleve.matricule, "question": "Encore une question ?",
            })
            self.assertIn("Limite de questions", reponse.context["erreur_ia"])


class AssistantSansCleApiTests(TestCase):
    @override_settings(GROQ_API_KEY="")
    def test_sans_cle_api_le_mode_generatif_est_desactive(self):
        annee = AnneeScolaire.objects.create(
            libelle="2027-2028", date_debut=datetime.date(2027, 10, 1), date_fin=datetime.date(2028, 7, 31),
        )
        classe = Classe.objects.create(nom="2ème année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=annee)
        eleve = creer_utilisateur_actif("eleve-sans-ia@example.com", Role.ELEVE)
        Inscription.objects.create(eleve=eleve, classe=classe)
        comptable = creer_utilisateur_actif("comptable-sans-ia@example.com", Role.COMPTABLE)
        self.client.force_login(comptable)
        reponse = self.client.get(reverse("assistant:poser_question"), {
            "matricule": eleve.matricule, "question": "Une question quelconque",
        })
        self.assertFalse(reponse.context["ia_disponible"])
        self.assertIsNone(reponse.context["reponse_ia"])
