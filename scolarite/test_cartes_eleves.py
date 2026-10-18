"""Cartes d'élève : pièces à plier (recto et verso côte à côte, quatre par feuille A4), QR code et code court de vérification, droits, arabe pur."""
import datetime
import io
import re
from unittest import mock

from django.core.files.base import ContentFile
from django.urls import reverse
from pypdf import PdfReader

from comptes.arabisation import invalider
from comptes.models import JournalAudit, Utilisateur
from comptes.outils_test_arabe import CaptureHtmlDuPdf, client_en, restes_hors_textes_saisis
from comptes.roles import Role
from scolarite.cartes import CARTES_PAR_PAGE, pages
from scolarite.models import Classe, Cycle, Inscription, TypeDocumentVerifiable, VerificationDocument
from scolarite.photos import enregistrer_photo
from scolarite.test_dossier_complet import StockageTemporaire, image_octets
from statistiques.test_education import creer_compte

FORME_DU_CODE = re.compile(r"^[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$")


def pages_du_pdf(reponse) -> int:
    return len(PdfReader(io.BytesIO(reponse.content)).pages)


class PagesTests(StockageTemporaire):
    """Le rangement des cartes sur la feuille (sans base de données ni PDF)."""

    def test_aucune_carte_aucune_page(self):
        self.assertEqual(pages([]), [])

    def test_quatre_cartes_par_feuille(self):
        self.assertEqual(CARTES_PAR_PAGE, 4)
        self.assertEqual(pages(["a", "b", "c"]), [["a", "b", "c"]])
        self.assertEqual(pages(["a", "b", "c", "d"]), [["a", "b", "c", "d"]])
        self.assertEqual(pages(["a", "b", "c", "d", "e"]), [["a", "b", "c", "d"], ["e"]])

    def test_chaque_carte_apparait_une_seule_fois_dans_l_ordre(self):
        cartes = [str(i) for i in range(19)]
        self.assertEqual([c for page in pages(cartes) for c in page], cartes)


class CartesEleveTests(StockageTemporaire):
    def setUp(self):
        self.client.force_login(self.secretaire)
        self.url_classe = reverse("scolarite:cartes_classe_pdf", args=[self.c6a.pk])
        self.url_eleve = reverse("scolarite:carte_eleve_pdf", args=[self.e1.matricule])

    def verifications(self):
        return VerificationDocument.objects.filter(type_document=TypeDocumentVerifiable.CARTE_ELEVE)

    def html_de(self, adresse, client=None):
        with CaptureHtmlDuPdf() as capture:
            reponse = (client or self.client).get(adresse)
        self.assertEqual(reponse.status_code, 200)
        return capture.html

    # --- le PDF
    def test_les_cartes_d_une_classe_tiennent_sur_une_page(self):
        reponse = self.client.get(self.url_classe)
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse["Content-Type"], "application/pdf")
        self.assertTrue(reponse.content.startswith(b"%PDF"))
        self.assertIn("cartes_6A_2026-2027.pdf", reponse["Content-Disposition"])
        self.assertEqual(pages_du_pdf(reponse), 1)  # trois cartes : une feuille

    def test_cinq_cartes_deux_feuilles(self):
        for numero in (1, 2):
            eleve = creer_compte(Role.ELEVE, f"carte-en-plus-{numero}@cartes.test", self.ecole)
            Inscription.objects.create(eleve=eleve, classe=self.c6a)
        reponse = self.client.get(self.url_classe)
        self.assertEqual(pages_du_pdf(reponse), 2)
        self.assertEqual(self.verifications().count(), 5)

    def test_une_seule_carte_une_seule_page(self):
        self.assertEqual(pages_du_pdf(self.client.get(self.url_eleve)), 1)

    # --- le contenu de la carte
    def test_le_recto_et_le_verso_portent_les_informations_de_l_eleve_et_de_l_ecole(self):
        self.ecole.devise = "Travail Discipline Reussite"
        self.ecole.commune = "Ségou"
        self.ecole.nom_signataire = "Mamadou Coulibaly"
        self.ecole.fonction_signataire = "La Directrice"
        self.ecole.save()
        Utilisateur.objects.filter(pk=self.e1.pk).update(
            prenom="Aminata", nom="Traoré", sexe="F", date_naissance=datetime.date(2012, 11, 5), lieu_naissance="Koutiala",
            contact_urgence_nom="Bakary Traoré", contact_urgence_telephone="76000000",
        )
        html = self.html_de(self.url_eleve)
        for attendu in (
            "CARTE D'ÉLÈVE", self.ecole.nom, "Ségou", "Traoré", "Aminata", "Née le", "05/11/2012", "Koutiala", "Classe :", "6A", "2026-2027",
            "Mat :", self.e1.matricule, "Travail Discipline Reussite", "La Directrice", "Mamadou Coulibaly",
            "En cas d'urgence, prévenir :", "Bakary Traoré", "76000000", "Cette carte est strictement personnelle", "Valable pour l'année scolaire 2026-2027",
            "Vérifier cette carte sur", "testserver/verifier", "plier sur le trait en pointillé",
        ):
            with self.subTest(attendu=attendu):
                self.assertIn(attendu, html)

    def test_le_ne_ou_nee_suit_le_sexe(self):
        for sexe, attendu, absent in (("F", "Née le", "Né le"), ("M", "Né le", "Née le"), (None, "Né(e) le", "Née le")):
            Utilisateur.objects.filter(pk=self.e1.pk).update(sexe=sexe, date_naissance=datetime.date(2012, 11, 5))
            with self.subTest(sexe=sexe):
                html = self.html_de(self.url_eleve)
                self.assertIn(f"<span>{attendu}</span>", html)
                self.assertNotIn(f"<span>{absent}</span>", html)

    def test_ce_qui_n_est_pas_renseigne_n_est_pas_imprime(self):
        Utilisateur.objects.filter(pk=self.e1.pk).update(date_naissance=None, lieu_naissance="", contact_urgence_nom="", contact_urgence_telephone="")
        html = self.html_de(self.url_eleve)
        for absent in ("Né le", "Née le", "Né(e) le", "En cas d'urgence"):
            self.assertNotIn(absent, html)

    def test_le_signataire_n_est_imprime_que_s_il_est_renseigne(self):
        self.assertNotIn('class="signataire"', self.html_de(self.url_eleve))
        self.ecole.nom_signataire = "Mamadou Coulibaly"
        self.ecole.save()
        html = self.html_de(self.url_eleve)
        self.assertIn("Mamadou Coulibaly", html)
        self.assertIn("Le Directeur", html)  # sans fonction saisie, la fonction habituelle

    def test_la_signature_de_l_ecole_est_imprimee_si_elle_existe(self):
        self.ecole.nom_signataire = "Mamadou Coulibaly"
        self.ecole.save()
        self.assertNotIn('class="signature"', self.html_de(self.url_eleve))
        self.ecole.signature.save("signature.png", ContentFile(image_octets((200, 80), format="PNG")), save=True)
        self.assertIn('class="signature"', self.html_de(self.url_eleve))

    def test_un_nom_tres_long_s_ecrit_plus_petit(self):
        Utilisateur.objects.filter(pk=self.e2.pk).update(nom="Coulibaly Diarra Konaté", prenom="Mamadou Lamine Bakary")
        html = self.html_de(self.url_classe)
        self.assertIn('class="nom-long"', html)
        self.assertIn('class="nom"', html)  # les noms courts gardent la taille habituelle

    def test_la_devise_manquante_laisse_la_mention_carte_d_eleve(self):
        self.ecole.devise = ""
        self.ecole.save()
        self.assertIn('<td class="bande">Carte d\'élève</td>', self.html_de(self.url_eleve))

    def test_la_carte_n_imprime_pas_les_donnees_privees_du_dossier(self):
        Utilisateur.objects.filter(pk=self.e1.pk).update(nom_pere="Père Confidentiel", adresse="Rue Secrète", ecole_origine="Ancienne École Privée")
        html = self.html_de(self.url_eleve)
        for interdit in ("Père Confidentiel", "Rue Secrète", "Ancienne École Privée"):
            self.assertNotIn(interdit, html)

    # --- le QR code et le code court
    def test_un_jeton_et_un_code_par_carte_jamais_en_double(self):
        self.client.get(self.url_classe)
        self.assertEqual(self.verifications().count(), 3)  # e1, e2, e3 sont inscrits en 6A
        jetons = set(self.verifications().values_list("jeton", flat=True))
        codes = set(self.verifications().values_list("code", flat=True))
        self.assertEqual(len(codes), 3)
        for code in codes:
            self.assertRegex(code, FORME_DU_CODE)
        self.client.get(self.url_classe)
        self.client.get(self.url_eleve)
        self.assertEqual(set(self.verifications().values_list("jeton", flat=True)), jetons)  # les mêmes cartes gardent leur jeton
        self.assertEqual(set(self.verifications().values_list("code", flat=True)), codes)  # et leur code

    def test_le_code_est_imprime_sous_le_qr_code_tel_quel(self):
        html = self.html_de(self.url_eleve)
        code = self.verifications().get(eleve=self.e1).code
        self.assertIn(f'<span class="code" translate="no" dir="ltr">{code}</span>', html)

    def test_le_qr_code_ouvre_la_page_publique_avec_le_code(self):
        adresses = []

        def espion(adresse):
            adresses.append(adresse)
            return "data:image/png;base64,AAAA"

        with mock.patch("scolarite.cartes.qr_en_donnees", side_effect=espion):
            self.client.get(self.url_eleve)
        code = self.verifications().get(eleve=self.e1).code
        self.assertEqual(adresses, [f"http://testserver{reverse('vitrine:verifier')}?code={code}"])
        reponse = self.client.get(adresses[0])
        self.assertContains(reponse, "Document authentique")

    def test_un_vrai_qr_code_est_dans_la_carte(self):
        self.assertIn("data:image/png;base64,", self.html_de(self.url_eleve))

    def test_une_ancienne_carte_recoit_un_code_sans_changer_de_jeton(self):
        self.client.get(self.url_eleve)
        ancienne = self.verifications().get(eleve=self.e1)
        jeton = ancienne.jeton
        VerificationDocument.objects.filter(pk=ancienne.pk).update(code=None)  # une carte imprimée avant l'arrivée du code court
        self.client.get(self.url_eleve)
        ancienne.refresh_from_db()
        self.assertRegex(ancienne.code, FORME_DU_CODE)
        self.assertEqual(ancienne.jeton, jeton)
        self.assertEqual(self.verifications().count(), 1)  # toujours une seule vérification pour cet élève
        self.assertEqual(self.client.get(reverse("scolarite:verifier_document", args=[jeton])).json()["valide"], True)  # l'ancien QR code marche encore

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
        self.assertIn("data:image/jpeg;base64,", self.html_de(self.url_eleve))
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
    def preparer(self):
        self.ecole.devise = "Travail Discipline Reussite"
        self.ecole.devise_ar = "العمل والانضباط والنجاح"
        self.ecole.commune = "Koutiala"
        self.ecole.nom_signataire = "Mamadou Coulibaly"
        self.ecole.save()
        Utilisateur.objects.filter(pk=self.e1.pk).update(
            prenom="Aminata", nom="Traoré", prenom_ar="أميناتا", nom_ar="تراوري", sexe="F", date_naissance=datetime.date(2012, 11, 5),
            lieu_naissance="Ségou", contact_urgence_nom="Bakary Traoré", contact_urgence_telephone="76000000",
        )
        invalider(self.ecole.pk)

    def test_la_carte_en_arabe_est_en_arabe_pur_avec_la_police_arabe(self):
        self.preparer()
        client = client_en(self.secretaire, "ar")
        with CaptureHtmlDuPdf() as capture:
            reponse = client.get(reverse("scolarite:cartes_classe_pdf", args=[self.c6a.pk]))
        self.assertEqual(reponse.status_code, 200)
        self.assertIn(b"Amiri", reponse.content)
        codes = set(VerificationDocument.objects.filter(type_document=TypeDocumentVerifiable.CARTE_ELEVE).values_list("code", flat=True))
        self.assertEqual(restes_hors_textes_saisis(capture.html, codes | {"testserver/verifier"}), [])  # seuls le code et l'adresse restent latins
        self.assertIn("أميناتا", capture.html)
        self.assertIn("وُلدت في", capture.html)  # « Née le » au féminin
        self.assertEqual(len(PdfReader(io.BytesIO(reponse.content)).pages), 1)

    def test_le_code_et_l_adresse_de_verification_restent_en_lettres_latines(self):
        """Ce qu'on recopie à la main ne se traduit pas : un chiffre arabe ou une lettre arabe au milieu du code le rendrait inutilisable."""
        self.preparer()
        client = client_en(self.secretaire, "ar")
        with CaptureHtmlDuPdf() as capture:
            client.get(reverse("scolarite:carte_eleve_pdf", args=[self.e1.matricule]))
        code = VerificationDocument.objects.get(eleve=self.e1, type_document=TypeDocumentVerifiable.CARTE_ELEVE).code
        self.assertIn(code, capture.html)
        self.assertIn("testserver/verifier", capture.html)

    def test_une_ecole_aux_noms_longs_et_des_cartes_en_arabe_restent_sur_les_pages_prevues(self):
        self.preparer()
        for numero in (1, 2):
            eleve = creer_compte(Role.ELEVE, f"carte-ar-{numero}@cartes.test", self.ecole)
            Inscription.objects.create(eleve=eleve, classe=self.c6a)
        reponse = client_en(self.secretaire, "ar").get(reverse("scolarite:cartes_classe_pdf", args=[self.c6a.pk]))
        self.assertEqual(len(PdfReader(io.BytesIO(reponse.content)).pages), 2)  # cinq cartes : quatre, puis une
