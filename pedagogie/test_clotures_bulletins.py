"""
Clôture des notes par trimestre (fondateur, administrateur général, développeur) et bulletins d'une classe entière en un seul PDF.

Un trimestre clôturé ne reçoit plus aucune note de matière ni de conduite, jusqu'à sa réouverture ; une année archivée est toujours clôturée.
"""
import io
import re

from django.core.exceptions import ValidationError
from django.urls import reverse
from pypdf import PdfReader

from comptes.arabisation import invalider
from comptes.models import JournalAudit, Utilisateur
from comptes.outils_test_arabe import CaptureHtmlDuPdf, client_en
from comptes.roles import Role
from comptes.traduction import restes_latins
from pedagogie.clotures import cloturer, periode_cloturee, rouvrir, trimestres_clotures, verifier_periode_ouverte
from pedagogie.conduite import enregistrer_conduite
from pedagogie.models import Note, PeriodeCloturee, Trimestre, VerificationBulletin, saisir_note
from pedagogie.views import reunir_les_bulletins
from scolarite.models import Affectation, AnneeScolaire, Classe, Cycle
from statistiques.test_education import EducationBase, creer_compte

T1, T2, T3 = Trimestre.T1.value, Trimestre.T2.value, Trimestre.T3.value


class ClotureBase(EducationBase):
    def setUp(self):
        self.admin = creer_compte(Role.ADMINISTRATEUR_GENERAL, "admin@clotures.test", self.ecole)
        self.developpeur = creer_compte(Role.DEVELOPPEUR, "dev@clotures.test", self.ecole)
        self.affectation = Affectation.objects.get(classe=self.c6a)
        self.url = reverse("pedagogie:clotures_notes")

    def noter(self, trimestre=T1, valeur=12, eleve=None):
        return saisir_note(
            eleve=eleve or self.e1, affectation=self.affectation, trimestre=trimestre, note_classe=valeur, enseignant=self.fondateur,
        )

    def url_de(self, nom, trimestre, annee=None):
        return reverse(f"pedagogie:{nom}", args=[(annee or self.annee).pk, trimestre])


class RegleDeClotureTests(ClotureBase):
    def test_un_trimestre_ouvert_accepte_les_notes(self):
        self.assertFalse(periode_cloturee(self.c6a, T1))
        self.assertEqual(self.noter(T1, 14).valeur, 14)

    def test_un_trimestre_cloture_refuse_toute_note_et_toute_correction(self):
        note = self.noter(T1, 12)
        self.assertTrue(cloturer(self.annee, T1, self.fondateur))
        self.assertTrue(periode_cloturee(self.c6a, T1))
        with self.assertRaisesMessage(ValidationError, "clôturées"):
            self.noter(T1, 18)  # correction d'une note existante
        with self.assertRaises(ValidationError):
            self.noter(T1, 10, eleve=self.e2)  # nouvelle note
        note.refresh_from_db()
        self.assertEqual(note.valeur, 12)

    def test_les_autres_trimestres_restent_ouverts(self):
        cloturer(self.annee, T1, self.fondateur)
        self.assertEqual(self.noter(T2, 15).valeur, 15)
        self.assertEqual(trimestres_clotures(self.annee), {T1})

    def test_rouvrir_permet_de_corriger_a_nouveau(self):
        cloturer(self.annee, T1, self.fondateur)
        self.assertTrue(rouvrir(self.annee, T1))
        self.assertEqual(self.noter(T1, 16).valeur, 16)
        self.assertFalse(rouvrir(self.annee, T1))  # déjà ouvert : rien à faire

    def test_cloturer_deux_fois_ne_cree_pas_de_doublon(self):
        self.assertTrue(cloturer(self.annee, T1, self.fondateur))
        self.assertFalse(cloturer(self.annee, T1, self.admin))
        self.assertEqual(PeriodeCloturee.objects.count(), 1)

    def test_la_cloture_d_une_ecole_ne_touche_pas_l_autre(self):
        cloturer(self.annee_b, T1, self.fondateur_b)
        self.assertFalse(periode_cloturee(self.c6a, T1))
        self.assertTrue(periode_cloturee(self.classe_b, T1))

    def test_une_annee_archivee_est_toujours_cloturee(self):
        AnneeScolaire.objects.filter(pk=self.annee.pk).update(est_archivee=True)
        self.annee.refresh_from_db()
        self.assertEqual(trimestres_clotures(self.annee), {T1, T2, T3})
        for trimestre in (T1, T2, T3):
            self.assertTrue(periode_cloturee(self.c6a, trimestre))
            with self.assertRaisesMessage(ValidationError, "archivée"):
                verifier_periode_ouverte(self.c6a, trimestre)
        with self.assertRaisesMessage(ValidationError, "archivée"):
            self.noter(T1)
        with self.assertRaises(ValidationError):
            rouvrir(self.annee, T1)  # une année archivée ne se rouvre pas

    def test_la_conduite_suit_la_meme_regle(self):
        classe = Classe.objects.create(nom="9B", cycle=Cycle.DEUXIEME_CYCLE, niveau="annee_9", annee_scolaire=self.annee)
        cloturer(self.annee, T1, self.fondateur)
        with self.assertRaisesMessage(ValidationError, "clôturées"):
            enregistrer_conduite(classe=classe, trimestre=T1, valeurs={}, par=self.fondateur)
        enregistrer_conduite(classe=classe, trimestre=T2, valeurs={}, par=self.fondateur)  # un autre trimestre : permis

    def test_aucune_note_n_est_supprimee_par_la_cloture(self):
        self.noter(T1, 12)
        cloturer(self.annee, T1, self.fondateur)
        self.assertEqual(Note.objects.count(), 1)


class SaisieParLesEnseignantsTests(ClotureBase):
    def donnees(self, trimestre=T1):
        return {"matricule_eleve": self.e1.matricule, "trimestre": trimestre, "note_classe": "13", "note_composition": ""}

    def test_l_enseignant_voit_un_message_clair_et_la_note_ne_change_pas(self):
        self.noter(T1, 12)
        cloturer(self.annee, T1, self.fondateur)
        self.client.force_login(self.t1)
        reponse = self.client.post(reverse("pedagogie:saisir_note", args=[self.affectation.pk]), self.donnees(), follow=True)
        self.assertContains(reponse, "clôturées")
        self.assertEqual(Note.objects.get(eleve=self.e1, trimestre=T1).valeur, 12)

    def test_la_saisie_hors_ligne_recoit_une_erreur_json(self):
        cloturer(self.annee, T1, self.fondateur)
        self.client.force_login(self.t1)
        reponse = self.client.post(
            reverse("pedagogie:saisir_note", args=[self.affectation.pk]), self.donnees(), headers={"X-Requested-With": "XMLHttpRequest"},
        )
        donnees = reponse.json()
        self.assertFalse(donnees["ok"])
        self.assertIn("clôturées", donnees["erreurs"]["matricule_eleve"][0])

    def test_un_autre_trimestre_reste_saisissable(self):
        cloturer(self.annee, T1, self.fondateur)
        self.client.force_login(self.t1)
        reponse = self.client.post(reverse("pedagogie:saisir_note", args=[self.affectation.pk]), self.donnees(T2))
        self.assertEqual(reponse.status_code, 302)
        self.assertTrue(Note.objects.filter(eleve=self.e1, trimestre=T2).exists())


class PageDeClotureTests(ClotureBase):
    def test_la_direction_cloture_et_rouvre(self):
        for compte in (self.fondateur, self.admin, self.developpeur):
            PeriodeCloturee.objects.all().delete()
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                reponse = self.client.post(self.url_de("cloturer_periode", T1))
                self.assertRedirects(reponse, f"{self.url}?annee={self.annee.pk}")
                cloture = PeriodeCloturee.objects.get()
                self.assertEqual((cloture.trimestre, cloture.cloturee_par), (T1, compte))
                self.client.post(self.url_de("rouvrir_periode", T1))
                self.assertFalse(PeriodeCloturee.objects.exists())

    def test_la_page_montre_l_etat_de_chaque_trimestre(self):
        cloturer(self.annee, T2, self.fondateur)
        self.client.force_login(self.fondateur)
        lignes = {ligne["valeur"]: ligne for ligne in self.client.get(self.url).context["lignes"]}
        self.assertEqual({t: lignes[t]["cloturee"] for t in (T1, T2, T3)}, {T1: False, T2: True, T3: False})
        self.assertEqual(lignes[T2]["par"], self.fondateur)

    def test_les_autres_roles_n_y_ont_pas_acces(self):
        for compte in (self.secretaire, self.dir_1er, self.comptable, self.t1, self.parent, self.e1, self.censeur):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertEqual(self.client.get(self.url).status_code, 403)
                self.assertEqual(self.client.post(self.url_de("cloturer_periode", T1)).status_code, 403)
                self.assertEqual(self.client.post(self.url_de("rouvrir_periode", T1)).status_code, 403)
        self.assertFalse(PeriodeCloturee.objects.exists())

    def test_une_autre_ecole_ne_peut_pas_cloturer_ma_periode(self):
        self.client.force_login(self.fondateur_b)
        self.assertEqual(self.client.post(self.url_de("cloturer_periode", T1)).status_code, 404)
        self.assertFalse(PeriodeCloturee.objects.exists())

    def test_trimestre_inconnu_et_methode_get(self):
        self.client.force_login(self.fondateur)
        self.assertEqual(self.client.post(self.url_de("cloturer_periode", "trimestre_9")).status_code, 404)
        self.assertEqual(self.client.get(self.url_de("cloturer_periode", T1)).status_code, 405)

    def test_une_annee_archivee_s_affiche_clôturee_et_ne_se_rouvre_pas(self):
        AnneeScolaire.objects.filter(pk=self.annee.pk).update(est_archivee=True)
        self.client.force_login(self.fondateur)
        page = self.client.get(self.url).context
        self.assertTrue(all(ligne["cloturee"] for ligne in page["lignes"]))
        reponse = self.client.post(self.url_de("rouvrir_periode", T1), follow=True)
        self.assertContains(reponse, "archivée")

    def test_la_cloture_est_journalisee(self):
        self.client.force_login(self.fondateur)
        self.client.post(self.url_de("cloturer_periode", T1))
        self.client.post(self.url_de("rouvrir_periode", T1))
        actions = list(JournalAudit.objects.values_list("action", flat=True))
        self.assertIn("cloture_notes", actions)
        self.assertIn("reouverture_notes", actions)

    def test_le_menu_propose_la_cloture_a_la_direction_seulement(self):
        for compte, attendu in ((self.fondateur, True), (self.t1, False), (self.secretaire, False)):
            self.client.force_login(compte)
            page = self.client.get(reverse("comptes:redirection_tableau_de_bord"), follow=True).content.decode()
            with self.subTest(compte=compte.email):
                self.assertEqual(self.url in page, attendu)

    def test_la_page_est_en_arabe_pur(self):
        cloturer(self.annee, T1, self.fondateur)
        invalider(self.ecole.pk)
        reponse = client_en(self.fondateur, "ar").get(self.url)
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual([t for t in restes_latins(reponse.content.decode()) if t != "Français"], [])


class BulletinsDeClasseTests(ClotureBase):
    def setUp(self):
        super().setUp()
        for eleve, note in ((self.e1, 14), (self.e2, 9), (self.e3, 17)):
            self.noter(T1, note, eleve)
        self.url_pdf = reverse("pedagogie:exporter_bulletins_classe_pdf", args=[self.c6a.pk])

    def test_un_seul_pdf_avec_un_bulletin_par_eleve(self):
        self.client.force_login(self.fondateur)
        with CaptureHtmlDuPdf() as capture:
            reponse = self.client.get(self.url_pdf)
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse["Content-Type"], "application/pdf")
        self.assertIn("bulletins_6A_2026-2027.pdf", reponse["Content-Disposition"])
        pages = PdfReader(io.BytesIO(reponse.content)).pages
        self.assertEqual(len(pages), 3)  # trois élèves, une page chacun
        texte = "\n".join(page.extract_text() for page in pages)
        for eleve in (self.e1, self.e2, self.e3):
            self.assertIn(eleve.nom_complet, texte)
        self.assertEqual(len(capture.pages), 1)  # un seul document HTML, une seule fabrication de PDF

    def test_chaque_bulletin_porte_son_propre_jeton_de_verification(self):
        self.client.force_login(self.fondateur)
        self.client.get(self.url_pdf)
        self.assertEqual(VerificationBulletin.objects.count(), 3)
        jetons = set(VerificationBulletin.objects.values_list("jeton", flat=True))
        self.client.get(self.url_pdf)
        self.assertEqual(set(VerificationBulletin.objects.values_list("jeton", flat=True)), jetons)  # la même feuille garde ses jetons

    def test_les_resultats_sont_ceux_du_bulletin_individuel(self):
        self.client.force_login(self.fondateur)
        classe = PdfReader(io.BytesIO(self.client.get(self.url_pdf).content))
        individuel = PdfReader(io.BytesIO(self.client.get(reverse("pedagogie:exporter_bulletin_pdf", args=[self.e3.matricule])).content))
        texte_classe = "\n".join(page.extract_text() for page in classe.pages)
        chiffres = re.findall(r"\d+[.,]\d{2}", individuel.pages[0].extract_text())
        self.assertTrue(chiffres)
        for chiffre in chiffres[:6]:
            self.assertIn(chiffre, texte_classe)

    def test_seule_la_supervision_imprime_les_bulletins_d_une_classe(self):
        for compte, code in (
            (self.fondateur, 200), (self.dir_1er, 200), (self.t1, 403), (self.parent, 403), (self.e1, 403), (self.comptable, 403),
        ):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertEqual(self.client.get(self.url_pdf).status_code, code)

    def test_un_directeur_de_cycle_ne_traite_que_son_cycle_et_une_autre_ecole_ne_voit_rien(self):
        self.client.force_login(self.dir_1er)
        self.assertEqual(self.client.get(reverse("pedagogie:exporter_bulletins_classe_pdf", args=[self.c9a.pk])).status_code, 404)
        self.client.force_login(self.fondateur_b)
        self.assertEqual(self.client.get(self.url_pdf).status_code, 404)

    def test_une_classe_vide_renvoie_a_la_liste(self):
        vide = Classe.objects.create(nom="6C", cycle=Cycle.PREMIER_CYCLE, niveau="annee_6", annee_scolaire=self.annee)
        self.client.force_login(self.fondateur)
        reponse = self.client.get(reverse("pedagogie:exporter_bulletins_classe_pdf", args=[vide.pk]), follow=True)
        self.assertContains(reponse, "aucun bulletin à imprimer")

    def test_une_classe_trop_nombreuse_est_refusee_avec_un_message(self):
        from unittest import mock

        self.client.force_login(self.fondateur)
        with mock.patch("pedagogie.views.LIMITE_BULLETINS_PAR_PDF", 2):
            reponse = self.client.get(self.url_pdf, follow=True)
        self.assertContains(reponse, "plus de 2 élèves")

    def test_le_bouton_est_dans_la_liste_des_classes(self):
        self.client.force_login(self.fondateur)
        self.assertIn(self.url_pdf, self.client.get(reverse("scolarite:liste_classes")).content.decode())

    def test_l_impression_est_journalisee(self):
        self.client.force_login(self.fondateur)
        self.client.get(self.url_pdf)
        self.assertEqual(JournalAudit.objects.get(action="export_bulletins_classe").details["bulletins"], 3)

    def test_reunir_les_bulletins_garde_l_entete_du_premier_et_separe_les_pages(self):
        pages = [f"<html><head><style>p {{ color: red; }}</style></head><body><p>Bulletin {i}</p></body></html>" for i in range(3)]
        html = reunir_les_bulletins(pages)
        self.assertEqual(html.count("<style>"), 1)
        self.assertEqual(html.count("<pdf:nextpage />"), 2)
        self.assertEqual(html.count("<body>"), 1)
        for i in range(3):
            self.assertIn(f"Bulletin {i}", html)

    def test_en_arabe_les_bulletins_sont_en_arabe_avec_la_police_arabe(self):
        Utilisateur.objects.filter(pk=self.e1.pk).update(prenom="Aminata", nom="Traoré", prenom_ar="أميناتا", nom_ar="تراوري")
        invalider(self.ecole.pk)
        with CaptureHtmlDuPdf() as capture:
            reponse = client_en(self.fondateur, "ar").get(self.url_pdf)
        self.assertEqual(reponse.status_code, 200)
        self.assertIn(b"Amiri", reponse.content)
        self.assertIn("أميناتا", capture.html)
        self.assertEqual(len(PdfReader(io.BytesIO(reponse.content)).pages), 3)
