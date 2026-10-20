"""Conseils de classe en arabe : aucune lettre latine ni chiffre occidental dans les pages et les PDF (hors ce que l'école a saisi elle-même)."""
from django.urls import reverse

from comptes.arabisation import invalider
from comptes.models import Utilisateur
from comptes.outils_test_arabe import CaptureHtmlDuPdf, client_en, restes_hors_textes_saisis
from pedagogie.test_conseils import T1, T3, ConseilBase

NOMS = [
    "Aminata Traoré", "Moussa Konaté", "Fatoumata Diarra", "Ibrahima Coulibaly", "Mariam Keïta", "Seydou Sissoko", "Awa Doumbia", "Bakary Camara",
    "Kadidia Sangaré", "Oumar Diallo", "Hawa Maïga", "Sékou Touré", "Salimata Cissé", "Modibo Bagayoko", "Nana Haïdara", "Drissa Berthé",
]
# ce que la direction écrit elle-même dans les observations (jamais traduit) et le bouton « Français », qui s'écrit dans la langue vers laquelle il bascule
SAISIS = ("Bon trimestre", "Très sérieuse", "Bavardages", "Français")


class ConseilEnArabeTests(ConseilBase):
    def setUp(self):
        # Les comptes de test portent des noms de courriel en minuscules (« parent », « comptable ») : de vrais noms, comme à l'école.
        for rang, compte in enumerate(Utilisateur.objects.filter(etablissement=self.ecole).order_by("pk")):
            prenom, nom = NOMS[rang % len(NOMS)].split()
            Utilisateur.objects.filter(pk=compte.pk).update(prenom=prenom, nom=nom)
        invalider(self.ecole.pk)
        self.fondateur.refresh_from_db()
        self.client = client_en(self.fondateur, "ar")
        for trimestre in (T1, T3):
            self.client.post(reverse("pedagogie:conseil", args=[self.c6a.pk, trimestre]), {
                "action": "suggestions", "date_conseil": "2026-12-20", "observations": "Bon trimestre.",
                f"sanction_{self.e3.pk}": "blame_conduite", f"observation_{self.e1.pk}": "Très sérieuse.",
            })

    def adresse(self, trimestre=T1):
        return reverse("pedagogie:conseil", args=[self.c6a.pk, trimestre])

    def verifier(self, texte):
        self.assertEqual(restes_hors_textes_saisis(texte, SAISIS), [], "Textes restés en lettres latines ou chiffres occidentaux")

    def test_la_liste_des_conseils(self):
        reponse = self.client.get(reverse("pedagogie:conseils"))
        self.assertEqual(reponse.status_code, 200)
        self.verifier(reponse.content.decode("utf-8"))

    def test_le_tableau_du_premier_trimestre(self):
        reponse = self.client.get(self.adresse(T1))
        self.assertEqual(reponse.status_code, 200)
        self.verifier(reponse.content.decode("utf-8"))

    def test_le_tableau_du_troisieme_trimestre_avec_le_passage(self):
        reponse = self.client.get(self.adresse(T3))
        self.assertEqual(reponse.status_code, 200)
        self.verifier(reponse.content.decode("utf-8"))

    def test_le_tableau_d_un_conseil_valide(self):
        self.client.post(self.adresse(T3), {"action": "valider"})
        reponse = self.client.get(self.adresse(T3))
        self.assertContains(reponse, "disabled")
        self.verifier(reponse.content.decode("utf-8"))

    def test_une_erreur_d_enregistrement_est_aussi_en_arabe(self):
        reponse = self.client.post(self.adresse(T1), {"action": "enregistrer", "seuil_tableau_d_honneur": "19", "seuil_encouragements": "14"}, follow=True)
        self.assertEqual(reponse.status_code, 200)
        self.verifier(reponse.content.decode("utf-8"))

    def test_le_proces_verbal_et_le_tableau_d_honneur_en_arabe(self):
        for trimestre in (T1, T3):
            for nom in ("pedagogie:conseil_proces_verbal_pdf", "pedagogie:conseil_tableau_d_honneur_pdf"):
                with self.subTest(document=nom, trimestre=trimestre), CaptureHtmlDuPdf() as capture:
                    reponse = self.client.get(reverse(nom, args=[self.c6a.pk, trimestre]))
                    self.assertEqual(reponse.status_code, 200)
                    self.assertTrue(reponse.content.startswith(b"%PDF"))
                    self.assertIn(b"Amiri", reponse.content)
                    self.assertEqual(restes_hors_textes_saisis(capture.html, SAISIS), [], "Textes restés en lettres latines ou chiffres occidentaux")

    def test_le_message_de_confirmation_des_boutons_est_traduit(self):
        reponse = self.client.get(self.adresse(T1))
        texte = reponse.content.decode("utf-8")
        self.assertNotIn("Remplacer les distinctions", texte)
        self.assertNotIn("Valider le conseil ?", texte)

    def test_le_bulletin_d_un_eleve_avec_les_decisions_du_conseil_valide_est_en_arabe(self):
        self.client.post(self.adresse(T1), {"valider": ""})
        self.client.post(self.adresse(T3), {"valider": ""})
        for eleve in (self.e1, self.e3):  # e1 : distinction et passage ; e3 : sanction et observation
            with self.subTest(eleve=eleve.pk), CaptureHtmlDuPdf() as capture:
                page = self.client.get(reverse("pedagogie:bulletin_eleve", args=[eleve.matricule]))
                self.assertEqual(page.status_code, 200)
                self.assertContains(page, "<table")
                self.verifier(page.content.decode("utf-8"))
                pdf = self.client.get(reverse("pedagogie:exporter_bulletin_pdf", args=[eleve.matricule]))
                self.assertEqual(pdf.status_code, 200)
                self.assertEqual(restes_hors_textes_saisis(capture.html, SAISIS), [], "Textes restés en lettres latines ou chiffres occidentaux")
