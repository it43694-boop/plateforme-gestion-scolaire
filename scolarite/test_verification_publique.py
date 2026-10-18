"""Page publique « Vérifier un document » : le code court imprimé sous le QR code d'une carte, sans connexion, sans rien révéler de plus que la carte."""
from django.core.cache import cache
from django.test import Client, SimpleTestCase
from django.urls import reverse

from comptes.langues import NOM_COOKIE_LANGUE
from comptes.models import Utilisateur
from comptes.outils_test_arabe import restes_hors_textes_saisis
from scolarite.models import (
    ALPHABET_CODE_VERIFICATION, TypeDocumentVerifiable, VerificationDocument, nouveau_code_verification, normaliser_code_verification,
)
from scolarite.test_dossier_complet import StockageTemporaire


class CodeCourtTests(SimpleTestCase):
    def test_la_forme_du_code(self):
        for _ in range(200):
            code = nouveau_code_verification()
            self.assertRegex(code, r"^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")
            self.assertTrue(set(code.replace("-", "")) <= set(ALPHABET_CODE_VERIFICATION))
        self.assertEqual(len({nouveau_code_verification() for _ in range(500)}), 500)  # jamais deux fois le même, en pratique

    def test_pas_de_signe_qui_se_confond(self):
        for signe in "IO01":
            self.assertNotIn(signe, ALPHABET_CODE_VERIFICATION)

    def test_ce_que_la_personne_a_tape_est_remis_en_forme(self):
        for saisi in ("A2B3-C4D5-E6F7", "a2b3-c4d5-e6f7", "A2B3C4D5E6F7", " a2b3 c4d5  e6f7 ", "A2B3_C4D5.E6F7"):
            with self.subTest(saisi=saisi):
                self.assertEqual(normaliser_code_verification(saisi), "A2B3-C4D5-E6F7")

    def test_ce_qui_n_est_pas_un_code_est_refuse(self):
        for saisi in ("", None, "abc", "A2B3-C4D5", "A2B3-C4D5-E6F7-G8H9", "A2B3-C4D5-E6F0", "A2B3-C4D5-E6FI", "جملة عربية"):
            with self.subTest(saisi=saisi):
                self.assertEqual(normaliser_code_verification(saisi), "")


class PageVerificationTests(StockageTemporaire):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        Utilisateur.objects.filter(pk=self.e1.pk).update(
            lieu_naissance="Lieu Confidentiel", contact_urgence_nom="Contact Confidentiel", contact_urgence_telephone="76000000", nom_pere="Père Confidentiel",
        )
        self.verification = VerificationDocument.objects.create(type_document=TypeDocumentVerifiable.CARTE_ELEVE, eleve=self.e1, inscription=self.i["e1"])
        self.adresse = reverse("vitrine:verifier")
        self.visiteur = Client()

    def test_la_page_est_publique_et_affiche_le_formulaire(self):
        reponse = self.visiteur.get(self.adresse)
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Code de vérification")
        self.assertNotContains(reponse, "Document authentique")
        self.assertNotContains(reponse, "Code inconnu")

    def test_un_bon_code_confirme_le_document(self):
        reponse = self.visiteur.post(self.adresse, {"code": self.verification.code})
        self.assertContains(reponse, "Document authentique")
        for attendu in ("Carte d&#x27;élève", self.e1.nom_complet, self.e1.matricule, "6A", self.ecole.nom, self.verification.code):
            self.assertContains(reponse, attendu)

    def test_le_qr_code_arrive_avec_le_code_dans_l_adresse(self):
        reponse = self.visiteur.get(self.adresse, {"code": self.verification.code})
        self.assertContains(reponse, "Document authentique")
        self.assertContains(reponse, self.e1.nom_complet)

    def test_le_code_peut_etre_tape_en_minuscules_et_sans_tirets(self):
        for saisi in (self.verification.code.lower(), self.verification.code.replace("-", ""), f"  {self.verification.code.lower()}  "):
            with self.subTest(saisi=saisi):
                self.assertContains(self.visiteur.post(self.adresse, {"code": saisi}), "Document authentique")

    def test_la_page_ne_montre_que_ce_que_la_carte_montre_deja(self):
        contenu = self.visiteur.post(self.adresse, {"code": self.verification.code}).content.decode()
        for interdit in ("Lieu Confidentiel", "Contact Confidentiel", "76000000", "Père Confidentiel", self.e1.email, self.parent.email):
            self.assertNotIn(interdit, contenu)

    def test_un_code_inconnu_ou_mal_forme_ne_dit_que_code_inconnu(self):
        for saisi in ("ZZZZ-ZZZZ-ZZZZ", "abc", "A2B3-C4D5-E6F0", "x" * 300):
            with self.subTest(saisi=saisi[:20]):
                reponse = self.visiteur.post(self.adresse, {"code": saisi})
                self.assertEqual(reponse.status_code, 200)
                self.assertContains(reponse, "Code inconnu")
                self.assertNotContains(reponse, "Document authentique")

    def test_un_document_desactive_est_inconnu(self):
        VerificationDocument.objects.filter(pk=self.verification.pk).update(actif=False)
        reponse = self.visiteur.post(self.adresse, {"code": self.verification.code})
        self.assertContains(reponse, "Code inconnu")  # même message qu'un code qui n'existe pas : rien n'est révélé

    def test_un_envoi_vide_n_affiche_aucune_erreur(self):
        reponse = self.visiteur.post(self.adresse, {"code": ""})
        self.assertNotContains(reponse, "Code inconnu")
        self.assertNotContains(reponse, "Document authentique")

    def test_les_essais_en_masse_sont_limites(self):
        refuses = 0
        for _ in range(30):
            reponse = self.visiteur.post(self.adresse, {"code": "ZZZZ-ZZZZ-ZZZZ"})
            refuses += "Trop de tentatives" in reponse.content.decode()
        self.assertGreaterEqual(refuses, 5)
        suite = self.visiteur.post(self.adresse, {"code": self.verification.code})  # une fois la limite atteinte, même le bon code attend
        self.assertContains(suite, "Trop de tentatives")
        self.assertNotContains(suite, "Document authentique")

    def test_l_ancienne_adresse_du_qr_code_fonctionne_toujours(self):
        donnees = self.visiteur.get(reverse("scolarite:verifier_document", args=[self.verification.jeton])).json()
        self.assertEqual((donnees["valide"], donnees["matricule"]), (True, self.e1.matricule))

    def test_un_document_sans_code_n_est_pas_trouve_par_un_code_vide(self):
        VerificationDocument.objects.filter(pk=self.verification.pk).update(code=None)
        for saisi in ("", "None", "null"):
            self.assertNotContains(self.visiteur.post(self.adresse, {"code": saisi}), "Document authentique")


class PageVerificationEnArabeTests(StockageTemporaire):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.verification = VerificationDocument.objects.create(type_document=TypeDocumentVerifiable.CARTE_ELEVE, eleve=self.e1, inscription=self.i["e1"])
        self.visiteur = Client()
        self.visiteur.cookies[NOM_COOKIE_LANGUE] = "ar"
        self.adresse = reverse("vitrine:verifier")

    def test_chaque_etat_de_la_page_est_en_arabe_pur(self):
        # Le bouton de langue s'écrit dans la langue vers laquelle il bascule, le code se recopie tel quel : ce sont les seules lettres latines permises.
        saisis = {"Français", "A2B3-C4D5-E6F7", self.verification.code}
        etats = {
            "formulaire": self.visiteur.get(self.adresse),
            "document authentique": self.visiteur.post(self.adresse, {"code": self.verification.code}),
            "code inconnu": self.visiteur.post(self.adresse, {"code": "ZZZZ-ZZZZ-ZZZZ"}),
        }
        for nom, reponse in etats.items():
            with self.subTest(etat=nom):
                self.assertEqual(reponse.status_code, 200)
                self.assertEqual(restes_hors_textes_saisis(reponse.content.decode(), saisis | {self.e1.nom_complet, self.e1.matricule, self.ecole.nom, "6A"}), [])
        self.assertIn("وثيقة أصلية", etats["document authentique"].content.decode())

    def test_l_etat_trop_de_tentatives_est_en_arabe_pur(self):
        for _ in range(25):
            reponse = self.visiteur.post(self.adresse, {"code": "ZZZZ-ZZZZ-ZZZZ"})
        self.assertIn("محاولات كثيرة جدًا", reponse.content.decode())
        self.assertEqual(restes_hors_textes_saisis(reponse.content.decode(), {"Français", "A2B3-C4D5-E6F7"}), [])
