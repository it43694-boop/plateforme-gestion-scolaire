"""
Vente de tenues : le stock (arrivage, vente, correction), la vente au comptoir (reçu, Caisse, comptabilité), l'annulation par la direction,
les droits (comptable et direction seulement) et le cloisonnement entre écoles.
"""
from unittest import mock

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse

from comptabilite.models import Ecriture
from comptabilite.services import ecarts_caisse, synchroniser_caisse, vecteur_attendu
from comptabilite.test_services import ComptaBase, compte_utilisateur
from comptes.roles import Role
from finances import tenues
from finances.models import ArticleTenue, LigneVenteTenue, MotifStockTenue, MouvementCaisse, MouvementStockTenue, VenteTenue
from statistiques.test_education import EducationBase, creer_compte


def client_de(compte):
    client = Client()
    if compte is not None:
        client.force_login(compte)
    return client


class TenuesBase(EducationBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.polo = cls.article(cls.ecole, "Chemisette bleue", "8 ans", 4500, stock=10)
        cls.pantalon = cls.article(cls.ecole, "Pantalon", "10 ans", 6000, stock=3)
        cls.jupe = cls.article(cls.ecole, "Jupe", "", 5500, stock=0)
        cls.retire = cls.article(cls.ecole, "Ancienne blouse", "M", 3000, stock=5, actif=False)
        cls.article_b = cls.article(cls.ecole_b, "Polo vert", "8 ans", 4000, stock=7)

    @classmethod
    def article(cls, ecole, libelle, taille, prix, stock=0, actif=True):
        article = ArticleTenue.objects.create(etablissement=ecole, libelle=libelle, taille=taille, prix=prix, actif=actif)
        if stock:
            ArticleTenue.objects.filter(pk=article.pk).update(stock=stock)
            article.refresh_from_db()
        return article

    def vendre(self, quantites, **options):
        base = dict(etablissement=self.ecole, eleve=None, acheteur="Mme Traoré", mode_paiement="especes", acteur=self.comptable)
        return tenues.vendre(quantites=quantites, **{**base, **options})

    def stock_de(self, article):
        article.refresh_from_db()
        return article.stock


# ---------------------------------------------------------------------------------------------------------------------
# Le stock
# ---------------------------------------------------------------------------------------------------------------------

class StockTests(TenuesBase):
    def test_un_arrivage_augmente_le_stock_et_laisse_une_trace(self):
        tenues.approvisionner(article=self.pantalon, quantite=20, note="Fournisseur Kone, bon 14", acteur=self.comptable)
        self.assertEqual(self.stock_de(self.pantalon), 23)
        mouvement = MouvementStockTenue.objects.get(article=self.pantalon)
        self.assertEqual((mouvement.quantite, mouvement.motif, mouvement.stock_apres, mouvement.cree_par), (20, MotifStockTenue.ARRIVAGE, 23, self.comptable))
        self.assertEqual(mouvement.note, "Fournisseur Kone, bon 14")

    def test_un_arrivage_nul_ou_negatif_est_refuse(self):
        for quantite in (0, -4):
            with self.subTest(quantite=quantite), self.assertRaises(ValidationError):
                tenues.approvisionner(article=self.polo, quantite=quantite, note="", acteur=self.comptable)
        self.assertEqual(self.stock_de(self.polo), 10)

    def test_une_correction_d_inventaire_exige_un_motif_et_un_ecart(self):
        with self.assertRaisesMessage(ValidationError, "motif"):
            tenues.corriger_stock(article=self.polo, nouveau_stock=8, note="  ", acteur=self.comptable)
        with self.assertRaisesMessage(ValidationError, "déjà de 10"):
            tenues.corriger_stock(article=self.polo, nouveau_stock=10, note="Inventaire", acteur=self.comptable)
        with self.assertRaises(ValidationError):
            tenues.corriger_stock(article=self.polo, nouveau_stock=-1, note="Inventaire", acteur=self.comptable)
        tenues.corriger_stock(article=self.polo, nouveau_stock=7, note="Trois polos abîmés", acteur=self.comptable)
        self.assertEqual(self.stock_de(self.polo), 7)
        mouvement = MouvementStockTenue.objects.get(article=self.polo)
        self.assertEqual((mouvement.quantite, mouvement.motif, mouvement.stock_apres), (-3, MotifStockTenue.CORRECTION, 7))

    def test_la_base_refuse_un_stock_negatif(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ArticleTenue.objects.filter(pk=self.polo.pk).update(stock=-1)

    def test_un_article_est_unique_par_ecole_nom_et_taille(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ArticleTenue.objects.create(etablissement=self.ecole, libelle="Chemisette bleue", taille="8 ans", prix=1)
        ArticleTenue.objects.create(etablissement=self.ecole, libelle="Chemisette bleue", taille="10 ans", prix=4500)  # une autre taille est permise
        ArticleTenue.objects.create(etablissement=self.ecole_b, libelle="Chemisette bleue", taille="8 ans", prix=4000)  # et une autre école aussi

    def test_une_valeur_de_stock_ne_se_saisit_pas_dans_un_formulaire(self):
        self.assertFalse(ArticleTenue._meta.get_field("stock").editable)
        self.assertEqual(str(self.polo), "Chemisette bleue - 8 ans")
        self.assertEqual(str(self.jupe), "Jupe")
        self.assertTrue(self.jupe.en_alerte)
        self.assertFalse(self.polo.en_alerte)


# ---------------------------------------------------------------------------------------------------------------------
# La vente
# ---------------------------------------------------------------------------------------------------------------------

class VenteTests(TenuesBase):
    def test_une_vente_complete(self):
        vente = self.vendre({self.polo.pk: 2, self.pantalon.pk: 1})
        self.assertEqual(vente.total, 2 * 4500 + 6000)
        self.assertRegex(vente.reference, r"^TEN-\d{4}-\d{6}$")
        self.assertEqual((self.stock_de(self.polo), self.stock_de(self.pantalon)), (8, 2))
        lignes = {ligne.article_id: (ligne.quantite, ligne.prix_unitaire, ligne.libelle) for ligne in vente.lignes.all()}
        self.assertEqual(lignes, {self.polo.pk: (2, 4500, "Chemisette bleue - 8 ans"), self.pantalon.pk: (1, 6000, "Pantalon - 10 ans")})
        sorties = MouvementStockTenue.objects.filter(vente=vente)
        self.assertEqual({(m.article_id, m.quantite, m.motif) for m in sorties}, {
            (self.polo.pk, -2, MotifStockTenue.VENTE), (self.pantalon.pk, -1, MotifStockTenue.VENTE),
        })
        self.assertEqual(vente.nom_acheteur, "Mme Traoré")

    def test_la_vente_cree_sa_ligne_de_caisse(self):
        vente = self.vendre({self.polo.pk: 2}, mode_paiement="mobile_money")
        mouvement = vente.mouvement_caisse
        self.assertEqual((mouvement.type_mouvement, mouvement.montant, mouvement.etablissement), (MouvementCaisse.TypeMouvement.ENTREE, 9000, self.ecole))
        self.assertEqual(mouvement.compte_contrepartie, "701")
        self.assertEqual(vecteur_attendu(mouvement), {"551": 9000, "701": -9000})

    def test_la_vente_a_un_eleve(self):
        vente = self.vendre({self.polo.pk: 1}, eleve=self.e1, acheteur="ignoré")
        self.assertEqual((vente.eleve, vente.acheteur, vente.nom_acheteur), (self.e1, "", self.e1.nom_complet))

    def test_le_prix_du_jour_est_garde_meme_si_le_prix_change_ensuite(self):
        vente = self.vendre({self.polo.pk: 1})
        ArticleTenue.objects.filter(pk=self.polo.pk).update(prix=9999)
        self.assertEqual(vente.lignes.get().prix_unitaire, 4500)
        self.assertEqual(vente.total, 4500)

    def test_stock_insuffisant_refuse_toute_la_vente(self):
        with self.assertRaisesMessage(ValidationError, "il en reste 3"):
            self.vendre({self.polo.pk: 2, self.pantalon.pk: 4})
        self.assertEqual((self.stock_de(self.polo), self.stock_de(self.pantalon)), (10, 3))  # rien n'a bougé, même pour le polo
        self.assertEqual(VenteTenue.objects.count(), 0)
        self.assertEqual(MouvementCaisse.objects.count(), 0)

    def test_on_peut_vendre_tout_le_stock_mais_pas_plus(self):
        self.vendre({self.pantalon.pk: 3})
        self.assertEqual(self.stock_de(self.pantalon), 0)
        with self.assertRaises(ValidationError):
            self.vendre({self.pantalon.pk: 1})

    def test_un_article_retire_de_la_vente_ne_se_vend_pas(self):
        with self.assertRaisesMessage(ValidationError, "n'est plus en vente"):
            self.vendre({self.retire.pk: 1})

    def test_un_article_d_une_autre_ecole_ou_inconnu_est_refuse(self):
        for pk in (self.article_b.pk, 999999):
            with self.subTest(pk=pk), self.assertRaisesMessage(ValidationError, "n'existe pas"):
                self.vendre({pk: 1})
        self.assertEqual(self.stock_de(self.article_b), 7)

    def test_une_vente_vide_est_refusee(self):
        for quantites in ({}, {self.polo.pk: 0}):
            with self.subTest(quantites=quantites), self.assertRaisesMessage(ValidationError, "au moins un article"):
                self.vendre(quantites)

    def test_un_eleve_d_une_autre_ecole_ne_peut_pas_etre_l_acheteur(self):
        eleve_b = creer_compte(Role.ELEVE, "eleve@tenues-b.test", self.ecole_b)
        with self.assertRaises(ValidationError):
            self.vendre({self.polo.pk: 1}, eleve=eleve_b)
        self.assertEqual(self.stock_de(self.polo), 10)

    def test_tout_ou_rien_si_la_caisse_echoue(self):
        with mock.patch("finances.tenues.MouvementCaisse.objects.create", side_effect=RuntimeError("panne")):
            with self.assertRaises(RuntimeError):
                self.vendre({self.polo.pk: 2})
        self.assertEqual(self.stock_de(self.polo), 10)
        self.assertEqual((VenteTenue.objects.count(), MouvementStockTenue.objects.count(), LigneVenteTenue.objects.count()), (0, 0, 0))

    def test_les_numeros_de_recu_se_suivent(self):
        un, deux = self.vendre({self.polo.pk: 1}), self.vendre({self.polo.pk: 1})
        self.assertEqual(int(deux.reference[-6:]), int(un.reference[-6:]) + 1)


class AnnulationTests(TenuesBase):
    def test_annuler_remet_en_stock_et_annule_la_caisse(self):
        vente = self.vendre({self.polo.pk: 2, self.pantalon.pk: 1})
        tenues.annuler_vente(vente=vente, motif="Erreur de taille", acteur=self.fondateur)
        vente.refresh_from_db()
        self.assertTrue(vente.annulee)
        self.assertEqual((vente.annulee_par, vente.motif_annulation), (self.fondateur, "Erreur de taille"))
        self.assertEqual((self.stock_de(self.polo), self.stock_de(self.pantalon)), (10, 3))
        self.assertTrue(vente.mouvement_caisse.annule)  # conservée, marquée annulée
        self.assertEqual(vecteur_attendu(vente.mouvement_caisse), {})
        retours = MouvementStockTenue.objects.filter(vente=vente, motif=MotifStockTenue.ANNULATION)
        self.assertEqual({(m.article_id, m.quantite) for m in retours}, {(self.polo.pk, 2), (self.pantalon.pk, 1)})

    def test_seule_la_direction_annule(self):
        vente = self.vendre({self.polo.pk: 1})
        for acteur in (self.comptable, self.secretaire, self.t1):
            with self.subTest(role=acteur.role), self.assertRaises(ValidationError):
                tenues.annuler_vente(vente=vente, motif="Test", acteur=acteur)
        vente.refresh_from_db()
        self.assertFalse(vente.annulee)

    def test_un_motif_est_obligatoire_et_on_n_annule_qu_une_fois(self):
        vente = self.vendre({self.polo.pk: 1})
        with self.assertRaisesMessage(ValidationError, "motif"):
            tenues.annuler_vente(vente=vente, motif=" ", acteur=self.fondateur)
        tenues.annuler_vente(vente=vente, motif="Erreur", acteur=self.fondateur)
        with self.assertRaisesMessage(ValidationError, "déjà annulée"):
            tenues.annuler_vente(vente=vente, motif="Encore", acteur=self.fondateur)
        self.assertEqual(self.stock_de(self.polo), 10)  # remis une seule fois en stock


# ---------------------------------------------------------------------------------------------------------------------
# Les pages
# ---------------------------------------------------------------------------------------------------------------------

class PagesTenuesTests(TenuesBase):
    def adresses(self):
        vente = self.vendre({self.polo.pk: 1})
        self.vente = vente
        return [
            reverse("finances:tenues"), reverse("finances:tenues_vendre"), reverse("finances:tenues_ventes"),
            reverse("finances:modifier_article_tenue", args=[self.polo.pk]), reverse("finances:tenues_recu_pdf", args=[vente.pk]),
        ]

    def test_le_comptable_et_la_direction_y_ont_acces(self):
        adresses = self.adresses()
        for compte in (self.comptable, self.fondateur):
            client = client_de(compte)
            for adresse in adresses:
                with self.subTest(role=compte.role, adresse=adresse):
                    self.assertEqual(client.get(adresse).status_code, 200)

    def test_les_autres_roles_n_y_ont_pas_acces(self):
        adresses = self.adresses()
        for compte in (self.secretaire, self.t1, self.parent, self.e1, self.censeur, self.dir_1er):
            client = client_de(compte)
            for adresse in adresses:
                with self.subTest(role=compte.role, adresse=adresse):
                    self.assertEqual(client.get(adresse).status_code, 403)

    def test_un_visiteur_anonyme_est_renvoye_vers_la_connexion(self):
        client = client_de(None)
        for adresse in self.adresses():
            reponse = client.get(adresse)
            self.assertEqual(reponse.status_code, 302)
            self.assertIn("/connexion", reponse["Location"])

    def test_ajouter_un_article(self):
        client = client_de(self.comptable)
        reponse = client.post(reverse("finances:tenues"), {"libelle": "  Short   sport ", "taille": " 12 ans", "prix": "3500", "seuil_alerte": "4", "actif": "on"})
        self.assertEqual(reponse.status_code, 302)
        article = ArticleTenue.objects.get(libelle="Short sport")
        self.assertEqual((article.etablissement, article.taille, article.prix, article.stock, article.seuil_alerte), (self.ecole, "12 ans", 3500, 0, 4))
        doublon = client.post(reverse("finances:tenues"), {"libelle": "short SPORT", "taille": "12 ANS", "prix": "100", "seuil_alerte": "1"})
        self.assertContains(doublon, "existe déjà")
        prix_nul = client.post(reverse("finances:tenues"), {"libelle": "Casquette", "taille": "", "prix": "0", "seuil_alerte": "1"})
        self.assertEqual(prix_nul.status_code, 200)
        self.assertFalse(ArticleTenue.objects.filter(libelle="Casquette").exists())

    def test_modifier_le_prix_ne_touche_pas_au_stock(self):
        client = client_de(self.comptable)
        client.post(reverse("finances:modifier_article_tenue", args=[self.polo.pk]), {
            "libelle": "Chemisette bleue", "taille": "8 ans", "prix": "5000", "seuil_alerte": "5", "stock": "999", "actif": "on",
        })
        self.polo.refresh_from_db()
        self.assertEqual((self.polo.prix, self.polo.stock), (5000, 10))

    def test_arrivage_et_correction_par_les_pages(self):
        client = client_de(self.comptable)
        client.post(reverse("finances:approvisionner_tenue", args=[self.jupe.pk]), {"quantite": "12", "note": "Bon 7"})
        self.assertEqual(self.stock_de(self.jupe), 12)
        client.post(reverse("finances:corriger_stock_tenue", args=[self.jupe.pk]), {"nouveau_stock": "10", "note": "Deux jupes tachées"})
        self.assertEqual(self.stock_de(self.jupe), 10)
        for donnees in ({"quantite": "0"}, {"quantite": "abc"}, {}):
            client.post(reverse("finances:approvisionner_tenue", args=[self.jupe.pk]), donnees)
        client.post(reverse("finances:corriger_stock_tenue", args=[self.jupe.pk]), {"nouveau_stock": "5", "note": ""})
        self.assertEqual(self.stock_de(self.jupe), 10)

    def test_vendre_par_la_page_avec_un_eleve(self):
        client = client_de(self.comptable)
        reponse = client.post(reverse("finances:tenues_vendre"), {
            "matricule_eleve": self.e1.matricule, "acheteur": "", "mode_paiement": "especes",
            f"qte_{self.polo.pk}": "2", f"qte_{self.pantalon.pk}": "1", f"qte_{self.jupe.pk}": "", f"qte_{self.retire.pk}": "3",
        })
        self.assertRedirects(reponse, reverse("finances:tenues_ventes"))
        vente = VenteTenue.objects.get()
        self.assertEqual((vente.eleve, vente.total, vente.enregistre_par), (self.e1, 15000, self.comptable))
        self.assertEqual(self.stock_de(self.retire), 5)  # un champ pour un article retiré de la vente est ignoré
        self.assertContains(client.get(reverse("finances:tenues_ventes")), vente.reference)

    def test_la_page_de_vente_ne_propose_que_les_articles_en_vente_et_en_stock(self):
        reponse = client_de(self.comptable).get(reverse("finances:tenues_vendre"))
        proposes = {article.pk for article, _ in reponse.context["lignes"]}
        self.assertEqual(proposes, {self.polo.pk, self.pantalon.pk})  # ni la jupe (stock 0), ni l'article retiré, ni l'autre école

    def test_une_vente_sans_article_ou_avec_un_mauvais_matricule_est_refusee(self):
        client = client_de(self.comptable)
        sans_article = client.post(reverse("finances:tenues_vendre"), {"matricule_eleve": "", "acheteur": "X", "mode_paiement": "especes"})
        self.assertContains(sans_article, "au moins un article")
        mauvais = client.post(reverse("finances:tenues_vendre"), {
            "matricule_eleve": "000000000", "mode_paiement": "especes", f"qte_{self.polo.pk}": "1",
        })
        self.assertContains(mauvais, "Aucun élève trouvé")
        trop = client.post(reverse("finances:tenues_vendre"), {"mode_paiement": "especes", f"qte_{self.pantalon.pk}": "9"})
        self.assertEqual(trop.status_code, 200)
        self.assertEqual(VenteTenue.objects.count(), 0)
        self.assertEqual(self.stock_de(self.pantalon), 3)

    def test_un_eleve_d_une_autre_ecole_n_est_pas_trouve(self):
        eleve_b = creer_compte(Role.ELEVE, "eleve2@tenues-b.test", self.ecole_b)
        reponse = client_de(self.comptable).post(reverse("finances:tenues_vendre"), {
            "matricule_eleve": eleve_b.matricule, "mode_paiement": "especes", f"qte_{self.polo.pk}": "1",
        })
        self.assertContains(reponse, "Aucun élève trouvé")
        self.assertEqual(VenteTenue.objects.count(), 0)

    def test_recu_pdf(self):
        vente = self.vendre({self.polo.pk: 2})
        reponse = client_de(self.comptable).get(reverse("finances:tenues_recu_pdf", args=[vente.pk]))
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(reponse.content.startswith(b"%PDF"))
        self.assertIn(vente.reference.lower().replace("-", ""), reponse["Content-Disposition"].lower().replace("-", "").replace("_", ""))

    def test_annuler_par_la_page_est_reserve_a_la_direction(self):
        vente = self.vendre({self.polo.pk: 1})
        adresse = reverse("finances:tenues_annuler_vente", args=[vente.pk])
        self.assertEqual(client_de(self.comptable).post(adresse, {"motif": "Test"}).status_code, 403)
        vente.refresh_from_db()
        self.assertFalse(vente.annulee)
        self.assertEqual(client_de(self.fondateur).post(adresse, {"motif": ""}).status_code, 302)  # sans motif : refusé avec un message
        vente.refresh_from_db()
        self.assertFalse(vente.annulee)
        client_de(self.fondateur).post(adresse, {"motif": "Erreur de taille"})
        vente.refresh_from_db()
        self.assertTrue(vente.annulee)
        self.assertEqual(self.stock_de(self.polo), 10)

    def test_le_bouton_d_annulation_n_est_visible_que_pour_la_direction(self):
        self.vendre({self.polo.pk: 1})
        self.assertNotContains(client_de(self.comptable).get(reverse("finances:tenues_ventes")), "tenues/ventes/1/annuler")
        self.assertContains(client_de(self.fondateur).get(reverse("finances:tenues_ventes")), "annuler")

    def test_recherche_dans_l_historique(self):
        self.vendre({self.polo.pk: 1}, eleve=self.e1)
        self.vendre({self.polo.pk: 1}, acheteur="Boubacar Maiga")
        page = client_de(self.comptable).get(reverse("finances:tenues_ventes"), {"q": "Boubacar"})
        self.assertEqual(len(page.context["ventes"]), 1)
        page = client_de(self.comptable).get(reverse("finances:tenues_ventes"), {"q": self.e1.matricule})
        self.assertEqual(len(page.context["ventes"]), 1)

    def test_le_menu_du_comptable_propose_la_vente_de_tenues(self):
        def liens(compte):
            reponse = client_de(compte).get(reverse("comptes:liste_notifications"))
            return [lien["url"] for section in reponse.context["sections_navigation"] for lien in section["liens"]]

        for compte in (self.comptable, self.fondateur):
            self.assertTrue({"finances:tenues_vendre", "finances:tenues"} <= set(liens(compte)))
        for compte in (self.secretaire, self.t1, self.parent):
            self.assertNotIn("finances:tenues_vendre", liens(compte))


class CloisonnementTenuesTests(TenuesBase):
    def test_une_autre_ecole_ne_voit_ni_ne_modifie_mon_stock_ni_mes_ventes(self):
        vente = self.vendre({self.polo.pk: 2})
        comptable_b = creer_compte(Role.COMPTABLE, "comptable@tenues-b.test", self.ecole_b)
        for compte in (comptable_b, self.fondateur_b):
            client = client_de(compte)
            for nom, arguments in (
                ("finances:tenues_recu_pdf", [vente.pk]), ("finances:modifier_article_tenue", [self.polo.pk]),
            ):
                with self.subTest(role=compte.role, page=nom):
                    self.assertEqual(client.get(reverse(nom, args=arguments)).status_code, 404)
            for nom, arguments, donnees in (
                ("finances:tenues_annuler_vente", [vente.pk], {"motif": "Piratage"}),
                ("finances:approvisionner_tenue", [self.polo.pk], {"quantite": "50"}),
                ("finances:corriger_stock_tenue", [self.polo.pk], {"nouveau_stock": "0", "note": "Piratage"}),
            ):
                with self.subTest(role=compte.role, action=nom):
                    self.assertIn(client.post(reverse(nom, args=arguments), donnees).status_code, {403, 404})
            page = client.get(reverse("finances:tenues"))
            self.assertNotContains(page, "Chemisette bleue")
            self.assertNotContains(client.get(reverse("finances:tenues_ventes")), vente.reference)
        vente.refresh_from_db()
        self.assertFalse(vente.annulee)
        self.assertEqual(self.stock_de(self.polo), 8)

    def test_une_autre_ecole_ne_peut_pas_vendre_mes_articles_par_la_page(self):
        comptable_b = creer_compte(Role.COMPTABLE, "comptable2@tenues-b.test", self.ecole_b)
        reponse = client_de(comptable_b).post(reverse("finances:tenues_vendre"), {"mode_paiement": "especes", f"qte_{self.polo.pk}": "1"})
        self.assertContains(reponse, "au moins un article")  # le champ d'un article d'une autre école n'existe pas pour elle
        self.assertEqual(self.stock_de(self.polo), 10)
        self.assertEqual(VenteTenue.objects.count(), 0)


# ---------------------------------------------------------------------------------------------------------------------
# Comptabilité
# ---------------------------------------------------------------------------------------------------------------------

class ComptabiliteDesVentesTests(ComptaBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.fondateur = compte_utilisateur("fond-t@compta.test", Role.FONDATEUR, cls.ecole)
        cls.polo = ArticleTenue.objects.create(etablissement=cls.ecole, libelle="Polo", taille="M", prix=4000)
        ArticleTenue.objects.filter(pk=cls.polo.pk).update(stock=20)

    def vendre(self, quantite=2, mode="especes"):
        return tenues.vendre(
            etablissement=self.ecole, quantites={self.polo.pk: quantite}, eleve=None, acheteur="Client", mode_paiement=mode, acteur=self.comptable,
        )

    def test_la_vente_est_comptabilisee_en_ventes_de_marchandises(self):
        self.vendre(2, "especes")
        self.vendre(1, "virement")
        self.assertEqual(len(ecarts_caisse(self.ecole)), 2)
        resultat = synchroniser_caisse(self.ecole, acteur=self.comptable)
        self.assertEqual((resultat.creees, resultat.ignorees), (2, []))
        self.assertEqual(self.soldes(), {"571": (8000, 0), "521": (4000, 0), "701": (0, 12000)})
        self.assertEqual(ecarts_caisse(self.ecole), [])

    def test_l_annulation_d_une_vente_est_regularisee(self):
        vente = self.vendre(2)
        synchroniser_caisse(self.ecole)
        tenues.annuler_vente(vente=vente, motif="Erreur", acteur=self.fondateur)
        self.assertEqual(len(ecarts_caisse(self.ecole)), 1)
        synchroniser_caisse(self.ecole)
        self.assertEqual({numero: debit - credit for numero, (debit, credit) in self.soldes().items()}, {"571": 0, "701": 0})
        self.assertIn("annulation", Ecriture.objects.order_by("id").last().libelle)
