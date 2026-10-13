"""
Indicateurs du rapport de la CPS ajoutés à la fiche annuelle : indice de parité F/G, pourcentage de redoublants par
sexe, élèves par classe et par enseignant par cycle, part de femmes parmi les enseignants, taux de promotion, de
redoublement et d'abandon par niveau et par sexe.

Chiffres calculés à la main à partir du jeu de données de EducationBase (voir son commentaire) :
- 1er cycle : 2 classes, 2 garçons (e2 e4), 2 filles (e1 e3), e1 redouble -> 25 % ; enseignants t1 (F) et t2 (M)
- 2ème cycle : 1 classe, e5 F e6 M, aucun redoublant ; enseignant t2 (M)
- Lycée : e7 F e8 M ; enseignant t3 (sexe non renseigné)
- Professionnel : e9 M seul ; aucun enseignant
"""
from django.urls import reverse

from comptes.models import Utilisateur
from comptes.roles import Role
from scolarite.models import Affectation, Inscription
from statistiques.fiche import construire_fiche
from statistiques.test_education import EducationBase, lignes_attendues, lignes_du_classeur


class IndicateursCPSTests(EducationBase):
    def cycle(self, fiche, cycle):
        return next(ligne for ligne in fiche["cycles"] if ligne["cycle"] == cycle)

    def decider(self):
        """Décisions de fin d'année : 6A e1 admise, e2 redouble, e3 abandon ; 6B e4 transféré ; 9A e5 e6 admis ;
        TSE e7 admise, e8 sans décision ; CAP e9 redouble."""
        Statut = Inscription.Statut
        for nom, statut in [
            ("e1", Statut.ADMIS), ("e2", Statut.REDOUBLE), ("e3", Statut.ABANDON), ("e4", Statut.TRANSFERE),
            ("e5", Statut.ADMIS), ("e6", Statut.ADMIS), ("e7", Statut.ADMIS), ("e9", Statut.REDOUBLE),
        ]:
            Inscription.objects.filter(pk=self.i[nom].pk).update(statut=statut)

    def ligne_efficacite(self, fiche, cycle_libelle, niveau_libelle, groupe):
        return next(
            ligne for ligne in fiche["efficacite"]["lignes"]
            if (ligne["cycle_libelle"], ligne["niveau_libelle"], ligne["groupe"]) == (cycle_libelle, niveau_libelle, groupe)
        )

    # --- indicateurs par cycle ---------------------------------------------------------------------------------

    def test_les_cycles_sont_dans_l_ordre_de_l_enseignement(self):
        fiche = self.fiche_pour(self.fondateur)
        self.assertEqual(
            [ligne["cycle"] for ligne in fiche["cycles"]], ["1er_cycle", "2eme_cycle", "lycee", "professionnel"],
        )

    def test_premier_cycle(self):
        cycle = self.cycle(self.fiche_pour(self.fondateur), "1er_cycle")
        self.assertEqual((cycle["classes"], cycle["garcons"], cycle["filles"], cycle["total"]), (2, 2, 2, 4))
        self.assertEqual((cycle["indice_parite"], cycle["eleves_par_classe"]), (1.0, 2.0))
        self.assertEqual((cycle["redoublants_garcons"], cycle["redoublants_filles"], cycle["redoublants"]), (0, 1, 1))
        self.assertEqual(
            (cycle["pourcentage_redoublants_garcons"], cycle["pourcentage_redoublants_filles"],
             cycle["pourcentage_redoublants"]), (0.0, 50.0, 25.0),
        )
        self.assertEqual(
            (cycle["enseignants"], cycle["enseignantes"], cycle["pourcentage_femmes"], cycle["eleves_par_enseignant"]),
            (2, 1, 50.0, 2.0),
        )

    def test_cycle_sans_redoublant_sans_enseignante_et_sans_enseignant(self):
        fiche = self.fiche_pour(self.fondateur)
        second = self.cycle(fiche, "2eme_cycle")
        self.assertEqual((second["redoublants"], second["pourcentage_redoublants"]), (0, 0.0))
        self.assertEqual((second["enseignants"], second["enseignantes"], second["pourcentage_femmes"]), (1, 0, 0.0))
        lycee = self.cycle(fiche, "lycee")
        self.assertEqual((lycee["enseignants"], lycee["pourcentage_femmes"]), (1, None))  # sexe de t3 non renseigné
        professionnel = self.cycle(fiche, "professionnel")
        self.assertEqual((professionnel["garcons"], professionnel["filles"], professionnel["indice_parite"]), (1, 0, 0.0))
        self.assertEqual(
            (professionnel["enseignants"], professionnel["eleves_par_enseignant"], professionnel["pourcentage_femmes"]),
            (0, None, None),
        )  # division par zéro évitée

    def test_sans_garcon_l_indice_de_parite_n_est_pas_calcule(self):
        Inscription.objects.filter(pk__in=[self.i["e2"].pk, self.i["e4"].pk]).delete()
        self.assertIsNone(self.cycle(self.fiche_pour(self.fondateur), "1er_cycle")["indice_parite"])

    def test_sans_annee_precedente_les_redoublants_par_cycle_ne_sont_pas_calcules(self):
        cycle = construire_fiche(self.fondateur_b, self.annee_b)["cycles"][0]  # classe vide, école sans historique
        self.assertEqual((cycle["total"], cycle["eleves_par_classe"], cycle["indice_parite"]), (0, 0.0, None))
        self.assertEqual((cycle["redoublants"], cycle["pourcentage_redoublants"]), (None, None))
        self.assertEqual((cycle["enseignants"], cycle["eleves_par_enseignant"]), (0, None))

    def test_part_de_femmes_parmi_les_enseignants(self):
        enseignants = self.fiche_pour(self.fondateur)["enseignants"]
        self.assertEqual((enseignants["hommes"], enseignants["femmes"], enseignants["sexe_inconnu"]), (1, 1, 1))
        self.assertEqual(enseignants["pourcentage_femmes"], 50.0)  # sur les deux dont le sexe est renseigné
        self.assertIsNone(construire_fiche(self.fondateur_b, self.annee_b)["enseignants"]["pourcentage_femmes"])

    def test_un_enseignant_de_deux_cycles_est_compte_dans_chacun_mais_une_fois_au_total(self):
        Affectation.objects.create(enseignant=self.t1, classe=self.c9a, matiere="Physique")
        fiche = self.fiche_pour(self.fondateur)
        self.assertEqual(self.cycle(fiche, "2eme_cycle")["enseignants"], 2)  # t2 et t1
        self.assertEqual(fiche["enseignants"]["total"], 3)

    # --- promotion, redoublement, abandon ----------------------------------------------------------------------

    def test_aucune_decision_de_fin_d_annee(self):
        efficacite = self.fiche_pour(self.fondateur)["efficacite"]
        self.assertEqual((efficacite["lignes"], efficacite["totaux"]), ([], []))
        self.assertEqual((efficacite["transferes"], efficacite["sans_decision"]), (0, 9))

    def test_taux_de_promotion_de_redoublement_et_d_abandon(self):
        self.decider()
        fiche = self.fiche_pour(self.fondateur)
        efficacite = fiche["efficacite"]
        self.assertEqual((efficacite["transferes"], efficacite["sans_decision"]), (1, 1))  # e4 ; e8

        garcons = self.ligne_efficacite(fiche, "1er cycle", "6ème année", "Garçons")  # e2 seul
        self.assertEqual((garcons["decides"], garcons["promus"], garcons["redoublent"], garcons["abandons"]), (1, 0, 1, 0))
        self.assertEqual(
            (garcons["taux_promotion"], garcons["taux_redoublement"], garcons["taux_abandon"]), (0.0, 100.0, 0.0),
        )
        self.assertTrue(garcons["debut_niveau"])
        filles = self.ligne_efficacite(fiche, "1er cycle", "6ème année", "Filles")  # e1 admise, e3 abandon
        self.assertEqual((filles["decides"], filles["taux_promotion"], filles["taux_abandon"]), (2, 50.0, 50.0))
        self.assertFalse(filles["debut_niveau"])
        ensemble = self.ligne_efficacite(fiche, "1er cycle", "6ème année", "Ensemble")  # e4 transféré : exclu
        self.assertEqual(
            (ensemble["decides"], ensemble["taux_promotion"], ensemble["taux_redoublement"], ensemble["taux_abandon"]),
            (3, 33.3, 33.3, 33.3),
        )
        self.assertEqual(self.ligne_efficacite(fiche, "2ème cycle", "9ème année", "Ensemble")["taux_promotion"], 100.0)

    def test_un_groupe_sans_decision_n_a_pas_de_ligne(self):
        self.decider()
        lignes = [ligne for ligne in self.fiche_pour(self.fondateur)["efficacite"]["lignes"]
                  if ligne["niveau_libelle"] == "12ème année"]
        self.assertEqual([ligne["groupe"] for ligne in lignes], ["Filles", "Ensemble"])  # e8 (garçon) : pas de décision
        self.assertTrue(lignes[0]["debut_niveau"])  # le nom du niveau s'affiche sur la première ligne présente
        self.assertFalse(lignes[1]["debut_niveau"])

    def test_totaux_de_l_etablissement(self):
        self.decider()
        totaux = {ligne["groupe"]: ligne for ligne in self.fiche_pour(self.fondateur)["efficacite"]["totaux"]}
        # garçons : e2 redouble, e6 admis, e9 redouble ; filles : e1 admise, e3 abandon, e5 admise, e7 admise
        garcons, filles, ensemble = totaux["Garçons"], totaux["Filles"], totaux["Ensemble"]
        self.assertEqual(
            (garcons["decides"], garcons["taux_promotion"], garcons["taux_redoublement"], garcons["taux_abandon"]),
            (3, 33.3, 66.7, 0.0),
        )
        self.assertEqual(
            (filles["decides"], filles["taux_promotion"], filles["taux_redoublement"], filles["taux_abandon"]),
            (4, 75.0, 0.0, 25.0),
        )
        self.assertEqual((ensemble["decides"], ensemble["promus"], ensemble["redoublent"], ensemble["abandons"]), (7, 4, 2, 1))
        self.assertEqual(
            (ensemble["taux_promotion"], ensemble["taux_redoublement"], ensemble["taux_abandon"]), (57.1, 28.6, 14.3),
        )

    # --- cloisonnement -----------------------------------------------------------------------------------------

    def test_le_directeur_de_cycle_ne_voit_que_son_cycle(self):
        self.decider()
        fiche = self.fiche_pour(self.dir_1er)
        self.assertEqual([ligne["cycle"] for ligne in fiche["cycles"]], ["1er_cycle"])
        self.assertEqual({ligne["cycle_libelle"] for ligne in fiche["efficacite"]["lignes"]}, {"1er cycle"})
        ensemble = next(ligne for ligne in fiche["efficacite"]["totaux"] if ligne["groupe"] == "Ensemble")
        self.assertEqual(ensemble["decides"], 3)  # e1 e2 e3 seulement
        self.assertEqual((fiche["efficacite"]["transferes"], fiche["efficacite"]["sans_decision"]), (1, 0))

    def test_l_autre_ecole_ne_voit_aucune_decision_de_l_ecole_a(self):
        self.decider()
        fiche = construire_fiche(self.fondateur_b, self.annee_b)
        self.assertEqual((fiche["efficacite"]["lignes"], fiche["efficacite"]["transferes"]), ([], 0))
        self.assertEqual([ligne["total"] for ligne in fiche["cycles"]], [0])

    def test_les_exports_du_directeur_de_cycle_ne_contiennent_pas_les_autres_cycles(self):
        self.decider()
        self.client.force_login(self.dir_1er)
        for nom in ("exporter_fiche_annuelle_csv", "exporter_fiche_annuelle_xlsx"):
            contenu = self.client.get(reverse(f"statistiques:{nom}"), {"annee": self.annee.id}).content
            texte = contenu.decode("utf-8") if nom.endswith("csv") else " ".join(
                str(valeur) for ligne in lignes_du_classeur(contenu) for valeur in ligne
            )
            with self.subTest(export=nom):
                self.assertIn("1er cycle", texte)
                for autre in ("2ème cycle", "Lycée", "Enseignement professionnel", "9ème année", "Baccalauréat"):
                    self.assertNotIn(autre, texte)

    def test_les_exports_ne_contiennent_aucun_nom_ni_matricule(self):
        self.decider()
        self.client.force_login(self.fondateur)
        contenu = self.client.get(
            reverse("statistiques:exporter_fiche_annuelle_csv"), {"annee": self.annee.id},
        ).content.decode("utf-8")
        for eleve in Utilisateur.objects.filter(role=Role.ELEVE, etablissement=self.ecole):
            self.assertNotIn(eleve.matricule, contenu)
            self.assertNotIn(eleve.email, contenu)

    # --- exports et page ---------------------------------------------------------------------------------------

    def test_csv_et_excel_contiennent_les_nouvelles_rubriques(self):
        self.decider()
        self.client.force_login(self.fondateur)
        parametres = {"annee": self.annee.id}
        csv_ = self.client.get(reverse("statistiques:exporter_fiche_annuelle_csv"), parametres).content.decode("utf-8")
        for attendu in (
            "INDICATEURS PAR CYCLE",
            "1er cycle;2;2;2;4;1.0;2.0;0;1;1;0.0;50.0;25.0;2;1;50.0;2.0",
            "PROMOTION, REDOUBLEMENT ET ABANDON (décisions de fin d'année)",
            "1er cycle;6ème année;Garçons;1;0;1;0;0.0;100.0;0.0",
            "TOTAL;;Ensemble;7;4;2;1;57.1;28.6;14.3",
            "Transférés vers une autre école (non comptés dans les taux);1",
            "Enseignantes (femmes);1",
            "Part de femmes parmi les enseignants dont le sexe est renseigné (%);50.0",
        ):
            self.assertIn(attendu, csv_)
        reponse = self.client.get(reverse("statistiques:exporter_fiche_annuelle_xlsx"), parametres)
        lignes = lignes_du_classeur(reponse.content)
        self.assertEqual(lignes, lignes_attendues(construire_fiche(self.fondateur, self.annee)))
        self.assertIn(["TOTAL", None, "Ensemble", 7, 4, 2, 1, 57.1, 28.6, 14.3], lignes)  # de vrais nombres
        self.assertIn(["1er cycle", 2, 2, 2, 4, 1, 2, 0, 1, 1, 0, 50, 25, 2, 1, 50, 2], lignes)

    def test_sans_decision_les_exports_l_indiquent_au_lieu_d_une_table_vide(self):
        self.client.force_login(self.fondateur)
        csv_ = self.client.get(
            reverse("statistiques:exporter_fiche_annuelle_csv"), {"annee": self.annee.id},
        ).content.decode("utf-8")
        self.assertIn("Aucune décision de fin d'année (admis, redouble, abandon) enregistrée pour cette année", csv_)
        self.assertNotIn("Taux de promotion (%)", csv_)
        self.assertIn("Sans décision de fin d'année (non comptés dans les taux);9", csv_)

    def test_la_page_affiche_les_nouvelles_rubriques(self):
        self.decider()
        self.client.force_login(self.fondateur)
        page = self.client.get(reverse("statistiques:fiche_annuelle"), {"annee": self.annee.id})
        for texte in ("Indicateurs par cycle", "Parité F/G", "Promotion, redoublement et abandon", "Taux de promotion",
                      "Part de femmes", "57,1 %", "vers une autre école", "rapport de suivi des indicateurs"):
            self.assertContains(page, texte)
        # sans décision : message explicatif à la place du tableau
        Inscription.objects.filter(classe__annee_scolaire=self.annee).update(statut=Inscription.Statut.EN_COURS)
        page = self.client.get(reverse("statistiques:fiche_annuelle"), {"annee": self.annee.id})
        self.assertContains(page, "encore enregistrée pour cette année")
        self.assertNotContains(page, "Taux de redoublement")

    def test_la_page_d_une_ecole_sans_historique_s_affiche(self):
        self.client.force_login(self.fondateur_b)
        page = self.client.get(reverse("statistiques:fiche_annuelle"), {"annee": self.annee_b.id})
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Indicateurs par cycle")
