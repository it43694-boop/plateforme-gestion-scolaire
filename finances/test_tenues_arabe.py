"""Vente de tenues en arabe pur : chaque page, chaque message et le reçu PDF, sans une lettre latine (hors noms d'articles saisis par l'école)."""
from django.urls import reverse

from comptes.arabisation import invalider
from comptes.outils_test_arabe import CaptureHtmlDuPdf, client_en, restes_hors_textes_saisis
from finances import tenues
from finances.models import ArticleTenue
from finances.test_tenues import TenuesBase

# Les noms d'articles sont saisis par l'école : ils restent tels qu'elle les a écrits.
SAISIS = {"Chemisette bleue", "Pantalon", "Jupe", "Ancienne blouse", "Short sport", "Polo vert", "Boubacar Maiga", "Français"}


def restes(reponse):
    return restes_hors_textes_saisis(reponse.content.decode(), SAISIS)


class TenuesEnArabeTests(TenuesBase):
    def setUp(self):
        invalider(self.ecole.pk)
        ArticleTenue.objects.filter(etablissement=self.ecole).update(taille="")  # les tailles sont saisies par l'école : ici, aucune
        self.vente = self.vendre({self.polo.pk: 2, self.pantalon.pk: 1}, eleve=self.e1)
        self.comptable_ar = client_en(self.comptable, "ar")
        self.direction_ar = client_en(self.fondateur, "ar")

    def verifier(self, adresse, client=None, **donnees):
        reponse = (client or self.comptable_ar).get(adresse, donnees)
        self.assertEqual(reponse.status_code, 200, adresse)
        self.assertEqual(restes(reponse), [], adresse)

    def test_les_pages(self):
        self.verifier(reverse("finances:tenues"))
        self.verifier(reverse("finances:tenues_vendre"))
        self.verifier(reverse("finances:tenues_ventes"))
        self.verifier(reverse("finances:tenues_ventes"), q="Chemisette")
        self.verifier(reverse("finances:modifier_article_tenue", args=[self.polo.pk]))

    def test_les_pages_de_la_direction_avec_une_vente_annulee(self):
        autre = self.vendre({self.polo.pk: 1}, acheteur="Boubacar Maiga")
        tenues.annuler_vente(vente=autre, motif="خطأ في المقاس", acteur=self.fondateur)
        self.verifier(reverse("finances:tenues_ventes"), client=self.direction_ar)
        self.verifier(reverse("finances:tenues"), client=self.direction_ar)

    def test_les_messages_apres_chaque_action(self):
        client = self.comptable_ar
        parcours = [
            ("post", reverse("finances:tenues"), {"libelle": "Short sport", "taille": "", "prix": "3500", "seuil_alerte": "4", "actif": "on"}),
            ("post", reverse("finances:tenues"), {"libelle": "Short sport", "taille": "", "prix": "3500", "seuil_alerte": "4"}),  # doublon
            ("post", reverse("finances:tenues"), {"libelle": "Casquette", "taille": "", "prix": "0", "seuil_alerte": "4"}),
            ("post", reverse("finances:modifier_article_tenue", args=[self.polo.pk]), {"libelle": "Chemisette bleue", "taille": "", "prix": "5000", "seuil_alerte": "5", "actif": "on"}),
            ("post", reverse("finances:approvisionner_tenue", args=[self.jupe.pk]), {"quantite": "12", "note": "وصل التسليم"}),
            ("post", reverse("finances:approvisionner_tenue", args=[self.jupe.pk]), {"quantite": "0"}),
            ("post", reverse("finances:corriger_stock_tenue", args=[self.jupe.pk]), {"nouveau_stock": "10", "note": "جرد المخزون"}),
            ("post", reverse("finances:corriger_stock_tenue", args=[self.jupe.pk]), {"nouveau_stock": "10", "note": "مرة أخرى"}),
            ("post", reverse("finances:corriger_stock_tenue", args=[self.jupe.pk]), {"nouveau_stock": "", "note": ""}),
            ("post", reverse("finances:tenues_vendre"), {"matricule_eleve": self.e2.matricule, "mode_paiement": "mobile_money", f"qte_{self.polo.pk}": "1"}),
            ("post", reverse("finances:tenues_vendre"), {"mode_paiement": "especes"}),
            ("post", reverse("finances:tenues_vendre"), {"mode_paiement": "especes", f"qte_{self.pantalon.pk}": "9"}),
            ("post", reverse("finances:tenues_vendre"), {"matricule_eleve": "000000000", "mode_paiement": "especes", f"qte_{self.polo.pk}": "1"}),
        ]
        for methode, adresse, donnees in parcours:
            with self.subTest(adresse=adresse, donnees=donnees):
                reponse = getattr(client, methode)(adresse, donnees, follow=True)
                self.assertEqual(restes(reponse), [])
        for donnees in ({"motif": "خطأ في المقاس"}, {"motif": ""}, {"motif": "مرة أخرى"}):
            with self.subTest(annulation=donnees):
                reponse = self.direction_ar.post(reverse("finances:tenues_annuler_vente", args=[self.vente.pk]), donnees, follow=True)
                self.assertEqual(restes(reponse), [])

    def test_le_recu_pdf(self):
        with CaptureHtmlDuPdf() as capture:
            reponse = self.comptable_ar.get(reverse("finances:tenues_recu_pdf", args=[self.vente.pk]))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(restes_hors_textes_saisis(capture.html, SAISIS | {self.e1.nom_complet}), [])

    def test_le_recu_tient_sur_une_seule_page_en_francais_et_en_arabe(self):
        import io

        from pypdf import PdfReader

        for client in (self.comptable_ar, client_en(self.comptable, "fr")):
            contenu = client.get(reverse("finances:tenues_recu_pdf", args=[self.vente.pk])).content
            self.assertEqual(len(PdfReader(io.BytesIO(contenu)).pages), 1)

    def test_le_recu_d_une_vente_annulee(self):
        tenues.annuler_vente(vente=self.vente, motif="خطأ", acteur=self.fondateur)
        with CaptureHtmlDuPdf() as capture:
            self.comptable_ar.get(reverse("finances:tenues_recu_pdf", args=[self.vente.pk]))
        self.assertEqual(restes_hors_textes_saisis(capture.html, SAISIS), [])
