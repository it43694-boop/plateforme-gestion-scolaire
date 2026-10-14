"""
Note de conduite : de la 7ème à la 12ème année seulement, une note sur 20 par trimestre, hors des matières, comptée dans la
moyenne avec le coefficient de l'école (1 par défaut ; 0 = affichée sans compter).

Jeu de données de EducationBase (statistiques.test_education) : école A, classes 6A et 6B (6ème année, 1er cycle), 9A (9ème
année, 2ème cycle : e5, e6), TSE (12ème année, lycée : e7, e8), CAP-E (professionnel, sans niveau) ; t2 enseigne en 6B et 9A,
t3 en TSE ; école B vide.
"""
import types
from decimal import Decimal

from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.urls import reverse

from assistant.alertes import _eleves_a_risque_academique
from comptes.models import JournalAudit, Utilisateur
from comptes.roles import Role
from espace_developpeur.forms import ParametresEtablissementForm
from espace_developpeur.retrait_eleve import historique_eleve
from pedagogie.conduite import (
    ROLES_SAISIE_CONDUITE, analyser_note, conduite_des_eleves, coefficient_conduite, enregistrer_conduite, moyenne_ponderee,
)
from pedagogie.models import NIVEAUX_AVEC_CONDUITE, NoteConduite, Trimestre, appreciation_pour, classe_note_la_conduite, saisir_note
from pedagogie.views import _calculer_bulletin, _calculer_classement
from scolarite.models import Affectation, AnneeScolaire, Classe, Inscription
from scolarite.test_exports_listes import donnees, feuilles, texte_du_classeur
from statistiques.test_education import EducationBase, creer_compte

T1, T2 = Trimestre.T1.value, Trimestre.T2.value


def url(classe, trimestre=None):
    adresse = reverse("pedagogie:saisir_conduite", args=[classe.pk])
    return f"{adresse}?trimestre={trimestre}" if trimestre else adresse


class EligibiliteTests(SimpleTestCase):
    def test_de_la_7eme_a_la_12eme_annee_seulement(self):
        for numero in range(1, 13):
            with self.subTest(niveau=f"annee_{numero}"):
                self.assertEqual(classe_note_la_conduite(types.SimpleNamespace(niveau=f"annee_{numero}")), numero >= 7)
        for autre in ("presco_ps", "presco_ms", "presco_gs", "", None):
            with self.subTest(niveau=autre):
                self.assertFalse(classe_note_la_conduite(types.SimpleNamespace(niveau=autre)))
        self.assertEqual(NIVEAUX_AVEC_CONDUITE, {f"annee_{n}" for n in range(7, 13)})

    def test_les_roles_qui_saisissent(self):
        for role in (Role.FONDATEUR, Role.ADMINISTRATEUR_GENERAL, Role.DEVELOPPEUR, Role.DIRECTEUR_2EME_CYCLE,
                     Role.DIRECTEUR_LYCEE, Role.CENSEUR, Role.SURVEILLANT_GENERAL, Role.SUPER_ADMINISTRATEUR):
            self.assertIn(role.value, ROLES_SAISIE_CONDUITE, role)
        for role in (Role.DIRECTEUR_1ER_CYCLE, Role.ENSEIGNANT, Role.PARENT, Role.ELEVE, Role.SECRETAIRE, Role.COMPTABLE,
                     Role.RESPONSABLE_PEDAGOGIQUE, Role.BIBLIOTHECAIRE, Role.PERSONNEL):
            self.assertNotIn(role.value, ROLES_SAISIE_CONDUITE, role)


class AnalyseDeLaSaisieTests(SimpleTestCase):
    def test_notes_valides(self):
        attendu = {"14": "14.00", "14,5": "14.50", "14.5": "14.50", " 20 ": "20.00", "0": "0.00", "7,25": "7.25"}
        for texte, valeur in attendu.items():
            with self.subTest(texte=texte):
                self.assertEqual(analyser_note(texte), Decimal(valeur))

    def test_case_vide(self):
        for texte in ("", "   ", None):
            self.assertIsNone(analyser_note(texte))

    def test_notes_refusees_avec_un_message_clair(self):
        for texte in ("21", "20,01", "-1", "abc", "1e3", "NaN", "Infinity", "14,555", "1 2"):
            with self.subTest(texte=texte):
                with self.assertRaises(ValueError) as erreur:
                    analyser_note(texte)
                self.assertTrue(str(erreur.exception))


class ConduiteBase(EducationBase):
    def setUp(self):
        self.dir_2e = creer_compte(Role.DIRECTEUR_2EME_CYCLE, "dir2e@conduite.test", self.ecole)
        self.dir_lycee = creer_compte(Role.DIRECTEUR_LYCEE, "dirlycee@conduite.test", self.ecole)
        self.sg = creer_compte(Role.SURVEILLANT_GENERAL, "sg@conduite.test", self.ecole)
        self.super_admin = creer_compte(Role.SUPER_ADMINISTRATEUR, "superadmin@conduite.test", self.ecole)
        self.affectation_9a = Affectation.objects.get(enseignant=self.t2, classe=self.c9a)

    def matiere(self, eleve, note, trimestre=T1, affectation=None):
        saisir_note(
            eleve=eleve, affectation=affectation or self.affectation_9a, trimestre=trimestre, note_classe=note,
            enseignant=self.t2,
        )

    def conduite(self, eleve, valeur, trimestre=T1, classe=None):
        enregistrer_conduite(classe=classe or self.c9a, trimestre=trimestre, valeurs={eleve.pk: Decimal(valeur)}, par=self.fondateur)

    def bulletin(self, eleve):
        return _calculer_bulletin(eleve, Inscription.objects.get(eleve=eleve, classe=self.c9a))

    def coefficient(self, valeur):
        self.ecole.coefficient_conduite = valeur
        self.ecole.save(update_fields=["coefficient_conduite"])


class AccesTests(ConduiteBase):
    def code(self, compte, classe, trimestre=None):
        self.client.force_login(compte)
        return self.client.get(url(classe, trimestre)).status_code

    def test_qui_peut_ouvrir_quelle_classe(self):
        attendu = {
            "fondateur": (self.fondateur, {self.c9a: 200, self.ctse: 200}),
            "super_admin": (self.super_admin, {self.c9a: 200, self.ctse: 200}),
            "directeur du 2ème cycle": (self.dir_2e, {self.c9a: 200, self.ctse: 404}),
            "directeur du lycée": (self.dir_lycee, {self.c9a: 404, self.ctse: 200}),
            "censeur (lycée)": (self.censeur, {self.c9a: 404, self.ctse: 200}),
            "surveillant général (lycée)": (self.sg, {self.c9a: 404, self.ctse: 200}),
        }
        for libelle, (compte, classes) in attendu.items():
            for classe, code in classes.items():
                with self.subTest(role=libelle, classe=classe.nom):
                    self.assertEqual(self.code(compte, classe), code)

    def test_les_autres_roles_sont_refuses(self):
        for compte in (self.t2, self.parent, self.e5, self.secretaire, self.comptable, self.dir_1er):
            with self.subTest(role=compte.role):
                self.assertEqual(self.code(compte, self.c9a), 403)
                self.client.force_login(compte)
                self.assertEqual(self.client.post(url(self.c9a), {"trimestre": T1, f"note-{self.e5.pk}": "15"}).status_code, 403)
        self.assertFalse(NoteConduite.objects.exists())

    def test_pas_en_primaire_ni_sans_niveau_ni_en_professionnel(self):
        self.client.force_login(self.fondateur)
        for classe in (self.c6a, self.c6b, self.ccap):
            with self.subTest(classe=classe.nom):
                reponse = self.client.get(url(classe))
                self.assertRedirects(reponse, reverse("scolarite:liste_classes"), fetch_redirect_response=False)
                self.assertEqual(self.client.post(url(classe), {"trimestre": T1}).status_code, 302)
        reponse = self.client.get(url(self.c6a), follow=True)
        self.assertContains(reponse, "de la 7ème à la 12ème année")

    def test_une_classe_dont_le_niveau_n_est_pas_defini_ne_note_pas_la_conduite(self):
        Classe.objects.filter(pk=self.c9a.pk).update(niveau="")
        self.client.force_login(self.fondateur)
        self.assertEqual(self.client.get(url(self.c9a)).status_code, 302)

    def test_une_classe_d_une_autre_ecole_est_introuvable(self):
        self.client.force_login(self.fondateur_b)
        self.assertEqual(self.client.get(url(self.c9a)).status_code, 404)
        self.assertEqual(self.client.post(url(self.c9a), {"trimestre": T1, f"note-{self.e5.pk}": "15"}).status_code, 404)
        self.assertFalse(NoteConduite.objects.exists())

    def test_visiteur_anonyme_redirige(self):
        self.client.logout()
        self.assertEqual(self.client.get(url(self.c9a)).status_code, 302)

    def test_le_lien_de_la_liste_des_classes(self):
        self.client.force_login(self.fondateur)
        page = self.client.get(reverse("scolarite:liste_classes"))
        for classe in (self.c9a, self.ctse):
            self.assertContains(page, reverse("pedagogie:saisir_conduite", args=[classe.pk]))
        for classe in (self.c6a, self.c6b, self.ccap):
            self.assertNotContains(page, reverse("pedagogie:saisir_conduite", args=[classe.pk]))
        self.client.force_login(self.secretaire)  # voit les classes, mais ne saisit pas la conduite
        self.assertNotContains(self.client.get(reverse("scolarite:liste_classes")), "saisir_conduite")
        self.assertNotContains(self.client.get(reverse("scolarite:liste_classes")), "/pedagogie/conduite/")


class SaisieTests(ConduiteBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.fondateur)

    def poster(self, valeurs, trimestre=T1, classe=None):
        donnees_post = {"trimestre": trimestre}
        donnees_post.update({f"note-{eleve.pk}": texte for eleve, texte in valeurs.items()})
        return self.client.post(url(classe or self.c9a), donnees_post)

    def test_la_page_liste_les_eleves_de_la_classe_seulement(self):
        page = self.client.get(url(self.c9a))
        self.assertEqual(page.status_code, 200)
        for eleve in (self.e5, self.e6):
            self.assertContains(page, f'name="note-{eleve.pk}"')
        for autre in (self.e1, self.e7, self.e9):
            self.assertNotContains(page, f'name="note-{autre.pk}"')
        self.assertContains(page, "note sur 20")
        self.assertContains(page, "coefficient 1")

    def test_enregistrement_d_un_trimestre(self):
        reponse = self.poster({self.e5: "14,5", self.e6: "9"})
        self.assertRedirects(reponse, url(self.c9a, T1), fetch_redirect_response=False)
        self.assertEqual(
            {n.eleve_id: n.valeur for n in NoteConduite.objects.filter(classe=self.c9a, trimestre=T1)},
            {self.e5.pk: Decimal("14.50"), self.e6.pk: Decimal("9.00")},
        )
        page = self.client.get(url(self.c9a, T1))
        self.assertContains(page, 'value="14,5"')
        self.assertContains(page, "2 notes sur 2")

    def test_un_trimestre_ne_touche_pas_les_autres(self):
        self.poster({self.e5: "14"}, T1)
        self.poster({self.e5: "8"}, T2)
        self.assertEqual(NoteConduite.objects.get(eleve=self.e5, trimestre=T1).valeur, Decimal("14.00"))
        self.assertEqual(NoteConduite.objects.get(eleve=self.e5, trimestre=T2).valeur, Decimal("8.00"))

    def test_corriger_et_effacer(self):
        self.poster({self.e5: "14", self.e6: "9"})
        self.poster({self.e5: "16", self.e6: ""})
        self.assertEqual(NoteConduite.objects.get(eleve=self.e5).valeur, Decimal("16.00"))
        self.assertFalse(NoteConduite.objects.filter(eleve=self.e6).exists())

    def test_une_case_vide_sans_note_ne_cree_rien(self):
        self.poster({self.e5: "", self.e6: ""})
        self.assertFalse(NoteConduite.objects.exists())

    def test_une_erreur_n_enregistre_rien_du_tout(self):
        reponse = self.poster({self.e5: "15", self.e6: "21"})
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "entre 0 et 20")
        self.assertContains(reponse, 'value="15"')  # ce qui a été tapé est conservé
        self.assertFalse(NoteConduite.objects.exists())

    def test_saisies_invalides(self):
        for texte in ("abc", "-3", "14,555", "NaN"):
            with self.subTest(texte=texte):
                self.assertEqual(self.poster({self.e5: texte}).status_code, 200)
                self.assertFalse(NoteConduite.objects.exists())

    def test_un_eleve_d_une_autre_classe_est_ignore(self):
        donnees_post = {"trimestre": T1, f"note-{self.e5.pk}": "12", f"note-{self.e1.pk}": "19", f"note-{self.e7.pk}": "19"}
        self.client.post(url(self.c9a), donnees_post)
        self.assertEqual(list(NoteConduite.objects.values_list("eleve_id", flat=True)), [self.e5.pk])

    def test_un_eleve_sorti_de_la_classe_n_est_plus_propose(self):
        Inscription.objects.filter(eleve=self.e6, classe=self.c9a).update(statut=Inscription.Statut.ABANDON)
        self.assertNotContains(self.client.get(url(self.c9a)), f'name="note-{self.e6.pk}"')
        self.poster({self.e6: "12"})
        self.assertFalse(NoteConduite.objects.exists())

    def test_trimestre_inconnu_revient_au_premier(self):
        self.client.post(url(self.c9a), {"trimestre": "trimestre_9", f"note-{self.e5.pk}": "12"})
        self.assertEqual(NoteConduite.objects.get().trimestre, T1)

    def test_annee_archivee_en_lecture_seule(self):
        self.poster({self.e5: "12"})
        AnneeScolaire.objects.filter(pk=self.c9a.annee_scolaire_id).update(est_archivee=True)
        page = self.client.get(url(self.c9a))
        self.assertContains(page, "archivée")
        self.assertContains(page, "disabled")
        self.assertEqual(self.poster({self.e5: "19"}).status_code, 403)
        self.assertEqual(NoteConduite.objects.get().valeur, Decimal("12.00"))

    def test_le_journal_note_des_compteurs_sans_nom(self):
        self.poster({self.e5: "14", self.e6: "9"})
        self.poster({self.e5: "15", self.e6: ""})
        premiere, seconde = JournalAudit.objects.filter(action="saisie_conduite").order_by("pk")
        self.assertEqual(premiere.details, {"trimestre": T1, "enregistrees": 2, "effacees": 0})
        self.assertEqual(seconde.details, {"trimestre": T1, "enregistrees": 1, "effacees": 1})
        self.assertEqual(premiere.acteur, self.fondateur)
        for entree in (premiere, seconde):
            self.assertNotIn(self.e5.nom, f"{entree.cible} {entree.details}")

    def test_la_vie_scolaire_saisit_dans_son_cycle(self):
        for compte, classe, eleve in ((self.dir_2e, self.c9a, self.e5), (self.dir_lycee, self.ctse, self.e7),
                                       (self.censeur, self.ctse, self.e8), (self.sg, self.ctse, self.e7)):
            with self.subTest(role=compte.role):
                self.client.force_login(compte)
                reponse = self.client.post(url(classe), {"trimestre": T1, f"note-{eleve.pk}": "13"})
                self.assertEqual(reponse.status_code, 302)
                self.assertEqual(NoteConduite.objects.get(eleve=eleve).enregistre_par, compte)

    def test_le_modele_refuse_ce_que_la_saisie_refuse(self):
        from django.core.exceptions import ValidationError

        for eleve, classe in ((self.e1, self.c6a), (self.e1, self.c9a), (self.t2, self.c9a)):
            with self.subTest(eleve=eleve.email, classe=classe.nom):
                with self.assertRaises(ValidationError):
                    NoteConduite(eleve=eleve, classe=classe, trimestre=T1, valeur=Decimal("12")).save()
        with self.assertRaises(ValidationError):
            NoteConduite(eleve=self.e5, classe=self.c9a, trimestre=T1, valeur=Decimal("21")).save()


class BulletinTests(ConduiteBase):
    def test_la_conduite_est_une_ligne_du_bulletin_et_compte_avec_le_coefficient_1(self):
        self.matiere(self.e5, 12)
        self.conduite(self.e5, "18")
        bulletin = self.bulletin(self.e5)
        trimestre = bulletin["bulletins_trimestre"][0]
        conduite = trimestre["lignes"][-1]
        self.assertEqual(conduite["matiere"], "Conduite")
        self.assertEqual((conduite["coefficient"], conduite["moyenne"], conduite["note_composition"]), (1, Decimal("18.00"), None))
        self.assertEqual(conduite["appreciation"], appreciation_pour(Decimal("18.00")))
        self.assertEqual(trimestre["total_coefficients"], 2)
        self.assertEqual(trimestre["moyenne"], Decimal("15.00"))  # (12 + 18) / 2
        self.assertEqual(bulletin["moyenne_generale"], Decimal("15.00"))

    def test_le_coefficient_est_celui_de_l_ecole(self):
        self.matiere(self.e5, 12)
        self.conduite(self.e5, "18")
        self.coefficient(2)
        self.assertEqual(self.bulletin(self.e5)["bulletins_trimestre"][0]["moyenne"], Decimal("16.00"))  # (12 + 18 x 2) / 3
        self.coefficient(0)
        trimestre = self.bulletin(self.e5)["bulletins_trimestre"][0]
        self.assertEqual(trimestre["moyenne"], Decimal("12.00"))  # affichée, pas comptée
        self.assertEqual(trimestre["lignes"][-1]["coefficient"], 0)
        self.assertEqual(coefficient_conduite(self.ecole), 0)

    def test_la_moyenne_generale_reprend_tous_les_trimestres(self):
        self.matiere(self.e5, 12, T1)
        self.matiere(self.e5, 10, T2)
        self.conduite(self.e5, "18", T1)
        self.conduite(self.e5, "14", T2)
        self.assertEqual(self.bulletin(self.e5)["moyenne_generale"], Decimal("13.50"))  # (12 + 18 + 10 + 14) / 4

    def test_pas_de_conduite_pas_de_ligne(self):
        self.matiere(self.e5, 12)
        trimestre = self.bulletin(self.e5)["bulletins_trimestre"][0]
        self.assertEqual([ligne["matiere"] for ligne in trimestre["lignes"]], ["Maths"])
        self.assertEqual(trimestre["moyenne"], Decimal("12.00"))

    def test_la_conduite_d_un_trimestre_sans_note_de_matiere_ne_compte_pas(self):
        self.matiere(self.e5, 12, T1)
        self.conduite(self.e5, "20", T2)  # aucune note de matière au 2ème trimestre : pas de bloc, rien à moyenner
        bulletin = self.bulletin(self.e5)
        self.assertEqual(len(bulletin["bulletins_trimestre"]), 1)
        self.assertEqual(bulletin["moyenne_generale"], Decimal("12.00"))

    def test_jamais_en_primaire_meme_si_une_note_existe(self):
        """Une note de conduite posée sur une classe de 6ème année (ancien niveau, import...) est ignorée."""
        self.matiere(self.e5, 12)
        self.conduite(self.e5, "18")
        Classe.objects.filter(pk=self.c9a.pk).update(niveau="annee_6")
        self.i["e5"].classe.refresh_from_db()
        bulletin = self.bulletin(self.e5)
        self.assertEqual(bulletin["bulletins_trimestre"][0]["moyenne"], Decimal("12.00"))
        self.assertNotIn("Conduite", [ligne["matiere"] for ligne in bulletin["bulletins_trimestre"][0]["lignes"]])
        self.assertEqual(conduite_des_eleves(self.i["e5"].classe), {})

    def test_une_classe_primaire_n_a_pas_de_ligne(self):
        saisir_note(
            eleve=self.e1, affectation=Affectation.objects.get(enseignant=self.t1, classe=self.c6a), trimestre=T1,
            note_classe=11, enseignant=self.t1,
        )
        NoteConduite.objects.bulk_create([NoteConduite(eleve=self.e1, classe=self.c6a, trimestre=T1, valeur=Decimal("20"))])
        trimestre = _calculer_bulletin(self.e1, self.i["e1"])["bulletins_trimestre"][0]
        self.assertEqual(trimestre["moyenne"], Decimal("11.00"))
        self.assertEqual(len(trimestre["lignes"]), 1)

    def test_le_rang_tient_compte_de_la_conduite(self):
        self.matiere(self.e5, 12)
        self.matiere(self.e6, 14)
        self.assertEqual((self.bulletin(self.e5)["rang"], self.bulletin(self.e6)["rang"]), (2, 1))
        self.conduite(self.e5, "18")  # e5 : (12 + 18) / 2 = 15 ; e6 : 14 (sans conduite)
        self.assertEqual((self.bulletin(self.e5)["rang"], self.bulletin(self.e6)["rang"]), (1, 2))
        self.assertEqual(_calculer_classement(self.i["e5"]), (1, 2))
        self.assertEqual(self.bulletin(self.e5)["bulletins_trimestre"][0]["rang"], 1)

    def test_la_plus_forte_et_la_plus_faible_moyenne_du_trimestre(self):
        self.matiere(self.e5, 12)
        self.matiere(self.e6, 14)
        self.conduite(self.e5, "18")
        trimestre = self.bulletin(self.e6)["bulletins_trimestre"][0]
        self.assertEqual((trimestre["moyenne_plus_forte"], trimestre["moyenne_plus_faible"]), (Decimal("15"), Decimal("14")))

    def test_la_ligne_s_affiche_a_l_ecran_et_dans_le_pdf(self):
        self.matiere(self.e5, 12)
        self.conduite(self.e5, "18")
        self.client.force_login(self.fondateur)
        page = self.client.get(reverse("pedagogie:bulletin_eleve", args=[self.e5.matricule]))
        self.assertContains(page, "Conduite")
        html = render_to_string("pedagogie/bulletin_pdf.html", {
            "eleve": self.e5, "inscription": self.i["e5"], "verification": None, "verification_url": "", "qr_code": "",
            **self.bulletin(self.e5),
        })
        self.assertIn("Conduite", html)
        reponse = self.client.get(reverse("pedagogie:exporter_bulletin_pdf", args=[self.e5.matricule]))
        self.assertEqual(reponse["Content-Type"], "application/pdf")

    def test_la_moyenne_ponderee_partagee(self):
        self.matiere(self.e5, 12, T1)
        self.matiere(self.e5, 10, T2)
        notes = list(self.e5.notes.select_related("affectation"))
        self.assertEqual(moyenne_ponderee(notes), Decimal(11))
        self.assertEqual(moyenne_ponderee(notes, {T1: Decimal(18), T2: Decimal(14)}, 1), Decimal("13.5"))
        self.assertEqual(moyenne_ponderee(notes, {T1: Decimal(18)}, 0), Decimal(11))
        self.assertIsNone(moyenne_ponderee([], {T1: Decimal(18)}, 1))


class ReleveExcelTests(ConduiteBase):
    def setUp(self):
        super().setUp()
        self.matiere(self.e5, 12)
        self.matiere(self.e6, 14)
        self.conduite(self.e5, "18")
        self.conduite(self.e6, "10")
        self.client.force_login(self.fondateur)

    def classeur(self, compte=None, classe=None):
        self.client.force_login(compte or self.fondateur)
        reponse = self.client.get(reverse("pedagogie:exporter_releve_notes_xlsx", args=[(classe or self.c9a).pk]))
        self.assertEqual(reponse.status_code, 200)
        return feuilles(reponse.content), reponse.content

    def test_colonne_conduite_moyenne_et_rang(self):
        classeur, _ = self.classeur()
        lignes = donnees(classeur["1er trimestre"], "N°")
        en_tete = next(ligne for ligne in classeur["1er trimestre"] if ligne and ligne[0] == "N°")
        self.assertEqual(en_tete[-4:], ["Maths (coef 1)", "Conduite (coef 1)", "Moyenne générale", "Rang"])
        par_matricule = {ligne[1]: ligne for ligne in lignes if ligne[1]}
        self.assertEqual(par_matricule[self.e5.matricule][4:], [12, 18, 15, 1])  # (12 + 18) / 2
        self.assertEqual(par_matricule[self.e6.matricule][4:], [14, 10, 12, 2])  # (14 + 10) / 2

    def test_meme_resultat_que_le_bulletin(self):
        classeur, _ = self.classeur()
        recap = {ligne[1]: ligne for ligne in donnees(classeur["Récapitulatif"], "N°") if ligne[1]}
        for eleve, cle in ((self.e5, "e5"), (self.e6, "e6")):
            bulletin = _calculer_bulletin(eleve, self.i[cle])
            rang, _ = _calculer_classement(self.i[cle])
            with self.subTest(eleve=cle):
                self.assertEqual(recap[eleve.matricule][4], float(bulletin["bulletins_trimestre"][0]["moyenne"]))
                self.assertEqual(recap[eleve.matricule][7], float(bulletin["moyenne_generale"]))
                self.assertEqual(recap[eleve.matricule][8], rang)

    def test_le_detail_contient_la_conduite(self):
        classeur, _ = self.classeur()
        detail = donnees(classeur["Détail des notes"], "Matricule")
        lignes_conduite = [ligne for ligne in detail if ligne[3] == "Conduite"]
        self.assertEqual(len(lignes_conduite), 2)
        self.assertIn([self.e5.matricule, self.e5.nom, self.e5.prenom, "Conduite", 1, "1er trimestre", 18, None, 18], lignes_conduite)

    def test_le_bareme_le_dit(self):
        self.assertIn("La conduite (sur 20, coefficient 1) compte dans la moyenne générale", texte_du_classeur(self.classeur()[1]))

    def test_coefficient_zero_la_colonne_reste_mais_ne_compte_pas(self):
        self.coefficient(0)
        classeur, _ = self.classeur()
        lignes = {ligne[1]: ligne for ligne in donnees(classeur["1er trimestre"], "N°") if ligne[1]}
        self.assertEqual(lignes[self.e5.matricule][4:], [12, 18, 12, 2])  # 12 contre 14 pour e6 : la conduite ne compte pas

    def test_l_enseignant_ne_voit_pas_la_conduite(self):
        classeur, contenu = self.classeur(self.t2)
        texte = texte_du_classeur(contenu)
        self.assertNotIn("Conduite", texte)
        self.assertNotIn("Moyenne générale", texte)

    def test_pas_de_colonne_dans_une_classe_primaire(self):
        saisir_note(
            eleve=self.e4, affectation=Affectation.objects.get(enseignant=self.t2, classe=self.c6b), trimestre=T1,
            note_classe=11, enseignant=self.t2,
        )
        _, contenu = self.classeur(classe=self.c6b)
        self.assertNotIn("Conduite", texte_du_classeur(contenu))


class AlertesTests(ConduiteBase):
    def test_la_conduite_compte_dans_le_risque_de_redoublement(self):
        self.matiere(self.e5, 11)
        self.assertEqual([a["eleve"] for a in _eleves_a_risque_academique(self.fondateur)], [])
        self.conduite(self.e5, "5")  # (11 + 5) / 2 = 8 : sous 10
        risques = _eleves_a_risque_academique(self.fondateur)
        self.assertEqual([(a["eleve"], a["moyenne"]) for a in risques], [(self.e5, Decimal("8.00"))])
        self.coefficient(0)
        self.assertEqual(_eleves_a_risque_academique(self.fondateur), [])  # non comptée


class ReglageEtRetraitTests(ConduiteBase):
    def test_le_coefficient_vaut_1_par_defaut_et_se_regle_dans_les_parametres_de_l_ecole(self):
        self.assertEqual(coefficient_conduite(self.ecole), 1)
        self.assertIn("coefficient_conduite", ParametresEtablissementForm(instance=self.ecole).fields)
        champ = ParametresEtablissementForm(instance=self.ecole).fields["coefficient_conduite"]
        self.assertIn("0 = affichée", champ.help_text)

    def _envoi_des_parametres(self, **changements):
        donnees = {
            "nom": self.ecole.nom, "devise": "", "code_devise": "FCFA", "pas_montant": 1, "code_etablissement": "",
            "statut_juridique": "", "region": "", "cercle": "", "commune": "", "milieu": "", "rattachement_administratif": "",
            "numero_agrement": "", "taux_inps_salarie": "3.6", "taux_inps_employeur": "16.4", "taux_amo_salarie": "3.06",
            "taux_amo_employeur": "3.5",
        }
        donnees.update(changements)
        return {cle: valeur for cle, valeur in donnees.items() if valeur is not None}

    def test_le_coefficient_se_modifie_et_un_envoi_sans_ce_champ_le_conserve(self):
        formulaire = ParametresEtablissementForm(self._envoi_des_parametres(coefficient_conduite="2"), instance=self.ecole)
        self.assertTrue(formulaire.is_valid(), formulaire.errors)
        self.assertEqual(formulaire.save().coefficient_conduite, 2)
        for envoi in ({}, {"coefficient_conduite": ""}):
            with self.subTest(envoi=envoi):
                formulaire = ParametresEtablissementForm(self._envoi_des_parametres(**envoi), instance=self.ecole)
                self.assertTrue(formulaire.is_valid(), formulaire.errors)
                self.assertEqual(formulaire.save().coefficient_conduite, 2)

    def test_le_coefficient_0_est_accepte_et_un_negatif_refuse(self):
        formulaire = ParametresEtablissementForm(self._envoi_des_parametres(coefficient_conduite="0"), instance=self.ecole)
        self.assertTrue(formulaire.is_valid(), formulaire.errors)
        self.assertEqual(formulaire.save().coefficient_conduite, 0)
        formulaire = ParametresEtablissementForm(self._envoi_des_parametres(coefficient_conduite="-1"), instance=self.ecole)
        self.assertFalse(formulaire.is_valid())
        self.assertIn("coefficient_conduite", formulaire.errors)

    def test_une_note_de_conduite_est_de_l_historique(self):
        avant = historique_eleve(self.e5)["notes"]
        self.conduite(self.e5, "12")
        self.assertEqual(historique_eleve(self.e5)["notes"], avant + 1)

    def test_les_eleves_d_une_autre_ecole_n_ont_pas_de_conduite_ici(self):
        self.conduite(self.e5, "12")
        self.client.force_login(self.fondateur_b)
        self.assertEqual(self.client.get(url(self.c9a)).status_code, 404)
        self.assertEqual(Utilisateur.objects.filter(role=Role.ELEVE, etablissement=self.ecole_b).count(), 0)
