"""
Graphiques du tableau de bord et des statistiques (anneau, barres, colonnes en SVG), raccourcis et « comptes à valider ».

Les graphiques ont les mêmes droits que les chiffres qu'ils illustrent : encaissements seulement avec le module Finances,
effectifs des seules classes que le rôle voit (un enseignant : les siennes, un directeur de cycle : son cycle).
"""
import datetime
from unittest import mock

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from comptes import graphiques
from comptes.roles import Role, StatutCompte
from finances.models import Paiement, TypeTranche, enregistrer_paiement
from scolarite.models import Classe, Cycle, Inscription
from statistiques.test_education import EducationBase, creer_compte

D = datetime.date
TABLEAU_DE_BORD = "/comptes/tableau-de-bord/"


class OutilsDeFormeTests(SimpleTestCase):
    def test_montant_compact(self):
        attendu = {
            0: "0", 999: "999", 1000: "1 k", 1499: "1 k", 1500: "2 k", 350_000: "350 k", 999_499: "999 k", 999_500: "1 M",
            1_000_000: "1 M", 1_200_000: "1,2 M", 1_460_000: "1,5 M", 12_000_000: "12 M", None: "0",
        }
        for valeur, texte in attendu.items():
            with self.subTest(valeur=valeur):
                self.assertEqual(graphiques.montant_compact(valeur), texte)

    def test_les_nombres_des_attributs_svg_n_ont_jamais_de_virgule(self):
        for valeur, texte in ((12.5, "12.5"), (33.3333333, "33.333"), (100, "100"), (0, "0"), (2, "2"), (0.0004, "0")):
            with self.subTest(valeur=valeur):
                self.assertEqual(graphiques.nombre_svg(valeur), texte)

    def test_espaces(self):
        self.assertEqual(graphiques.espaces(1234567), "1 234 567")
        self.assertEqual(graphiques.espaces(12), "12")


class AnneauTests(SimpleTestCase):
    def test_deux_parts(self):
        figure = graphiques.anneau([("Garçons", 13, "bleu"), ("Filles", 14, "or")])
        premiere, seconde = figure["segments"]
        self.assertEqual(figure["total"], 27)
        self.assertFalse(figure["vide"])
        self.assertEqual((premiere["pourcentage"], seconde["pourcentage"]), ("48", "52"))
        for segment in figure["segments"]:  # un arc et son reste font toujours le tour complet (100 unités)
            self.assertAlmostEqual(float(segment["longueur"]) + float(segment["reste"]), 100, places=2)
        self.assertEqual(premiere["decalage"], "25")  # le premier arc commence en haut
        self.assertAlmostEqual(float(seconde["decalage"]), 25 - float(premiere["longueur"]), places=2)
        self.assertEqual(figure["resume"], "Garçons : 13 (48 %), Filles : 14 (52 %)")

    def test_sans_donnee(self):
        figure = graphiques.anneau([("Garçons", 0, "bleu"), ("Filles", 0, "or")])
        self.assertTrue(figure["vide"])
        self.assertEqual(figure["resume"], "aucune donnée")
        self.assertFalse(any(segment["dessine"] for segment in figure["segments"]))

    def test_une_part_nulle_n_est_pas_dessinee_mais_reste_dans_la_legende(self):
        figure = graphiques.anneau([("Admis", 5, "vert"), ("Redoublants", 0, "rouge")])
        self.assertEqual([segment["dessine"] for segment in figure["segments"]], [True, False])
        self.assertEqual(figure["segments"][0]["pourcentage"], "100")
        self.assertEqual(len(figure["segments"]), 2)

    def test_les_valeurs_vides_comptent_pour_zero(self):
        self.assertEqual(graphiques.anneau([("A", None, "bleu"), ("B", 4, "or")])["total"], 4)


class BarresEtColonnesTests(SimpleTestCase):
    def test_la_plus_longue_barre_prend_toute_la_largeur(self):
        figure = graphiques.barres([("6ème A", 8), ("7ème A", 6), ("9ème A", 2)])
        self.assertEqual([ligne["largeur"] for ligne in figure["lignes"]], ["100", "75", "25"])
        self.assertEqual(figure["lignes"][0]["texte"], "8")
        self.assertEqual(figure["resume"], "6ème A : 8, 7ème A : 6, 9ème A : 2")

    def test_unite_et_teinte(self):
        figure = graphiques.barres([("Inscription", 455_000, "vert")], unite="FCFA")
        self.assertEqual(figure["lignes"][0]["texte"], "455 000 FCFA")
        self.assertEqual(figure["lignes"][0]["teinte"], "vert")

    def test_barres_sans_donnee(self):
        self.assertTrue(graphiques.barres([])["vide"])
        figure = graphiques.barres([("A", 0), ("B", 0)])
        self.assertEqual([ligne["largeur"] for ligne in figure["lignes"]], ["0", "0"])

    def test_la_plus_haute_colonne_prend_toute_la_hauteur(self):
        figure = graphiques.colonnes([("mai", 0, False), ("juin", 500, False), ("juil.", 1000, True)], unite="FCFA")
        mai, juin, juillet = figure["colonnes"]
        self.assertEqual((mai["hauteur"], mai["y"]), ("0", "100"))
        self.assertEqual((juin["hauteur"], juin["y"]), ("50", "50"))
        self.assertEqual((juillet["hauteur"], juillet["y"]), ("100", "0"))
        self.assertEqual([c["courant"] for c in figure["colonnes"]], [False, False, True])
        self.assertEqual(juillet["complet"], "1 000 FCFA")
        self.assertFalse(figure["vide"])

    def test_une_petite_valeur_reste_visible(self):
        figure = graphiques.colonnes([("a", 1, False), ("b", 100_000, False)])
        self.assertEqual(figure["colonnes"][0]["hauteur"], "2")

    def test_colonnes_toutes_nulles(self):
        figure = graphiques.colonnes([("a", 0, False), ("b", 0, True)])
        self.assertTrue(figure["vide"])
        self.assertEqual({c["hauteur"] for c in figure["colonnes"]}, {"0"})


class EncaissementsParMoisTests(EducationBase):
    def setUp(self):
        self.caissier = creer_compte(Role.COMPTABLE, "caisse@graphiques.test", self.ecole)

    def payer(self, eleve_cle, montant, quand, supprime=False):
        inscription = self.i[eleve_cle]
        paiement = enregistrer_paiement(
            eleve=inscription.eleve, inscription=inscription, tranche=TypeTranche.VERSEMENT, montant=montant,
            mode_paiement="especes", enregistre_par=self.caissier,
        )
        Paiement.objects.filter(pk=paiement.pk).update(
            date_paiement=timezone.make_aware(datetime.datetime(quand.year, quand.month, quand.day, 10, 0)), est_supprime=supprime,
        )
        return paiement

    def test_six_mois_le_mois_en_cours_en_dernier(self):
        self.payer("e5", 10_000, D(2026, 10, 3))
        self.payer("e6", 5_000, D(2026, 10, 20))
        self.payer("e5", 20_000, D(2026, 8, 12))
        self.payer("e7", 7_000, D(2026, 5, 31))
        mois = graphiques.encaissements_par_mois(self.ecole, aujourdhui=D(2026, 10, 15))
        self.assertEqual(mois, [
            ("mai", 7_000, False), ("juin", 0, False), ("juil.", 0, False), ("août", 20_000, False), ("sept.", 0, False),
            ("oct.", 15_000, True),
        ])

    def test_le_passage_d_une_annee_a_l_autre(self):
        self.payer("e5", 9_000, D(2026, 12, 20))
        self.payer("e5", 4_000, D(2027, 2, 1))
        mois = graphiques.encaissements_par_mois(self.ecole, aujourdhui=D(2027, 2, 10))
        self.assertEqual([libelle for libelle, _, _ in mois], ["sept.", "oct.", "nov.", "déc.", "janv.", "févr."])
        self.assertEqual([total for _, total, _ in mois], [0, 0, 0, 9_000, 0, 4_000])

    def test_plus_ancien_que_six_mois_ne_compte_pas(self):
        self.payer("e5", 50_000, D(2026, 3, 15))
        mois = graphiques.encaissements_par_mois(self.ecole, aujourdhui=D(2026, 10, 15))
        self.assertEqual(sum(total for _, total, _ in mois), 0)

    def test_un_paiement_supprime_ne_compte_pas(self):
        self.payer("e5", 10_000, D(2026, 10, 3))
        self.payer("e6", 99_000, D(2026, 10, 4), supprime=True)
        self.assertEqual(graphiques.encaissements_par_mois(self.ecole, aujourdhui=D(2026, 10, 15))[-1][1], 10_000)

    def test_jamais_les_paiements_d_une_autre_ecole(self):
        eleve_b = creer_compte(Role.ELEVE, "eleve-b@graphiques.test", self.ecole_b)
        inscription_b = Inscription.objects.create(eleve=eleve_b, classe=self.classe_b)
        paiement = enregistrer_paiement(
            eleve=eleve_b, inscription=inscription_b, tranche=TypeTranche.VERSEMENT, montant=77_000, mode_paiement="especes",
            enregistre_par=creer_compte(Role.COMPTABLE, "caisse-b@graphiques.test", self.ecole_b),
        )
        Paiement.objects.filter(pk=paiement.pk).update(date_paiement=timezone.make_aware(datetime.datetime(2026, 10, 5, 9, 0)))
        self.payer("e5", 10_000, D(2026, 10, 3))
        self.assertEqual(graphiques.encaissements_par_mois(self.ecole, aujourdhui=D(2026, 10, 15))[-1][1], 10_000)
        self.assertEqual(graphiques.encaissements_par_mois(self.ecole_b, aujourdhui=D(2026, 10, 15))[-1][1], 77_000)


class TableauDeBordTests(EducationBase):
    def setUp(self):
        self.fondateur = creer_compte(Role.FONDATEUR, "fondateur@graphiques.test", self.ecole)

    def page(self, compte):
        self.client.force_login(compte)
        return self.client.get(TABLEAU_DE_BORD)

    def test_la_direction_voit_les_encaissements_et_les_effectifs(self):
        reponse = self.page(self.fondateur)
        self.assertEqual(reponse.status_code, 200)
        graphique = reponse.context["graphiques"]
        self.assertEqual(len(graphique["encaissements"]), 6)
        self.assertEqual(graphique["devise"], "FCFA")
        effectifs = dict(graphique["effectifs"])
        self.assertEqual(effectifs["9A"], 2)
        self.assertEqual(effectifs["6A"], 3)
        self.assertNotIn(self.classe_5a.nom, effectifs)  # l'année précédente n'est pas l'année active
        self.assertContains(reponse, "graphique-colonnes")
        self.assertContains(reponse, "graphique-barres")
        self.assertContains(reponse, "Encaissements des 6 derniers mois")

    def test_un_enseignant_n_a_aucun_graphique_sans_les_modules_correspondants(self):
        """Mêmes droits que les chiffres : ni Finances ni Élèves dans sa matrice, donc ni encaissements ni effectifs."""
        reponse = self.page(self.t2)
        self.assertEqual(reponse.context["graphiques"], {})
        self.assertNotContains(reponse, "Encaissements des 6 derniers mois")
        self.assertNotContains(reponse, "Effectifs par classe")

    def test_un_directeur_de_cycle_ne_voit_que_son_cycle(self):
        directeur = creer_compte(Role.DIRECTEUR_2EME_CYCLE, "d2@graphiques.test", self.ecole)
        graphique = self.page(directeur).context["graphiques"]
        self.assertEqual({nom for nom, _ in graphique.get("effectifs", [])}, {"9A"})

    def test_jamais_les_classes_d_une_autre_ecole(self):
        Classe.objects.create(nom="Classe de l'école B", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee_b)
        noms = {nom for nom, _ in self.page(self.fondateur).context["graphiques"]["effectifs"]}
        self.assertNotIn("Classe de l'école B", noms)

    def test_au_dela_de_dix_classes_on_garde_les_dix_plus_grandes(self):
        for numero in range(8):
            Classe.objects.create(nom=f"Vide {numero}", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=self.annee)
        reponse = self.page(self.fondateur)
        graphique = reponse.context["graphiques"]
        self.assertEqual(len(graphique["effectifs"]), 10)
        self.assertTrue(graphique["effectifs_limites"])
        noms = {nom for nom, _ in graphique["effectifs"]}
        self.assertTrue({"6A", "6B", "9A"} <= noms)  # les classes qui ont des élèves restent
        self.assertContains(reponse, "Les 10 plus grandes classes")

    def test_pas_de_style_en_ligne_dans_les_graphiques(self):
        """La politique de sécurité du site interdit les styles en ligne : les graphiques n'en ont jamais."""
        html = self.page(self.fondateur).content.decode()
        debut = html.index("graphique-colonnes")
        self.assertNotIn(" style=", html[debut:])

    def test_raccourcis_des_taches_et_plus_de_doublons_du_menu(self):
        reponse = self.page(self.fondateur)
        libelles = [action["label"] for action in reponse.context["actions_rapides"]]
        self.assertEqual(libelles, ["Inscrire un élève", "Enregistrer un paiement", "Publier une annonce"])
        self.assertNotContains(reponse, "Modules auxquels vous avez accès")

    def test_un_enseignant_n_a_ni_inscription_ni_paiement_dans_ses_raccourcis(self):
        libelles = [action["label"] for action in self.page(self.t2).context["actions_rapides"]]
        self.assertNotIn("Inscrire un élève", libelles)
        self.assertNotIn("Enregistrer un paiement", libelles)

    def test_comptes_a_valider(self):
        creer_compte(Role.ENSEIGNANT, "attente@graphiques.test", self.ecole)
        creer_compte(Role.ENSEIGNANT, "attente-b@graphiques.test", self.ecole_b)  # autre école : ne compte jamais
        from comptes.models import Utilisateur
        Utilisateur.objects.filter(email="attente@graphiques.test").update(statut=StatutCompte.EN_ATTENTE_VALIDATION)
        Utilisateur.objects.filter(email="attente-b@graphiques.test").update(statut=StatutCompte.EN_ATTENTE_VALIDATION)
        reponse = self.page(self.fondateur)
        carte = next(i for i in reponse.context["indicateurs"] if i["label"] == "Comptes à valider")
        self.assertEqual((carte["valeur"], carte["url"]), (1, "comptes:comptes_en_attente"))
        self.assertContains(reponse, reverse("comptes:comptes_en_attente"))
        self.assertNotIn("Comptes à valider", [i["label"] for i in self.page(self.t2).context["indicateurs"]])

    def test_pas_de_carte_comptes_a_valider_quand_il_n_y_en_a_pas(self):
        self.assertNotIn("Comptes à valider", [i["label"] for i in self.page(self.fondateur).context["indicateurs"]])

    def test_le_message_aucun_module_ne_s_affiche_que_sans_aucun_module(self):
        self.assertNotContains(self.page(self.fondateur), "Aucun module ne vous est encore attribué")
        with mock.patch("permissions_matrix.models.PermissionMatrix.modules_autorises", return_value=set()):
            reponse = self.page(self.fondateur)
        self.assertTrue(reponse.context["aucun_module"])
        self.assertContains(reponse, "Aucun module ne vous est encore attribué")


class PagesDeStatistiquesTests(EducationBase):
    def setUp(self):
        self.client.force_login(creer_compte(Role.FONDATEUR, "stats@graphiques.test", self.ecole))

    def test_vue_d_ensemble_garcons_filles_et_effectifs(self):
        reponse = self.client.get(reverse("statistiques:vue_ensemble"))
        parts = reponse.context["repartition_sexe_graphique"]
        self.assertEqual([(libelle, valeur) for libelle, valeur, _ in parts], [
            ("Garçons", reponse.context["repartition_sexe"]["M"]), ("Filles", reponse.context["repartition_sexe"]["F"]),
        ])
        self.assertContains(reponse, "graphique-anneau")
        self.assertContains(reponse, "graphique-barres")
        self.assertEqual(dict(reponse.context["par_classe"])["9A"], 2)
        self.assertNotContains(reponse, "Décisions de fin d")  # aucune décision saisie : pas d'anneau vide

    def test_l_anneau_des_decisions_apparait_une_fois_les_decisions_saisies(self):
        Inscription.objects.filter(pk=self.i["e5"].pk).update(statut=Inscription.Statut.ADMIS)
        Inscription.objects.filter(pk=self.i["e6"].pk).update(statut=Inscription.Statut.REDOUBLE)
        reponse = self.client.get(reverse("statistiques:vue_ensemble"))
        self.assertContains(reponse, "Décisions de fin d")
        self.assertEqual([(libelle, valeur) for libelle, valeur, _ in reponse.context["decisions_graphique"]], [("Admis", 1), ("Redoublants", 1)])

    def test_une_classe(self):
        reponse = self.client.get(reverse("statistiques:statistiques_classe", args=[self.c9a.pk]))
        self.assertContains(reponse, "graphique-anneau")
        self.assertEqual(sum(valeur for _, valeur, _ in reponse.context["repartition_sexe_graphique"]), 2)

    def test_finances_barres_seulement_s_il_y_a_des_encaissements(self):
        adresse = reverse("statistiques:statistiques_finances")
        self.assertNotContains(self.client.get(adresse), "Encaissé par échéance")
        enregistrer_paiement(
            eleve=self.e5, inscription=self.i["e5"], tranche=TypeTranche.INSCRIPTION, montant=30_000, mode_paiement="especes",
            enregistre_par=creer_compte(Role.COMPTABLE, "caisse@stats.test", self.ecole),
        )
        reponse = self.client.get(adresse)
        self.assertContains(reponse, "Encaissé par échéance")
        self.assertContains(reponse, "30 000 FCFA")

    def test_le_sous_menu_marque_la_page_courante(self):
        reponse = self.client.get(reverse("statistiques:vue_ensemble")).content.decode()
        self.assertEqual(reponse.count('aria-current="page"'), 1)
        self.assertIn('<nav class="sous-menu" aria-label="Rapports de statistiques">', reponse)
        finances = self.client.get(reverse("statistiques:statistiques_finances")).content.decode()
        self.assertEqual(finances.count('aria-current="page"'), 1)
        self.assertRegex(finances, r'nav-lien-stats actif"\s+aria-current="page">\s*Finances')
