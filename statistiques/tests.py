import datetime

from django.test import TestCase
from django.urls import reverse

from comptes.models import Utilisateur
from comptes.roles import Role, StatutCompte
from finances.models import TypeTranche, enregistrer_paiement
from scolarite.models import AnneeScolaire, Classe, Cycle, Inscription


def creer_utilisateur_actif(email, role, **kwargs):
    utilisateur = Utilisateur(email=email, prenom="Test", nom="Utilisateur", role=role, **kwargs)
    utilisateur.set_password("MotDePasse#2026")
    utilisateur.statut = StatutCompte.ACTIF
    utilisateur.is_active = True
    utilisateur.full_clean(exclude=["password"])
    utilisateur.save()
    return utilisateur


class StatistiquesEnsembleTests(TestCase):
    def setUp(self):
        self.annee = AnneeScolaire.objects.create(
            libelle="2026-2027", date_debut=datetime.date(2026, 10, 1),
            date_fin=datetime.date(2027, 7, 31), est_active=True,
        )
        self.classe_1er = Classe.objects.create(nom="2ème année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        self.classe_2eme = Classe.objects.create(nom="8ème année A", cycle=Cycle.DEUXIEME_CYCLE, annee_scolaire=self.annee)

        for i, sexe in enumerate(["M", "M", "F"]):
            eleve = creer_utilisateur_actif(f"eleve-stat-1er-{i}@example.com", Role.ELEVE, sexe=sexe)
            Inscription.objects.create(eleve=eleve, classe=self.classe_1er)
        for i, sexe in enumerate(["F", "F"]):
            eleve = creer_utilisateur_actif(f"eleve-stat-2eme-{i}@example.com", Role.ELEVE, sexe=sexe)
            Inscription.objects.create(eleve=eleve, classe=self.classe_2eme)

        self.direction = creer_utilisateur_actif("direction-stat@example.com", Role.FONDATEUR)
        self.directeur_1er = creer_utilisateur_actif("dir1-stat@example.com", Role.DIRECTEUR_1ER_CYCLE)

    def test_effectif_total_et_repartition_par_sexe(self):
        self.client.force_login(self.direction)
        reponse = self.client.get(reverse("statistiques:vue_ensemble"), {"annee": self.annee.id})
        self.assertEqual(reponse.context["effectif_total"], 5)
        self.assertEqual(reponse.context["repartition_sexe"], {"M": 2, "F": 3})

    def test_sans_parametre_annee_utilise_lannee_active_automatiquement(self):
        self.client.force_login(self.direction)
        reponse = self.client.get(reverse("statistiques:vue_ensemble"))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.context["annee"], self.annee)

    def test_directeur_de_cycle_ne_voit_que_son_cycle(self):
        self.client.force_login(self.directeur_1er)
        reponse = self.client.get(reverse("statistiques:vue_ensemble"), {"annee": self.annee.id})
        self.assertEqual(reponse.context["effectif_total"], 3)
        self.assertEqual(reponse.context["repartition_sexe"], {"M": 2, "F": 1})
        classes_listees = list(reponse.context["classes"])
        self.assertIn(self.classe_1er, classes_listees)
        self.assertNotIn(self.classe_2eme, classes_listees)

    def test_statistiques_par_classe(self):
        self.client.force_login(self.direction)
        reponse = self.client.get(reverse("statistiques:statistiques_classe", args=[self.classe_1er.id]))
        self.assertEqual(reponse.context["effectif"], 3)


class StatistiquesFinancesTests(TestCase):
    def test_total_par_tranche(self):
        annee = AnneeScolaire.objects.create(
            libelle="2027-2028", date_debut=datetime.date(2027, 10, 1),
            date_fin=datetime.date(2028, 7, 31), est_active=True,
        )
        classe = Classe.objects.create(nom="3ème année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=annee)
        eleve = creer_utilisateur_actif("eleve-fin-stat@example.com", Role.ELEVE)
        inscription = Inscription.objects.create(eleve=eleve, classe=classe)
        comptable = creer_utilisateur_actif("comptable-fin-stat@example.com", Role.COMPTABLE)

        enregistrer_paiement(
            eleve=eleve, inscription=inscription, tranche=TypeTranche.INSCRIPTION,
            montant=30000, mode_paiement="especes", enregistre_par=comptable,
        )
        enregistrer_paiement(
            eleve=eleve, inscription=inscription, tranche=TypeTranche.TRANCHE_1,
            montant=15000, mode_paiement="especes", enregistre_par=comptable,
        )

        self.client.force_login(comptable)
        reponse = self.client.get(reverse("statistiques:statistiques_finances"), {"annee": annee.id})
        self.assertEqual(reponse.context["total_general"], 45000)


class ExportsCsvTests(TestCase):
    def setUp(self):
        self.annee = AnneeScolaire.objects.create(
            libelle="2028-2029", date_debut=datetime.date(2028, 10, 1),
            date_fin=datetime.date(2029, 7, 31), est_active=True,
        )
        self.classe = Classe.objects.create(nom="4ème année A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        self.direction = creer_utilisateur_actif("direction-csv@example.com", Role.FONDATEUR)
        eleve_m = creer_utilisateur_actif("eleve-csv-m@example.com", Role.ELEVE, sexe="M")
        eleve_f = creer_utilisateur_actif("eleve-csv-f@example.com", Role.ELEVE, sexe="F")
        Inscription.objects.create(eleve=eleve_m, classe=self.classe)
        Inscription.objects.create(eleve=eleve_f, classe=self.classe)

    def test_export_effectifs_csv(self):
        self.client.force_login(self.direction)
        reponse = self.client.get(reverse("statistiques:exporter_effectifs_csv"), {"annee": self.annee.id})
        self.assertEqual(reponse["Content-Type"], "text/csv; charset=utf-8")
        contenu = reponse.content.decode("utf-8-sig")
        self.assertIn("4ème année A", contenu)
        self.assertIn("Garçons", contenu)  # vérifie l'encodage : pas de "GarÃ§ons"
        self.assertIn("2", contenu)  # effectif total de 2

    def test_export_finances_csv(self):
        comptable = creer_utilisateur_actif("comptable-csv@example.com", Role.COMPTABLE)
        eleve = Utilisateur.objects.get(email="eleve-csv-m@example.com")
        inscription = Inscription.objects.get(eleve=eleve)
        enregistrer_paiement(
            eleve=eleve, inscription=inscription, tranche=TypeTranche.TRANCHE_1,
            montant=12000, mode_paiement="especes", enregistre_par=comptable,
        )
        self.client.force_login(comptable)
        reponse = self.client.get(reverse("statistiques:exporter_finances_csv"), {"annee": self.annee.id})
        self.assertEqual(reponse["Content-Type"], "text/csv; charset=utf-8")
        contenu = reponse.content.decode("utf-8-sig")
        self.assertIn("12000", contenu)
        self.assertIn("Total général", contenu)

    def test_enseignant_sans_acces_statistiques_ne_peut_pas_exporter(self):
        enseignant = creer_utilisateur_actif("prof-csv@example.com", Role.ENSEIGNANT)
        self.client.force_login(enseignant)
        reponse = self.client.get(reverse("statistiques:exporter_effectifs_csv"))
        self.assertEqual(reponse.status_code, 403)
