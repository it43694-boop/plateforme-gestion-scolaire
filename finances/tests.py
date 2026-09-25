import datetime

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from comptes.models import Utilisateur
from comptes.roles import Role, StatutCompte
from finances.models import (
    MouvementCaisse, Paiement, Salaire, TypeTranche,
    corriger_paiement, enregistrer_paiement, marquer_salaire_paye,
    supprimer_paiement, supprimer_salaire,
)
from scolarite.models import AnneeScolaire, Classe, Cycle, EcheancierFrais, Inscription


def creer_utilisateur_actif(email, role, **kwargs):
    utilisateur = Utilisateur(email=email, prenom="Test", nom="Utilisateur", role=role, **kwargs)
    utilisateur.set_password("MotDePasse#2026")
    utilisateur.statut = StatutCompte.ACTIF
    utilisateur.is_active = True
    utilisateur.full_clean(exclude=["password"])
    utilisateur.save()
    return utilisateur


def creer_annee_et_classe():
    annee = AnneeScolaire.objects.create(
        libelle="2026-2027", date_debut=datetime.date(2026, 10, 1),
        date_fin=datetime.date(2027, 7, 31), est_active=True,
    )
    classe = Classe.objects.create(nom="5ème année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=annee)
    return annee, classe


class CascadePaiementCaisseTests(TestCase):
    def setUp(self):
        self.annee, self.classe = creer_annee_et_classe()
        self.eleve = creer_utilisateur_actif("eleve-fin@example.com", Role.ELEVE)
        self.inscription = Inscription.objects.create(eleve=self.eleve, classe=self.classe)
        self.comptable = creer_utilisateur_actif("comptable-fin@example.com", Role.COMPTABLE)

    def test_paiement_cree_automatiquement_une_ligne_de_caisse(self):
        paiement = enregistrer_paiement(
            eleve=self.eleve, inscription=self.inscription, tranche=TypeTranche.TRANCHE_1,
            montant=15000, mode_paiement="especes", enregistre_par=self.comptable,
        )
        mouvement = paiement.mouvement_caisse
        self.assertEqual(mouvement.type_mouvement, MouvementCaisse.TypeMouvement.ENTREE)
        self.assertEqual(mouvement.montant, 15000)
        self.assertFalse(mouvement.annule)

    def test_reference_paiement_et_caisse_uniques_et_generees(self):
        p1 = enregistrer_paiement(
            eleve=self.eleve, inscription=self.inscription, tranche=TypeTranche.INSCRIPTION,
            montant=20000, mode_paiement="especes", enregistre_par=self.comptable,
        )
        self.assertTrue(p1.reference.startswith("REC-"))
        self.assertTrue(p1.mouvement_caisse.reference.startswith("CAI-"))

    def test_references_strictement_sequentielles_sans_trou(self):
        from django.utils import timezone
        annee = timezone.now().year
        p1 = enregistrer_paiement(
            eleve=self.eleve, inscription=self.inscription, tranche=TypeTranche.INSCRIPTION,
            montant=5000, mode_paiement="especes", enregistre_par=self.comptable,
        )
        p2 = enregistrer_paiement(
            eleve=self.eleve, inscription=self.inscription, tranche=TypeTranche.TRANCHE_1,
            montant=5000, mode_paiement="especes", enregistre_par=self.comptable,
        )
        self.assertEqual(p1.reference, f"REC-{annee}-000001")
        self.assertEqual(p2.reference, f"REC-{annee}-000002")
        # La caisse a sa propre séquence, indépendante de celle des reçus.
        self.assertEqual(p1.mouvement_caisse.reference, f"CAI-{annee}-000001")
        self.assertEqual(p2.mouvement_caisse.reference, f"CAI-{annee}-000002")

    def test_sequences_independantes_par_etablissement(self):
        from etablissement.models import Etablissement
        autre_etablissement = Etablissement.objects.create(nom="Autre école")
        autre_annee = AnneeScolaire.objects.create(
            etablissement=autre_etablissement, libelle="2026-2027",
            date_debut=datetime.date(2026, 10, 1), date_fin=datetime.date(2027, 7, 31),
        )
        autre_classe = Classe.objects.create(nom="6ème A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=autre_annee)
        autre_eleve = creer_utilisateur_actif(
            "eleve-autre-ecole@example.com", Role.ELEVE, etablissement=autre_etablissement,
        )
        autre_inscription = Inscription.objects.create(eleve=autre_eleve, classe=autre_classe)

        p1 = enregistrer_paiement(
            eleve=self.eleve, inscription=self.inscription, tranche=TypeTranche.INSCRIPTION,
            montant=5000, mode_paiement="especes", enregistre_par=self.comptable,
        )
        p2_autre_ecole = enregistrer_paiement(
            eleve=autre_eleve, inscription=autre_inscription, tranche=TypeTranche.INSCRIPTION,
            montant=5000, mode_paiement="especes", enregistre_par=self.comptable,
        )
        # Chaque établissement démarre sa propre séquence à 1, même le même jour.
        self.assertTrue(p1.reference.endswith("-000001"))
        self.assertTrue(p2_autre_ecole.reference.endswith("-000001"))

    def test_correction_paiement_repercutee_sur_la_caisse(self):
        paiement = enregistrer_paiement(
            eleve=self.eleve, inscription=self.inscription, tranche=TypeTranche.TRANCHE_1,
            montant=15000, mode_paiement="especes", enregistre_par=self.comptable,
        )
        corriger_paiement(paiement=paiement, montant=18000, mode_paiement="mobile_money", acteur=self.comptable)
        paiement.refresh_from_db()
        self.assertEqual(paiement.montant, 18000)
        self.assertEqual(paiement.mouvement_caisse.montant, 18000)

    def test_suppression_paiement_reservee_a_la_direction(self):
        paiement = enregistrer_paiement(
            eleve=self.eleve, inscription=self.inscription, tranche=TypeTranche.TRANCHE_2,
            montant=15000, mode_paiement="especes", enregistre_par=self.comptable,
        )
        with self.assertRaises(ValidationError):
            supprimer_paiement(paiement=paiement, acteur=self.comptable)

    def test_suppression_par_direction_annule_paiement_et_caisse_sans_effacer(self):
        fondateur = creer_utilisateur_actif("fondateur-fin@example.com", Role.FONDATEUR)
        paiement = enregistrer_paiement(
            eleve=self.eleve, inscription=self.inscription, tranche=TypeTranche.TRANCHE_2,
            montant=15000, mode_paiement="especes", enregistre_par=self.comptable,
        )
        reference_caisse = paiement.mouvement_caisse.reference
        supprimer_paiement(paiement=paiement, acteur=fondateur)

        paiement.refresh_from_db()
        self.assertTrue(paiement.est_supprime)
        self.assertEqual(paiement.supprime_par, fondateur)

        # La ligne de Caisse existe toujours (annulée, jamais effacée).
        mouvement = MouvementCaisse.objects.get(reference=reference_caisse)
        self.assertTrue(mouvement.annule)
        self.assertEqual(mouvement.annule_par, fondateur)


class CascadeSalaireCaisseTests(TestCase):
    def setUp(self):
        self.comptable = creer_utilisateur_actif("comptable-sal@example.com", Role.COMPTABLE)
        self.enseignant = creer_utilisateur_actif("prof-sal@example.com", Role.ENSEIGNANT)

    def test_salaire_ne_cree_pas_de_caisse_avant_paiement(self):
        salaire = Salaire.objects.create(
            employe=self.enseignant, periode="2026-10", montant=150000, enregistre_par=self.comptable,
        )
        self.assertFalse(hasattr(salaire, "mouvement_caisse"))

    def test_marquer_paye_cree_la_depense_en_caisse(self):
        salaire = Salaire.objects.create(
            employe=self.enseignant, periode="2026-11", montant=150000, enregistre_par=self.comptable,
        )
        marquer_salaire_paye(salaire=salaire, paye_par=self.comptable)
        salaire.refresh_from_db()
        self.assertEqual(salaire.statut, Salaire.Statut.PAYE)
        self.assertIsNotNone(salaire.reference)
        mouvement = salaire.mouvement_caisse
        self.assertEqual(mouvement.type_mouvement, MouvementCaisse.TypeMouvement.SORTIE)
        self.assertEqual(mouvement.montant, 150000)

    def test_impossible_de_payer_deux_fois_le_meme_salaire(self):
        salaire = Salaire.objects.create(
            employe=self.enseignant, periode="2026-12", montant=150000, enregistre_par=self.comptable,
        )
        marquer_salaire_paye(salaire=salaire, paye_par=self.comptable)
        with self.assertRaises(ValidationError):
            marquer_salaire_paye(salaire=salaire, paye_par=self.comptable)

    def test_anti_doublon_salaire_meme_employe_meme_periode(self):
        Salaire.objects.create(
            employe=self.enseignant, periode="2027-01", montant=150000, enregistre_par=self.comptable,
        )
        with self.assertRaises(Exception):
            Salaire.objects.create(
                employe=self.enseignant, periode="2027-01", montant=160000, enregistre_par=self.comptable,
            )

    def test_suppression_salaire_reservee_a_la_direction(self):
        salaire = Salaire.objects.create(
            employe=self.enseignant, periode="2027-02", montant=150000, enregistre_par=self.comptable,
        )
        with self.assertRaises(ValidationError):
            supprimer_salaire(salaire=salaire, acteur=self.comptable)

    def test_suppression_salaire_paye_annule_la_caisse(self):
        fondateur = creer_utilisateur_actif("fondateur-sal@example.com", Role.FONDATEUR)
        salaire = Salaire.objects.create(
            employe=self.enseignant, periode="2027-03", montant=150000, enregistre_par=self.comptable,
        )
        marquer_salaire_paye(salaire=salaire, paye_par=self.comptable)
        reference_caisse = salaire.mouvement_caisse.reference
        supprimer_salaire(salaire=salaire, acteur=fondateur)

        salaire.refresh_from_db()
        self.assertTrue(salaire.est_supprime)
        mouvement = MouvementCaisse.objects.get(reference=reference_caisse)
        self.assertTrue(mouvement.annule)


class RegistreCaisseSoldeTests(TestCase):
    def test_solde_caisse_entrees_moins_sorties_hors_annules(self):
        annee, classe = creer_annee_et_classe()
        eleve = creer_utilisateur_actif("eleve-solde@example.com", Role.ELEVE)
        inscription = Inscription.objects.create(eleve=eleve, classe=classe)
        comptable = creer_utilisateur_actif("comptable-solde@example.com", Role.COMPTABLE)
        enseignant = creer_utilisateur_actif("prof-solde@example.com", Role.ENSEIGNANT)

        enregistrer_paiement(
            eleve=eleve, inscription=inscription, tranche=TypeTranche.INSCRIPTION,
            montant=30000, mode_paiement="especes", enregistre_par=comptable,
        )
        salaire = Salaire.objects.create(employe=enseignant, periode="2026-10", montant=10000, enregistre_par=comptable)
        marquer_salaire_paye(salaire=salaire, paye_par=comptable)

        self.client.force_login(comptable)
        reponse = self.client.get(reverse("finances:registre_caisse"))
        self.assertEqual(reponse.context["solde"], 20000)


class VuesFinancesAccesTests(TestCase):
    def setUp(self):
        self.annee, self.classe = creer_annee_et_classe()
        self.eleve = creer_utilisateur_actif("eleve-vue@example.com", Role.ELEVE)
        Inscription.objects.create(eleve=self.eleve, classe=self.classe)
        self.comptable = creer_utilisateur_actif("comptable-vue@example.com", Role.COMPTABLE)
        self.secretaire = creer_utilisateur_actif("secretaire-vue@example.com", Role.SECRETAIRE)

    def test_comptable_peut_enregistrer_un_paiement_via_la_vue(self):
        self.client.force_login(self.comptable)
        reponse = self.client.post(reverse("finances:enregistrer_paiement"), {
            "matricule_eleve": self.eleve.matricule, "tranche": TypeTranche.TRANCHE_1,
            "montant": 15000, "mode_paiement": "especes",
        })
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(Paiement.objects.filter(eleve=self.eleve).count(), 1)

    def test_secretaire_na_pas_acces_aux_finances_par_defaut(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.get(reverse("finances:liste_paiements"))
        self.assertEqual(reponse.status_code, 403)

    def test_suppression_refusee_en_http_pour_non_direction(self):
        paiement = enregistrer_paiement(
            eleve=self.eleve, inscription=Inscription.objects.get(eleve=self.eleve),
            tranche=TypeTranche.TRANCHE_1, montant=15000, mode_paiement="especes",
            enregistre_par=self.comptable,
        )
        self.client.force_login(self.comptable)
        reponse = self.client.post(reverse("finances:supprimer_paiement", args=[paiement.id]))
        self.assertEqual(reponse.status_code, 403)

    def test_liste_paiements_paginee(self):
        inscription = Inscription.objects.get(eleve=self.eleve)
        for _ in range(30):
            enregistrer_paiement(
                eleve=self.eleve, inscription=inscription, tranche=TypeTranche.TRANCHE_1,
                montant=1000, mode_paiement="especes", enregistre_par=self.comptable,
            )
        self.client.force_login(self.comptable)
        reponse = self.client.get(reverse("finances:liste_paiements"))
        self.assertEqual(len(reponse.context["paiements"]), 25)
        self.assertTrue(reponse.context["page_obj"].has_next())

    def test_apercu_json_renvoie_le_nom_de_leleve(self):
        self.client.force_login(self.comptable)
        reponse = self.client.get(reverse("finances:rechercher_eleve_json"), {"matricule": self.eleve.matricule})
        self.assertEqual(reponse.json(), {"trouve": True, "nom_complet": self.eleve.nom_complet})

    def test_apercu_json_matricule_inconnu(self):
        self.client.force_login(self.comptable)
        reponse = self.client.get(reverse("finances:rechercher_eleve_json"), {"matricule": "00000000"})
        self.assertEqual(reponse.json(), {"trouve": False})

    def test_page_enregistrement_affiche_le_nom_via_parametre_get(self):
        self.client.force_login(self.comptable)
        reponse = self.client.get(reverse("finances:enregistrer_paiement"), {"matricule": self.eleve.matricule})
        self.assertContains(reponse, self.eleve.nom_complet)

    def test_apercu_json_employe_renvoie_le_nom(self):
        enseignant = creer_utilisateur_actif("prof-apercu@example.com", Role.ENSEIGNANT)
        self.client.force_login(self.comptable)
        reponse = self.client.get(reverse("finances:rechercher_employe_json"), {"email": enseignant.email})
        self.assertEqual(reponse.json(), {
            "trouve": True, "nom_complet": enseignant.nom_complet, "role": enseignant.get_role_display(),
        })

    def test_page_saisie_salaire_affiche_le_nom_via_parametre_get(self):
        enseignant = creer_utilisateur_actif("prof-apercu2@example.com", Role.ENSEIGNANT)
        self.client.force_login(self.comptable)
        reponse = self.client.get(reverse("finances:saisir_salaire"), {"email": enseignant.email})
        self.assertContains(reponse, enseignant.nom_complet)

    def test_recu_pdf_genere_un_vrai_pdf(self):
        inscription = Inscription.objects.get(eleve=self.eleve)
        paiement = enregistrer_paiement(
            eleve=self.eleve, inscription=inscription, tranche=TypeTranche.TRANCHE_1,
            montant=15000, mode_paiement="especes", enregistre_par=self.comptable,
        )
        self.client.force_login(self.comptable)
        reponse = self.client.get(reverse("finances:exporter_recu_paiement_pdf", args=[paiement.id]))
        self.assertEqual(reponse["Content-Type"], "application/pdf")
        self.assertTrue(reponse.content.startswith(b"%PDF"))

    def test_recu_pdf_refuse_pour_paiement_dune_autre_ecole(self):
        from etablissement.models import Etablissement
        from permissions_matrix.models import PermissionMatrix
        autre_ecole = Etablissement.objects.create(nom="Autre école reçu")
        PermissionMatrix.seed_pour(autre_ecole)
        autre_comptable = creer_utilisateur_actif("comptable-autre-recu@example.com", Role.COMPTABLE, etablissement=autre_ecole)
        inscription = Inscription.objects.get(eleve=self.eleve)
        paiement = enregistrer_paiement(
            eleve=self.eleve, inscription=inscription, tranche=TypeTranche.TRANCHE_1,
            montant=15000, mode_paiement="especes", enregistre_par=self.comptable,
        )
        self.client.force_login(autre_comptable)
        reponse = self.client.get(reverse("finances:exporter_recu_paiement_pdf", args=[paiement.id]))
        self.assertEqual(reponse.status_code, 404)


class IsolationInterEtablissementsTests(TestCase):
    """
    La preuve la plus importante de tout le chantier multi-établissement :
    deux écoles réelles, deux comptables, et la certitude qu'aucun des deux
    ne voit jamais un centime de l'autre école.
    """

    def setUp(self):
        from etablissement.models import Etablissement
        from permissions_matrix.models import PermissionMatrix

        self.ecole_a = Etablissement.objects.create(nom="École A")
        self.ecole_b = Etablissement.objects.create(nom="École B")
        PermissionMatrix.seed_pour(self.ecole_a)
        PermissionMatrix.seed_pour(self.ecole_b)

        self.annee_a, self.classe_a = creer_annee_et_classe()
        self.classe_a.annee_scolaire.etablissement = self.ecole_a
        self.classe_a.annee_scolaire.save()

        self.annee_b, self.classe_b = creer_annee_et_classe()
        self.classe_b.annee_scolaire.etablissement = self.ecole_b
        self.classe_b.annee_scolaire.save()

        self.eleve_a = creer_utilisateur_actif("eleve-a@example.com", Role.ELEVE, etablissement=self.ecole_a)
        self.inscription_a = Inscription.objects.create(eleve=self.eleve_a, classe=self.classe_a)
        self.comptable_a = creer_utilisateur_actif("comptable-a@example.com", Role.COMPTABLE, etablissement=self.ecole_a)

        self.eleve_b = creer_utilisateur_actif("eleve-b@example.com", Role.ELEVE, etablissement=self.ecole_b)
        self.inscription_b = Inscription.objects.create(eleve=self.eleve_b, classe=self.classe_b)
        self.comptable_b = creer_utilisateur_actif("comptable-b@example.com", Role.COMPTABLE, etablissement=self.ecole_b)

        self.paiement_a = enregistrer_paiement(
            eleve=self.eleve_a, inscription=self.inscription_a, tranche=TypeTranche.TRANCHE_1,
            montant=15000, mode_paiement="especes", enregistre_par=self.comptable_a,
        )
        self.paiement_b = enregistrer_paiement(
            eleve=self.eleve_b, inscription=self.inscription_b, tranche=TypeTranche.TRANCHE_1,
            montant=25000, mode_paiement="especes", enregistre_par=self.comptable_b,
        )

    def test_comptable_ne_voit_que_les_paiements_de_son_ecole(self):
        # Comparaison par identifiant, pas par référence : avec une
        # numérotation séquentielle PAR établissement, école A et école B
        # ont chacune leur propre reçu n°1, avec la même référence textuelle
        # - une coïncidence attendue, pas une fuite entre établissements.
        self.client.force_login(self.comptable_a)
        reponse = self.client.get(reverse("finances:liste_paiements"))
        identifiants = [p.id for p in reponse.context["paiements"]]
        self.assertIn(self.paiement_a.id, identifiants)
        self.assertNotIn(self.paiement_b.id, identifiants)

    def test_comptable_ne_peut_pas_enregistrer_un_paiement_pour_un_eleve_dune_autre_ecole(self):
        self.client.force_login(self.comptable_a)
        reponse = self.client.post(reverse("finances:enregistrer_paiement"), {
            "matricule_eleve": self.eleve_b.matricule, "tranche": TypeTranche.TRANCHE_1,
            "montant": 15000, "mode_paiement": "especes",
        })
        self.assertContains(reponse, "Aucun élève trouvé avec ce matricule")

    def test_comptable_ne_peut_pas_corriger_un_paiement_dune_autre_ecole(self):
        self.client.force_login(self.comptable_a)
        reponse = self.client.get(reverse("finances:corriger_paiement", args=[self.paiement_b.id]))
        self.assertEqual(reponse.status_code, 404)

    def test_caisse_isolee_par_etablissement(self):
        self.client.force_login(self.comptable_a)
        reponse = self.client.get(reverse("finances:registre_caisse"))
        self.assertEqual(reponse.context["solde"], 15000)  # pas 15000 + 25000

    def test_salaire_isole_par_etablissement(self):
        enseignant_a = creer_utilisateur_actif("prof-a@example.com", Role.ENSEIGNANT, etablissement=self.ecole_a)
        enseignant_b = creer_utilisateur_actif("prof-b@example.com", Role.ENSEIGNANT, etablissement=self.ecole_b)
        Salaire.objects.create(employe=enseignant_a, periode="2026-10", montant=100000, enregistre_par=self.comptable_a)
        Salaire.objects.create(employe=enseignant_b, periode="2026-10", montant=200000, enregistre_par=self.comptable_b)

        self.client.force_login(self.comptable_a)
        reponse = self.client.get(reverse("finances:liste_salaires"))
        employes = [s.employe.email for s in reponse.context["salaires"]]
        self.assertIn("prof-a@example.com", employes)
        self.assertNotIn("prof-b@example.com", employes)

    def test_comptable_ne_peut_pas_saisir_salaire_pour_employe_dune_autre_ecole(self):
        enseignant_b = creer_utilisateur_actif("prof-b2@example.com", Role.ENSEIGNANT, etablissement=self.ecole_b)
        self.client.force_login(self.comptable_a)
        reponse = self.client.post(reverse("finances:saisir_salaire"), {
            "email_employe": enseignant_b.email, "periode": "2026-11", "montant": 100000,
        })
        self.assertContains(reponse, "Aucun compte trouvé avec cet email")


class SuiviPaiementsTests(TestCase):
    def setUp(self):
        self.annee, self.classe = creer_annee_et_classe()
        self.echeancier = EcheancierFrais.objects.create(
            classe=self.classe, montant_inscription=10000, montant_tranche_1=10000, montant_tranche_2=10000,
        )
        self.comptable = creer_utilisateur_actif("comptable-suivi@example.com", Role.COMPTABLE)

        self.eleve_paye = creer_utilisateur_actif("eleve-paye@example.com", Role.ELEVE)
        inscription_paye = Inscription.objects.create(eleve=self.eleve_paye, classe=self.classe)
        enregistrer_paiement(
            eleve=self.eleve_paye, inscription=inscription_paye, tranche=TypeTranche.INSCRIPTION,
            montant=10000, mode_paiement="especes", enregistre_par=self.comptable,
        )
        enregistrer_paiement(
            eleve=self.eleve_paye, inscription=inscription_paye, tranche=TypeTranche.TRANCHE_1,
            montant=10000, mode_paiement="especes", enregistre_par=self.comptable,
        )
        enregistrer_paiement(
            eleve=self.eleve_paye, inscription=inscription_paye, tranche=TypeTranche.TRANCHE_2,
            montant=10000, mode_paiement="especes", enregistre_par=self.comptable,
        )

        self.eleve_partiel = creer_utilisateur_actif("eleve-partiel@example.com", Role.ELEVE)
        inscription_partiel = Inscription.objects.create(eleve=self.eleve_partiel, classe=self.classe)
        enregistrer_paiement(
            eleve=self.eleve_partiel, inscription=inscription_partiel, tranche=TypeTranche.INSCRIPTION,
            montant=10000, mode_paiement="especes", enregistre_par=self.comptable,
        )

        self.eleve_impaye = creer_utilisateur_actif("eleve-impaye@example.com", Role.ELEVE)
        Inscription.objects.create(eleve=self.eleve_impaye, classe=self.classe)

    def test_statuts_calcules_correctement(self):
        self.client.force_login(self.comptable)
        reponse = self.client.get(reverse("finances:suivi_paiements"))
        par_eleve = {l["inscription"].eleve.email: l for l in reponse.context["lignes"]}
        self.assertEqual(par_eleve["eleve-paye@example.com"]["statut"], "paye")
        self.assertEqual(par_eleve["eleve-paye@example.com"]["solde"], 0)
        self.assertEqual(par_eleve["eleve-partiel@example.com"]["statut"], "partiel")
        self.assertEqual(par_eleve["eleve-partiel@example.com"]["solde"], 20000)
        self.assertEqual(par_eleve["eleve-impaye@example.com"]["statut"], "impaye")
        self.assertEqual(par_eleve["eleve-impaye@example.com"]["solde"], 30000)

    def test_filtre_par_statut_impaye(self):
        self.client.force_login(self.comptable)
        reponse = self.client.get(reverse("finances:suivi_paiements"), {"statut": "impaye"})
        emails = [l["inscription"].eleve.email for l in reponse.context["lignes"]]
        self.assertEqual(emails, ["eleve-impaye@example.com"])

    def test_paiement_supprime_nest_pas_compte(self):
        direction = creer_utilisateur_actif("direction-suivi@example.com", Role.FONDATEUR)
        eleve = creer_utilisateur_actif("eleve-supprime@example.com", Role.ELEVE)
        inscription = Inscription.objects.create(eleve=eleve, classe=self.classe)
        paiement = enregistrer_paiement(
            eleve=eleve, inscription=inscription, tranche=TypeTranche.INSCRIPTION,
            montant=10000, mode_paiement="especes", enregistre_par=self.comptable,
        )
        supprimer_paiement(paiement=paiement, acteur=direction)
        self.client.force_login(self.comptable)
        reponse = self.client.get(reverse("finances:suivi_paiements"))
        ligne = next(l for l in reponse.context["lignes"] if l["inscription"].eleve.email == "eleve-supprime@example.com")
        self.assertEqual(ligne["total_paye"], 0)
        self.assertEqual(ligne["statut"], "impaye")


class RelancerImpayesTests(TestCase):
    def setUp(self):
        from django.core.management import call_command
        self.call_command = call_command
        self.annee, self.classe = creer_annee_et_classe()
        self.echeancier = EcheancierFrais.objects.create(
            classe=self.classe, montant_inscription=10000, montant_tranche_1=10000, montant_tranche_2=10000,
        )
        self.comptable = creer_utilisateur_actif("comptable-relance@example.com", Role.COMPTABLE)

    def test_relance_creee_pour_eleve_avec_parent(self):
        from comptes.models import Notification
        eleve = creer_utilisateur_actif("eleve-relance-avec-parent@example.com", Role.ELEVE)
        parent = creer_utilisateur_actif(
            "parent-relance@example.com", Role.PARENT, telephone="70199901", profession="X",
        )
        eleve.parents_lies.add(parent)
        Inscription.objects.create(eleve=eleve, classe=self.classe)

        self.call_command("relancer_impayes")

        self.assertTrue(Notification.objects.filter(destinataire=parent).exists())
        self.assertFalse(Notification.objects.filter(destinataire=eleve).exists())

    def test_eleve_sans_parent_nenvoie_rien_a_ladresse_fantome(self):
        """Le bug corrigé : avant, la relance partait vers l'adresse
        auto-générée de l'élève quand aucun parent n'était lié. Elle ne doit
        plus jamais y aller."""
        from comptes.models import Notification
        eleve = creer_utilisateur_actif("eleve-relance-sans-parent@example.com", Role.ELEVE)
        Inscription.objects.create(eleve=eleve, classe=self.classe)

        self.call_command("relancer_impayes")

        self.assertFalse(Notification.objects.filter(destinataire=eleve).exists())
        self.assertEqual(Notification.objects.count(), 0)

    def test_eleve_a_jour_naucune_relance(self):
        from comptes.models import Notification
        eleve = creer_utilisateur_actif("eleve-relance-a-jour@example.com", Role.ELEVE)
        parent = creer_utilisateur_actif(
            "parent-relance-a-jour@example.com", Role.PARENT, telephone="70199902", profession="X",
        )
        eleve.parents_lies.add(parent)
        inscription = Inscription.objects.create(eleve=eleve, classe=self.classe)
        for tranche, montant in [(TypeTranche.INSCRIPTION, 10000), (TypeTranche.TRANCHE_1, 10000), (TypeTranche.TRANCHE_2, 10000)]:
            enregistrer_paiement(
                eleve=eleve, inscription=inscription, tranche=tranche,
                montant=montant, mode_paiement="especes", enregistre_par=self.comptable,
            )

        self.call_command("relancer_impayes")

        self.assertEqual(Notification.objects.count(), 0)

    def test_pas_de_double_relance_le_meme_jour(self):
        from comptes.models import Notification
        eleve = creer_utilisateur_actif("eleve-relance-double@example.com", Role.ELEVE)
        parent = creer_utilisateur_actif(
            "parent-relance-double@example.com", Role.PARENT, telephone="70199903", profession="X",
        )
        eleve.parents_lies.add(parent)
        Inscription.objects.create(eleve=eleve, classe=self.classe)

        self.call_command("relancer_impayes")
        self.call_command("relancer_impayes")

        self.assertEqual(Notification.objects.filter(destinataire=parent).count(), 1)
