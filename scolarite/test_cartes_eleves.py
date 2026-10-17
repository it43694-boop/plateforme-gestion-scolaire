"""Cartes d'élève : planche A4 (8 cartes, recto puis verso permuté), QR de vérification, droits, arabe pur."""
from django.urls import reverse

from comptes.arabisation import invalider
from comptes.models import JournalAudit, Utilisateur
from comptes.outils_test_arabe import CaptureHtmlDuPdf, client_en
from scolarite.cartes import CARTES_PAR_PAGE, planches
from scolarite.models import Classe, Cycle, Inscription, TypeDocumentVerifiable, VerificationDocument
from scolarite.photos import enregistrer_photo
from scolarite.test_dossier_complet import StockageTemporaire, image_octets


class PlanchesTests(StockageTemporaire):
    """Le rangement des cartes sur la feuille (sans base de données ni PDF)."""

    def test_aucune_carte_aucune_page(self):
        self.assertEqual(planches([]), [])

    def test_trois_cartes_une_page_a_moitie_remplie(self):
        page, = planches(["a", "b", "c"])
        self.assertEqual(page["recto"], [["a", "b"], ["c", None]])
        self.assertEqual(page["verso"], [["b", "a"], [None, "c"]])  # le verso de chaque ligne est permuté : il tombe derrière son recto

    def test_huit_cartes_une_page_neuf_cartes_deux_pages(self):
        cartes = [str(i) for i in range(9)]
        self.assertEqual(len(planches(cartes[:CARTES_PAR_PAGE])), 1)
        pages = planches(cartes)
        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[1]["recto"], [["8", None]])

    def test_chaque_carte_apparait_une_fois_au_recto_et_une_fois_au_verso(self):
        cartes = [str(i) for i in range(19)]
        pages = planches(cartes)
        recto = [c for p in pages for ligne in p["recto"] for c in ligne if c]
        verso = [c for p in pages for ligne in p["verso"] for c in ligne if c]
        self.assertEqual((sorted(recto), sorted(verso)), (sorted(cartes), sorted(cartes)))


class CartesEleveTests(StockageTemporaire):
    def setUp(self):
        self.client.force_login(self.secretaire)
        self.url_classe = reverse("scolarite:cartes_classe_pdf", args=[self.c6a.pk])
        self.url_eleve = reverse("scolarite:carte_eleve_pdf", args=[self.e1.matricule])

    def verifications(self):
        return VerificationDocument.objects.filter(type_document=TypeDocumentVerifiable.CARTE_ELEVE)

    def test_la_planche_d_une_classe_est_un_pdf_a_deux_pages(self):
        reponse = self.client.get(self.url_classe)
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse["Content-Type"], "application/pdf")
        self.assertTrue(reponse.content.startswith(b"%PDF"))
        self.assertIn("cartes_6A_2026-2027.pdf", reponse["Content-Disposition"])
        self.assertEqual(reponse.content.count(b"/Type /Page\n") or reponse.content.count(b"/Type /Page "), 2)  # recto et verso

    def test_un_jeton_de_verification_par_carte_jamais_en_double(self):
        self.client.get(self.url_classe)
        self.assertEqual(self.verifications().count(), 3)  # e1, e2, e3 sont inscrits en 6A
        jetons = set(self.verifications().values_list("jeton", flat=True))
        self.client.get(self.url_classe)
        self.client.get(self.url_eleve)
        self.assertEqual(set(self.verifications().values_list("jeton", flat=True)), jetons)  # les mêmes cartes gardent leur jeton

    def test_le_qr_code_ouvre_la_page_de_verification(self):
        with CaptureHtmlDuPdf() as capture:
            self.client.get(self.url_eleve)
        self.assertIn("data:image/png;base64,", capture.html)  # le QR code
        jeton = self.verifications().get(eleve=self.e1).jeton
        reponse = self.client.get(reverse("scolarite:verifier_document", args=[jeton]))
        donnees = reponse.json()
        self.assertEqual((donnees["valide"], donnees["type_document"], donnees["matricule"]), (True, "Carte d'élève", self.e1.matricule))

    def test_seules_les_inscriptions_en_cours_ont_une_carte(self):
        Inscription.objects.filter(eleve=self.e3).update(statut=Inscription.Statut.ABANDON)
        self.client.get(self.url_classe)
        self.assertEqual(set(self.verifications().values_list("eleve_id", flat=True)), {self.e1.pk, self.e2.pk})

    def test_une_classe_vide_renvoie_a_la_liste_avec_un_message(self):
        vide = Classe.objects.create(nom="6C", cycle=Cycle.PREMIER_CYCLE, niveau="annee_6", annee_scolaire=self.annee)
        reponse = self.client.get(reverse("scolarite:cartes_classe_pdf", args=[vide.pk]), follow=True)
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "aucune carte à imprimer")
        self.assertEqual(self.verifications().count(), 0)

    def test_un_eleve_sans_inscription_en_cours_n_a_pas_de_carte(self):
        Inscription.objects.filter(eleve=self.e1).update(statut=Inscription.Statut.ABANDON)
        reponse = self.client.get(self.url_eleve, follow=True)
        self.assertContains(reponse, "aucune carte à imprimer")

    def test_la_photo_est_sur_la_carte_et_un_fichier_manquant_ne_bloque_pas(self):
        enregistrer_photo(self.e1, image_octets((600, 800)))
        with CaptureHtmlDuPdf() as capture:
            self.client.get(self.url_eleve)
        self.assertIn("data:image/jpeg;base64,", capture.html)
        self.e1.refresh_from_db()
        self.e1.photo.storage.delete(self.e1.photo.name)  # le fichier disparaît du stockage, la base le garde
        reponse = self.client.get(self.url_eleve)
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(reponse.content.startswith(b"%PDF"))

    def test_l_impression_est_journalisee(self):
        self.client.get(self.url_classe)
        journal = JournalAudit.objects.get(action="impression_cartes_eleves")
        self.assertEqual(journal.details["cartes"], 3)

    # --- droits
    def test_seule_l_administration_imprime_des_cartes(self):
        for compte, code in (
            (self.secretaire, 200), (self.fondateur, 200), (self.dir_1er, 200),
            (self.t1, 403), (self.parent, 403), (self.e1, 403), (self.comptable, 403), (self.censeur, 403),
        ):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertEqual(self.client.get(self.url_classe).status_code, code)
                self.assertEqual(self.client.get(self.url_eleve).status_code, code)

    def test_un_directeur_de_cycle_ne_traite_que_son_cycle(self):
        self.client.force_login(self.dir_1er)
        self.assertEqual(self.client.get(reverse("scolarite:cartes_classe_pdf", args=[self.c9a.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("scolarite:carte_eleve_pdf", args=[self.e5.matricule])).status_code, 403)

    def test_une_autre_ecole_ne_voit_rien(self):
        self.client.force_login(self.fondateur_b)
        self.assertEqual(self.client.get(self.url_classe).status_code, 404)
        self.assertEqual(self.client.get(self.url_eleve).status_code, 404)

    def test_les_cartes_ne_sont_pas_pour_les_visiteurs(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url_classe).status_code, 302)

    # --- boutons
    def test_les_boutons_sont_proposes_a_qui_peut_les_utiliser(self):
        page = self.client.get(reverse("scolarite:liste_eleves") + f"?classe={self.c6a.pk}").content.decode()
        self.assertIn(self.url_classe, page)
        self.assertIn(self.url_eleve, self.client.get(reverse("scolarite:dossier_eleve", args=[self.e1.matricule])).content.decode())
        self.client.force_login(self.parent)
        self.assertNotIn(self.url_eleve, self.client.get(reverse("scolarite:dossier_eleve", args=[self.e1.matricule])).content.decode())


class CartesEnArabeTests(StockageTemporaire):
    def test_la_carte_en_arabe_est_en_arabe_pur_avec_la_police_arabe(self):
        Utilisateur.objects.filter(pk=self.e1.pk).update(
            prenom="Aminata", nom="Traoré", prenom_ar="أميناتا", nom_ar="تراوري", contact_urgence_nom="Bakary Traoré",
            contact_urgence_telephone="76000000",
        )
        invalider(self.ecole.pk)
        client = client_en(self.secretaire, "ar")
        with CaptureHtmlDuPdf() as capture:
            reponse = client.get(reverse("scolarite:cartes_classe_pdf", args=[self.c6a.pk]))
        self.assertEqual(reponse.status_code, 200)
        self.assertIn(b"Amiri", reponse.content)
        self.assertEqual(capture.restes_latins(), [])
        self.assertIn("أميناتا", capture.html)
        self.assertIn("امسح رمز QR", capture.html.replace("كيو آر", "QR"))  # le mot « QR » du lexique est écrit en arabe
