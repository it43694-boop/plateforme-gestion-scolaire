"""
Rang de l'élève pour CHAQUE trimestre (en plus du rang de l'année) sur le bulletin, à l'écran et dans le PDF.

Même règle que le rang de l'année et que le relevé Excel : élèves actuellement inscrits, moyenne pondérée par les
coefficients, ex æquo au même rang puis saut (1, 1, 3) ; seuls ceux qui ont des notes ce trimestre-là sont classés, mais
l'effectif affiché est celui de la classe.
"""
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from comptes.roles import Role
from pedagogie.models import Trimestre, saisir_note
from pedagogie.tests import creer_contexte_classe, creer_utilisateur_actif
from pedagogie.views import _calculer_bulletin
from scolarite.models import Affectation, Inscription
from scolarite.test_exports_listes import ExportsBase, donnees, feuilles

T1, T2, T3 = Trimestre.T1, Trimestre.T2, Trimestre.T3


class RangDuTrimestreTests(TestCase):
    def setUp(self):
        self.annee, self.classe = creer_contexte_classe()
        self.prof = creer_utilisateur_actif("prof-rang@example.com", Role.ENSEIGNANT)
        self.maths = Affectation.objects.create(enseignant=self.prof, classe=self.classe, matiere="Mathématiques")
        self.directeur = creer_utilisateur_actif("fondateur-rang@example.com", Role.FONDATEUR)
        self.eleves = {}
        for nom in ("alpha", "beta", "gamma"):
            eleve = creer_utilisateur_actif(f"{nom}-rang@example.com", Role.ELEVE, matricule=f"RANG-{nom}")
            Inscription.objects.create(eleve=eleve, classe=self.classe)
            self.eleves[nom] = eleve

    def noter(self, nom, trimestre, note):
        saisir_note(
            eleve=self.eleves[nom], affectation=self.maths, trimestre=trimestre, note_classe=note, enseignant=self.prof,
        )

    def bulletin(self, nom):
        eleve = self.eleves[nom]
        return _calculer_bulletin(eleve, Inscription.objects.get(eleve=eleve))

    def rangs(self, nom):
        """{trimestre: rang} d'après le bulletin."""
        return {b["trimestre"]: b["rang"] for b in self.bulletin(nom)["bulletins_trimestre"]}

    def test_le_rang_change_d_un_trimestre_a_l_autre(self):
        # alpha : 18 puis 8 (moyenne annuelle 13) ; beta : 12 puis 16 (annuelle 14) ; gamma : 8 puis 12 (annuelle 10)
        for nom, premiere, seconde in (("alpha", 18, 8), ("beta", 12, 16), ("gamma", 8, 12)):
            self.noter(nom, T1, premiere)
            self.noter(nom, T2, seconde)
        self.assertEqual(self.rangs("alpha"), {"1er trimestre": 1, "2ème trimestre": 3})
        self.assertEqual(self.rangs("beta"), {"1er trimestre": 2, "2ème trimestre": 1})
        self.assertEqual(self.rangs("gamma"), {"1er trimestre": 3, "2ème trimestre": 2})
        # Le rang de l'année reste calculé sur toutes les notes : beta devant alpha, alors que alpha était premier au 1er.
        self.assertEqual(self.bulletin("beta")["rang"], 1)
        self.assertEqual(self.bulletin("alpha")["rang"], 2)

    def test_ex_aequo_dans_un_trimestre(self):
        self.noter("alpha", T1, 15)
        self.noter("beta", T1, 15)
        self.noter("gamma", T1, 10)
        self.assertEqual([self.rangs(nom)["1er trimestre"] for nom in ("alpha", "beta", "gamma")], [1, 1, 3])

    def test_l_effectif_est_celui_de_la_classe_meme_si_certains_n_ont_pas_de_note(self):
        self.noter("alpha", T1, 14)
        self.noter("beta", T1, 12)  # gamma n'a aucune note
        bulletin = self.bulletin("beta")["bulletins_trimestre"][0]
        self.assertEqual((bulletin["rang"], bulletin["effectif_classe"]), (2, 3))
        self.assertEqual(self.bulletin("gamma")["bulletins_trimestre"], [])  # rien à classer, aucun bloc de trimestre

    def test_un_trimestre_sans_note_pour_l_eleve_n_a_pas_de_bloc(self):
        self.noter("alpha", T1, 14)
        self.noter("beta", T2, 12)
        self.assertEqual(self.rangs("alpha"), {"1er trimestre": 1})
        self.assertEqual(self.rangs("beta"), {"2ème trimestre": 1})

    def test_un_eleve_parti_n_est_plus_classe(self):
        self.noter("alpha", T1, 18)
        self.noter("beta", T1, 12)
        Inscription.objects.filter(eleve=self.eleves["alpha"]).update(statut=Inscription.Statut.ABANDON)
        bulletin = self.bulletin("beta")["bulletins_trimestre"][0]
        self.assertEqual((bulletin["rang"], bulletin["effectif_classe"]), (1, 2))

    def test_sans_inscription_aucun_rang(self):
        self.noter("alpha", T1, 14)
        bulletin = _calculer_bulletin(self.eleves["alpha"], None)["bulletins_trimestre"][0]
        self.assertIsNone(bulletin["rang"])

    def test_la_moyenne_plus_forte_et_plus_faible_restent_justes(self):
        for nom, note in (("alpha", 18), ("beta", 12), ("gamma", 8)):
            self.noter(nom, T1, note)
        bulletin = self.bulletin("beta")["bulletins_trimestre"][0]
        self.assertEqual((bulletin["moyenne_plus_forte"], bulletin["moyenne_plus_faible"]), (18, 8))

    def test_le_rang_s_affiche_a_l_ecran(self):
        for nom, note in (("alpha", 18), ("beta", 12), ("gamma", 8)):
            self.noter(nom, T1, note)
        self.client.force_login(self.directeur)
        page = self.client.get(reverse("pedagogie:bulletin_eleve", args=[self.eleves["beta"].matricule]))
        self.assertContains(page, "Rang du trimestre")
        self.assertContains(page, "2ème sur 3")
        page = self.client.get(reverse("pedagogie:bulletin_eleve", args=[self.eleves["alpha"].matricule]))
        self.assertContains(page, "1er sur 3")

    def test_le_rang_s_affiche_dans_le_pdf(self):
        for nom, note in (("alpha", 18), ("beta", 12), ("gamma", 8)):
            self.noter(nom, T1, note)
        eleve = self.eleves["beta"]
        html = render_to_string("pedagogie/bulletin_pdf.html", {
            "eleve": eleve, "inscription": Inscription.objects.get(eleve=eleve), "verification": None,
            "verification_url": "", "qr_code": "", **_calculer_bulletin(eleve, Inscription.objects.get(eleve=eleve)),
        })
        self.assertIn("Rang du trimestre", html)
        self.assertIn("2ème sur 3", html)
        self.client.force_login(self.directeur)
        reponse = self.client.get(reverse("pedagogie:exporter_bulletin_pdf", args=[eleve.matricule]))
        self.assertEqual((reponse.status_code, reponse["Content-Type"]), (200, "application/pdf"))

    def test_pas_de_ligne_de_rang_sans_notes(self):
        self.client.force_login(self.directeur)
        page = self.client.get(reverse("pedagogie:bulletin_eleve", args=[self.eleves["alpha"].matricule]))
        self.assertNotContains(page, "Rang du trimestre")


class MemeRangQueLeReleveTests(ExportsBase):
    """Le rang d'un trimestre sur le bulletin = la colonne « Rang » de la feuille de ce trimestre du relevé Excel."""

    def test_rang_du_bulletin_egal_au_rang_du_releve(self):
        classeur = feuilles(self.releve(self.fondateur).content)
        for feuille, trimestre in (("1er trimestre", "1er trimestre"), ("2ème trimestre", "2ème trimestre")):
            rang_releve = {ligne[1]: ligne[-1] for ligne in donnees(classeur[feuille], "N°") if ligne and ligne[1]}
            for eleve in (self.e1, self.e2, self.e3):
                inscription = Inscription.objects.get(eleve=eleve, classe=self.c6a)
                blocs = {b["trimestre"]: b for b in _calculer_bulletin(eleve, inscription)["bulletins_trimestre"]}
                if trimestre not in blocs:
                    continue  # e3 n'a aucune note au 2ème trimestre : pas de bloc, pas de rang
                with self.subTest(feuille=feuille, eleve=eleve.matricule):
                    self.assertEqual(blocs[trimestre]["rang"], rang_releve[eleve.matricule])
        # valeurs attendues du jeu de données : 1er trimestre e1 = 1, e2 = 3, e3 = 1 (ex æquo) ; 2ème : e1 = 1, e2 = 2
        premier = {b["trimestre"]: b["rang"] for b in _calculer_bulletin(
            self.e2, Inscription.objects.get(eleve=self.e2, classe=self.c6a))["bulletins_trimestre"]}
        self.assertEqual(premier, {"1er trimestre": 3, "2ème trimestre": 2})
