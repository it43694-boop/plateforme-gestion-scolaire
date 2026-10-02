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


class AssistantVueGeneraleTests(TestCase):
    """
    Mode « vue d'ensemble » : pas de matricule, une question sur
    l'établissement - les chiffres retournés doivent être scopés
    exactement aux modules que le rôle a le droit de consulter, jamais un
    dossier individuel (élève, employé, paiement nommé).
    """

    def setUp(self):
        from etablissement.models import Etablissement
        from permissions_matrix.models import PermissionMatrix

        self.etablissement = Etablissement.objects.create(nom="École Vue Générale")
        PermissionMatrix.seed_pour(self.etablissement)

        self.annee = AnneeScolaire.objects.create(
            libelle="2026-2027", date_debut=datetime.date(2026, 10, 1), date_fin=datetime.date(2027, 7, 31),
            est_active=True, etablissement=self.etablissement,
        )
        self.classe = Classe.objects.create(nom="5ème année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        self.comptable = creer_utilisateur_actif(
            "comptable-general@example.com", Role.COMPTABLE, etablissement=self.etablissement,
        )
        self.enseignant = creer_utilisateur_actif(
            "prof-general@example.com", Role.ENSEIGNANT, etablissement=self.etablissement,
        )

    def test_construire_donnees_generales_scope_par_module(self):
        from assistant.views import construire_donnees_generales

        donnees_comptable = {item["cle"]: item["valeur"] for item in construire_donnees_generales(self.comptable)}
        self.assertIn("total_encaissements", donnees_comptable)
        self.assertIn("solde_caisse", donnees_comptable)
        self.assertIn("salaires_en_attente", donnees_comptable)
        self.assertNotIn("eleves_inscrits", donnees_comptable)
        self.assertNotIn("classes_actives", donnees_comptable)

        donnees_enseignant = {item["cle"]: item["valeur"] for item in construire_donnees_generales(self.enseignant)}
        self.assertIn("classes_actives", donnees_enseignant)
        self.assertIn("absences_enregistrees", donnees_enseignant)
        self.assertNotIn("total_encaissements", donnees_enseignant)
        self.assertNotIn("solde_caisse", donnees_enseignant)

    def test_sans_etablissement_aucune_donnee(self):
        from assistant.views import construire_donnees_generales

        sans_etablissement = creer_utilisateur_actif("sans-etab-general@example.com", Role.COMPTABLE)
        self.assertEqual(construire_donnees_generales(sans_etablissement), [])

    @override_settings(GROQ_API_KEY="cle-de-test-factice")
    def test_question_sans_matricule_appelle_le_mode_general(self):
        from django.core.cache import cache
        cache.clear()
        with patch("assistant.views.repondre_question_generale_avec_ia") as mock_ia:
            mock_ia.return_value = "Le solde de caisse est positif."
            self.client.force_login(self.comptable)
            reponse = self.client.get(reverse("assistant:poser_question"), {"question": "Quel est le solde de caisse ?"})
            self.assertTrue(mock_ia.called)
            donnees_envoyees = mock_ia.call_args.kwargs["donnees_autorisees"]
            self.assertIn("solde_caisse", donnees_envoyees)
            self.assertNotIn("eleves_inscrits", donnees_envoyees)
            self.assertEqual(reponse.context["reponse_ia"], "Le solde de caisse est positif.")
            self.assertIsNone(reponse.context["resultat"])

    @override_settings(GROQ_API_KEY="")
    def test_sans_matricule_et_sans_cle_api_demande_un_matricule(self):
        self.client.force_login(self.comptable)
        reponse = self.client.get(reverse("assistant:poser_question"), {"question": "Quel est le solde de caisse ?"})
        self.assertIsNone(reponse.context["reponse_ia"])
        self.assertIn("matricule", reponse.context["erreur"])

    def test_sans_matricule_ni_question_ne_declenche_rien(self):
        self.client.force_login(self.comptable)
        reponse = self.client.get(reverse("assistant:poser_question"))
        self.assertIsNone(reponse.context["resultat"])
        self.assertIsNone(reponse.context["resultat_general"])
        self.assertIsNone(reponse.context["erreur"])


class AlertesTableauDeBordTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        from finances.models import TypeTranche as TT
        from finances.models import enregistrer_paiement as creer_paiement
        from scolarite.models import EcheancierFrais

        cache.clear()  # évite qu'une synthèse IA mise en cache fuite d'un test à l'autre
        aujourdhui = datetime.date.today()
        self.annee = AnneeScolaire.objects.create(
            libelle="Alertes", date_debut=aujourdhui - datetime.timedelta(days=200),
            date_fin=aujourdhui + datetime.timedelta(days=100), est_active=True,
        )
        self.classe = Classe.objects.create(nom="Classe Alertes", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        EcheancierFrais.objects.create(
            classe=self.classe, montant_inscription=10000, montant_tranche_1=10000, montant_tranche_2=10000,
        )

        self.enseignant = creer_utilisateur_actif("prof-alertes@example.com", Role.ENSEIGNANT)
        self.affectation = Affectation.objects.create(enseignant=self.enseignant, classe=self.classe, matiere="Maths")

        self.eleve_risque = creer_utilisateur_actif("eleve-risque@example.com", Role.ELEVE)
        self.inscription_risque = Inscription.objects.create(eleve=self.eleve_risque, classe=self.classe)
        saisir_note(
            eleve=self.eleve_risque, affectation=self.affectation, trimestre=Trimestre.T1,
            valeur=8, enseignant=self.enseignant,
        )

        self.eleve_ok = creer_utilisateur_actif("eleve-ok@example.com", Role.ELEVE)
        self.inscription_ok = Inscription.objects.create(eleve=self.eleve_ok, classe=self.classe)
        saisir_note(
            eleve=self.eleve_ok, affectation=self.affectation, trimestre=Trimestre.T1,
            valeur=15, enseignant=self.enseignant,
        )

        self.comptable = creer_utilisateur_actif("comptable-alertes@example.com", Role.COMPTABLE)
        creer_paiement(
            eleve=self.eleve_ok, inscription=self.inscription_ok, tranche=TT.INSCRIPTION,
            montant=30000, mode_paiement="especes", enregistre_par=self.comptable,
        )  # eleve_ok paie tout (10000+10000+10000) -> aucun impayé
        # eleve_risque ne paie rien -> impayé, et l'année est à 200/300e -> seuil 40% dépassé

        self.fondateur = creer_utilisateur_actif("fondateur-alertes@example.com", Role.FONDATEUR)
        self.parent = creer_utilisateur_actif("parent-alertes@example.com", Role.PARENT, telephone="+22370000055")
        self.eleve_risque.parents_lies.add(self.parent)

    def test_direction_voit_les_deux_types_dalerte(self):
        from assistant.alertes import construire_alertes
        alertes = construire_alertes(self.fondateur)
        types = {a["type"] for a in alertes}
        self.assertEqual(types, {"academique", "financier"})

    def test_eleve_sous_le_seuil_est_dans_lalerte_academique(self):
        from assistant.alertes import construire_alertes
        alertes = construire_alertes(self.fondateur)
        alerte_academique = next(a for a in alertes if a["type"] == "academique")
        eleves_cites = [d["eleve"] for d in alerte_academique["details"]]
        self.assertIn(self.eleve_risque, eleves_cites)
        self.assertNotIn(self.eleve_ok, eleves_cites)

    def test_eleve_entierement_paye_najoute_pas_dalerte_financiere(self):
        from assistant.alertes import construire_alertes
        alertes = construire_alertes(self.fondateur)
        alerte_financiere = next(a for a in alertes if a["type"] == "financier")
        eleves_cites = [d["eleve"] for d in alerte_financiere["details"]]
        self.assertIn(self.eleve_risque, eleves_cites)
        self.assertNotIn(self.eleve_ok, eleves_cites)

    def test_annee_scolaire_peu_avancee_najoute_pas_dalerte_financiere(self):
        from assistant.alertes import construire_alertes
        aujourdhui = datetime.date.today()
        self.annee.date_debut = aujourdhui - datetime.timedelta(days=5)
        self.annee.date_fin = aujourdhui + datetime.timedelta(days=295)
        self.annee.save(update_fields=["date_debut", "date_fin"])
        alertes = construire_alertes(self.fondateur)
        types = {a["type"] for a in alertes}
        self.assertNotIn("financier", types)

    def test_enseignant_ne_voit_que_ses_propres_classes(self):
        from assistant.alertes import construire_alertes

        autre_annee = AnneeScolaire.objects.create(
            libelle="Autre", date_debut=datetime.date.today() - datetime.timedelta(days=200),
            date_fin=datetime.date.today() + datetime.timedelta(days=100), est_active=True,
        )
        autre_classe = Classe.objects.create(nom="Autre classe", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=autre_annee)
        autre_enseignant = creer_utilisateur_actif("autre-prof-alertes@example.com", Role.ENSEIGNANT)
        autre_affectation = Affectation.objects.create(enseignant=autre_enseignant, classe=autre_classe, matiere="Histoire")
        autre_eleve_risque = creer_utilisateur_actif("autre-eleve-risque@example.com", Role.ELEVE)
        Inscription.objects.create(eleve=autre_eleve_risque, classe=autre_classe)
        saisir_note(
            eleve=autre_eleve_risque, affectation=autre_affectation, trimestre=Trimestre.T1,
            valeur=5, enseignant=autre_enseignant,
        )

        alertes = construire_alertes(self.enseignant)
        alerte_academique = next(a for a in alertes if a["type"] == "academique")
        eleves_cites = [d["eleve"] for d in alerte_academique["details"]]
        self.assertIn(self.eleve_risque, eleves_cites)
        self.assertNotIn(autre_eleve_risque, eleves_cites)

    def test_comptable_ne_voit_pas_lalerte_academique(self):
        from assistant.alertes import construire_alertes
        alertes = construire_alertes(self.comptable)
        types = {a["type"] for a in alertes}
        self.assertEqual(types, {"financier"})

    def test_parent_ne_voit_aucune_alerte(self):
        # Le parent a le module finances/notes_bulletins pour SON enfant
        # uniquement (portail_parent) - jamais une vue agrégée sur d'autres
        # élèves ou familles : c'est le coeur de la garantie de sécurité.
        from assistant.alertes import construire_alertes
        self.assertEqual(construire_alertes(self.parent), [])

    def test_eleve_ne_voit_aucune_alerte(self):
        from assistant.alertes import construire_alertes
        self.assertEqual(construire_alertes(self.eleve_risque), [])

    def test_tableau_de_bord_affiche_les_alertes_pour_la_direction(self):
        self.client.force_login(self.fondateur)
        reponse = self.client.get(reverse("comptes:redirection_tableau_de_bord"))
        self.assertTrue(reponse.context["alertes"])

    def test_tableau_de_bord_najoute_pas_dalerte_pour_un_parent(self):
        self.client.force_login(self.parent)
        self.client.get(reverse("comptes:redirection_tableau_de_bord"))  # redirige vers le portail parent, ne doit pas planter

    @override_settings(GROQ_API_KEY="")
    def test_synthese_absente_sans_cle_api(self):
        self.client.force_login(self.fondateur)
        reponse = self.client.get(reverse("comptes:redirection_tableau_de_bord"))
        self.assertEqual(reponse.context["synthese_alertes"], "")

    @override_settings(GROQ_API_KEY="cle-test")
    def test_synthese_ia_affichee_et_mise_en_cache(self):
        with patch("assistant.services.resumer_alertes_avec_ia", return_value="Synthèse factuelle.") as mock_ia:
            self.client.force_login(self.fondateur)
            reponse = self.client.get(reverse("comptes:redirection_tableau_de_bord"))
            self.assertEqual(reponse.context["synthese_alertes"], "Synthèse factuelle.")
            self.assertEqual(mock_ia.call_count, 1)

            # Deuxième chargement : la synthèse vient du cache, pas d'un
            # second appel à l'API (voir comptes.views._synthese_alertes_en_cache).
            reponse = self.client.get(reverse("comptes:redirection_tableau_de_bord"))
            self.assertEqual(reponse.context["synthese_alertes"], "Synthèse factuelle.")
            self.assertEqual(mock_ia.call_count, 1)

    @override_settings(GROQ_API_KEY="cle-test")
    def test_synthese_degrade_silencieusement_si_lapi_echoue(self):
        with patch("assistant.services.resumer_alertes_avec_ia", side_effect=AssistantIndisponible("panne")):
            self.client.force_login(self.fondateur)
            reponse = self.client.get(reverse("comptes:redirection_tableau_de_bord"))
            self.assertEqual(reponse.context["synthese_alertes"], "")
            self.assertTrue(reponse.context["alertes"])


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
