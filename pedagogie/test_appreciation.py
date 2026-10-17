"""
Appréciations du bulletin : six niveaux, une seule règle pour les notes de matières, la note de conduite et la moyenne du trimestre.

    Insuffisant (moins de 10) · Passable (10) · Assez Bien (12) · Bien (14) · Très Bien (16) · Excellent (18 et plus)

Une note de 13 est « Assez Bien » : l'ancienne échelle, relevée sur un seul bulletin, n'avait pas ce niveau et la notait « Bien ».
"""
from decimal import Decimal

from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.urls import reverse

from pedagogie.models import APPRECIATIONS_PAR_SEUIL, appreciation_pour
from pedagogie.test_conduite import ConduiteBase


class EchelleTests(SimpleTestCase):
    def test_les_bornes_de_chaque_niveau(self):
        attendus = (
            ("0", "Insuffisant"), ("9.99", "Insuffisant"),
            ("10", "Passable"), ("11.99", "Passable"),
            ("12", "Assez Bien"), ("13", "Assez Bien"), ("13.99", "Assez Bien"),
            ("14", "Bien"), ("15.99", "Bien"),
            ("16", "Très Bien"), ("16.99", "Très Bien"), ("17", "Très Bien"), ("17.99", "Très Bien"),
            ("18", "Excellent"), ("19.5", "Excellent"), ("20", "Excellent"),
        )
        for valeur, libelle in attendus:
            with self.subTest(valeur=valeur):
                self.assertEqual(appreciation_pour(Decimal(valeur)), libelle)

    def test_une_note_de_13_est_assez_bien(self):
        for valeur in ("13", "13.01", "13.5", "13.69", "13.81"):
            with self.subTest(valeur=valeur):
                self.assertEqual(appreciation_pour(Decimal(valeur)), "Assez Bien")

    def test_pas_de_note_pas_d_appreciation(self):
        self.assertEqual(appreciation_pour(None), "")

    def test_les_seuils_sont_classes_du_plus_haut_au_plus_bas_sans_doublon(self):
        seuils = [seuil for seuil, _ in APPRECIATIONS_PAR_SEUIL]
        self.assertEqual(seuils, sorted(seuils, reverse=True))
        self.assertEqual(len(set(seuils)), len(seuils))
        self.assertEqual([libelle for _, libelle in APPRECIATIONS_PAR_SEUIL],
                         ["Excellent", "Très Bien", "Bien", "Assez Bien", "Passable"])


class BulletinTests(ConduiteBase):
    """La même règle sert aux trois endroits du bulletin, à l'écran comme dans le PDF."""

    def lignes_et_moyenne(self, eleve):
        trimestre = self.bulletin(eleve)["bulletins_trimestre"][0]
        return trimestre["lignes"], trimestre

    def test_une_matiere_a_13_est_assez_bien(self):
        self.matiere(self.e5, 13)
        lignes, trimestre = self.lignes_et_moyenne(self.e5)
        self.assertEqual(lignes[0]["moyenne"], Decimal("13"))
        self.assertEqual(lignes[0]["appreciation"], "Assez Bien")
        self.assertEqual(trimestre["appreciation"], "Assez Bien")

    def test_la_conduite_a_13_est_assez_bien_aussi(self):
        self.matiere(self.e5, 15)
        self.conduite(self.e5, "13")
        lignes, _ = self.lignes_et_moyenne(self.e5)
        conduite = lignes[-1]
        self.assertEqual((conduite["matiere"], conduite["appreciation"]), ("Conduite", "Assez Bien"))
        self.assertEqual(lignes[0]["appreciation"], "Bien")  # 15 : Bien

    def test_la_moyenne_du_trimestre_suit_la_meme_regle(self):
        self.matiere(self.e5, 12)
        self.conduite(self.e5, "14")  # (12 + 14) / 2 = 13
        _, trimestre = self.lignes_et_moyenne(self.e5)
        self.assertEqual(trimestre["moyenne"], Decimal("13.00"))
        self.assertEqual(trimestre["appreciation"], "Assez Bien")

    def test_l_ecran_et_le_pdf_affichent_assez_bien(self):
        self.matiere(self.e5, 13)
        self.client.force_login(self.fondateur)
        page = self.client.get(reverse("pedagogie:bulletin_eleve", args=[self.e5.matricule]))
        self.assertContains(page, "Assez Bien")
        self.assertNotContains(page, ">Bien<")
        html = render_to_string("pedagogie/bulletin_pdf.html", {
            "eleve": self.e5, "inscription": self.i["e5"], "verification": None, "verification_url": "", "qr_code": "",
            **self.bulletin(self.e5),
        })
        self.assertIn("Assez Bien", html)
