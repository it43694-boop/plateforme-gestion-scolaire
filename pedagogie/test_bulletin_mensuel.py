"""
Bulletin mensuel du premier cycle : calculs (total, moyenne sur 10, rang, plus forte et plus faible moyenne, moyenne de l'année = moyenne des moyennes
mensuelles), saisie par le maître de la classe, clôture, bulletins PDF, droits et cloisonnement entre écoles.

Le premier exemple reprend un vrai bulletin : 14 disciplines notées (l'anglais n'est pas noté), total 122,5 sur 14 = 8,75.
"""
import datetime
import io
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
from pypdf import PdfReader

from comptes.models import JournalAudit
from comptes.roles import Role
from etablissement.models import Etablissement
from pedagogie import mensuel
from pedagogie.models import DisciplineMensuelle, NoteMensuelle, ObservationMensuelle, PeriodeCloturee
from scolarite.models import AnneeScolaire, Classe, Inscription
from statistiques.test_education import EducationBase, creer_compte

D = datetime.date
D2 = Decimal
OCT, NOV, DEC, JAN = D(2026, 10, 1), D(2026, 11, 1), D(2026, 12, 1), D(2027, 1, 1)
BULLETIN_DE_LA_PHOTO = {
    "Dictée": "9.5", "Questions de dictée": "8", "Expression écrite": "10", "Vocabulaire": "9", "Grammaire": "10", "Conjugaison": "10",
    "Mathématiques": "10", "Questions de cours": "10", "Informatique": "10", "Lecture": "7.5", "Récitation": "7.5", "Écriture": "7", "Dessin": "7", "Chant": "7",
}


def client_de(compte):
    client = Client()
    if compte is not None:
        client.force_login(compte)
    return client


class MensuelBase(EducationBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        mensuel.creer_disciplines_habituelles(cls.c6a)
        cls.disc = {d.libelle: d for d in DisciplineMensuelle.objects.filter(classe=cls.c6a)}
        cls.e10 = creer_compte(Role.ELEVE, "eleve10@mensuel.test", cls.ecole)
        cls.e11 = creer_compte(Role.ELEVE, "eleve11@mensuel.test", cls.ecole)
        for eleve in (cls.e10, cls.e11):
            Inscription.objects.create(eleve=eleve, classe=cls.c6a)
        cls.responsable = creer_compte(Role.RESPONSABLE_PEDAGOGIQUE, "responsable@mensuel.test", cls.ecole)
        cls.parent_autre = creer_compte(Role.PARENT, "parent-autre@mensuel.test", cls.ecole)
        cls.e4.parents_lies.add(cls.parent_autre)
        cls.maitre_b = creer_compte(Role.ENSEIGNANT, "maitre-b@mensuel.test", cls.ecole_b)
        cls.eleve_b = creer_compte(Role.ELEVE, "eleve-b@mensuel.test", cls.ecole_b)
        Inscription.objects.create(eleve=cls.eleve_b, classe=cls.classe_b)

    def noter(self, eleve, mois, notes, classe=None):
        disciplines = self.disc if classe is None else {d.libelle: d for d in DisciplineMensuelle.objects.filter(classe=classe)}
        for libelle, valeur in notes.items():
            NoteMensuelle.objects.update_or_create(eleve=eleve, discipline=disciplines[libelle], mois=mois, defaults={"valeur": D2(str(valeur))})

    def ligne(self, eleve, mois=OCT):
        return next(l for l in mensuel.calculer_mois(self.c6a, mois).lignes if l.eleve.pk == eleve.pk)


# ---------------------------------------------------------------------------------------------------------------------
# Les calculs
# ---------------------------------------------------------------------------------------------------------------------

class CalculDuMoisTests(MensuelBase):
    def test_le_vrai_bulletin_total_122_5_moyenne_8_75(self):
        self.noter(self.e1, OCT, BULLETIN_DE_LA_PHOTO)  # pas de note d'anglais
        ligne = self.ligne(self.e1)
        self.assertEqual((ligne.total, ligne.nombre, ligne.moyenne), (D2("122.5"), 14, D2("8.75")))
        self.assertEqual(ligne.appreciation, "Très Bien")  # 8,75 sur 10 = 17,5 sur 20

    def test_la_moyenne_arrondit_la_moitie_vers_le_haut(self):
        self.noter(self.e1, OCT, {"Dictée": "8.99", "Lecture": "8.5"})  # 17,49 / 2 = 8,745
        self.assertEqual(self.ligne(self.e1).moyenne, D2("8.75"))

    def test_une_discipline_non_notee_n_entre_pas_dans_la_division(self):
        self.noter(self.e1, OCT, {"Dictée": 10, "Lecture": 6})
        self.assertEqual((self.ligne(self.e1).nombre, self.ligne(self.e1).moyenne), (2, D2("8")))

    def test_un_zero_est_une_vraie_note(self):
        self.noter(self.e1, OCT, {"Dictée": 10, "Lecture": 0})
        self.assertEqual(self.ligne(self.e1).moyenne, D2("5"))

    def test_un_eleve_sans_aucune_note_n_a_ni_moyenne_ni_rang(self):
        self.noter(self.e1, OCT, {"Dictée": 7})
        ligne = self.ligne(self.e11)
        self.assertEqual((ligne.total, ligne.nombre, ligne.moyenne, ligne.rang, ligne.appreciation), (None, 0, None, None, ""))

    def test_rang_ex_aequo_puis_saut(self):
        for eleve, valeur in ((self.e1, 9), (self.e2, 8), (self.e3, 8), (self.e10, 5)):
            self.noter(eleve, OCT, {"Dictée": valeur})
        rangs = {l.eleve.pk: l.rang for l in mensuel.calculer_mois(self.c6a, OCT).lignes}
        self.assertEqual(rangs, {self.e1.pk: 1, self.e2.pk: 2, self.e3.pk: 2, self.e10.pk: 4, self.e11.pk: None})

    def test_plus_forte_et_plus_faible_moyenne_et_effectif(self):
        for eleve, valeur in ((self.e1, 9), (self.e2, 6), (self.e10, 5.5)):
            self.noter(eleve, OCT, {"Dictée": valeur})
        resultat = mensuel.calculer_mois(self.c6a, OCT)
        self.assertEqual((resultat.plus_forte, resultat.plus_faible, resultat.effectif), (D2("9"), D2("5.5"), 5))

    def test_une_classe_sans_note_n_a_ni_plus_forte_ni_plus_faible(self):
        resultat = mensuel.calculer_mois(self.c6a, OCT)
        self.assertEqual((resultat.plus_forte, resultat.plus_faible), (None, None))

    def test_une_discipline_desactivee_ne_compte_plus(self):
        self.noter(self.e1, OCT, {"Dictée": 10, "Lecture": 2})
        DisciplineMensuelle.objects.filter(pk=self.disc["Lecture"].pk).update(active=False)
        ligne = self.ligne(self.e1)
        self.assertEqual((ligne.nombre, ligne.moyenne), (1, D2("10")))
        self.assertTrue(NoteMensuelle.objects.filter(discipline=self.disc["Lecture"]).exists())  # la note reste

    def test_un_eleve_parti_n_est_pas_classe(self):
        self.noter(self.e1, OCT, {"Dictée": 9})
        self.noter(self.e2, OCT, {"Dictée": 5})
        Inscription.objects.filter(eleve=self.e1, classe=self.c6a).update(statut=Inscription.Statut.ABANDON)
        resultat = mensuel.calculer_mois(self.c6a, OCT)
        self.assertNotIn(self.e1.pk, [l.eleve.pk for l in resultat.lignes])
        self.assertEqual((resultat.plus_forte, self.ligne(self.e2).rang), (D2("5"), 1))

    def test_les_notes_d_un_autre_mois_ne_se_melangent_pas(self):
        self.noter(self.e1, OCT, {"Dictée": 9})
        self.noter(self.e1, NOV, {"Dictée": 3})
        self.assertEqual((self.ligne(self.e1, OCT).moyenne, self.ligne(self.e1, NOV).moyenne), (D2("9"), D2("3")))

    def test_l_appreciation_suit_l_echelle_a_six_niveaux_doublee(self):
        for moyenne, attendu in (("10", "Excellent"), ("9", "Excellent"), ("8", "Très Bien"), ("7", "Bien"), ("6", "Assez Bien"), ("5", "Passable"), ("4.99", "Insuffisant")):
            with self.subTest(moyenne=moyenne):
                self.assertEqual(mensuel.appreciation_du_mois(D2(moyenne)), attendu)

    def test_le_calcul_d_une_classe_entiere_ne_fait_pas_une_requete_par_eleve(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        for eleve in (self.e1, self.e2, self.e3, self.e10):
            self.noter(eleve, OCT, BULLETIN_DE_LA_PHOTO)
        with CaptureQueriesContext(connection) as requetes:
            mensuel.calculer_mois(self.c6a, OCT, avec_observations=True)
        self.assertLess(len(requetes), 12)


class MoyenneDeLAnneeTests(MensuelBase):
    def test_la_moyenne_de_l_annee_est_la_moyenne_des_moyennes_mensuelles(self):
        self.noter(self.e1, OCT, {"Dictée": 8})
        self.noter(self.e1, NOV, {"Dictée": 6})
        self.noter(self.e1, DEC, {"Dictée": 4})
        annuel = mensuel.calculer_annee(self.c6a)
        ligne = next(l for l in annuel.lignes if l.eleve.pk == self.e1.pk)
        self.assertEqual(ligne.moyennes, {OCT: D2("8"), NOV: D2("6"), DEC: D2("4")})
        self.assertEqual(ligne.moyenne_annuelle, D2("6"))
        self.assertEqual(annuel.mois, [OCT, NOV, DEC])

    def test_la_moyenne_annuelle_n_est_pas_la_moyenne_de_toutes_les_notes(self):
        self.noter(self.e1, OCT, {"Dictée": 10})  # 1 note
        self.noter(self.e1, NOV, {"Dictée": 0, "Lecture": 0, "Dessin": 0, "Chant": 0})  # 4 notes
        ligne = next(l for l in mensuel.calculer_annee(self.c6a).lignes if l.eleve.pk == self.e1.pk)
        self.assertEqual(ligne.moyenne_annuelle, D2("5"))  # (10 + 0) / 2, et non 10 / 5

    def test_un_mois_sans_note_pour_l_eleve_n_est_pas_compte_mais_est_signale(self):
        self.noter(self.e1, OCT, {"Dictée": 8})
        self.noter(self.e2, OCT, {"Dictée": 6})
        self.noter(self.e2, NOV, {"Dictée": 4})  # e1 était absent à la composition de novembre
        annuel = mensuel.calculer_annee(self.c6a)
        e1 = next(l for l in annuel.lignes if l.eleve.pk == self.e1.pk)
        self.assertEqual((e1.moyenne_annuelle, e1.mois_manquants), (D2("8"), 1))
        self.assertEqual(next(l for l in annuel.lignes if l.eleve.pk == self.e2.pk).moyenne_annuelle, D2("5"))

    def test_la_decision_de_passage_est_a_5_sur_10_par_defaut(self):
        for eleve, valeur in ((self.e1, 5), (self.e2, "4.99"), (self.e3, 9)):
            self.noter(eleve, OCT, {"Dictée": valeur})
        decisions = {l.eleve.pk: l.admis for l in mensuel.calculer_annee(self.c6a).lignes}
        self.assertEqual(decisions, {self.e1.pk: True, self.e2.pk: False, self.e3.pk: True, self.e10.pk: None, self.e11.pk: None})

    def test_la_moyenne_de_passage_est_un_reglage_de_l_ecole(self):
        self.assertEqual(self.ecole.moyenne_passage_premier_cycle, D2("5"))
        self.noter(self.e1, OCT, {"Dictée": 5.5})
        Etablissement.objects.filter(pk=self.ecole.pk).update(moyenne_passage_premier_cycle=D2("6"))
        annuel = mensuel.calculer_annee(Classe.objects.get(pk=self.c6a.pk))  # la classe relue : le réglage vient de changer
        self.assertEqual((annuel.seuil, next(l for l in annuel.lignes if l.eleve.pk == self.e1.pk).admis), (D2("6"), False))

    def test_la_moyenne_de_passage_doit_etre_entre_0_5_et_10(self):
        for valeur in ("0", "-1", "10.5", "20"):
            self.ecole.moyenne_passage_premier_cycle = D2(valeur)
            with self.subTest(valeur=valeur), self.assertRaises(ValidationError):
                self.ecole.full_clean(exclude=["logo", "slug", "code_etablissement"])
        self.ecole.moyenne_passage_premier_cycle = D2("5")

    def test_rang_de_l_annee(self):
        self.noter(self.e1, OCT, {"Dictée": 9})
        self.noter(self.e2, OCT, {"Dictée": 6})
        self.noter(self.e3, OCT, {"Dictée": 6})
        rangs = {l.eleve.pk: l.rang for l in mensuel.calculer_annee(self.c6a).lignes}
        self.assertEqual((rangs[self.e1.pk], rangs[self.e2.pk], rangs[self.e3.pk], rangs[self.e11.pk]), (1, 2, 2, None))


class OutilsDeMoisEtDeNoteTests(MensuelBase):
    def test_les_mois_de_l_annee_scolaire(self):
        mois = mensuel.mois_de_l_annee(self.annee)  # 1er octobre 2026 - 31 juillet 2027
        self.assertEqual((mois[0], mois[-1], len(mois)), (OCT, D(2027, 7, 1), 10))
        self.assertEqual(mois[3], JAN)  # le passage d'une année civile à la suivante

    def test_le_trimestre_d_un_mois(self):
        for mois, attendu in ((9, "trimestre_1"), (10, "trimestre_1"), (12, "trimestre_1"), (1, "trimestre_2"), (3, "trimestre_2"), (4, "trimestre_3"), (7, "trimestre_3")):
            with self.subTest(mois=mois):
                self.assertEqual(mensuel.trimestre_du_mois(D(2026, mois, 1)), attendu)

    def test_le_mois_a_proposer(self):
        self.assertEqual(mensuel.mois_courant_de_la_classe(self.c6a, D(2026, 11, 17)), NOV)
        self.assertEqual(mensuel.mois_courant_de_la_classe(self.c6a, D(2026, 8, 3)), OCT)  # avant l'année : le premier mois
        self.assertEqual(mensuel.mois_courant_de_la_classe(self.c6a, D(2028, 1, 3)), D(2027, 7, 1))  # après : le dernier

    def test_lire_une_note(self):
        for texte, attendu in (("9", D2("9")), ("9,5", D2("9.5")), ("9.5", D2("9.5")), (" 7.25 ", D2("7.25")), ("10", D2("10")), ("0", D2("0")), ("10,00", D2("10")), ("", None), ("  ", None), ("-", None), ("—", None)):
            with self.subTest(texte=texte):
                self.assertEqual(mensuel.lire_note(texte), attendu)

    def test_une_note_invalide_est_refusee(self):
        for texte in ("abc", "10,01", "11", "-1", "9,555", "NaN", "Infinity", "9;5", "1e400", "9 5"):
            with self.subTest(texte=texte), self.assertRaises(ValidationError):
                mensuel.lire_note(texte)


# ---------------------------------------------------------------------------------------------------------------------
# L'enregistrement des notes
# ---------------------------------------------------------------------------------------------------------------------

class EnregistrerLesNotesTests(MensuelBase):
    def saisir(self, saisies, mois=OCT, acteur=None, **options):
        cles = {(self.eleves[nom].pk, self.disc[libelle].pk): texte for (nom, libelle), texte in saisies.items()}
        return mensuel.enregistrer_notes(classe=self.c6a, mois=mois, saisies=cles, acteur=acteur or self.t1, **options)

    def setUp(self):
        self.eleves = {"e1": self.e1, "e2": self.e2, "e3": self.e3}

    def test_creer_modifier_effacer(self):
        bilan = self.saisir({("e1", "Dictée"): "9,5", ("e1", "Lecture"): "7", ("e2", "Dictée"): "8"})
        self.assertEqual((bilan["crees"], bilan["modifiees"], bilan["supprimees"]), (3, 0, 0))
        self.assertEqual(NoteMensuelle.objects.get(eleve=self.e1, discipline=self.disc["Dictée"]).valeur, D2("9.5"))
        self.assertEqual(NoteMensuelle.objects.get(eleve=self.e1, discipline=self.disc["Dictée"]).saisie_par, self.t1)
        bilan = self.saisir({("e1", "Dictée"): "10", ("e1", "Lecture"): "", ("e2", "Dictée"): "8"})
        self.assertEqual((bilan["crees"], bilan["modifiees"], bilan["supprimees"]), (0, 1, 1))  # e2 n'a pas changé
        self.assertFalse(NoteMensuelle.objects.filter(eleve=self.e1, discipline=self.disc["Lecture"]).exists())

    def test_une_case_absente_n_est_pas_touchee(self):
        self.noter(self.e1, OCT, {"Dictée": 9, "Lecture": 7})
        self.saisir({("e1", "Dictée"): "6"})  # la lecture n'est pas dans l'envoi
        self.assertEqual(NoteMensuelle.objects.get(eleve=self.e1, discipline=self.disc["Lecture"]).valeur, D2("7"))

    def test_une_note_refusee_n_en_enregistre_aucune(self):
        with self.assertRaises(mensuel.ErreursDeSaisie) as contexte:
            self.saisir({("e1", "Dictée"): "9", ("e2", "Dictée"): "12", ("e3", "Dictée"): "abc"})
        self.assertEqual(set(contexte.exception.erreurs), {(self.e2.pk, self.disc["Dictée"].pk), (self.e3.pk, self.disc["Dictée"].pk)})
        self.assertEqual(NoteMensuelle.objects.count(), 0)

    def test_un_eleve_ou_une_discipline_d_ailleurs_est_ignore(self):
        discipline_b = DisciplineMensuelle.objects.create(classe=self.classe_b, libelle="Dictée")
        bilan = mensuel.enregistrer_notes(
            classe=self.c6a, mois=OCT, acteur=self.t1,
            saisies={(self.eleve_b.pk, self.disc["Dictée"].pk): "10", (self.e1.pk, discipline_b.pk): "10", (self.e4.pk, self.disc["Dictée"].pk): "10", (self.e1.pk, self.disc["Dictée"].pk): "7"},
        )
        self.assertEqual(bilan["crees"], 1)  # seul e1 / Dictée de 6A est une vraie case
        self.assertEqual(NoteMensuelle.objects.count(), 1)

    def test_une_discipline_desactivee_ne_se_note_plus(self):
        DisciplineMensuelle.objects.filter(pk=self.disc["Chant"].pk).update(active=False)
        bilan = self.saisir({("e1", "Chant"): "9", ("e1", "Dictée"): "8"})
        self.assertEqual(bilan["crees"], 1)

    def test_les_observations(self):
        self.saisir({("e1", "Dictée"): "9"}, observations={self.e1.pk: "  Bon   travail ", self.e2.pk: "", self.eleve_b.pk: "intrus"})
        self.assertEqual(ObservationMensuelle.objects.get(eleve=self.e1, classe=self.c6a, mois=OCT).observation, "Bon travail")
        self.assertEqual(ObservationMensuelle.objects.count(), 1)  # ni la vide, ni celle d'un élève d'une autre classe
        self.saisir({("e1", "Dictée"): "9"}, observations={self.e1.pk: ""})
        self.assertEqual(ObservationMensuelle.objects.count(), 0)
        self.saisir({("e1", "Dictée"): "9"}, observations={self.e1.pk: "x" * 400})
        self.assertEqual(len(ObservationMensuelle.objects.get().observation), 255)

    def test_trimestre_cloture_refuse(self):
        PeriodeCloturee.objects.create(annee_scolaire=self.annee, trimestre="trimestre_1", cloturee_par=self.fondateur)
        for mois in (OCT, NOV, DEC):
            with self.subTest(mois=mois), self.assertRaisesMessage(ValidationError, "clôturées"):
                self.saisir({("e1", "Dictée"): "9"}, mois=mois)
        self.saisir({("e1", "Dictée"): "9"}, mois=JAN)  # le trimestre suivant reste ouvert
        self.assertEqual(NoteMensuelle.objects.count(), 1)

    def test_annee_archivee_refusee(self):
        AnneeScolaire.objects.filter(pk=self.annee.pk).update(est_archivee=True)
        self.c6a.annee_scolaire.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "archivée"):
            self.saisir({("e1", "Dictée"): "9"})

    def test_un_mois_hors_de_l_annee_est_refuse(self):
        for mois in (D(2026, 8, 1), D(2027, 9, 1), D(2020, 10, 1)):
            with self.subTest(mois=mois), self.assertRaisesMessage(ValidationError, "n'appartient pas"):
                self.saisir({("e1", "Dictée"): "9"}, mois=mois)

    def test_une_classe_du_deuxieme_cycle_est_refusee(self):
        with self.assertRaisesMessage(ValidationError, "premier cycle"):
            mensuel.enregistrer_notes(classe=self.c9a, mois=OCT, saisies={}, acteur=self.t2)

    def test_la_base_refuse_une_note_hors_de_0_10(self):
        from django.db import IntegrityError, transaction

        for valeur in (D2("-0.01"), D2("10.01")):
            with self.subTest(valeur=valeur), self.assertRaises(IntegrityError), transaction.atomic():
                NoteMensuelle.objects.bulk_create([NoteMensuelle(eleve=self.e1, discipline=self.disc["Dictée"], mois=OCT, valeur=valeur)])

    def test_une_seule_note_par_eleve_discipline_et_mois(self):
        from django.db import IntegrityError, transaction

        self.noter(self.e1, OCT, {"Dictée": 9})
        with self.assertRaises(IntegrityError), transaction.atomic():
            NoteMensuelle.objects.create(eleve=self.e1, discipline=self.disc["Dictée"], mois=OCT, valeur=D2("5"))


class DisciplinesTests(MensuelBase):
    def test_liste_habituelle_sans_doublon(self):
        self.assertEqual(DisciplineMensuelle.objects.filter(classe=self.c6a).count(), 15)
        self.assertEqual(mensuel.creer_disciplines_habituelles(self.c6a), 0)  # déjà faites
        self.assertEqual(list(DisciplineMensuelle.objects.filter(classe=self.c6a).values_list("libelle", flat=True))[:3], ["Dictée", "Questions de dictée", "Expression écrite"])

    def test_ajouter_renommer_supprimer(self):
        discipline = mensuel.ajouter_discipline(self.c6a, "  Éducation   civique ")
        self.assertEqual((discipline.libelle, discipline.ordre), ("Éducation civique", 15))
        with self.assertRaisesMessage(ValidationError, "existe déjà"):
            mensuel.ajouter_discipline(self.c6a, "éducation CIVIQUE")
        for libelle in ("", "  ", "x" * 81):
            with self.subTest(libelle=libelle), self.assertRaises(ValidationError):
                mensuel.ajouter_discipline(self.c6a, libelle)
        mensuel.renommer_discipline(discipline, "Morale")
        discipline.refresh_from_db()
        self.assertEqual(discipline.libelle, "Morale")
        with self.assertRaisesMessage(ValidationError, "existe déjà"):
            mensuel.renommer_discipline(discipline, "Dessin")
        mensuel.supprimer_discipline(discipline)
        self.assertFalse(DisciplineMensuelle.objects.filter(pk=discipline.pk).exists())

    def test_une_discipline_avec_notes_ne_se_supprime_pas(self):
        self.noter(self.e1, OCT, {"Dictée": 9})
        with self.assertRaisesMessage(ValidationError, "désactivez"):
            mensuel.supprimer_discipline(self.disc["Dictée"])
        self.assertTrue(DisciplineMensuelle.objects.filter(pk=self.disc["Dictée"].pk).exists())

    def test_copier_les_disciplines_d_une_autre_classe(self):
        mensuel.ajouter_discipline(self.c6b, "Lecture")
        DisciplineMensuelle.objects.filter(pk=self.disc["Chant"].pk).update(active=False)
        ajoutees = mensuel.copier_disciplines(self.c6a, self.c6b)
        self.assertEqual(ajoutees, 13)  # 15 - le chant désactivé - la lecture déjà présente
        self.assertFalse(DisciplineMensuelle.objects.filter(classe=self.c6b, libelle="Chant").exists())
        with self.assertRaises(ValidationError):
            mensuel.copier_disciplines(self.c6a, self.c6a)
        with self.assertRaisesMessage(ValidationError, "n'appartient pas"):
            mensuel.copier_disciplines(self.classe_b, self.c6a)


# ---------------------------------------------------------------------------------------------------------------------
# Les pages : droits
# ---------------------------------------------------------------------------------------------------------------------

class DroitsTests(MensuelBase):
    def adresses_de_la_classe(self):
        return [
            reverse("pedagogie:mensuel_grille", args=[self.c6a.pk, 2026, 10]), reverse("pedagogie:mensuel_resultats", args=[self.c6a.pk, 2026, 10]),
            reverse("pedagogie:mensuel_annuel", args=[self.c6a.pk]), reverse("pedagogie:mensuel_disciplines", args=[self.c6a.pk]),
            reverse("pedagogie:mensuel_bulletins_classe_pdf", args=[self.c6a.pk, 2026, 10]),
        ]

    def test_le_maitre_de_la_classe_la_direction_et_le_directeur_du_1er_cycle(self):
        self.noter(self.e1, OCT, {"Dictée": 9})
        for compte in (self.t1, self.fondateur, self.dir_1er):
            client = client_de(compte)
            for adresse in self.adresses_de_la_classe():
                with self.subTest(role=compte.role, adresse=adresse):
                    self.assertEqual(client.get(adresse).status_code, 200)

    def test_le_responsable_pedagogique_consulte_mais_ne_saisit_pas(self):
        client = client_de(self.responsable)
        for adresse in self.adresses_de_la_classe()[:3]:
            self.assertEqual(client.get(adresse).status_code, 200)
        self.assertEqual(client.get(self.adresses_de_la_classe()[3]).status_code, 403)  # les disciplines : réservées à ceux qui saisissent
        grille = reverse("pedagogie:mensuel_grille", args=[self.c6a.pk, 2026, 10])
        self.assertNotContains(client.get(grille), "Enregistrer les notes du mois")
        self.assertEqual(client.post(grille, {f"n_{self.e1.pk}_{self.disc['Dictée'].pk}": "9"}).status_code, 403)
        self.assertEqual(NoteMensuelle.objects.count(), 0)

    def test_un_enseignant_d_une_autre_classe_n_a_aucun_droit_sur_celle_ci(self):
        client = client_de(self.t2)  # t2 enseigne en 6B et en 9A
        for adresse in self.adresses_de_la_classe():
            with self.subTest(adresse=adresse):
                self.assertEqual(client.get(adresse).status_code, 403)
        grille = reverse("pedagogie:mensuel_grille", args=[self.c6a.pk, 2026, 10])
        self.assertEqual(client.post(grille, {f"n_{self.e1.pk}_{self.disc['Dictée'].pk}": "9"}).status_code, 403)
        self.assertEqual(NoteMensuelle.objects.count(), 0)

    def test_les_autres_roles_sont_refuses(self):
        for compte in (self.parent, self.e1, self.comptable, self.secretaire):
            client = client_de(compte)
            for adresse in self.adresses_de_la_classe() + [reverse("pedagogie:mensuel_classes")]:
                with self.subTest(role=compte.role, adresse=adresse):
                    self.assertEqual(client.get(adresse).status_code, 403)

    def test_le_censeur_et_les_directeurs_des_autres_cycles_ne_voient_pas_le_premier_cycle(self):
        directeur_2e = creer_compte(Role.DIRECTEUR_2EME_CYCLE, "dir2@mensuel.test", self.ecole)
        for compte in (self.censeur, directeur_2e):
            client = client_de(compte)
            for adresse in self.adresses_de_la_classe():
                with self.subTest(role=compte.role, adresse=adresse):
                    self.assertEqual(client.get(adresse).status_code, 404)

    def test_une_classe_du_deuxieme_cycle_n_a_pas_de_bulletin_mensuel(self):
        client = client_de(self.fondateur)
        for nom, arguments in (
            ("pedagogie:mensuel_grille", [self.c9a.pk, 2026, 10]), ("pedagogie:mensuel_resultats", [self.c9a.pk, 2026, 10]),
            ("pedagogie:mensuel_annuel", [self.c9a.pk]), ("pedagogie:mensuel_disciplines", [self.c9a.pk]),
            ("pedagogie:mensuel_bulletins_classe_pdf", [self.c9a.pk, 2026, 10]),
        ):
            with self.subTest(page=nom):
                self.assertEqual(client.get(reverse(nom, args=arguments)).status_code, 404)

    def test_un_visiteur_anonyme_est_renvoye_vers_la_connexion(self):
        for adresse in self.adresses_de_la_classe() + [reverse("pedagogie:mensuel_classes"), reverse("pedagogie:mensuel_eleve", args=[self.e1.matricule])]:
            with self.subTest(adresse=adresse):
                reponse = client_de(None).get(adresse)
                self.assertEqual(reponse.status_code, 302)
                self.assertIn("/connexion", reponse["Location"])

    def test_un_mois_qui_n_existe_pas_est_introuvable(self):
        client = client_de(self.fondateur)
        for annee, mois in ((2026, 13), (2026, 0), (0, 5), (10000, 1)):
            with self.subTest(annee=annee, mois=mois):
                self.assertEqual(client.get(reverse("pedagogie:mensuel_grille", args=[self.c6a.pk, annee, mois])).status_code, 404)

    def test_la_liste_des_classes_de_chacun(self):
        def classes(compte):
            return [ligne["classe"].pk for ligne in client_de(compte).get(reverse("pedagogie:mensuel_classes")).context["lignes"]]

        self.assertEqual(classes(self.t1), [self.c6a.pk])  # sa seule classe du premier cycle
        self.assertEqual(classes(self.t2), [self.c6b.pk])  # sa classe de 9ème année n'y est pas
        for compte in (self.fondateur, self.dir_1er):  # toutes les classes du premier cycle de l'école (6A, 6B, et la 5A de l'année précédente), pas la 9A
            self.assertEqual(set(classes(compte)), {self.c6a.pk, self.c6b.pk, self.classe_5a.pk})
        self.assertEqual(classes(self.fondateur_b), [self.classe_b.pk])


# ---------------------------------------------------------------------------------------------------------------------
# Les pages : parcours
# ---------------------------------------------------------------------------------------------------------------------

class ParcoursDuMaitreTests(MensuelBase):
    def setUp(self):
        self.client = client_de(self.t1)
        self.adresse = reverse("pedagogie:mensuel_grille", args=[self.c6a.pk, 2026, 10])

    def donnees(self, notes):
        return {f"n_{eleve.pk}_{self.disc[libelle].pk}": valeur for (eleve, libelle), valeur in notes.items()}

    def test_la_grille_affiche_les_eleves_et_les_disciplines(self):
        page = self.client.get(self.adresse)
        self.assertEqual(page.status_code, 200)
        for attendu in ("<span>Composition du mois de</span> octobre 2026", "Dictée", "Chant", self.e1.nom, "Enregistrer les notes du mois"):
            self.assertContains(page, attendu)
        self.assertEqual(page.content.decode().count('name="n_'), 5 * 15)  # cinq élèves, quinze disciplines
        self.assertEqual(page.context["modifiable"], True)

    def test_saisir_une_grille(self):
        reponse = self.client.post(self.adresse, {
            **self.donnees({(self.e1, "Dictée"): "9,5", (self.e1, "Lecture"): "7.5", (self.e2, "Dictée"): "8", (self.e2, "Chant"): ""}),
            f"o_{self.e1.pk}": "Bon travail",
        })
        self.assertRedirects(reponse, self.adresse, fetch_redirect_response=False)
        self.assertEqual(NoteMensuelle.objects.count(), 3)
        page = self.client.get(self.adresse)
        self.assertContains(page, "Les notes du mois sont enregistrées")
        ligne = next(l for l in page.context["lignes"] if l["eleve"].pk == self.e1.pk)
        self.assertEqual((ligne["total"], ligne["moyenne"], ligne["rang"], ligne["observation"]), (D2("17"), D2("8.5"), 1, "Bon travail"))
        self.assertTrue(JournalAudit.objects.filter(action="saisie_notes_mensuelles", acteur=self.t1).exists())

    def test_une_note_fausse_affiche_l_erreur_garde_la_saisie_et_n_enregistre_rien(self):
        reponse = self.client.post(self.adresse, self.donnees({(self.e1, "Dictée"): "9", (self.e2, "Dictée"): "12", (self.e3, "Lecture"): "abc"}))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "2 note(s) à corriger : rien n&#x27;a été enregistré.")
        self.assertContains(reponse, "Une note est comprise entre 0 et 10.")
        self.assertContains(reponse, 'value="12"')  # ce qui a été tapé reste dans la case
        self.assertEqual(NoteMensuelle.objects.count(), 0)

    def test_on_ne_peut_pas_noter_un_mois_cloture(self):
        PeriodeCloturee.objects.create(annee_scolaire=self.annee, trimestre="trimestre_1", cloturee_par=self.fondateur)
        page = self.client.get(self.adresse)
        self.assertContains(page, "clôturées")
        self.assertNotContains(page, "Enregistrer les notes du mois")
        self.client.post(self.adresse, self.donnees({(self.e1, "Dictée"): "9"}))
        self.assertEqual(NoteMensuelle.objects.count(), 0)
        self.assertEqual(client_de(self.t1).get(reverse("pedagogie:mensuel_grille", args=[self.c6a.pk, 2027, 1])).context["modifiable"], True)

    def test_un_mois_hors_de_l_annee_peut_se_voir_mais_pas_se_remplir(self):
        adresse = reverse("pedagogie:mensuel_grille", args=[self.c6a.pk, 2026, 8])
        self.assertEqual(self.client.get(adresse).status_code, 200)
        reponse = self.client.post(adresse, self.donnees({(self.e1, "Dictée"): "9"}), follow=True)
        self.assertContains(reponse, "n&#x27;appartient pas à l&#x27;année scolaire")
        self.assertEqual(NoteMensuelle.objects.count(), 0)

    def test_classe_sans_discipline_renvoie_vers_leur_creation(self):
        page = client_de(self.fondateur).get(reverse("pedagogie:mensuel_grille", args=[self.c6b.pk, 2026, 10]))
        self.assertContains(page, "pas encore de disciplines")
        self.assertContains(page, reverse("pedagogie:mensuel_disciplines", args=[self.c6b.pk]))

    def test_navigation_entre_les_mois(self):
        page = self.client.get(reverse("pedagogie:mensuel_grille", args=[self.c6a.pk, 2026, 12]))
        self.assertEqual((page.context["precedent"], page.context["suivant"]), (NOV, JAN))
        self.assertEqual(self.client.get(self.adresse).context["precedent"], None)  # octobre : le premier mois

    def test_les_resultats_sont_classes_par_rang(self):
        for eleve, valeur in ((self.e1, 6), (self.e2, 9), (self.e3, 7.5)):
            self.noter(eleve, OCT, {"Dictée": valeur})
        page = self.client.get(reverse("pedagogie:mensuel_resultats", args=[self.c6a.pk, 2026, 10]))
        self.assertEqual([l.eleve.pk for l in page.context["lignes"][:3]], [self.e2.pk, self.e3.pk, self.e1.pk])
        self.assertEqual(page.context["avec_notes"], 3)
        self.assertContains(page, "Bulletins de la classe (PDF)")

    def test_la_moyenne_de_l_annee_par_la_page(self):
        self.noter(self.e1, OCT, {"Dictée": 8})
        self.noter(self.e1, NOV, {"Dictée": 4})
        page = self.client.get(reverse("pedagogie:mensuel_annuel", args=[self.c6a.pk]))
        ligne = next(l for l in page.context["lignes"] if l.eleve.pk == self.e1.pk)
        self.assertEqual((ligne.moyenne_annuelle, ligne.cases), (D2("6"), [D2("8"), D2("4")]))
        self.assertEqual((page.context["admis"], page.context["non_admis"]), (1, 0))

    def test_les_disciplines_par_la_page(self):
        adresse = reverse("pedagogie:mensuel_disciplines", args=[self.c6b.pk])
        direction = client_de(self.fondateur)
        direction.post(adresse, {"action": "habituelles"})
        self.assertEqual(DisciplineMensuelle.objects.filter(classe=self.c6b).count(), 15)
        direction.post(adresse, {"action": "ajouter", "libelle": "Morale"})
        discipline = DisciplineMensuelle.objects.get(classe=self.c6b, libelle="Morale")
        direction.post(adresse, {"action": "renommer", "discipline": discipline.pk, "libelle": "Éducation morale"})
        direction.post(adresse, {"action": "basculer", "discipline": discipline.pk})
        discipline.refresh_from_db()
        self.assertEqual((discipline.libelle, discipline.active), ("Éducation morale", False))
        direction.post(adresse, {"action": "supprimer", "discipline": discipline.pk})
        self.assertFalse(DisciplineMensuelle.objects.filter(pk=discipline.pk).exists())
        page = direction.post(adresse, {"action": "ajouter", "libelle": "dessin"}, follow=True)
        self.assertContains(page, "existe déjà dans la classe")
        self.assertEqual(direction.post(adresse, {"action": "inconnue"}).status_code, 404)

    def test_une_discipline_d_une_autre_classe_est_introuvable(self):
        adresse = reverse("pedagogie:mensuel_disciplines", args=[self.c6b.pk])
        reponse = client_de(self.fondateur).post(adresse, {"action": "supprimer", "discipline": self.disc["Dictée"].pk})
        self.assertEqual(reponse.status_code, 404)
        self.assertTrue(DisciplineMensuelle.objects.filter(pk=self.disc["Dictée"].pk).exists())

    def test_reprendre_les_disciplines_d_une_autre_classe_par_la_page(self):
        adresse = reverse("pedagogie:mensuel_disciplines", args=[self.c6b.pk])
        client_de(self.fondateur).post(adresse, {"action": "copier", "source": self.c6a.pk})
        self.assertEqual(DisciplineMensuelle.objects.filter(classe=self.c6b).count(), 15)
        page = client_de(self.fondateur).get(adresse)
        self.assertIn(self.c6a, list(page.context["autres_classes"]))

    def test_on_ne_reprend_pas_les_disciplines_d_une_classe_d_une_autre_ecole(self):
        DisciplineMensuelle.objects.create(classe=self.classe_b, libelle="Secret de B")
        client_de(self.fondateur).post(reverse("pedagogie:mensuel_disciplines", args=[self.c6b.pk]), {"action": "copier", "source": self.classe_b.pk})
        self.assertFalse(DisciplineMensuelle.objects.filter(classe=self.c6b, libelle="Secret de B").exists())

    def test_annee_archivee_disciplines_en_lecture_seule(self):
        AnneeScolaire.objects.filter(pk=self.annee.pk).update(est_archivee=True)
        adresse = reverse("pedagogie:mensuel_disciplines", args=[self.c6a.pk])
        self.assertEqual(client_de(self.fondateur).get(adresse).status_code, 200)
        self.assertEqual(client_de(self.fondateur).post(adresse, {"action": "ajouter", "libelle": "Nouvelle"}).status_code, 403)

    def test_le_menu(self):
        def liens(compte):
            page = client_de(compte).get(reverse("comptes:liste_notifications"))
            return [lien["url"] for section in page.context["sections_navigation"] for lien in section["liens"]]

        for compte in (self.t1, self.fondateur, self.dir_1er, self.responsable):
            self.assertIn("pedagogie:mensuel_classes", liens(compte), compte.role)
        for compte in (self.parent, self.e1, self.comptable, self.secretaire, self.censeur):
            self.assertNotIn("pedagogie:mensuel_classes", liens(compte), compte.role)

    def test_le_bouton_de_mes_classes(self):
        page = self.client.get(reverse("pedagogie:mes_classes"))
        self.assertContains(page, reverse("pedagogie:mensuel_classes"))


# ---------------------------------------------------------------------------------------------------------------------
# Les bulletins PDF et la page de l'élève
# ---------------------------------------------------------------------------------------------------------------------

class BulletinsPdfTests(MensuelBase):
    def setUp(self):
        for eleve in (self.e1, self.e2):
            self.noter(eleve, OCT, BULLETIN_DE_LA_PHOTO)
        self.noter(self.e3, OCT, {"Dictée": 5})
        ObservationMensuelle.objects.create(eleve=self.e1, classe=self.c6a, mois=OCT, observation="Assez bien, peut faire mieux")

    def pages(self, reponse):
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(reponse.content.startswith(b"%PDF"))
        return PdfReader(io.BytesIO(reponse.content)).pages

    def test_le_bulletin_d_un_eleve_tient_sur_une_page_avec_les_chiffres_du_bulletin(self):
        reponse = client_de(self.t1).get(reverse("pedagogie:mensuel_bulletin_pdf", args=[self.e1.matricule, 2026, 10]))
        pages = self.pages(reponse)
        self.assertEqual(len(pages), 1)
        texte = " ".join(pages[0].extract_text().split())
        for attendu in ("NOTES ET APPRÉCIATIONS", "Composition du mois de octobre 2026", "Dictée", "Chant", "122,5", "8,75", "Visa du Maître", "Visa des Parents", "Visa du Directeur", "Assez bien"):
            self.assertIn(attendu, texte)
        self.assertIn("1 / 5", texte.replace("  ", " "))  # rang 1 sur 5 élèves : e1 et e2 sont ex æquo
        self.assertIn("bulletin", reponse["Content-Disposition"])

    def test_les_bulletins_de_la_classe_un_par_page_pour_les_eleves_notes(self):
        reponse = client_de(self.fondateur).get(reverse("pedagogie:mensuel_bulletins_classe_pdf", args=[self.c6a.pk, 2026, 10]))
        self.assertEqual(len(self.pages(reponse)), 3)  # e1, e2 et e3 ont des notes ; e10 et e11 non
        self.assertTrue(JournalAudit.objects.filter(action="export_bulletins_mensuels_classe").exists())

    def test_sans_aucune_note_rien_a_imprimer(self):
        reponse = client_de(self.fondateur).get(reverse("pedagogie:mensuel_bulletins_classe_pdf", args=[self.c6a.pk, 2026, 11]), follow=True)
        self.assertContains(reponse, "aucun bulletin à imprimer")
        for eleve in (self.e10,):
            self.assertEqual(client_de(self.t1).get(reverse("pedagogie:mensuel_bulletin_pdf", args=[eleve.matricule, 2026, 10])).status_code, 404)

    def test_le_parent_de_l_enfant_telecharge_son_bulletin_et_pas_celui_d_un_autre(self):
        client = client_de(self.parent)  # parent de e1
        self.assertEqual(len(self.pages(client.get(reverse("pedagogie:mensuel_bulletin_pdf", args=[self.e1.matricule, 2026, 10])))), 1)
        for eleve in (self.e2, self.e3):
            self.assertEqual(client.get(reverse("pedagogie:mensuel_bulletin_pdf", args=[eleve.matricule, 2026, 10])).status_code, 403)
        self.assertEqual(client_de(self.parent_autre).get(reverse("pedagogie:mensuel_bulletin_pdf", args=[self.e1.matricule, 2026, 10])).status_code, 403)

    def test_l_eleve_voit_son_bulletin_mais_pas_celui_d_un_camarade(self):
        client = client_de(self.e1)
        self.assertEqual(client.get(reverse("pedagogie:mensuel_bulletin_pdf", args=[self.e1.matricule, 2026, 10])).status_code, 200)
        self.assertEqual(client.get(reverse("pedagogie:mensuel_bulletin_pdf", args=[self.e2.matricule, 2026, 10])).status_code, 403)

    def test_l_enseignant_d_une_autre_classe_n_a_pas_le_bulletin(self):
        self.assertEqual(client_de(self.t2).get(reverse("pedagogie:mensuel_bulletin_pdf", args=[self.e1.matricule, 2026, 10])).status_code, 403)

    def test_la_page_de_l_eleve_pour_la_famille_et_pour_le_personnel(self):
        self.noter(self.e1, NOV, {"Dictée": 6})
        adresse = reverse("pedagogie:mensuel_eleve", args=[self.e1.matricule])
        famille = client_de(self.parent).get(adresse)
        self.assertEqual([l["mois"] for l in famille.context["lignes"]], [OCT, NOV])
        self.assertEqual(famille.context["voit_la_decision"], False)
        self.assertNotContains(famille, "Ne passe pas")
        self.assertEqual(famille.context["annuel"].moyenne_annuelle, D2("7.38"))  # (8,75 + 6) / 2 = 7,375, arrondi vers le haut
        personnel = client_de(self.t1).get(adresse)
        self.assertEqual(personnel.context["voit_la_decision"], True)
        self.assertContains(personnel, "Passe")
        self.assertEqual(client_de(self.parent_autre).get(adresse).status_code, 403)

    def test_la_page_de_l_eleve_d_un_autre_cycle_est_introuvable(self):
        e5 = self.e5  # en 9ème année
        self.assertEqual(client_de(self.fondateur).get(reverse("pedagogie:mensuel_eleve", args=[e5.matricule])).status_code, 404)

    def test_le_bulletin_trimestriel_renvoie_vers_les_bulletins_mensuels_au_premier_cycle(self):
        page = client_de(self.parent).get(reverse("pedagogie:bulletin_eleve", args=[self.e1.matricule]))
        self.assertContains(page, "le bulletin est mensuel")
        self.assertContains(page, reverse("pedagogie:mensuel_eleve", args=[self.e1.matricule]))
        autre_cycle = client_de(self.fondateur).get(reverse("pedagogie:bulletin_eleve", args=[self.e5.matricule]))
        self.assertNotContains(autre_cycle, "le bulletin est mensuel")


# ---------------------------------------------------------------------------------------------------------------------
# Cloisonnement entre écoles
# ---------------------------------------------------------------------------------------------------------------------

class CloisonnementTests(MensuelBase):
    def setUp(self):
        self.noter(self.e1, OCT, BULLETIN_DE_LA_PHOTO)
        ObservationMensuelle.objects.create(eleve=self.e1, classe=self.c6a, mois=OCT, observation="OBSERVATION-DE-A")

    def test_une_autre_ecole_n_atteint_rien(self):
        adresses = [
            reverse("pedagogie:mensuel_grille", args=[self.c6a.pk, 2026, 10]), reverse("pedagogie:mensuel_resultats", args=[self.c6a.pk, 2026, 10]),
            reverse("pedagogie:mensuel_annuel", args=[self.c6a.pk]), reverse("pedagogie:mensuel_disciplines", args=[self.c6a.pk]),
            reverse("pedagogie:mensuel_bulletins_classe_pdf", args=[self.c6a.pk, 2026, 10]),
            reverse("pedagogie:mensuel_eleve", args=[self.e1.matricule]), reverse("pedagogie:mensuel_bulletin_pdf", args=[self.e1.matricule, 2026, 10]),
        ]
        for compte in (self.fondateur_b, self.maitre_b):
            client = client_de(compte)
            for adresse in adresses:
                with self.subTest(role=compte.role, adresse=adresse):
                    self.assertIn(client.get(adresse).status_code, (403, 404))
                    self.assertIn(client.post(adresse, {"action": "habituelles"}).status_code, (403, 404, 405))
        self.assertEqual(NoteMensuelle.objects.count(), 14)

    def test_les_pages_d_une_autre_ecole_ne_montrent_rien_de_l_ecole_a(self):
        for compte in (self.fondateur_b, self.maitre_b):
            page = client_de(compte).get(reverse("pedagogie:mensuel_classes"))
            if page.status_code == 200:
                self.assertNotIn(self.c6a.pk, [ligne["classe"].pk for ligne in page.context["lignes"]])
                self.assertNotIn(self.e1.matricule, page.content.decode())

    def test_le_maitre_d_une_autre_ecole_ne_peut_pas_noter_dans_ma_classe(self):
        client = client_de(self.maitre_b)
        reponse = client.post(
            reverse("pedagogie:mensuel_grille", args=[self.c6a.pk, 2026, 10]), {f"n_{self.e2.pk}_{self.disc['Dictée'].pk}": "10"},
        )
        self.assertIn(reponse.status_code, (403, 404))
        self.assertFalse(NoteMensuelle.objects.filter(eleve=self.e2).exists())

    def test_le_maitre_d_ici_ne_note_que_les_eleves_de_sa_classe(self):
        grille = reverse("pedagogie:mensuel_grille", args=[self.c6a.pk, 2026, 10])
        client_de(self.t1).post(grille, {f"n_{self.e4.pk}_{self.disc['Dictée'].pk}": "10", f"n_{self.eleve_b.pk}_{self.disc['Dictée'].pk}": "10"})
        self.assertFalse(NoteMensuelle.objects.filter(eleve__in=[self.e4, self.eleve_b]).exists())
