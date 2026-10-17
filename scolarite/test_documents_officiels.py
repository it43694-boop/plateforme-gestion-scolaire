"""
Documents officiels : certificat de scolarité, attestation de fréquentation, certificat de radiation.

Numéro d'ordre « 003/SIGLE/CERT/2026 » (jamais deux fois le même), un document par inscription (même numéro, même QR code), version
française, arabe ou les deux, signature et cachet imprimés au choix, droits par rôle.
"""
import datetime
import io
import re
from unittest import mock

from django.core.files.base import ContentFile
from django.urls import reverse
from PIL import Image
from pypdf import PdfReader

from comptes.arabisation import invalider
from comptes.models import JournalAudit, Utilisateur
from comptes.outils_test_arabe import CaptureHtmlDuPdf, client_en
from comptes.roles import Role
from comptes.traduction import restes_latins
from etablissement.models import Etablissement
from scolarite.documents import TYPES, emettre, format_numero, fusionner_pdf, inscription_concernee
from scolarite.models import (
    Abandon, Inscription, TransfertEleve, TypeDocumentVerifiable, VerificationDocument,
)
from scolarite.test_dossier_complet import StockageTemporaire, image_octets

NUMERO = re.compile(r"[0-9٠-٩]{3}/[A-Z0-9]+/[A-Z]+/[0-9٠-٩]{4}")
CERT, ATTEST, RAD = TYPES["certificat-scolarite"], TYPES["attestation-frequentation"], TYPES["certificat-radiation"]


def texte_du_pdf(contenu):
    """Le texte du PDF avec des espaces simples : un retour à la ligne au milieu d'une phrase ne doit pas faire échouer un test."""
    return " ".join(" ".join(page.extract_text() for page in PdfReader(io.BytesIO(contenu)).pages).split())


def png_transparent(taille=(300, 120), couleur=(20, 40, 160, 255)):
    image = Image.new("RGBA", taille, (0, 0, 0, 0))
    for x in range(20, taille[0] - 20):
        image.putpixel((x, taille[1] // 2), couleur)
    sortie = io.BytesIO()
    image.save(sortie, format="PNG")
    return sortie.getvalue()


class BaseDocuments(StockageTemporaire):
    def setUp(self):
        self.client.force_login(self.secretaire)
        Etablissement.objects.filter(pk=self.ecole.pk).update(sigle="CSE", nom="Complexe Scolaire Exemple")
        self.ecole.refresh_from_db()

    def url(self, code, eleve=None, **options):
        adresse = reverse("scolarite:document_officiel", args=[(eleve or self.e1).matricule, code])
        return adresse + ("?" + "&".join(f"{cle}={valeur}" for cle, valeur in options.items()) if options else "")

    def transferer(self, eleve, destination="Lycée Askia"):
        inscription = Inscription.objects.get(eleve=eleve, statut=Inscription.Statut.EN_COURS)
        Inscription.objects.filter(pk=inscription.pk).update(statut=Inscription.Statut.TRANSFERE)
        TransfertEleve.objects.create(
            inscription=inscription, destination_libelle=destination, date_transfert=datetime.date(2026, 11, 3), motif="Déménagement",
            enregistre_par=self.secretaire,
        )
        return inscription

    def abandonner(self, eleve):
        inscription = Inscription.objects.get(eleve=eleve, statut=Inscription.Statut.EN_COURS)
        Inscription.objects.filter(pk=inscription.pk).update(statut=Inscription.Statut.ABANDON)
        Abandon.objects.create(inscription=inscription, date_abandon=datetime.date(2026, 12, 1), motif="Raison privée", enregistre_par=self.secretaire)
        return inscription


class NumerotationTests(BaseDocuments):
    def inscription(self, eleve):
        return Inscription.objects.get(eleve=eleve, statut=Inscription.Statut.EN_COURS)

    def test_le_format_du_numero(self):
        self.assertEqual(format_numero(3, self.ecole, CERT, 2026), "003/CSE/CERT/2026")
        self.assertEqual(format_numero(1234, self.ecole, RAD, 2026), "1234/CSE/RAD/2026")

    def test_sans_sigle_ce_sont_les_initiales_du_nom(self):
        Etablissement.objects.filter(pk=self.ecole.pk).update(sigle="")
        self.ecole.refresh_from_db()
        self.assertEqual(self.ecole.sigle_effectif, "CSE")  # Complexe Scolaire Exemple
        self.ecole.nom = "Groupe Scolaire Les Étoiles de Bamako"
        self.assertEqual(self.ecole.sigle_effectif, "GSLEB")
        self.ecole.nom = "***"
        self.assertEqual(self.ecole.sigle_effectif, "ECOLE")
        self.ecole.sigle = " cse "
        self.assertEqual(self.ecole.sigle_effectif, "CSE")

    def test_les_numeros_se_suivent_par_type_sans_trou_ni_doublon(self):
        numeros = [emettre(self.inscription(e), CERT).numero for e in (self.e1, self.e2, self.e3)]
        annee = datetime.date.today().year
        self.assertEqual(numeros, [f"00{i}/CSE/CERT/{annee}" for i in (1, 2, 3)])
        self.assertEqual(emettre(self.inscription(self.e1), ATTEST).numero, f"001/CSE/ATTEST/{annee}")  # chaque type a son compteur

    def test_le_meme_document_garde_son_numero_et_son_jeton(self):
        premier = emettre(self.inscription(self.e1), CERT)
        second = emettre(self.inscription(self.e1), CERT)
        self.assertEqual((premier.pk, premier.numero, premier.jeton), (second.pk, second.numero, second.jeton))
        self.assertEqual(VerificationDocument.objects.filter(type_document=TypeDocumentVerifiable.CERTIFICAT_SCOLARITE).count(), 1)

    def test_le_compteur_repart_a_un_chaque_annee(self):
        with mock.patch("scolarite.documents.timezone.localdate", return_value=datetime.date(2026, 12, 31)):
            emettre(self.inscription(self.e1), CERT)
            self.assertEqual(emettre(self.inscription(self.e2), CERT).numero, "002/CSE/CERT/2026")
        with mock.patch("scolarite.documents.timezone.localdate", return_value=datetime.date(2027, 1, 2)):
            self.assertEqual(emettre(self.inscription(self.e3), CERT).numero, "001/CSE/CERT/2027")

    def test_chaque_ecole_a_ses_propres_numeros(self):
        emettre(self.inscription(self.e1), CERT)
        self.assertEqual(emettre(self.inscription(self.e5), CERT).numero.split("/")[0], "002")  # même école : le suivant
        compteurs = {s.etablissement_id: s.dernier_numero for s in __import__("finances.models", fromlist=["SequenceReference"]).SequenceReference.objects.filter(prefixe="DOC-CERT")}
        self.assertEqual(compteurs, {self.ecole.pk: 2})  # l'autre école n'a aucun compteur

    def test_un_document_emis_avant_la_numerotation_recoit_un_numero(self):
        ancien = VerificationDocument.objects.create(
            type_document=TypeDocumentVerifiable.CERTIFICAT_SCOLARITE, eleve=self.e1, inscription=self.inscription(self.e1),
        )
        self.assertEqual(ancien.numero, "")
        emis = emettre(self.inscription(self.e1), CERT)
        self.assertEqual(emis.pk, ancien.pk)
        self.assertTrue(NUMERO.fullmatch(emis.numero))

    def test_l_attestation_de_scolarite_d_origine_n_est_pas_touchee(self):
        reponse = self.client.get(reverse("scolarite:generer_attestation_scolarite", args=[self.e1.matricule]))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(VerificationDocument.objects.get(type_document=TypeDocumentVerifiable.ATTESTATION_SCOLARITE).numero, "")


class ChoixDeLInscriptionTests(BaseDocuments):
    def test_attestation_et_certificat_pour_une_inscription_en_cours(self):
        for type_document in (CERT, ATTEST):
            self.assertEqual(inscription_concernee(self.e1, type_document).statut, Inscription.Statut.EN_COURS)
        self.assertIsNone(inscription_concernee(self.e1, RAD))

    def test_un_eleve_admis_a_un_certificat_mais_pas_d_attestation(self):
        Inscription.objects.filter(eleve=self.e1, statut=Inscription.Statut.EN_COURS).update(statut=Inscription.Statut.ADMIS)
        self.assertEqual(inscription_concernee(self.e1, CERT).statut, Inscription.Statut.ADMIS)
        self.assertIsNone(inscription_concernee(self.e1, ATTEST))

    def test_la_radiation_ne_concerne_que_transfert_et_abandon(self):
        self.transferer(self.e1)
        self.abandonner(self.e2)
        self.assertEqual(inscription_concernee(self.e1, RAD).statut, Inscription.Statut.TRANSFERE)
        self.assertEqual(inscription_concernee(self.e2, RAD).statut, Inscription.Statut.ABANDON)
        self.assertIsNone(inscription_concernee(self.e3, RAD))
        self.transferer(self.e4)
        self.assertIsNone(inscription_concernee(self.e1, ATTEST))  # un élève radié n'est plus « en cours »
        self.assertEqual(inscription_concernee(self.e1, CERT).statut, Inscription.Statut.REDOUBLE)  # le certificat porte sur sa dernière année menée à terme
        self.assertIsNone(inscription_concernee(self.e4, CERT))  # e4 n'a que l'inscription en cours : il n'a rien à certifier une fois radié

    def test_l_inscription_la_plus_recente_gagne(self):
        # e1 a une inscription 2025-2026 (redoublement) et une inscription en cours : c'est celle en cours qui compte
        self.assertEqual(Inscription.objects.filter(eleve=self.e1).count(), 2)
        self.assertEqual(inscription_concernee(self.e1, CERT).classe, self.c6a)


class DocumentsPdfTests(BaseDocuments):
    def test_le_certificat_de_scolarite_francais(self):
        reponse = self.client.get(self.url("certificat-scolarite"))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse["Content-Type"], "application/pdf")
        self.assertIn("cert_", reponse["Content-Disposition"])
        texte = texte_du_pdf(reponse.content)
        for attendu in ("CERTIFICAT DE SCOLARITÉ", self.e1.nom_complet, self.e1.matricule, "6A", "2026-2027", "est régulièrement inscrit(e)"):
            self.assertIn(attendu, texte)
        self.assertRegex(texte, r"N° 001/CSE/CERT/\d{4}")
        self.assertEqual(len(PdfReader(io.BytesIO(reponse.content)).pages), 1)

    def test_l_attestation_de_frequentation(self):
        texte = texte_du_pdf(self.client.get(self.url("attestation-frequentation")).content)
        self.assertIn("ATTESTATION DE FRÉQUENTATION", texte)
        self.assertIn("fréquente régulièrement", texte)
        self.assertRegex(texte, r"/ATTEST/")

    def test_le_certificat_de_scolarite_d_un_eleve_admis_parle_au_passe(self):
        Inscription.objects.filter(eleve=self.e1, statut=Inscription.Statut.EN_COURS).update(statut=Inscription.Statut.ADMIS)
        texte = texte_du_pdf(self.client.get(self.url("certificat-scolarite")).content)
        self.assertIn("a été régulièrement inscrit(e)", texte)
        self.assertNotIn("est régulièrement inscrit(e)", texte)

    def test_le_certificat_de_radiation_pour_un_transfert(self):
        self.transferer(self.e1, "Lycée Askia")
        texte = texte_du_pdf(self.client.get(self.url("certificat-radiation")).content)
        for attendu in ("CERTIFICAT DE RADIATION", "03/11/2026", "Transfert vers une autre école", "Lycée Askia"):
            self.assertIn(attendu, texte)

    def test_le_certificat_de_radiation_pour_un_abandon_ne_donne_pas_le_motif_prive(self):
        self.abandonner(self.e2)
        texte = texte_du_pdf(self.client.get(self.url("certificat-radiation", self.e2)).content)
        self.assertIn("Abandon de la scolarité", texte)
        self.assertIn("01/12/2026", texte)
        self.assertNotIn("Raison privée", texte)  # le motif saisi par l'école n'est jamais imprimé

    def test_un_document_impossible_renvoie_au_dossier_avec_un_message(self):
        reponse = self.client.get(self.url("certificat-radiation", self.e3), follow=True)
        self.assertContains(reponse, "pas été radié")  # (l'apostrophe est écrite &#x27; dans la page)
        Inscription.objects.filter(eleve=self.e3).update(statut=Inscription.Statut.ADMIS)
        reponse = self.client.get(self.url("attestation-frequentation", self.e3), follow=True)
        self.assertContains(reponse, "pas d&#x27;inscription en cours")
        self.assertEqual(VerificationDocument.objects.count(), 0)  # aucun numéro n'est consommé par un refus

    def test_un_code_de_document_inconnu_est_introuvable(self):
        self.assertEqual(self.client.get(self.url("diplome-de-fin-d-etudes")).status_code, 404)

    def test_la_page_de_verification_donne_le_numero(self):
        self.client.get(self.url("certificat-scolarite"))
        jeton = VerificationDocument.objects.get().jeton
        self.client.logout()
        donnees = self.client.get(reverse("scolarite:verifier_document", args=[jeton])).json()
        self.assertEqual(donnees["type_document"], "Certificat de scolarité")
        self.assertRegex(donnees["numero"], r"^001/CSE/CERT/\d{4}$")

    def test_l_edition_est_journalisee(self):
        self.client.get(self.url("certificat-scolarite", signature=1, bilingue=1))
        journal = JournalAudit.objects.get(action="generation_document_officiel")
        self.assertEqual((journal.details["type"], journal.details["bilingue"]), ("CERT", True))
        self.assertRegex(journal.details["numero"], r"^001/CSE/CERT/")

    # --- options
    def test_la_version_bilingue_est_un_pdf_de_deux_pages_francais_puis_arabe(self):
        with CaptureHtmlDuPdf() as capture:
            reponse = self.client.get(self.url("certificat-scolarite", bilingue=1))
        self.assertEqual(len(PdfReader(io.BytesIO(reponse.content)).pages), 2)
        self.assertEqual(len(capture.pages), 2)
        self.assertNotIn("Amiri", capture.pages[0])  # d'abord le français (la page est en français)
        self.assertIn("Amiri", capture.pages[1])
        self.assertIn(self.e1.nom, capture.pages[0])

    def test_sans_option_une_seule_langue(self):
        self.assertEqual(len(PdfReader(io.BytesIO(self.client.get(self.url("certificat-scolarite")).content)).pages), 1)

    def test_signature_et_cachet_ne_sont_imprimes_que_s_ils_existent_et_sont_demandes(self):
        def images(**options):
            with CaptureHtmlDuPdf() as capture:
                self.client.get(self.url("certificat-scolarite", **options))
            return capture.html.count("data:image/png;base64,")

        base = images()  # le QR code seulement
        self.assertEqual(images(signature=1, cachet=1), base)  # rien n'est téléversé : rien à imprimer
        self.ecole.signature.save("signature.png", ContentFile(png_transparent()), save=False)
        self.ecole.cachet.save("cachet.png", ContentFile(png_transparent((200, 200), (160, 20, 20, 255))), save=True)
        self.assertEqual(images(), base)  # téléversés mais non demandés
        self.assertEqual(images(signature=1), base + 1)
        self.assertEqual(images(cachet=1), base + 1)
        self.assertEqual(images(signature=1, cachet=1), base + 2)

    def test_le_nom_et_la_fonction_du_signataire(self):
        Etablissement.objects.filter(pk=self.ecole.pk).update(nom_signataire="Mamadou Keita", fonction_signataire="Le Directeur")
        texte = texte_du_pdf(self.client.get(self.url("certificat-scolarite")).content)
        self.assertIn("Mamadou Keita", texte)
        self.assertIn("Le Directeur", texte)
        self.assertNotIn("Signature et cachet de l'établissement", texte)

    def test_la_ville_est_celle_de_l_ecole(self):
        Etablissement.objects.filter(pk=self.ecole.pk).update(commune="Kati")
        self.assertIn("Fait à Kati, le", texte_du_pdf(self.client.get(self.url("certificat-scolarite")).content))

    def test_fusionner_des_pdf(self):
        un = self.client.get(self.url("certificat-scolarite")).content
        self.assertEqual(len(PdfReader(io.BytesIO(fusionner_pdf(un, un, un))).pages), 3)

    # --- droits
    def test_seule_l_administration_edite_des_documents(self):
        for compte, code in (
            (self.secretaire, 200), (self.fondateur, 200), (self.dir_1er, 200),
            (self.t1, 403), (self.parent, 403), (self.e1, 403), (self.comptable, 403), (self.censeur, 403),
        ):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertEqual(self.client.get(self.url("certificat-scolarite")).status_code, code)

    def test_un_directeur_de_cycle_ne_traite_que_son_cycle(self):
        self.client.force_login(self.dir_1er)
        self.assertEqual(self.client.get(self.url("certificat-scolarite", self.e5)).status_code, 403)  # e5 est en 9A (2ème cycle)

    def test_une_autre_ecole_ne_voit_rien(self):
        self.client.force_login(self.fondateur_b)
        self.assertEqual(self.client.get(self.url("certificat-scolarite")).status_code, 404)

    def test_un_visiteur_est_renvoye_a_la_connexion(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url("certificat-scolarite")).status_code, 302)

    # --- dossier
    def test_les_boutons_du_dossier_suivent_l_etat_de_l_eleve(self):
        def boutons(eleve, compte=self.secretaire):
            self.client.force_login(compte)
            page = self.client.get(reverse("scolarite:dossier_eleve", args=[eleve.matricule])).content.decode()
            return {code for code in TYPES if reverse("scolarite:document_officiel", args=[eleve.matricule, code]) in page}

        self.assertEqual(boutons(self.e1), {"certificat-scolarite", "attestation-frequentation"})
        self.transferer(self.e4)  # e4 n'a pas d'autre inscription : il ne reste que la radiation
        self.assertEqual(boutons(self.e4), {"certificat-radiation"})
        self.transferer(self.e2)  # e2 a aussi une inscription terminée (admis l'an dernier) : un certificat de scolarité reste possible
        self.assertEqual(boutons(self.e2), {"certificat-scolarite", "certificat-radiation"})
        self.assertEqual(boutons(self.e1, self.parent), set())  # un parent ne voit pas ces boutons

    def test_la_signature_se_televerse_dans_les_parametres_de_l_ecole(self):
        self.client.force_login(self.developpeur)
        donnees = {
            "nom": self.ecole.nom, "code_devise": "FCFA", "pas_montant": 5000, "sigle": "cse", "nom_signataire": "  Mamadou   Keita ",
            "fonction_signataire": "Le Directeur", "signature": ContentFile(png_transparent(), name="signature.png"),
            "taux_inps_salarie": "3.6", "taux_inps_employeur": "20", "taux_amo_salarie": "3.06", "taux_amo_employeur": "3.5",
            "situation_fonctionnement": "ouvert", "coefficient_conduite": 1, "langue_par_defaut": "fr",
        }
        reponse = self.client.post(reverse("espace_developpeur:parametres_etablissement"), donnees)
        self.assertEqual(reponse.status_code, 302, getattr(getattr(reponse, "context", None), "get", lambda *_: None)("formulaire") and reponse.context["formulaire"].errors)
        self.ecole.refresh_from_db()
        self.assertEqual((self.ecole.sigle, self.ecole.nom_signataire), ("CSE", "Mamadou Keita"))
        self.assertTrue(self.ecole.signature)

    def test_un_sigle_invalide_est_refuse(self):
        from espace_developpeur.forms import ParametresEtablissementForm

        formulaire = ParametresEtablissementForm({"nom": "X", "code_devise": "FCFA", "pas_montant": 5000, "sigle": "É-C!"}, instance=self.ecole)
        self.assertFalse(formulaire.is_valid())
        self.assertIn("sigle", formulaire.errors)

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.developpeur = __import__("statistiques.test_education", fromlist=["creer_compte"]).creer_compte(Role.DEVELOPPEUR, "dev@documents.test", cls.ecole)


class DocumentsEnArabeTests(BaseDocuments):
    def setUp(self):
        super().setUp()
        Utilisateur.objects.filter(pk=self.e1.pk).update(prenom="Aminata", nom="Traoré", prenom_ar="أميناتا", nom_ar="تراوري", lieu_naissance="Bamako")
        Etablissement.objects.filter(pk=self.ecole.pk).update(nom_signataire="Mamadou Keita", fonction_signataire="Le Directeur")
        invalider(self.ecole.pk)
        self.arabe = client_en(self.secretaire, "ar")

    def sans_numero(self, html):
        return [t for t in restes_latins(html) if not NUMERO.sub("", t).strip(" :رقم") == "" and re.search("[A-Za-z]", NUMERO.sub("", t))]

    def test_chaque_document_est_en_arabe_pur_hors_numero(self):
        self.transferer(self.e2)
        for code, eleve in (("certificat-scolarite", self.e1), ("attestation-frequentation", self.e1), ("certificat-radiation", self.e2)):
            with self.subTest(code=code), CaptureHtmlDuPdf() as capture:
                reponse = self.arabe.get(self.url(code, eleve, signature=1))
                self.assertEqual(reponse.status_code, 200)
                self.assertIn(b"Amiri", reponse.content)
                self.assertEqual(self.sans_numero(capture.html), [])
                self.assertEqual(len(capture.pages), 1)

    def test_les_noms_sont_en_arabe(self):
        with CaptureHtmlDuPdf() as capture:
            self.arabe.get(self.url("certificat-scolarite"))
        self.assertIn("أميناتا", capture.html)
        self.assertIn("تراوري", capture.html)
        self.assertNotIn("Aminata", capture.html)

    def test_bilingue_depuis_une_page_arabe_met_l_arabe_d_abord(self):
        with CaptureHtmlDuPdf() as capture:
            reponse = self.arabe.get(self.url("certificat-scolarite", bilingue=1))
        self.assertEqual(len(PdfReader(io.BytesIO(reponse.content)).pages), 2)
        self.assertIn("Amiri", capture.pages[0])
        self.assertNotIn("Amiri", capture.pages[1])
        self.assertIn("Aminata", capture.pages[1])  # la version française garde les noms latins

    def test_les_fonctions_usuelles_du_signataire_sont_traduites(self):
        with CaptureHtmlDuPdf() as capture:
            self.arabe.get(self.url("certificat-scolarite"))
        self.assertIn("المدير", capture.html)
        self.assertNotIn("Le Directeur", capture.html)
