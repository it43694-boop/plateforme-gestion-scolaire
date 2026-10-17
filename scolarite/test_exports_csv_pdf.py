"""Liste des élèves d'une classe en CSV et en PDF : mêmes droits que l'Excel, noms protégés, arabe pur."""
import csv
import io

from django.urls import reverse

from comptes.arabisation import invalider
from comptes.models import JournalAudit, Utilisateur
from comptes.outils_test_arabe import CaptureHtmlDuPdf, client_en
from comptes.roles import Role
from scolarite.models import Affectation
from statistiques.test_education import EducationBase, creer_compte


def lignes_csv(reponse):
    texte = reponse.content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(texte), delimiter=";"))


class ListeDeClasseCsvPdfTests(EducationBase):
    def setUp(self):
        self.fondateur = creer_compte(Role.FONDATEUR, "fondateur@liste-csv.test", self.ecole)
        self.parent = creer_compte(Role.PARENT, "parent@liste-csv.test", self.ecole, telephone="70130001")
        self.url_csv = reverse("scolarite:exporter_liste_classe_csv", args=[self.c6a.pk])
        self.url_pdf = reverse("scolarite:exporter_liste_classe_pdf", args=[self.c6a.pk])

    def test_le_csv_contient_les_eleves_de_la_classe(self):
        self.client.force_login(self.fondateur)
        reponse = self.client.get(self.url_csv)
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(reponse["Content-Type"].startswith("text/csv"))
        self.assertIn(".csv", reponse["Content-Disposition"])
        self.assertTrue(reponse.content.startswith("﻿".encode("utf-8")))  # BOM pour Excel
        lignes = lignes_csv(reponse)
        self.assertEqual(lignes[0], ["N°", "Matricule", "Nom", "Prénom", "Sexe", "Date de naissance", "Statut"])
        matricules = {ligne[1] for ligne in lignes[1:]}
        self.assertEqual(matricules, {self.e1.matricule, self.e2.matricule, self.e3.matricule})

    def test_un_nom_qui_ressemble_a_une_formule_est_neutralise(self):
        Utilisateur.objects.filter(pk=self.e1.pk).update(nom="=CMD()")
        self.client.force_login(self.fondateur)
        reponse = self.client.get(self.url_csv)
        self.assertIn("'=CMD()", [ligne[2] for ligne in lignes_csv(reponse)])

    def test_l_enseignant_affecte_n_a_pas_la_date_de_naissance(self):
        affectation = Affectation.objects.get(classe=self.c6a)
        self.client.force_login(affectation.enseignant)
        lignes = lignes_csv(self.client.get(self.url_csv))
        self.assertNotIn("Date de naissance", lignes[0])

    def test_un_parent_n_exporte_rien(self):
        self.client.force_login(self.parent)
        self.assertEqual(self.client.get(self.url_csv).status_code, 403)
        self.assertEqual(self.client.get(self.url_pdf).status_code, 403)

    def test_la_classe_d_une_autre_ecole_est_introuvable(self):
        self.client.force_login(self.fondateur)
        for nom in ("exporter_liste_classe_csv", "exporter_liste_classe_pdf"):
            self.assertEqual(self.client.get(reverse(f"scolarite:{nom}", args=[self.classe_b.pk])).status_code, 404)

    def test_l_export_est_journalise(self):
        self.client.force_login(self.fondateur)
        self.client.get(self.url_csv)
        self.client.get(self.url_pdf)
        formats = [j.details.get("format") for j in JournalAudit.objects.filter(action="export_liste_classe")]
        self.assertEqual(sorted(formats), ["csv", "pdf"])

    def test_le_pdf_francais(self):
        self.client.force_login(self.fondateur)
        reponse = self.client.get(self.url_pdf)
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(reponse.content.startswith(b"%PDF"))
        self.assertNotIn(b"Amiri", reponse.content)

    def test_le_pdf_et_le_csv_en_arabe_sont_en_arabe_pur(self):
        Utilisateur.objects.filter(pk=self.e1.pk).update(prenom="Salem", nom="Keita", prenom_ar="سالم", nom_ar="كيتا")
        invalider(self.ecole.pk)
        client = client_en(self.fondateur, "ar")
        with CaptureHtmlDuPdf() as capture:
            reponse = client.get(self.url_pdf)
        self.assertEqual(reponse.status_code, 200)
        self.assertIn(b"Amiri", reponse.content)
        self.assertEqual(capture.restes_latins(), [])
        self.assertIn("سالم", capture.html)
        lignes = lignes_csv(client.get(self.url_csv))
        self.assertEqual(lignes[0][2], "الاسم")
        self.assertIn("كيتا", [ligne[2] for ligne in lignes])
