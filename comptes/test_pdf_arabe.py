"""PDF en arabe : texte traduit, de droite à gauche, police arabe intégrée, parenthèses retournées ; PDF français inchangés."""
import io

from django.test import Client, SimpleTestCase
from django.urls import reverse

from comptes.arabisation import invalider
from comptes.langues import NOM_COOKIE_LANGUE
from comptes.models import Utilisateur
from comptes.pdf import PARENTHESES, creer_pdf, html_en_arabe
from comptes.roles import Role
from finances.models import TypeTranche, enregistrer_paiement
from scolarite.models import Inscription
from statistiques.test_education import EducationBase, creer_compte


class HtmlEnArabeTests(SimpleTestCase):
    HTML = '<html><head><style>p { font-size: 10px; }</style></head><body><p class="x">Élève : Awa (2026-2027)</p><a href="/x/(a)">lien</a></body></html>'

    def test_le_document_est_de_droite_a_gauche_avec_la_police_arabe(self):
        html = html_en_arabe(self.HTML)
        self.assertIn('<html lang="ar" dir="rtl">', html)
        self.assertIn("Amiri", html)
        self.assertIn("Amiri-Regular.ttf", html)

    def test_les_tailles_de_police_sont_agrandies(self):
        self.assertIn("font-size: 11.8px", html_en_arabe(self.HTML))

    def test_les_parentheses_du_texte_sont_retournees_mais_pas_celles_des_adresses(self):
        html = html_en_arabe(self.HTML)
        self.assertIn(")2026-2027(", html.replace("٢٠٢٦-٢٠٢٧", "2026-2027"))
        self.assertIn('href="/x/(a)"', html)  # une adresse n'est jamais modifiée

    def test_la_table_des_parentheses_est_symetrique(self):
        self.assertEqual("(a)[b]{c}«d»".translate(PARENTHESES), ")a(]b[}c{»d«")


class PdfEnArabeTests(EducationBase):
    def setUp(self):
        self.fondateur = creer_compte(Role.FONDATEUR, "fondateur@pdf-ar.test", self.ecole)
        Utilisateur.objects.filter(pk=self.e5.pk).update(prenom="Awa", nom="Traore", prenom_ar="عوا", nom_ar="تراوري")
        invalider(self.ecole.pk)

    def client_de(self, langue):
        client = Client()
        client.force_login(self.fondateur)
        client.cookies[NOM_COOKIE_LANGUE] = langue
        return client

    def test_le_bulletin_en_arabe_embarque_la_police_arabe(self):
        reponse = self.client_de("ar").get(reverse("pedagogie:exporter_bulletin_pdf", args=[self.e5.matricule]))
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(reponse.content.startswith(b"%PDF"))
        self.assertIn(b"Amiri", reponse.content)

    def test_le_bulletin_en_francais_n_embarque_pas_la_police_arabe(self):
        reponse = self.client_de("fr").get(reverse("pedagogie:exporter_bulletin_pdf", args=[self.e5.matricule]))
        self.assertEqual(reponse.status_code, 200)
        self.assertNotIn(b"Amiri", reponse.content)

    def test_le_recu_en_arabe(self):
        inscription = Inscription.objects.get(eleve=self.e5, statut=Inscription.Statut.EN_COURS)
        paiement = enregistrer_paiement(
            eleve=self.e5, inscription=inscription, tranche=TypeTranche.INSCRIPTION, montant=5000, mode_paiement="especes", enregistre_par=self.fondateur,
        )
        reponse = self.client_de("ar").get(reverse("finances:exporter_recu_paiement_pdf", args=[paiement.id]))
        self.assertEqual(reponse.status_code, 200)
        self.assertIn(b"Amiri", reponse.content)

    def test_l_attestation_en_arabe(self):
        reponse = self.client_de("ar").get(reverse("scolarite:generer_attestation_scolarite", args=[self.e5.matricule]))
        self.assertEqual(reponse.status_code, 200)
        self.assertIn(b"Amiri", reponse.content)

    def test_creer_pdf_sans_requete_utilise_la_langue_donnee(self):
        html = "<html><head></head><body><p>Reçu de paiement de scolarité</p></body></html>"
        arabe, francais = io.BytesIO(), io.BytesIO()
        self.assertFalse(creer_pdf(html, arabe, langue="ar", etablissement_id=self.ecole.pk).err)
        self.assertFalse(creer_pdf(html, francais, langue="fr").err)
        self.assertIn(b"Amiri", arabe.getvalue())
        self.assertNotIn(b"Amiri", francais.getvalue())

    def test_la_police_arabe_est_sous_licence_libre_et_livree(self):
        from comptes.pdf import DOSSIER_POLICES

        for nom in ("Amiri-Regular.ttf", "Amiri-Bold.ttf", "OFL-Amiri.txt"):
            with self.subTest(fichier=nom):
                self.assertTrue((DOSSIER_POLICES / nom).is_file())
