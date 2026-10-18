"""Cantine en arabe pur : chaque page, chaque message et le reçu PDF, sans une lettre latine (hors textes saisis par l'école)."""
import datetime

from django.urls import reverse

from cantine import services
from cantine.models import PaiementCantine
from cantine.test_cantine import CantineBase
from comptes.arabisation import invalider
from comptes.outils_test_arabe import CaptureHtmlDuPdf, client_en, restes_hors_textes_saisis

D = datetime.date
# Le nom d'une formule est un texte saisi par l'école : il reste tel qu'elle l'a écrit.
SAISIS = {"Français", "Formule du midi", "Repas à l'unité", "Formule du soir"}


def restes(reponse):
    return restes_hors_textes_saisis(reponse.content.decode(), SAISIS)


class CantineEnArabeTests(CantineBase):
    def setUp(self):
        invalider(self.ecole.pk)
        self.inscription = self.inscrire(debut=D(2026, 10, 15))
        self.paiement = services.enregistrer_paiement(inscription=self.inscription, montant=5000, mode_paiement="especes", acteur=self.gerant)
        self.gerant_ar = client_en(self.gerant, "ar")

    def verifier(self, adresse, client=None, **donnees):
        reponse = (client or self.gerant_ar).get(adresse, donnees)
        self.assertEqual(reponse.status_code, 200, adresse)
        self.assertEqual(restes(reponse), [], adresse)
        return reponse

    def test_les_pages_du_gerant(self):
        self.verifier(reverse("cantine:tableau"))
        self.verifier(reverse("cantine:tableau"), etat="toutes")
        self.verifier(reverse("cantine:inscrire_eleves"))
        self.verifier(reverse("cantine:inscrire_eleves"), classe=self.c6a.pk)
        self.verifier(reverse("cantine:appel"))
        self.verifier(reverse("cantine:formules"))
        self.verifier(reverse("cantine:fiche_inscription", args=[self.inscription.pk]))
        self.verifier(reverse("cantine:paiement", args=[self.inscription.pk]))

    def test_la_fiche_de_la_direction_avec_les_annulations(self):
        services.annuler_paiement(paiement=self.paiement, acteur=self.fondateur, motif="خطأ في الإدخال")
        services.enregistrer_paiement(inscription=self.inscription, montant=2000, mode_paiement="mobile_money", acteur=self.gerant)
        self.verifier(reverse("cantine:fiche_inscription", args=[self.inscription.pk]), client=client_en(self.fondateur, "ar"))

    def test_la_fiche_d_une_inscription_terminee_et_de_l_appel_rempli(self):
        services.terminer(inscription=self.inscription, date_fin=D(2026, 11, 30), acteur=self.gerant)
        self.verifier(reverse("cantine:fiche_inscription", args=[self.inscription.pk]))
        self.verifier(reverse("cantine:tableau"), etat="terminees")

    def test_le_suivi_des_familles(self):
        self.verifier(reverse("cantine:mon_suivi"), client=client_en(self.parent, "ar"))
        self.verifier(reverse("cantine:mon_suivi"), client=client_en(self.e1, "ar"))

    def test_les_pages_vides(self):
        client = client_en(self.gerant_b, "ar")
        self.verifier(reverse("cantine:tableau"), client=client)
        self.verifier(reverse("cantine:appel"), client=client)

    def test_les_messages_apres_chaque_action(self):
        client = self.gerant_ar
        parcours = [
            ("post", reverse("cantine:formules"), {"libelle": "Formule du soir", "mode": "mensuel", "montant": "3000"}),
            ("post", reverse("cantine:formules"), {"libelle": "Formule du soir", "mode": "mensuel", "montant": "3000"}),  # déjà existante
            ("post", reverse("cantine:formules"), {"libelle": "Autre", "mode": "mensuel", "montant": "0"}),
            ("post", reverse("cantine:basculer_formule", args=[self.au_repas.pk]), {}),
            ("post", reverse("cantine:basculer_formule", args=[self.au_repas.pk]), {}),
            ("post", reverse("cantine:inscrire_eleves"), {"classe": self.c6a.pk, "formule": self.mensuelle.pk, "date_debut": "2026-10-15", "eleves": [self.e2.pk]}),
            ("post", reverse("cantine:inscrire_eleves"), {"classe": self.c6a.pk, "formule": self.mensuelle.pk, "date_debut": "2026-10-15"}),
            ("post", reverse("cantine:appel"), {"date": datetime.date.today().isoformat(), "presents": [self.inscription.pk]}),
            ("get", reverse("cantine:appel"), {"date": (datetime.date.today() + datetime.timedelta(days=4)).isoformat()}),
            ("post", reverse("cantine:paiement", args=[self.inscription.pk]), {"montant": "7500", "mode_paiement": "virement"}),
            ("post", reverse("cantine:paiement", args=[self.inscription.pk]), {"montant": "0", "mode_paiement": "virement"}),
            ("post", reverse("cantine:terminer_inscription", args=[self.inscription.pk]), {"date_fin": "2026-12-20"}),
            ("post", reverse("cantine:terminer_inscription", args=[self.inscription.pk]), {"date_fin": "2026-12-21"}),
            ("post", reverse("cantine:terminer_inscription", args=[self.inscription.pk]), {"date_fin": "n'importe quoi"}),
        ]
        for methode, adresse, donnees in parcours:
            with self.subTest(adresse=adresse, donnees=donnees):
                reponse = getattr(client, methode)(adresse, donnees, follow=True)
                self.assertEqual(restes(reponse), [])
        direction = client_en(self.fondateur, "ar")
        for donnees in ({"motif": "خطأ في الإدخال"}, {"motif": ""}, {"motif": "مرة أخرى"}):
            with self.subTest(annulation=donnees):
                reponse = direction.post(reverse("cantine:annuler_paiement", args=[self.paiement.pk]), donnees, follow=True)
                self.assertEqual(restes(reponse), [])

    def test_le_recu_pdf(self):
        with CaptureHtmlDuPdf() as capture:
            reponse = self.gerant_ar.get(reverse("cantine:recu_pdf", args=[self.paiement.pk]))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(restes_hors_textes_saisis(capture.html, SAISIS), [])
        self.assertIn("direction: rtl", capture.html.replace("\n", " ").replace("  ", " "))

    def test_le_recu_tient_sur_une_seule_page_en_francais_et_en_arabe(self):
        import io

        from pypdf import PdfReader

        for client in (self.gerant_ar, client_en(self.gerant, "fr")):
            contenu = client.get(reverse("cantine:recu_pdf", args=[self.paiement.pk])).content
            self.assertEqual(len(PdfReader(io.BytesIO(contenu)).pages), 1)

    def test_le_recu_d_un_paiement_annule(self):
        services.annuler_paiement(paiement=self.paiement, acteur=self.fondateur, motif="خطأ")
        with CaptureHtmlDuPdf() as capture:
            self.gerant_ar.get(reverse("cantine:recu_pdf", args=[self.paiement.pk]))
        self.assertEqual(restes_hors_textes_saisis(capture.html, SAISIS), [])
        self.assertEqual(PaiementCantine.objects.filter(annule=True).count(), 1)
