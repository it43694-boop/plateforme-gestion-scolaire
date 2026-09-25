import datetime
import os
import tempfile

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from comptes.models import Utilisateur
from comptes.roles import Role, StatutCompte
from scolarite.models import (
    Affectation, AnneeScolaire, Classe, Cycle, EcheancierFrais, Inscription,
    classes_visibles_pour, dossier_complet, lier_parent_a_eleve,
)


def creer_utilisateur_actif(email, role, **kwargs):
    utilisateur = Utilisateur(email=email, prenom="Test", nom="Utilisateur", role=role, **kwargs)
    utilisateur.set_password("MotDePasse#2026")
    utilisateur.statut = StatutCompte.ACTIF
    utilisateur.is_active = True
    utilisateur.full_clean(exclude=["password"])
    utilisateur.save()
    return utilisateur


def creer_annee(libelle="2026-2027", active=True):
    return AnneeScolaire.objects.create(
        libelle=libelle,
        date_debut=datetime.date(2026, 10, 1),
        date_fin=datetime.date(2027, 7, 31),
        est_active=active,
    )


class AnneeScolaireTests(TestCase):
    def test_une_seule_annee_active_a_la_fois(self):
        annee_1 = creer_annee("2025-2026", active=True)
        annee_2 = creer_annee("2026-2027", active=True)
        annee_1.refresh_from_db()
        self.assertFalse(annee_1.est_active)
        self.assertTrue(annee_2.est_active)
        self.assertEqual(AnneeScolaire.active(None), annee_2)

    def test_date_fin_avant_date_debut_refusee(self):
        with self.assertRaises(ValidationError):
            AnneeScolaire.objects.create(
                libelle="Invalide", date_debut=datetime.date(2026, 10, 1),
                date_fin=datetime.date(2026, 1, 1),
            )


class ClasseEtFraisTests(TestCase):
    def setUp(self):
        self.annee = creer_annee()

    def test_classe_unique_par_nom_et_annee(self):
        Classe.objects.create(nom="6ème A", cycle=Cycle.DEUXIEME_CYCLE, annee_scolaire=self.annee)
        with self.assertRaises(Exception):
            Classe.objects.create(nom="6ème A", cycle=Cycle.DEUXIEME_CYCLE, annee_scolaire=self.annee)

    def test_frais_multiple_de_5000_obligatoire(self):
        classe = Classe.objects.create(nom="1ère année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        with self.assertRaises(ValidationError):
            EcheancierFrais.objects.create(
                classe=classe, montant_inscription=12345, montant_tranche_1=10000, montant_tranche_2=10000,
            )

    def test_frais_eleves_acceptes_sans_plafond(self):
        classe = Classe.objects.create(nom="1ère année B", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        frais = EcheancierFrais.objects.create(
            classe=classe, montant_inscription=100000, montant_tranche_1=50000, montant_tranche_2=50000,
        )
        self.assertEqual(frais.montant_inscription, 100000)

    def test_frais_valides_acceptes(self):
        classe = Classe.objects.create(nom="1ère année C", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        frais = EcheancierFrais.objects.create(
            classe=classe, montant_inscription=30000, montant_tranche_1=15000, montant_tranche_2=15000,
        )
        self.assertEqual(frais.total_annuel, 60000)

    def test_pas_de_montant_configurable_par_etablissement(self):
        from etablissement.models import Etablissement
        etablissement = Etablissement.objects.create(nom="École EUR", code_devise="EUR", pas_montant=100)
        annee = AnneeScolaire.objects.create(
            etablissement=etablissement, libelle="2026-2027",
            date_debut=datetime.date(2026, 10, 1), date_fin=datetime.date(2027, 7, 31),
        )
        classe_valide = Classe.objects.create(nom="CP", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=annee)
        classe_invalide = Classe.objects.create(nom="CE1", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=annee)

        # Multiple de 100 (le pas de CET établissement) mais pas de 5000 : accepté.
        frais = EcheancierFrais.objects.create(
            classe=classe_valide, montant_inscription=300, montant_tranche_1=200, montant_tranche_2=200,
        )
        self.assertEqual(frais.total_annuel, 700)

        # Pas multiple de 100 : refusé, avec le message qui porte la devise de l'établissement.
        with self.assertRaises(ValidationError) as cm:
            EcheancierFrais.objects.create(
                classe=classe_invalide, montant_inscription=250, montant_tranche_1=200, montant_tranche_2=200,
            )
        self.assertIn("EUR", str(cm.exception))


class CloisonnementCycleTests(TestCase):
    def setUp(self):
        self.annee = creer_annee()
        self.classe_1er = Classe.objects.create(nom="3ème année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        self.classe_2eme = Classe.objects.create(nom="8ème année A", cycle=Cycle.DEUXIEME_CYCLE, annee_scolaire=self.annee)

    def test_directeur_1er_cycle_ne_voit_que_son_cycle(self):
        directeur = creer_utilisateur_actif("dir1@example.com", Role.DIRECTEUR_1ER_CYCLE)
        visibles = classes_visibles_pour(directeur)
        self.assertIn(self.classe_1er, visibles)
        self.assertNotIn(self.classe_2eme, visibles)

    def test_directeur_2eme_cycle_ne_voit_que_son_cycle(self):
        directeur = creer_utilisateur_actif("dir2@example.com", Role.DIRECTEUR_2EME_CYCLE)
        visibles = classes_visibles_pour(directeur)
        self.assertIn(self.classe_2eme, visibles)
        self.assertNotIn(self.classe_1er, visibles)

    def test_fondateur_voit_toutes_les_classes(self):
        fondateur = creer_utilisateur_actif("fondateur@example.com", Role.FONDATEUR)
        visibles = classes_visibles_pour(fondateur)
        self.assertIn(self.classe_1er, visibles)
        self.assertIn(self.classe_2eme, visibles)


class LiaisonParentEleveTests(TestCase):
    def test_telephone_effectif_repris_du_parent(self):
        parent = creer_utilisateur_actif(
            "parent1@example.com", Role.PARENT, telephone="70111111", profession="Commerçant",
        )
        eleve = creer_utilisateur_actif("eleve1@example.com", Role.ELEVE)
        self.assertIsNone(eleve.telephone_effectif)
        lier_parent_a_eleve(eleve, parent)
        self.assertEqual(eleve.telephone_effectif, "70111111")
        # Le champ telephone de l'élève lui-même reste vide : pas de conflit d'unicité.
        self.assertIsNone(eleve.telephone)

    def test_maximum_deux_parents(self):
        eleve = creer_utilisateur_actif("eleve2@example.com", Role.ELEVE)
        parent_1 = creer_utilisateur_actif("p1@example.com", Role.PARENT, telephone="70111112", profession="X")
        parent_2 = creer_utilisateur_actif("p2@example.com", Role.PARENT, telephone="70111113", profession="X")
        parent_3 = creer_utilisateur_actif("p3@example.com", Role.PARENT, telephone="70111114", profession="X")
        lier_parent_a_eleve(eleve, parent_1)
        lier_parent_a_eleve(eleve, parent_2)
        with self.assertRaises(ValidationError):
            lier_parent_a_eleve(eleve, parent_3)

    def test_dossier_complet_seulement_si_tout_est_reuni(self):
        eleve = creer_utilisateur_actif("eleve3@example.com", Role.ELEVE)
        self.assertFalse(dossier_complet(eleve))
        parent = creer_utilisateur_actif("parent3@example.com", Role.PARENT, telephone="70111115", profession="X")
        lier_parent_a_eleve(eleve, parent)
        self.assertFalse(dossier_complet(eleve))  # date de naissance manquante
        eleve.date_naissance = datetime.date(2015, 3, 12)
        eleve.save()
        self.assertTrue(dossier_complet(eleve))


class InscriptionEleveDansClasseTests(TestCase):
    def setUp(self):
        self.annee = creer_annee()
        self.classe = Classe.objects.create(nom="4ème année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        self.eleve = creer_utilisateur_actif("eleve4@example.com", Role.ELEVE)

    def test_un_eleve_ne_peut_avoir_deux_inscriptions_la_meme_annee(self):
        autre_classe = Classe.objects.create(nom="4ème année B", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        Inscription.objects.create(eleve=self.eleve, classe=self.classe)
        with self.assertRaises(ValidationError):
            Inscription.objects.create(eleve=self.eleve, classe=autre_classe)

    def test_seul_un_eleve_peut_etre_inscrit(self):
        parent = creer_utilisateur_actif("parentX@example.com", Role.PARENT, telephone="70111116", profession="X")
        with self.assertRaises(ValidationError):
            Inscription.objects.create(eleve=parent, classe=self.classe)


class AffectationEnseignantTests(TestCase):
    def test_seul_un_enseignant_peut_etre_affecte(self):
        annee = creer_annee()
        classe = Classe.objects.create(nom="5ème année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=annee)
        secretaire = creer_utilisateur_actif("secX@example.com", Role.SECRETAIRE)
        affectation = Affectation(enseignant=secretaire, classe=classe)
        with self.assertRaises(ValidationError):
            affectation.full_clean()


class VueCreerClasseTests(TestCase):
    def setUp(self):
        self.annee = creer_annee()
        self.secretaire = creer_utilisateur_actif("secretaire-creer-classe@example.com", Role.SECRETAIRE)

    def test_creer_une_classe_avec_echeancier(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.post(reverse("scolarite:creer_classe"), {
            "nom": "5ème année C", "cycle": Cycle.PREMIER_CYCLE, "annee_scolaire": self.annee.id,
            "montant_inscription": 30000, "montant_tranche_1": 15000, "montant_tranche_2": 15000,
        })
        self.assertEqual(reponse.status_code, 302)
        classe = Classe.objects.get(nom="5ème année C")
        self.assertEqual(classe.echeancier.montant_inscription, 30000)

    def test_montant_non_multiple_de_5000_refuse(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.post(reverse("scolarite:creer_classe"), {
            "nom": "5ème année D", "cycle": Cycle.PREMIER_CYCLE, "annee_scolaire": self.annee.id,
            "montant_inscription": 12345, "montant_tranche_1": 15000, "montant_tranche_2": 15000,
        })
        self.assertFalse(Classe.objects.filter(nom="5ème année D").exists())

    def test_nom_duplique_meme_annee_refuse(self):
        Classe.objects.create(nom="5ème année E", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        self.client.force_login(self.secretaire)
        self.client.post(reverse("scolarite:creer_classe"), {
            "nom": "5ème année E", "cycle": Cycle.PREMIER_CYCLE, "annee_scolaire": self.annee.id,
            "montant_inscription": 30000, "montant_tranche_1": 15000, "montant_tranche_2": 15000,
        })
        self.assertEqual(Classe.objects.filter(nom="5ème année E").count(), 1)


class VueInscrireEleveTests(TestCase):
    def setUp(self):
        self.annee = creer_annee()
        self.classe = Classe.objects.create(nom="2ème année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        self.secretaire = creer_utilisateur_actif("secretaire2@example.com", Role.SECRETAIRE)
        self.parent = creer_utilisateur_actif(
            "parent-vue@example.com", Role.PARENT, telephone="70111117", profession="X",
        )

    def test_secretaire_peut_inscrire_un_eleve(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.post(reverse("scolarite:inscrire_eleve"), {
            "prenom": "Kadidia", "nom": "Sidibé", "sexe": "F", "date_naissance": "2016-05-20",
            "classe": self.classe.id, "parent_email_1": self.parent.email, "parent_email_2": "",
        })
        self.assertEqual(reponse.status_code, 302)
        eleve = Utilisateur.objects.get(role=Role.ELEVE, prenom="Kadidia")
        self.assertIsNotNone(eleve.matricule)
        self.assertTrue(eleve.parents_lies.filter(pk=self.parent.pk).exists())
        self.assertEqual(Inscription.objects.filter(eleve=eleve, classe=self.classe).count(), 1)

    def test_secretaire_peut_attribuer_un_matricule_manuel(self):
        self.client.force_login(self.secretaire)
        self.client.post(reverse("scolarite:inscrire_eleve"), {
            "prenom": "Fanta", "nom": "Keita", "matricule": "MALI-2026-001", "sexe": "F",
            "date_naissance": "2016-03-10", "classe": self.classe.id,
            "parent_email_1": self.parent.email, "parent_email_2": "",
        })
        eleve = Utilisateur.objects.get(role=Role.ELEVE, prenom="Fanta")
        self.assertEqual(eleve.matricule, "MALI-2026-001")

    def test_matricule_manuel_deja_utilise_refuse(self):
        self.client.force_login(self.secretaire)
        self.client.post(reverse("scolarite:inscrire_eleve"), {
            "prenom": "Awa", "nom": "Diarra", "matricule": "MALI-2026-002", "sexe": "F",
            "date_naissance": "2016-03-10", "classe": self.classe.id,
            "parent_email_1": self.parent.email, "parent_email_2": "",
        })
        reponse = self.client.post(reverse("scolarite:inscrire_eleve"), {
            "prenom": "Sekou", "nom": "Traore", "matricule": "MALI-2026-002", "sexe": "M",
            "date_naissance": "2016-03-10", "classe": self.classe.id,
            "parent_email_1": self.parent.email, "parent_email_2": "",
        })
        self.assertContains(reponse, "déjà utilisé")
        self.assertFalse(Utilisateur.objects.filter(prenom="Sekou").exists())

    def test_eleve_herite_de_letablissement_du_secretaire(self):
        from etablissement.models import Etablissement
        from permissions_matrix.models import PermissionMatrix
        ecole = Etablissement.objects.create(nom="École du secrétaire")
        PermissionMatrix.seed_pour(ecole)
        annee = creer_annee("2027-2028")
        annee.etablissement = ecole
        annee.save()
        classe = Classe.objects.create(nom="3ème année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=annee)
        secretaire = creer_utilisateur_actif("sec-etab@example.com", Role.SECRETAIRE, etablissement=ecole)
        parent = creer_utilisateur_actif(
            "parent-etab@example.com", Role.PARENT, telephone="70111199", profession="X", etablissement=ecole,
        )
        self.client.force_login(secretaire)
        self.client.post(reverse("scolarite:inscrire_eleve"), {
            "prenom": "Oumar", "nom": "Traore", "sexe": "M", "date_naissance": "2015-01-01",
            "classe": classe.id, "parent_email_1": parent.email, "parent_email_2": "",
        })
        eleve = Utilisateur.objects.get(role=Role.ELEVE, prenom="Oumar")
        self.assertEqual(eleve.etablissement, ecole)

    def test_enseignant_ne_peut_pas_acceder_a_la_vue(self):
        enseignant = creer_utilisateur_actif("profX@example.com", Role.ENSEIGNANT)
        self.client.force_login(enseignant)
        reponse = self.client.get(reverse("scolarite:inscrire_eleve"))
        self.assertEqual(reponse.status_code, 403)


class VueListeElevesTests(TestCase):
    def setUp(self):
        self.annee = creer_annee()
        self.classe = Classe.objects.create(nom="1ère année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        self.autre_classe = Classe.objects.create(nom="7ème année A", cycle=Cycle.DEUXIEME_CYCLE, annee_scolaire=self.annee)
        self.secretaire = creer_utilisateur_actif("sec-liste-eleves@example.com", Role.SECRETAIRE)
        self.eleve_1 = creer_utilisateur_actif("eleve-liste-1@example.com", Role.ELEVE)
        self.eleve_2 = creer_utilisateur_actif("eleve-liste-2@example.com", Role.ELEVE)
        Inscription.objects.create(eleve=self.eleve_1, classe=self.classe)
        Inscription.objects.create(eleve=self.eleve_2, classe=self.autre_classe)

    def test_liste_tous_les_eleves(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.get(reverse("scolarite:liste_eleves"))
        self.assertEqual(len(reponse.context["inscriptions"]), 2)

    def test_filtre_par_classe(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.get(reverse("scolarite:liste_eleves"), {"classe": self.classe.id})
        eleves = [i.eleve for i in reponse.context["inscriptions"]]
        self.assertEqual(eleves, [self.eleve_1])

    def test_directeur_de_cycle_ne_voit_que_son_cycle(self):
        directeur_2eme = creer_utilisateur_actif("dir2-liste-eleves@example.com", Role.DIRECTEUR_2EME_CYCLE)
        self.client.force_login(directeur_2eme)
        reponse = self.client.get(reverse("scolarite:liste_eleves"))
        eleves = [i.eleve for i in reponse.context["inscriptions"]]
        self.assertEqual(eleves, [self.eleve_2])


class VueAffecterEnseignantTests(TestCase):
    def setUp(self):
        self.annee = creer_annee()
        self.classe = Classe.objects.create(nom="1ère année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        self.secretaire = creer_utilisateur_actif("sec-affect@example.com", Role.SECRETAIRE)
        self.enseignant = creer_utilisateur_actif("prof-affect@example.com", Role.ENSEIGNANT)

    def test_affecter_un_enseignant_a_une_classe(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.post(reverse("scolarite:affecter_enseignant"), {
            "enseignant": self.enseignant.id, "classe": self.classe.id, "matiere": "Mathématiques",
        })
        self.assertEqual(reponse.status_code, 302)
        self.assertTrue(Affectation.objects.filter(enseignant=self.enseignant, classe=self.classe, matiere="Mathématiques").exists())

    def test_double_affectation_meme_matiere_signalee(self):
        Affectation.objects.create(enseignant=self.enseignant, classe=self.classe, matiere="Français")
        self.client.force_login(self.secretaire)
        self.client.post(reverse("scolarite:affecter_enseignant"), {
            "enseignant": self.enseignant.id, "classe": self.classe.id, "matiere": "Français",
        })
        self.assertEqual(Affectation.objects.filter(enseignant=self.enseignant, classe=self.classe, matiere="Français").count(), 1)

    def test_enseignant_dune_autre_ecole_absent_du_choix(self):
        from etablissement.models import Etablissement
        autre_ecole = Etablissement.objects.create(nom="Autre école affect")
        enseignant_exterieur = creer_utilisateur_actif("prof-exterieur-affect@example.com", Role.ENSEIGNANT, etablissement=autre_ecole)
        self.client.force_login(self.secretaire)
        reponse = self.client.get(reverse("scolarite:affecter_enseignant"))
        enseignants_proposes = list(reponse.context["formulaire"].fields["enseignant"].queryset)
        self.assertNotIn(enseignant_exterieur, enseignants_proposes)


class DossierEleveTests(TestCase):
    def setUp(self):
        self.annee = creer_annee()
        self.classe = Classe.objects.create(nom="5ème année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        EcheancierFrais.objects.create(
            classe=self.classe, montant_inscription=10000, montant_tranche_1=10000, montant_tranche_2=10000,
        )
        self.direction = creer_utilisateur_actif("direction-dossier@example.com", Role.FONDATEUR)
        self.eleve = creer_utilisateur_actif("eleve-dossier@example.com", Role.ELEVE)
        self.inscription = Inscription.objects.create(eleve=self.eleve, classe=self.classe)

    def test_dossier_affiche_classe_et_historique(self):
        self.client.force_login(self.direction)
        reponse = self.client.get(reverse("scolarite:dossier_eleve", args=[self.eleve.matricule]))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.context["inscription_active"], self.inscription)
        self.assertEqual(len(reponse.context["inscriptions"]), 1)

    def test_solde_annee_active_calcule(self):
        from finances.models import enregistrer_paiement, TypeTranche
        enregistrer_paiement(
            eleve=self.eleve, inscription=self.inscription, tranche=TypeTranche.INSCRIPTION,
            montant=10000, mode_paiement="especes", enregistre_par=self.direction,
        )
        self.client.force_login(self.direction)
        reponse = self.client.get(reverse("scolarite:dossier_eleve", args=[self.eleve.matricule]))
        self.assertEqual(reponse.context["total_paye"], 10000)
        self.assertEqual(reponse.context["solde_annee_active"], 20000)

    def test_enseignant_non_affecte_ne_peut_pas_voir_le_dossier(self):
        exterieur = creer_utilisateur_actif("prof-dossier-exterieur@example.com", Role.ENSEIGNANT)
        self.client.force_login(exterieur)
        reponse = self.client.get(reverse("scolarite:dossier_eleve", args=[self.eleve.matricule]))
        self.assertEqual(reponse.status_code, 403)

    def test_champs_finances_absents_pour_role_sans_acces(self):
        secretaire = creer_utilisateur_actif("sec-dossier@example.com", Role.SECRETAIRE)
        self.client.force_login(secretaire)
        reponse = self.client.get(reverse("scolarite:dossier_eleve", args=[self.eleve.matricule]))
        self.assertFalse(reponse.context["peut_voir_finances"])
        self.assertNotIn("total_paye", reponse.context)


class PassageDeClasseTests(TestCase):
    def setUp(self):
        self.annee_2026 = AnneeScolaire.objects.create(
            libelle="2026-2027", date_debut=datetime.date(2026, 10, 1), date_fin=datetime.date(2027, 7, 31),
        )
        self.annee_2027 = AnneeScolaire.objects.create(
            libelle="2027-2028", date_debut=datetime.date(2027, 10, 1), date_fin=datetime.date(2028, 7, 31),
        )
        self.classe_1ere_2026 = Classe.objects.create(nom="1ère année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee_2026)
        self.classe_2eme_2027 = Classe.objects.create(nom="2ème année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee_2027)
        self.classe_1ere_2027 = Classe.objects.create(nom="1ère année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee_2027)

        self.direction = creer_utilisateur_actif("direction-passage@example.com", Role.FONDATEUR)
        self.eleve_admis = creer_utilisateur_actif("eleve-admis@example.com", Role.ELEVE)
        self.eleve_redouble = creer_utilisateur_actif("eleve-redouble@example.com", Role.ELEVE)
        self.eleve_transfere = creer_utilisateur_actif("eleve-transfere@example.com", Role.ELEVE)
        self.inscription_admis = Inscription.objects.create(eleve=self.eleve_admis, classe=self.classe_1ere_2026)
        self.inscription_redouble = Inscription.objects.create(eleve=self.eleve_redouble, classe=self.classe_1ere_2026)
        self.inscription_transfere = Inscription.objects.create(eleve=self.eleve_transfere, classe=self.classe_1ere_2026)

    def test_passage_de_classe_complet(self):
        self.client.force_login(self.direction)
        reponse = self.client.post(reverse("scolarite:passage_de_classe", args=[self.classe_1ere_2026.id]), {
            "annee_destination": self.annee_2027.id,
            "classe_admis": self.classe_2eme_2027.id,
            "classe_redouble": self.classe_1ere_2027.id,
            f"decision_{self.inscription_admis.id}": "admis",
            f"decision_{self.inscription_redouble.id}": "redouble",
            f"decision_{self.inscription_transfere.id}": "transfere",
        })
        self.assertEqual(reponse.status_code, 302)

        self.inscription_admis.refresh_from_db()
        self.assertEqual(self.inscription_admis.statut, Inscription.Statut.ADMIS)
        self.assertTrue(Inscription.objects.filter(
            eleve=self.eleve_admis, classe=self.classe_2eme_2027, statut=Inscription.Statut.EN_COURS,
        ).exists())

        self.inscription_redouble.refresh_from_db()
        self.assertEqual(self.inscription_redouble.statut, Inscription.Statut.REDOUBLE)
        self.assertTrue(Inscription.objects.filter(
            eleve=self.eleve_redouble, classe=self.classe_1ere_2027, statut=Inscription.Statut.EN_COURS,
        ).exists())

        self.inscription_transfere.refresh_from_db()
        self.assertEqual(self.inscription_transfere.statut, Inscription.Statut.TRANSFERE)
        self.assertFalse(Inscription.objects.filter(eleve=self.eleve_transfere, statut=Inscription.Statut.EN_COURS).exists())

    def test_classe_suivante_memorisee_pour_lannee_prochaine(self):
        self.client.force_login(self.direction)
        self.client.post(reverse("scolarite:passage_de_classe", args=[self.classe_1ere_2026.id]), {
            "annee_destination": self.annee_2027.id,
            "classe_admis": self.classe_2eme_2027.id,
            "classe_redouble": self.classe_1ere_2027.id,
            f"decision_{self.inscription_admis.id}": "admis",
            f"decision_{self.inscription_redouble.id}": "admis",
            f"decision_{self.inscription_transfere.id}": "admis",
        })
        self.classe_1ere_2026.refresh_from_db()
        self.assertEqual(self.classe_1ere_2026.classe_suivante, self.classe_2eme_2027)

    def test_admis_sans_classe_destination_refuse(self):
        self.client.force_login(self.direction)
        reponse = self.client.post(reverse("scolarite:passage_de_classe", args=[self.classe_1ere_2026.id]), {
            "annee_destination": self.annee_2027.id,
            "classe_admis": "", "classe_redouble": self.classe_1ere_2027.id,
            f"decision_{self.inscription_admis.id}": "admis",
        })
        self.inscription_admis.refresh_from_db()
        self.assertEqual(self.inscription_admis.statut, Inscription.Statut.EN_COURS)  # inchangé

    def test_statistiques_refletent_les_admis(self):
        self.client.force_login(self.direction)
        self.client.post(reverse("scolarite:passage_de_classe", args=[self.classe_1ere_2026.id]), {
            "annee_destination": self.annee_2027.id,
            "classe_admis": self.classe_2eme_2027.id,
            "classe_redouble": self.classe_1ere_2027.id,
            f"decision_{self.inscription_admis.id}": "admis",
            f"decision_{self.inscription_redouble.id}": "redouble",
            f"decision_{self.inscription_transfere.id}": "transfere",
        })
        reponse = self.client.get(reverse("statistiques:vue_ensemble"), {"annee": self.annee_2026.id})
        self.assertEqual(reponse.context["taux_reussite"], 50.0)


class ListeMatieresTests(TestCase):
    def setUp(self):
        self.annee = creer_annee()
        self.classe = Classe.objects.create(nom="6ème année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        self.secretaire = creer_utilisateur_actif("sec-matieres@example.com", Role.SECRETAIRE)
        self.enseignant = creer_utilisateur_actif("prof-matieres@example.com", Role.ENSEIGNANT)
        Affectation.objects.create(enseignant=self.enseignant, classe=self.classe, matiere="Mathématiques")
        Affectation.objects.create(enseignant=self.enseignant, classe=self.classe, matiere="")  # titulaire, exclu

    def test_liste_regroupe_par_matiere(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.get(reverse("scolarite:liste_matieres"))
        self.assertIn("Mathématiques", reponse.context["matieres"])
        self.assertEqual(len(reponse.context["matieres"]), 1)  # le titulaire (matière vide) est exclu


class ImporterElevesExcelTests(TestCase):
    def setUp(self):
        import openpyxl
        from etablissement.models import Etablissement

        self.ecole = Etablissement.objects.create(nom="École Import Excel")
        self.annee_2026 = AnneeScolaire.objects.create(
            libelle="2026-2027", date_debut=datetime.date(2026, 10, 1), date_fin=datetime.date(2027, 7, 31),
            etablissement=self.ecole,
        )
        self.annee_2027 = AnneeScolaire.objects.create(
            libelle="2027-2028", date_debut=datetime.date(2027, 10, 1), date_fin=datetime.date(2028, 7, 31),
            etablissement=self.ecole,
        )
        # Même nom de classe sur les deux années — exactement le cas qui provoquait le bug.
        self.classe_2026 = Classe.objects.create(nom="1ère année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee_2026)
        self.classe_2027 = Classe.objects.create(nom="1ère année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee_2027)

        self.fichier = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        classeur = openpyxl.Workbook()
        feuille = classeur.active
        feuille.append(["prenom", "nom", "classe"])
        feuille.append(["Awa", "Coulibaly", "1ère année A"])
        feuille.append(["Sekou", "Traore", "1ère année A"])
        classeur.save(self.fichier.name)

    def tearDown(self):
        os.unlink(self.fichier.name)

    def test_import_cible_la_bonne_annee_scolaire(self):
        call_command(
            "importer_eleves_excel", self.fichier.name,
            **{"etablissement": self.ecole.id, "annee_scolaire": self.annee_2027.id},
        )
        eleves = Utilisateur.objects.filter(role=Role.ELEVE, prenom__in=["Awa", "Sekou"])
        self.assertEqual(eleves.count(), 2)
        for eleve in eleves:
            inscription = Inscription.objects.get(eleve=eleve)
            self.assertEqual(inscription.classe, self.classe_2027)
            self.assertNotEqual(inscription.classe, self.classe_2026)

    def test_dry_run_necrit_rien(self):
        call_command(
            "importer_eleves_excel", self.fichier.name,
            **{"etablissement": self.ecole.id, "annee_scolaire": self.annee_2027.id, "dry_run": True},
        )
        self.assertEqual(Utilisateur.objects.filter(role=Role.ELEVE).count(), 0)

    def test_classe_inexistante_pour_cette_annee_refuse_tout(self):
        import openpyxl
        fichier_invalide = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        classeur = openpyxl.Workbook()
        feuille = classeur.active
        feuille.append(["prenom", "nom", "classe"])
        feuille.append(["Test", "Inconnu", "Classe qui n'existe pas"])
        classeur.save(fichier_invalide.name)
        try:
            with self.assertRaises(CommandError):
                call_command(
                    "importer_eleves_excel", fichier_invalide.name,
                    **{"etablissement": self.ecole.id, "annee_scolaire": self.annee_2027.id},
                )
            self.assertEqual(Utilisateur.objects.filter(role=Role.ELEVE).count(), 0)
        finally:
            os.unlink(fichier_invalide.name)

    def test_annee_scolaire_obligatoire(self):
        with self.assertRaises(CommandError):
            call_command(
                "importer_eleves_excel", self.fichier.name,
                **{"etablissement": self.ecole.id, "annee_scolaire": 999999},
            )
