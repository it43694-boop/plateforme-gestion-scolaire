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
    Affectation, AnneeScolaire, Classe, Cycle, EcheancierFrais, Inscription, ParentEnAttente, Periodicite, Serie,
    TypeDocumentVerifiable, VerificationDocument,
    classes_visibles_pour, dossier_complet, eleve_visible_pour, lier_parent_a_eleve,
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

    def test_serie_hors_lycee_refusee(self):
        classe = Classe(
            nom="9ème A", cycle=Cycle.DEUXIEME_CYCLE, serie=Serie.SCIENCES_EXACTES, annee_scolaire=self.annee,
        )
        with self.assertRaises(ValidationError):
            classe.clean()

    def test_serie_au_lycee_acceptee(self):
        classe = Classe(
            nom="Terminale A", cycle=Cycle.LYCEE, serie=Serie.SCIENCES_EXACTES, annee_scolaire=self.annee,
        )
        classe.clean()  # ne doit pas lever d'exception
        classe.save()
        self.assertEqual(classe.get_serie_display(), "Sciences Exactes (TSE)")

    def test_classe_lycee_sans_serie_acceptee(self):
        # La 10ème année (tronc commun) n'a pas encore de série.
        classe = Classe(nom="10ème A", cycle=Cycle.LYCEE, annee_scolaire=self.annee)
        classe.clean()
        classe.save()

    def test_frais_multiple_de_5000_obligatoire(self):
        classe = Classe.objects.create(nom="1ère année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        with self.assertRaises(ValidationError):
            EcheancierFrais.objects.create(
                classe=classe, montant_inscription=12345, periodicite=Periodicite.ANNUEL, montant_periode=20000, nombre_versements=1,
            )

    def test_frais_eleves_acceptes_sans_plafond(self):
        classe = Classe.objects.create(nom="1ère année B", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        frais = EcheancierFrais.objects.create(
            classe=classe, montant_inscription=100000, periodicite=Periodicite.ANNUEL, montant_periode=100000, nombre_versements=1,
        )
        self.assertEqual(frais.montant_inscription, 100000)

    def test_frais_valides_acceptes(self):
        classe = Classe.objects.create(nom="1ère année C", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        frais = EcheancierFrais.objects.create(
            classe=classe, montant_inscription=30000, periodicite=Periodicite.ANNUEL, montant_periode=30000, nombre_versements=1,
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
            classe=classe_valide, montant_inscription=300, periodicite=Periodicite.ANNUEL, montant_periode=400, nombre_versements=1,
        )
        self.assertEqual(frais.total_annuel, 700)

        # Pas multiple de 100 : refusé, avec le message qui porte la devise de l'établissement.
        with self.assertRaises(ValidationError) as cm:
            EcheancierFrais.objects.create(
                classe=classe_invalide, montant_inscription=250, periodicite=Periodicite.ANNUEL, montant_periode=400, nombre_versements=1,
            )
        self.assertIn("EUR", str(cm.exception))


class CloisonnementCycleTests(TestCase):
    def setUp(self):
        self.annee = creer_annee()
        self.classe_1er = Classe.objects.create(nom="3ème année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        self.classe_2eme = Classe.objects.create(nom="8ème année A", cycle=Cycle.DEUXIEME_CYCLE, annee_scolaire=self.annee)
        self.classe_lycee = Classe.objects.create(nom="11ème année A", cycle=Cycle.LYCEE, annee_scolaire=self.annee)

    def test_directeur_1er_cycle_ne_voit_que_son_cycle(self):
        directeur = creer_utilisateur_actif("dir1@example.com", Role.DIRECTEUR_1ER_CYCLE)
        visibles = classes_visibles_pour(directeur)
        self.assertIn(self.classe_1er, visibles)
        self.assertNotIn(self.classe_2eme, visibles)
        self.assertNotIn(self.classe_lycee, visibles)

    def test_directeur_2eme_cycle_ne_voit_que_son_cycle(self):
        directeur = creer_utilisateur_actif("dir2@example.com", Role.DIRECTEUR_2EME_CYCLE)
        visibles = classes_visibles_pour(directeur)
        self.assertIn(self.classe_2eme, visibles)
        self.assertNotIn(self.classe_1er, visibles)
        self.assertNotIn(self.classe_lycee, visibles)

    def test_directeur_lycee_ne_voit_que_le_lycee(self):
        directeur = creer_utilisateur_actif("dir-lycee@example.com", Role.DIRECTEUR_LYCEE)
        visibles = classes_visibles_pour(directeur)
        self.assertIn(self.classe_lycee, visibles)
        self.assertNotIn(self.classe_1er, visibles)
        self.assertNotIn(self.classe_2eme, visibles)

    def test_fondateur_voit_toutes_les_classes(self):
        fondateur = creer_utilisateur_actif("fondateur@example.com", Role.FONDATEUR)
        visibles = classes_visibles_pour(fondateur)
        self.assertIn(self.classe_1er, visibles)
        self.assertIn(self.classe_2eme, visibles)
        self.assertIn(self.classe_lycee, visibles)

    def test_directeur_lycee_voit_le_dossier_dun_eleve_du_lycee(self):
        directeur = creer_utilisateur_actif("dir-lycee-dossier@example.com", Role.DIRECTEUR_LYCEE)
        eleve = creer_utilisateur_actif("eleve-lycee@example.com", Role.ELEVE)
        Inscription.objects.create(eleve=eleve, classe=self.classe_lycee)
        self.assertTrue(eleve_visible_pour(directeur, eleve))

    def test_directeur_1er_cycle_ne_voit_pas_le_dossier_dun_eleve_du_lycee(self):
        directeur = creer_utilisateur_actif("dir1-dossier@example.com", Role.DIRECTEUR_1ER_CYCLE)
        eleve = creer_utilisateur_actif("eleve-lycee2@example.com", Role.ELEVE)
        Inscription.objects.create(eleve=eleve, classe=self.classe_lycee)
        self.assertFalse(eleve_visible_pour(directeur, eleve))


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


class LierParentsEnAttenteTests(TestCase):
    """lier_parents_en_attente est le mécanisme appelé par
    comptes.views.verifier_email dès qu'un compte parent vient d'être vérifié."""

    def test_lie_et_supprime_lattente_correspondante(self):
        from scolarite.models import lier_parents_en_attente

        eleve = creer_utilisateur_actif("eleve-attente1@example.com", Role.ELEVE)
        ParentEnAttente.objects.create(eleve=eleve, email="parent-attente1@example.com", nom="X", prenom="Y")
        parent = creer_utilisateur_actif(
            "parent-attente1@example.com", Role.PARENT, telephone="70222221", profession="X",
        )
        lier_parents_en_attente(parent)
        self.assertTrue(eleve.parents_lies.filter(pk=parent.pk).exists())
        self.assertFalse(ParentEnAttente.objects.filter(eleve=eleve).exists())

    def test_insensible_a_la_casse_de_lemail(self):
        from scolarite.models import lier_parents_en_attente

        eleve = creer_utilisateur_actif("eleve-attente2@example.com", Role.ELEVE)
        ParentEnAttente.objects.create(eleve=eleve, email="Parent-Attente2@Example.com")
        parent = creer_utilisateur_actif(
            "parent-attente2@example.com", Role.PARENT, telephone="70222222", profession="X",
        )
        lier_parents_en_attente(parent)
        self.assertTrue(eleve.parents_lies.filter(pk=parent.pk).exists())

    def test_lattente_dun_autre_etablissement_nest_jamais_liee(self):
        from etablissement.models import Etablissement
        from scolarite.models import lier_parents_en_attente

        ecole_a = Etablissement.objects.create(nom="École attente A")
        ecole_b = Etablissement.objects.create(nom="École attente B")
        eleve = creer_utilisateur_actif("eleve-attente3@example.com", Role.ELEVE, etablissement=ecole_a)
        ParentEnAttente.objects.create(eleve=eleve, email="parent-attente3@example.com")
        parent = creer_utilisateur_actif(
            "parent-attente3@example.com", Role.PARENT, telephone="70222223", profession="X",
            etablissement=ecole_b,
        )
        lier_parents_en_attente(parent)
        self.assertFalse(eleve.parents_lies.filter(pk=parent.pk).exists())
        self.assertTrue(ParentEnAttente.objects.filter(eleve=eleve).exists())  # laissée en place

    def test_attente_non_resolue_si_deja_deux_parents_est_conservee(self):
        from scolarite.models import lier_parents_en_attente

        eleve = creer_utilisateur_actif("eleve-attente4@example.com", Role.ELEVE)
        lier_parent_a_eleve(eleve, creer_utilisateur_actif("p1-attente4@example.com", Role.PARENT, telephone="70222224", profession="X"))
        lier_parent_a_eleve(eleve, creer_utilisateur_actif("p2-attente4@example.com", Role.PARENT, telephone="70222225", profession="X"))
        ParentEnAttente.objects.create(eleve=eleve, email="p3-attente4@example.com")
        parent_3 = creer_utilisateur_actif("p3-attente4@example.com", Role.PARENT, telephone="70222226", profession="X")

        lier_parents_en_attente(parent_3)
        self.assertFalse(eleve.parents_lies.filter(pk=parent_3.pk).exists())
        self.assertTrue(ParentEnAttente.objects.filter(eleve=eleve, email="p3-attente4@example.com").exists())


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
            "montant_inscription": 30000, "periodicite": Periodicite.TRIMESTRIEL, "montant_periode": 15000,
        })
        self.assertEqual(reponse.status_code, 302)
        classe = Classe.objects.get(nom="5ème année C")
        self.assertEqual(classe.echeancier.montant_inscription, 30000)

    def test_creer_une_classe_de_lycee_avec_serie(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.post(reverse("scolarite:creer_classe"), {
            "nom": "Terminale A", "cycle": Cycle.LYCEE, "serie": Serie.SCIENCES_EXACTES,
            "annee_scolaire": self.annee.id,
            "montant_inscription": 30000, "periodicite": Periodicite.TRIMESTRIEL, "montant_periode": 15000,
        })
        self.assertEqual(reponse.status_code, 302)
        classe = Classe.objects.get(nom="Terminale A")
        self.assertEqual(classe.serie, Serie.SCIENCES_EXACTES)

    def test_serie_hors_lycee_refusee_par_la_vue(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.post(reverse("scolarite:creer_classe"), {
            "nom": "5ème année D", "cycle": Cycle.PREMIER_CYCLE, "serie": Serie.SCIENCES_EXACTES,
            "annee_scolaire": self.annee.id,
            "montant_inscription": 30000, "periodicite": Periodicite.TRIMESTRIEL, "montant_periode": 15000,
        })
        self.assertEqual(reponse.status_code, 200)  # formulaire réaffiché avec erreur
        self.assertFalse(Classe.objects.filter(nom="5ème année D").exists())

    def test_montant_non_multiple_de_5000_refuse(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.post(reverse("scolarite:creer_classe"), {
            "nom": "5ème année D", "cycle": Cycle.PREMIER_CYCLE, "annee_scolaire": self.annee.id,
            "montant_inscription": 12345, "periodicite": Periodicite.TRIMESTRIEL, "montant_periode": 15000,
        })
        self.assertFalse(Classe.objects.filter(nom="5ème année D").exists())

    def test_nom_duplique_meme_annee_refuse(self):
        Classe.objects.create(nom="5ème année E", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        self.client.force_login(self.secretaire)
        self.client.post(reverse("scolarite:creer_classe"), {
            "nom": "5ème année E", "cycle": Cycle.PREMIER_CYCLE, "annee_scolaire": self.annee.id,
            "montant_inscription": 30000, "periodicite": Periodicite.TRIMESTRIEL, "montant_periode": 15000,
        })
        self.assertEqual(Classe.objects.filter(nom="5ème année E").count(), 1)

    def test_un_enseignant_ne_peut_pas_creer_de_classe(self):
        """
        Module Classes = administration de toute l'école (création de classes,
        affectation d'enseignants, passage de classe), pas le périmètre d'un
        enseignant - qui ne doit voir que ses propres classes via "Mes classes".
        """
        enseignant = creer_utilisateur_actif("enseignant-creer-classe@example.com", Role.ENSEIGNANT)
        self.client.force_login(enseignant)
        reponse = self.client.post(reverse("scolarite:creer_classe"), {
            "nom": "5ème année F", "cycle": Cycle.PREMIER_CYCLE, "annee_scolaire": self.annee.id,
            "montant_inscription": 30000, "periodicite": Periodicite.TRIMESTRIEL, "montant_periode": 15000,
        })
        self.assertEqual(reponse.status_code, 403)
        self.assertFalse(Classe.objects.filter(nom="5ème année F").exists())


class VueSupprimerClasseTests(TestCase):
    def setUp(self):
        self.annee = creer_annee()
        self.secretaire = creer_utilisateur_actif("secretaire-suppr-classe@example.com", Role.SECRETAIRE)
        self.classe_vide = Classe.objects.create(nom="5ème année G", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)

    def test_supprimer_une_classe_vide(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.post(reverse("scolarite:supprimer_classe", args=[self.classe_vide.id]))
        self.assertEqual(reponse.status_code, 302)
        self.assertFalse(Classe.objects.filter(id=self.classe_vide.id).exists())

    def test_refuse_si_un_eleve_est_inscrit(self):
        eleve = creer_utilisateur_actif("eleve-suppr-classe@example.com", Role.ELEVE)
        Inscription.objects.create(eleve=eleve, classe=self.classe_vide, statut=Inscription.Statut.EN_COURS)
        self.client.force_login(self.secretaire)
        reponse = self.client.post(reverse("scolarite:supprimer_classe", args=[self.classe_vide.id]))
        self.assertEqual(reponse.status_code, 302)
        self.assertTrue(Classe.objects.filter(id=self.classe_vide.id).exists())

    def test_refuse_meme_pour_une_inscription_passee(self):
        """effectif == 0 (plus aucune inscription EN_COURS) ne veut pas dire
        « sans historique » - un élève admis/redoublant/transféré y a quand
        même été inscrit : la classe reste protégée."""
        eleve = creer_utilisateur_actif("eleve-suppr-classe-2@example.com", Role.ELEVE)
        Inscription.objects.create(eleve=eleve, classe=self.classe_vide, statut=Inscription.Statut.ADMIS)
        self.assertEqual(self.classe_vide.effectif, 0)
        self.client.force_login(self.secretaire)
        reponse = self.client.post(reverse("scolarite:supprimer_classe", args=[self.classe_vide.id]))
        self.assertEqual(reponse.status_code, 302)
        self.assertTrue(Classe.objects.filter(id=self.classe_vide.id).exists())

    def test_un_enseignant_ne_peut_pas_supprimer_de_classe(self):
        enseignant = creer_utilisateur_actif("enseignant-suppr-classe@example.com", Role.ENSEIGNANT)
        self.client.force_login(enseignant)
        reponse = self.client.post(reverse("scolarite:supprimer_classe", args=[self.classe_vide.id]))
        self.assertEqual(reponse.status_code, 403)
        self.assertTrue(Classe.objects.filter(id=self.classe_vide.id).exists())

    def test_classe_dune_autre_ecole_introuvable(self):
        from etablissement.models import Etablissement
        autre_ecole = Etablissement.objects.create(nom="Autre école suppr classe")
        autre_annee = AnneeScolaire.objects.create(
            etablissement=autre_ecole, libelle="2026-2027",
            date_debut=datetime.date(2026, 10, 1), date_fin=datetime.date(2027, 7, 31),
        )
        classe_exterieure = Classe.objects.create(nom="Classe externe", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=autre_annee)
        self.client.force_login(self.secretaire)
        reponse = self.client.post(reverse("scolarite:supprimer_classe", args=[classe_exterieure.id]))
        self.assertEqual(reponse.status_code, 404)
        self.assertTrue(Classe.objects.filter(id=classe_exterieure.id).exists())


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

    def test_parent_dun_autre_etablissement_jamais_lie_mais_eleve_cree(self):
        """
        L'email d'un parent d'un AUTRE établissement ne doit jamais être
        trouvé/lié ici (cloisonnement) - mais comme un email inconnu de cet
        établissement est désormais traité comme « en attente » plutôt que
        refusé (voir test_parent_sans_compte_cree_une_attente), l'élève est
        bien créé, avec une simple mémorisation en attente (qui ne pourra
        jamais se résoudre pour cet email précis, déjà pris ailleurs - sans
        conséquence : aucun accès n'est accordé tant qu'aucun lien ne se fait).
        """
        from etablissement.models import Etablissement
        from permissions_matrix.models import PermissionMatrix

        ecole_a = Etablissement.objects.create(nom="École A")
        ecole_b = Etablissement.objects.create(nom="École B")
        PermissionMatrix.seed_pour(ecole_a)
        annee = creer_annee("2029-2030")
        annee.etablissement = ecole_a
        annee.save()
        classe = Classe.objects.create(nom="4ème année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=annee)
        secretaire = creer_utilisateur_actif("sec-cross-etab@example.com", Role.SECRETAIRE, etablissement=ecole_a)
        parent_autre_ecole = creer_utilisateur_actif(
            "parent-autre-ecole@example.com", Role.PARENT, telephone="70111188", profession="X",
            etablissement=ecole_b,
        )

        self.client.force_login(secretaire)
        reponse = self.client.post(reverse("scolarite:inscrire_eleve"), {
            "prenom": "Mariam", "nom": "Coulibaly", "sexe": "F", "date_naissance": "2016-01-01",
            "classe": classe.id, "parent_email_1": parent_autre_ecole.email, "parent_email_2": "",
        })
        self.assertEqual(reponse.status_code, 302)
        eleve = Utilisateur.objects.get(prenom="Mariam", role=Role.ELEVE)
        self.assertFalse(eleve.parents_lies.filter(pk=parent_autre_ecole.pk).exists())
        self.assertTrue(ParentEnAttente.objects.filter(eleve=eleve, email=parent_autre_ecole.email).exists())

    def test_parent_sans_compte_cree_une_attente(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.post(reverse("scolarite:inscrire_eleve"), {
            "prenom": "Issa", "nom": "Konaté", "sexe": "M", "date_naissance": "2016-01-01",
            "classe": self.classe.id, "parent_email_1": "nouveau-parent@example.com",
            "parent_nom_1": "Konaté", "parent_prenom_1": "Aminata", "parent_telephone_1": "70123456",
            "parent_email_2": "",
        })
        self.assertEqual(reponse.status_code, 302)
        eleve = Utilisateur.objects.get(prenom="Issa", role=Role.ELEVE)
        attente = ParentEnAttente.objects.get(eleve=eleve, email="nouveau-parent@example.com")
        self.assertEqual(attente.nom, "Konaté")
        self.assertEqual(attente.prenom, "Aminata")
        self.assertEqual(attente.telephone, "70123456")
        self.assertFalse(eleve.parents_lies.exists())

    def test_lien_se_fait_automatiquement_a_la_verification_email(self):
        """Bout en bout : inscription de l'élève avec un email non encore inscrit, puis
        ce parent crée son compte et le vérifie - le lien doit se faire sans aucune action manuelle."""
        from comptes.models import CodeVerificationEmail

        self.client.force_login(self.secretaire)
        self.client.post(reverse("scolarite:inscrire_eleve"), {
            "prenom": "Salif", "nom": "Diabaté", "sexe": "M", "date_naissance": "2016-01-01",
            "classe": self.classe.id, "parent_email_1": "futur-parent@example.com", "parent_email_2": "",
        })
        eleve = Utilisateur.objects.get(prenom="Salif", role=Role.ELEVE)
        self.client.logout()

        # Reproduit l'état d'un compte juste après l'étape 1 (mot de passe choisi,
        # email pas encore vérifié) sans dépendre de la résolution d'établissement
        # du formulaire public, hors sujet pour ce test.
        nouveau_parent = Utilisateur(
            email="futur-parent@example.com", prenom="Mamadou", nom="Diabaté",
            role=Role.PARENT, telephone="70999999",
        )
        nouveau_parent.set_password("MotDePasse#2026")
        nouveau_parent.full_clean(exclude=["password"])
        nouveau_parent.save()
        code_verif = CodeVerificationEmail.objects.create(utilisateur=nouveau_parent, code="123456")
        session = self.client.session
        session["utilisateur_en_verification_id"] = nouveau_parent.id
        session.save()

        self.client.post(reverse("comptes:verifier_email"), {"code": code_verif.code})

        eleve.refresh_from_db()
        self.assertTrue(eleve.parents_lies.filter(pk=nouveau_parent.pk).exists())
        self.assertFalse(ParentEnAttente.objects.filter(eleve=eleve).exists())
        self.assertEqual(eleve.telephone_effectif, "70999999")  # repris du parent (voir LiaisonParentEleveTests)


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

    def test_ne_fait_pas_une_requete_par_eleve(self):
        # Régression : {{ inscription.classe }} (affiché dans le template)
        # déclenche Classe.__str__, qui accède à annee_scolaire - sans
        # classe__annee_scolaire dans le select_related, c'était une
        # requête de plus par élève affiché.
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        for i in range(5):
            eleve = creer_utilisateur_actif(f"perf-liste{i}@example.com", Role.ELEVE)
            Inscription.objects.create(eleve=eleve, classe=self.classe)

        self.client.force_login(self.secretaire)
        with CaptureQueriesContext(connection) as capture:
            self.client.get(reverse("scolarite:liste_eleves"))
        self.assertLess(
            len(capture.captured_queries), 20,
            "liste_eleves semble à nouveau faire une requête par élève.",
        )


class RechercheGlobaleTests(TestCase):
    def setUp(self):
        self.annee = creer_annee()
        self.classe = Classe.objects.create(nom="1ère année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        self.autre_classe = Classe.objects.create(nom="7ème année A", cycle=Cycle.DEUXIEME_CYCLE, annee_scolaire=self.annee)
        self.secretaire = creer_utilisateur_actif("sec-recherche@example.com", Role.SECRETAIRE)
        self.eleve = creer_utilisateur_actif("eleve-recherche@example.com", Role.ELEVE)
        self.eleve.prenom, self.eleve.nom = "Awa", "Coulibaly"
        self.eleve.save(update_fields=["prenom", "nom"])
        self.autre_eleve = creer_utilisateur_actif("autre-recherche@example.com", Role.ELEVE)
        self.autre_eleve.prenom, self.autre_eleve.nom = "Sekou", "Traore"
        self.autre_eleve.save(update_fields=["prenom", "nom"])
        Inscription.objects.create(eleve=self.eleve, classe=self.classe)
        Inscription.objects.create(eleve=self.autre_eleve, classe=self.autre_classe)

    def test_recherche_par_nom(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.get(reverse("scolarite:recherche_globale"), {"q": "Coulibaly"})
        eleves = [i.eleve for i in reponse.context["resultats"]]
        self.assertEqual(eleves, [self.eleve])

    def test_recherche_par_matricule(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.get(reverse("scolarite:recherche_globale"), {"q": self.eleve.matricule})
        eleves = [i.eleve for i in reponse.context["resultats"]]
        self.assertEqual(eleves, [self.eleve])

    def test_recherche_insensible_a_la_casse_et_partielle(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.get(reverse("scolarite:recherche_globale"), {"q": "coul"})
        eleves = [i.eleve for i in reponse.context["resultats"]]
        self.assertEqual(eleves, [self.eleve])

    def test_sans_terme_ne_renvoie_rien(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.get(reverse("scolarite:recherche_globale"))
        self.assertEqual(list(reponse.context["resultats"]), [])

    def test_directeur_de_cycle_ne_trouve_que_son_cycle(self):
        directeur_2eme = creer_utilisateur_actif("dir2-recherche@example.com", Role.DIRECTEUR_2EME_CYCLE)
        self.client.force_login(directeur_2eme)
        reponse = self.client.get(reverse("scolarite:recherche_globale"), {"q": "Coulibaly"})
        self.assertEqual(list(reponse.context["resultats"]), [])

    def test_parent_ne_trouve_que_ses_enfants(self):
        parent = creer_utilisateur_actif("parent-recherche@example.com", Role.PARENT, telephone="+22370000099")
        self.autre_eleve.parents_lies.add(parent)
        self.client.force_login(parent)
        reponse = self.client.get(reverse("scolarite:recherche_globale"), {"q": "Coulibaly"})
        self.assertEqual(list(reponse.context["resultats"]), [])
        reponse = self.client.get(reverse("scolarite:recherche_globale"), {"q": "Traore"})
        eleves = [i.eleve for i in reponse.context["resultats"]]
        self.assertEqual(eleves, [self.autre_eleve])

    def test_role_sans_module_eleves_na_pas_acces(self):
        comptable = creer_utilisateur_actif("comptable-recherche@example.com", Role.COMPTABLE)
        self.client.force_login(comptable)
        reponse = self.client.get(reverse("scolarite:recherche_globale"), {"q": "Coulibaly"})
        self.assertEqual(reponse.status_code, 403)


class AttestationScolariteTests(TestCase):
    def setUp(self):
        from etablissement.models import Etablissement
        from permissions_matrix.models import PermissionMatrix

        self.ecole = Etablissement.objects.create(nom="École Attestation")
        PermissionMatrix.seed_pour(self.ecole)
        self.annee = creer_annee()
        self.annee.etablissement = self.ecole
        self.annee.save(update_fields=["etablissement"])
        self.classe = Classe.objects.create(nom="1ère année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        self.secretaire = creer_utilisateur_actif("sec-attestation@example.com", Role.SECRETAIRE, etablissement=self.ecole)
        self.eleve = creer_utilisateur_actif("eleve-attestation@example.com", Role.ELEVE, etablissement=self.ecole)
        self.inscription = Inscription.objects.create(eleve=self.eleve, classe=self.classe)

    def test_genere_un_pdf_et_cree_un_jeton_de_verification(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.get(reverse("scolarite:generer_attestation_scolarite", args=[self.eleve.matricule]))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse["Content-Type"], "application/pdf")
        self.assertTrue(
            VerificationDocument.objects.filter(
                eleve=self.eleve, inscription=self.inscription,
                type_document=TypeDocumentVerifiable.ATTESTATION_SCOLARITE,
            ).exists()
        )

    def test_reutilise_le_meme_jeton_pour_la_meme_inscription(self):
        self.client.force_login(self.secretaire)
        self.client.get(reverse("scolarite:generer_attestation_scolarite", args=[self.eleve.matricule]))
        self.client.get(reverse("scolarite:generer_attestation_scolarite", args=[self.eleve.matricule]))
        self.assertEqual(
            VerificationDocument.objects.filter(eleve=self.eleve, inscription=self.inscription).count(), 1,
        )

    def test_sans_inscription_en_cours_redirige_avec_message(self):
        self.inscription.statut = Inscription.Statut.ADMIS
        self.inscription.save(update_fields=["statut"])
        self.client.force_login(self.secretaire)
        reponse = self.client.get(
            reverse("scolarite:generer_attestation_scolarite", args=[self.eleve.matricule]), follow=True,
        )
        self.assertRedirects(reponse, reverse("scolarite:dossier_eleve", args=[self.eleve.matricule]))

    def test_role_sans_acces_a_leleve_refuse(self):
        # Même établissement (donc même module ELEVES autorisé) pour isoler
        # ce que ce test vérifie réellement : qu'un autre élève - un rôle
        # sans lien direct avec ce dossier - est bloqué par eleve_visible_pour,
        # pas par une matrice de permissions différente.
        autre_eleve = creer_utilisateur_actif("autre-attestation@example.com", Role.ELEVE, etablissement=self.ecole)
        self.client.force_login(autre_eleve)
        reponse = self.client.get(reverse("scolarite:generer_attestation_scolarite", args=[self.eleve.matricule]))
        self.assertEqual(reponse.status_code, 403)

    def test_verification_publique_renvoie_les_bonnes_informations(self):
        self.client.force_login(self.secretaire)
        self.client.get(reverse("scolarite:generer_attestation_scolarite", args=[self.eleve.matricule]))
        verification = VerificationDocument.objects.get(eleve=self.eleve)

        self.client.logout()
        reponse = self.client.get(reverse("scolarite:verifier_document", args=[verification.jeton]))
        self.assertEqual(reponse.status_code, 200)
        donnees = reponse.json()
        self.assertTrue(donnees["valide"])
        self.assertEqual(donnees["matricule"], self.eleve.matricule)

    def test_jeton_inconnu_renvoie_404(self):
        import uuid
        reponse = self.client.get(reverse("scolarite:verifier_document", args=[uuid.uuid4()]))
        self.assertEqual(reponse.status_code, 404)


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

    def test_un_enseignant_ne_peut_pas_saffecter_lui_meme(self):
        self.client.force_login(self.enseignant)
        reponse = self.client.post(reverse("scolarite:affecter_enseignant"), {
            "enseignant": self.enseignant.id, "classe": self.classe.id, "matiere": "Mathématiques",
        })
        self.assertEqual(reponse.status_code, 403)
        self.assertFalse(Affectation.objects.filter(enseignant=self.enseignant, classe=self.classe).exists())


class VueSupprimerAffectationTests(TestCase):
    """
    « Supprimer une matière » revient à retirer la ou les affectations qui
    la composent - il n'existe pas de table Matière séparée (voir
    liste_matieres : une matière est une vue groupée sur Affectation).
    """

    def setUp(self):
        self.annee = creer_annee()
        self.classe = Classe.objects.create(nom="1ère année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        self.secretaire = creer_utilisateur_actif("sec-suppr-affect@example.com", Role.SECRETAIRE)
        self.enseignant = creer_utilisateur_actif("prof-suppr-affect@example.com", Role.ENSEIGNANT)
        self.affectation = Affectation.objects.create(enseignant=self.enseignant, classe=self.classe, matiere="Mathématiques")

    def test_supprimer_une_affectation_sans_notes(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.post(reverse("scolarite:supprimer_affectation", args=[self.affectation.id]))
        self.assertEqual(reponse.status_code, 302)
        self.assertFalse(Affectation.objects.filter(id=self.affectation.id).exists())

    def test_refuse_si_des_notes_existent(self):
        from pedagogie.models import Note, Trimestre

        eleve = creer_utilisateur_actif("eleve-suppr-affect@example.com", Role.ELEVE)
        Note.objects.create(eleve=eleve, affectation=self.affectation, trimestre=Trimestre.T1, valeur=12)
        self.client.force_login(self.secretaire)
        reponse = self.client.post(reverse("scolarite:supprimer_affectation", args=[self.affectation.id]))
        self.assertEqual(reponse.status_code, 302)
        self.assertTrue(Affectation.objects.filter(id=self.affectation.id).exists())

    def test_supprimer_une_affectation_supprime_ses_creneaux(self):
        from pedagogie.models import CreneauEmploiDuTemps, JourSemaine

        CreneauEmploiDuTemps.objects.create(
            classe=self.classe, affectation=self.affectation, jour_semaine=JourSemaine.LUNDI,
            heure_debut="08:00", heure_fin="09:00",
        )
        self.client.force_login(self.secretaire)
        self.client.post(reverse("scolarite:supprimer_affectation", args=[self.affectation.id]))
        self.assertEqual(CreneauEmploiDuTemps.objects.count(), 0)

    def test_affectation_dune_autre_ecole_introuvable(self):
        from etablissement.models import Etablissement
        autre_ecole = Etablissement.objects.create(nom="Autre école suppr affect")
        autre_annee = AnneeScolaire.objects.create(
            etablissement=autre_ecole, libelle="2026-2027",
            date_debut=datetime.date(2026, 10, 1), date_fin=datetime.date(2027, 7, 31),
        )
        classe_exterieure = Classe.objects.create(nom="Classe externe", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=autre_annee)
        enseignant_exterieur = creer_utilisateur_actif("prof-exterieur-suppr@example.com", Role.ENSEIGNANT, etablissement=autre_ecole)
        affectation_exterieure = Affectation.objects.create(
            enseignant=enseignant_exterieur, classe=classe_exterieure, matiere="Histoire",
        )
        self.client.force_login(self.secretaire)
        reponse = self.client.post(reverse("scolarite:supprimer_affectation", args=[affectation_exterieure.id]))
        self.assertEqual(reponse.status_code, 404)
        self.assertTrue(Affectation.objects.filter(id=affectation_exterieure.id).exists())

    def test_un_enseignant_ne_peut_pas_supprimer_une_affectation(self):
        self.client.force_login(self.enseignant)
        reponse = self.client.post(reverse("scolarite:supprimer_affectation", args=[self.affectation.id]))
        self.assertEqual(reponse.status_code, 403)
        self.assertTrue(Affectation.objects.filter(id=self.affectation.id).exists())


class DossierEleveTests(TestCase):
    def setUp(self):
        self.annee = creer_annee()
        self.classe = Classe.objects.create(nom="5ème année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        EcheancierFrais.objects.create(
            classe=self.classe, montant_inscription=10000, periodicite=Periodicite.ANNUEL, montant_periode=20000, nombre_versements=1,
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
        self.fichier.close()

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
        fichier_invalide.close()
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
