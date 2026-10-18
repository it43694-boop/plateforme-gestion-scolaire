"""Bulletin mensuel du premier cycle en arabe pur : chaque page, chaque message et le bulletin PDF, sans une lettre latine (hors textes saisis par l'école)."""
import io

from django.urls import reverse
from pypdf import PdfReader

from comptes.arabisation import invalider
from comptes.outils_test_arabe import CaptureHtmlDuPdf, client_en, restes_hors_textes_saisis
from pedagogie.models import DisciplineMensuelle, ObservationMensuelle, PeriodeCloturee
from pedagogie.test_bulletin_mensuel import BULLETIN_DE_LA_PHOTO, NOV, OCT, MensuelBase

SAISIS = {"Français", "Discipline du jeudi"}  # le nom d'une discipline ajoutée par l'école reste tel qu'elle l'a écrit


def restes(reponse):
    return restes_hors_textes_saisis(reponse.content.decode(), SAISIS)


class BulletinMensuelEnArabeTests(MensuelBase):
    def setUp(self):
        invalider(self.ecole.pk)
        for eleve in (self.e1, self.e2):
            self.noter(eleve, OCT, BULLETIN_DE_LA_PHOTO)
        self.noter(self.e3, OCT, {"Dictée": 5})
        self.noter(self.e1, NOV, {"Dictée": 6})
        ObservationMensuelle.objects.create(eleve=self.e1, classe=self.c6a, mois=OCT, observation="عمل جيد")
        self.maitre = client_en(self.t1, "ar")
        self.direction = client_en(self.fondateur, "ar")

    def verifier(self, adresse, client=None, **donnees):
        reponse = (client or self.maitre).get(adresse, donnees)
        with self.subTest(adresse=adresse):  # une page en défaut n'empêche pas de vérifier les suivantes
            self.assertEqual(reponse.status_code, 200, adresse)
            self.assertEqual(restes(reponse), [], adresse)
        return reponse

    def test_les_pages_du_maitre(self):
        self.verifier(reverse("pedagogie:mensuel_classes"))
        self.verifier(reverse("pedagogie:mensuel_grille", args=[self.c6a.pk, 2026, 10]))
        self.verifier(reverse("pedagogie:mensuel_grille", args=[self.c6a.pk, 2026, 12]))  # un mois sans note
        self.verifier(reverse("pedagogie:mensuel_resultats", args=[self.c6a.pk, 2026, 10]))
        self.verifier(reverse("pedagogie:mensuel_resultats", args=[self.c6a.pk, 2026, 12]))
        self.verifier(reverse("pedagogie:mensuel_annuel", args=[self.c6a.pk]))
        self.verifier(reverse("pedagogie:mensuel_disciplines", args=[self.c6a.pk]))
        self.verifier(reverse("pedagogie:mensuel_eleve", args=[self.e1.matricule]))

    def test_les_pages_de_la_direction_et_des_classes_vides(self):
        self.verifier(reverse("pedagogie:mensuel_classes"), client=self.direction)
        self.verifier(reverse("pedagogie:mensuel_grille", args=[self.c6b.pk, 2026, 10]), client=self.direction)  # sans discipline
        self.verifier(reverse("pedagogie:mensuel_disciplines", args=[self.c6b.pk]), client=self.direction)
        self.verifier(reverse("pedagogie:mensuel_annuel", args=[self.c6b.pk]), client=self.direction)
        self.verifier(reverse("pedagogie:mensuel_resultats", args=[self.c6b.pk, 2026, 10]), client=self.direction)

    def test_le_trimestre_cloture_et_l_annee_archivee(self):
        PeriodeCloturee.objects.create(annee_scolaire=self.annee, trimestre="trimestre_1", cloturee_par=self.fondateur)
        self.verifier(reverse("pedagogie:mensuel_grille", args=[self.c6a.pk, 2026, 10]))
        self.verifier(reverse("pedagogie:mensuel_resultats", args=[self.c6a.pk, 2026, 10]))

    def test_le_responsable_pedagogique_qui_consulte(self):
        self.verifier(reverse("pedagogie:mensuel_grille", args=[self.c6a.pk, 2026, 10]), client=client_en(self.responsable, "ar"))

    def test_la_famille(self):
        self.verifier(reverse("pedagogie:mensuel_eleve", args=[self.e1.matricule]), client=client_en(self.parent, "ar"))
        self.verifier(reverse("pedagogie:mensuel_eleve", args=[self.e1.matricule]), client=client_en(self.e1, "ar"))
        self.verifier(reverse("pedagogie:bulletin_eleve", args=[self.e1.matricule]), client=client_en(self.parent, "ar"))

    def test_les_messages_apres_chaque_action(self):
        grille = reverse("pedagogie:mensuel_grille", args=[self.c6a.pk, 2026, 10])
        disciplines = reverse("pedagogie:mensuel_disciplines", args=[self.c6b.pk])
        enregistrer = {f"n_{self.e1.pk}_{DisciplineMensuelle.objects.get(classe=self.c6a, libelle='Dictée').pk}": "9,5", f"o_{self.e1.pk}": "عمل جيد"}
        parcours = [
            (self.maitre, "post", grille, enregistrer),
            (self.maitre, "post", grille, {f"n_{self.e2.pk}_{DisciplineMensuelle.objects.get(classe=self.c6a, libelle='Dictée').pk}": "12"}),
            (self.maitre, "post", grille, {f"n_{self.e2.pk}_{DisciplineMensuelle.objects.get(classe=self.c6a, libelle='Lecture').pk}": "abc"}),
            (self.maitre, "post", grille, {f"n_{self.e2.pk}_{DisciplineMensuelle.objects.get(classe=self.c6a, libelle='Lecture').pk}": "7,555"}),
            (self.maitre, "post", reverse("pedagogie:mensuel_grille", args=[self.c6a.pk, 2026, 8]), enregistrer),  # un mois hors de l'année
            (self.direction, "post", disciplines, {"action": "habituelles"}),
            (self.direction, "post", disciplines, {"action": "habituelles"}),
            (self.direction, "post", disciplines, {"action": "ajouter", "libelle": "Discipline du jeudi"}),
            (self.direction, "post", disciplines, {"action": "ajouter", "libelle": "discipline du jeudi"}),
            (self.direction, "post", disciplines, {"action": "ajouter", "libelle": ""}),
            (self.direction, "post", disciplines, {"action": "copier", "source": self.c6a.pk}),
            (self.direction, "post", reverse("pedagogie:mensuel_disciplines", args=[self.classe_5a.pk]), {"action": "copier", "source": self.c6a.pk}),
        ]
        for client, methode, adresse, donnees in parcours:
            with self.subTest(adresse=adresse, donnees=donnees):
                reponse = getattr(client, methode)(adresse, donnees, follow=True)
                self.assertEqual(restes(reponse), [])
        ajoutee = DisciplineMensuelle.objects.get(classe=self.c6b, libelle="Discipline du jeudi")
        for donnees in ({"action": "renommer", "discipline": ajoutee.pk, "libelle": "Discipline du jeudi"}, {"action": "renommer", "discipline": ajoutee.pk, "libelle": "Dictée"},
                        {"action": "basculer", "discipline": ajoutee.pk}, {"action": "basculer", "discipline": ajoutee.pk}, {"action": "supprimer", "discipline": ajoutee.pk}):
            with self.subTest(action=donnees["action"]):
                self.assertEqual(restes(self.direction.post(disciplines, donnees, follow=True)), [])
        sans_note = DisciplineMensuelle.objects.get(classe=self.c6a, libelle="Dictée")
        self.assertEqual(restes(self.direction.post(reverse("pedagogie:mensuel_disciplines", args=[self.c6a.pk]), {"action": "supprimer", "discipline": sans_note.pk}, follow=True)), [])

    def test_le_bulletin_pdf(self):
        with CaptureHtmlDuPdf() as capture:
            reponse = self.maitre.get(reverse("pedagogie:mensuel_bulletin_pdf", args=[self.e1.matricule, 2026, 10]))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(restes_hors_textes_saisis(capture.html, SAISIS), [])
        self.assertIn("direction: rtl", capture.html.replace("\n", " ").replace("  ", " "))
        self.assertEqual(len(PdfReader(io.BytesIO(reponse.content)).pages), 1)

    def test_les_bulletins_de_la_classe_pdf(self):
        with CaptureHtmlDuPdf() as capture:
            reponse = self.direction.get(reverse("pedagogie:mensuel_bulletins_classe_pdf", args=[self.c6a.pk, 2026, 10]))
        self.assertEqual(restes_hors_textes_saisis(capture.html, SAISIS), [])
        self.assertEqual(len(PdfReader(io.BytesIO(reponse.content)).pages), 3)
