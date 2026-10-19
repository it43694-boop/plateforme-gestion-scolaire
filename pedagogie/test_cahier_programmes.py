"""Cahier de textes (séances et devoirs, vus des familles) et suivi des programmes (avancement par chapitre, retards en tête)."""
import datetime

from django.core.exceptions import ValidationError
from django.urls import reverse

from comptes.arabisation import invalider
from comptes.models import JournalAudit, Utilisateur
from comptes.outils_test_arabe import client_en
from comptes.roles import Role
from comptes.traduction import restes_latins
from pedagogie.cahier import devoirs_des_familles, peut_lire_la_classe, peut_tenir
from pedagogie.models import ChapitreProgramme, SeanceCahier
from pedagogie.views_programmes import resume_du_programme
from scolarite.models import Affectation, AnneeScolaire, Inscription
from statistiques.test_education import EducationBase, creer_compte

D = datetime.date
AUJOURDHUI = D.today()


def jours(n):
    return AUJOURDHUI + datetime.timedelta(days=n)


class CahierBase(EducationBase):
    def setUp(self):
        self.maths_6a = Affectation.objects.get(enseignant=self.t1, classe=self.c6a)
        self.francais_6a = Affectation.objects.create(enseignant=self.t2, classe=self.c6a, matiere="Français")
        self.maths_6b = Affectation.objects.get(enseignant=self.t2, classe=self.c6b)
        self.url_cahier = reverse("pedagogie:cahier_affectation", args=[self.maths_6a.pk])
        self.url_programme = reverse("pedagogie:programme_affectation", args=[self.maths_6a.pk])

    def seance(self, affectation=None, jour=0, contenu="Les fractions", travail="Exercices 1 à 5", remise=1, **extra):
        return SeanceCahier.objects.create(
            affectation=affectation or self.maths_6a, date_seance=jours(jour), contenu=contenu, travail_a_faire=travail,
            date_remise=jours(remise) if remise is not None else None, **extra,
        )

    def chapitre(self, titre="Les fractions", pourcentage=40, date_prevue=None, affectation=None, **extra):
        return ChapitreProgramme.objects.create(
            affectation=affectation or self.maths_6a, titre=titre, pourcentage=pourcentage, date_prevue=date_prevue,
            ordre=ChapitreProgramme.objects.count() + 1, **extra,
        )


class SeanceTests(CahierBase):
    donnees = {"date_seance": AUJOURDHUI.isoformat(), "contenu": "  Les   fractions ", "travail_a_faire": "Exercices 1 à 5", "date_remise": jours(3).isoformat()}

    def test_l_enseignant_note_une_seance(self):
        self.client.force_login(self.t1)
        reponse = self.client.post(self.url_cahier, self.donnees)
        self.assertRedirects(reponse, self.url_cahier)
        seance = SeanceCahier.objects.get()
        self.assertEqual((seance.affectation, seance.contenu, seance.date_remise, seance.cree_par), (self.maths_6a, "Les fractions", jours(3), self.t1))
        self.assertTrue(JournalAudit.objects.filter(action="saisie_cahier_de_textes").exists())

    def test_une_seance_sans_devoir(self):
        self.client.force_login(self.t1)
        self.client.post(self.url_cahier, {**self.donnees, "travail_a_faire": "", "date_remise": ""})
        seance = SeanceCahier.objects.get()
        self.assertEqual((seance.travail_a_faire, seance.date_remise), ("", None))

    def test_les_erreurs_sont_expliquees_et_rien_n_est_cree(self):
        self.client.force_login(self.t1)
        for champs, erreur in (
            ({"date_seance": jours(2).isoformat()}, "pas de date future"),
            ({"date_remise": jours(-3).isoformat()}, "ne peut pas précéder"),
            ({"travail_a_faire": ""}, "Indiquez le travail à faire"),
            ({"contenu": "   "}, "obligatoire"),
        ):
            with self.subTest(erreur=erreur):
                self.assertContains(self.client.post(self.url_cahier, {**self.donnees, **champs}), erreur)
        self.assertEqual(SeanceCahier.objects.count(), 0)

    def test_qui_tient_le_cahier(self):
        for compte, code in (
            (self.t1, 200), (self.fondateur, 200), (self.dir_1er, 200),  # le directeur de cycle ne peut qu'en lecture : voir plus bas
            (self.t2, 403), (self.t3, 404), (self.parent, 403), (self.e1, 403), (self.comptable, 403),  # t3 : classe hors de son périmètre, introuvable
        ):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertEqual(self.client.get(self.url_cahier).status_code, code if compte != self.dir_1er else 403)

    def test_la_direction_tient_aussi_le_cahier_et_une_autre_ecole_ne_voit_rien(self):
        self.client.force_login(self.fondateur)
        self.assertEqual(self.client.post(self.url_cahier, self.donnees).status_code, 302)
        self.assertEqual(SeanceCahier.objects.get().cree_par, self.fondateur)
        self.client.force_login(self.fondateur_b)
        self.assertEqual(self.client.get(self.url_cahier).status_code, 404)

    def test_un_enseignant_ne_note_que_dans_ses_propres_matieres(self):
        self.client.force_login(self.t1)
        reponse = self.client.post(reverse("pedagogie:cahier_affectation", args=[self.francais_6a.pk]), self.donnees)
        self.assertEqual(reponse.status_code, 403)
        self.assertEqual(SeanceCahier.objects.count(), 0)

    def test_modifier_et_supprimer(self):
        seance = self.seance()
        self.client.force_login(self.t1)
        self.assertEqual(self.client.post(reverse("pedagogie:modifier_seance", args=[seance.pk]), {**self.donnees, "contenu": "Les décimaux"}).status_code, 302)
        seance.refresh_from_db()
        self.assertEqual(seance.contenu, "Les décimaux")
        self.assertEqual(self.client.get(reverse("pedagogie:supprimer_seance", args=[seance.pk])).status_code, 405)
        self.client.post(reverse("pedagogie:supprimer_seance", args=[seance.pk]))
        self.assertFalse(SeanceCahier.objects.exists())
        actions = list(JournalAudit.objects.values_list("action", flat=True))
        self.assertIn("modification_cahier_de_textes", actions)
        self.assertIn("suppression_cahier_de_textes", actions)

    def test_on_ne_touche_pas_a_la_seance_d_un_collegue(self):
        seance = self.seance(affectation=self.francais_6a)
        self.client.force_login(self.t1)
        self.assertEqual(self.client.get(reverse("pedagogie:modifier_seance", args=[seance.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("pedagogie:supprimer_seance", args=[seance.pk])).status_code, 403)
        self.assertTrue(SeanceCahier.objects.filter(pk=seance.pk).exists())

    def test_une_annee_archivee_est_en_lecture_seule(self):
        seance = self.seance()
        AnneeScolaire.objects.filter(pk=self.annee.pk).update(est_archivee=True)
        self.client.force_login(self.t1)
        self.assertEqual(self.client.post(self.url_cahier, self.donnees).status_code, 403)
        self.assertEqual(self.client.post(reverse("pedagogie:supprimer_seance", args=[seance.pk])).status_code, 403)
        self.assertContains(self.client.get(self.url_cahier), "lecture seule")

    def test_la_validation_du_modele(self):
        for erreur in (
            SeanceCahier(affectation=self.maths_6a, date_seance=jours(1), contenu="x"),
            SeanceCahier(affectation=self.maths_6a, date_seance=jours(0), contenu="x", travail_a_faire="y", date_remise=jours(-1)),
            SeanceCahier(affectation=self.maths_6a, date_seance=jours(0), contenu="x", travail_a_faire="", date_remise=jours(1)),
        ):
            with self.assertRaises(ValidationError):
                erreur.full_clean()

    def test_les_droits_en_python(self):
        self.assertTrue(peut_tenir(self.t1, self.maths_6a))
        self.assertFalse(peut_tenir(self.t1, self.francais_6a))
        self.assertTrue(peut_tenir(self.fondateur, self.maths_6a))
        self.assertFalse(peut_tenir(self.fondateur_b, self.maths_6a))  # une autre école
        self.assertFalse(peut_tenir(self.dir_1er, self.maths_6a))


class CahierDeClasseTests(CahierBase):
    def test_les_enseignants_de_la_classe_et_la_supervision_lisent_toutes_les_matieres(self):
        self.seance(self.maths_6a, contenu="Contenu maths")
        self.seance(self.francais_6a, contenu="Contenu français")
        url = reverse("pedagogie:cahier_classe", args=[self.c6a.pk])
        for compte in (self.t1, self.t2, self.fondateur, self.dir_1er):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                page = self.client.get(url)
                self.assertContains(page, "Contenu maths")
                self.assertContains(page, "Contenu français")

    def test_les_autres_ne_lisent_pas(self):
        url = reverse("pedagogie:cahier_classe", args=[self.c6a.pk])
        for compte in (self.t3, self.parent, self.e1, self.comptable):  # t3 n'enseigne pas en 6A
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertEqual(self.client.get(url).status_code, 404 if compte == self.t3 else 403)  # t3 : une classe hors de son périmètre est introuvable
        self.client.force_login(self.fondateur_b)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.dir_1er)  # 9A n'est pas de son cycle
        self.assertEqual(self.client.get(reverse("pedagogie:cahier_classe", args=[self.c9a.pk])).status_code, 404)

    def test_le_filtre_par_matiere(self):
        self.seance(self.maths_6a, contenu="Contenu maths")
        self.seance(self.francais_6a, contenu="Contenu français")
        self.client.force_login(self.fondateur)
        page = self.client.get(reverse("pedagogie:cahier_classe", args=[self.c6a.pk]), {"affectation": self.francais_6a.pk})
        self.assertContains(page, "Contenu français")
        self.assertNotContains(page, "Contenu maths")
        self.assertEqual(self.client.get(reverse("pedagogie:cahier_classe", args=[self.c6a.pk]), {"affectation": "abc"}).status_code, 200)

    def test_les_droits_en_python(self):
        self.assertTrue(peut_lire_la_classe(self.t1, self.c6a))
        self.assertFalse(peut_lire_la_classe(self.t3, self.c6a))
        self.assertFalse(peut_lire_la_classe(self.parent, self.c6a))


class DevoirsDesFamillesTests(CahierBase):
    def test_le_parent_voit_les_devoirs_de_la_classe_de_son_enfant(self):
        proche = self.seance(contenu="Séance proche", travail="Devoir proche", remise=2)
        lointain = self.seance(self.francais_6a, contenu="Séance lointaine", travail="Devoir lointain", remise=9)
        self.seance(self.maths_6b, contenu="Une autre classe", travail="Devoir de la 6B", remise=2)  # pas la classe de e1
        self.client.force_login(self.parent)
        reponse = self.client.get(reverse("pedagogie:devoirs"))
        self.assertEqual(reponse.status_code, 200)
        famille, = reponse.context["familles"]
        self.assertEqual((famille["eleve"], famille["classe"]), (self.e1, self.c6a))
        self.assertEqual(famille["a_rendre"], [proche, lointain])  # les plus proches d'abord
        self.assertNotContains(reponse, "Devoir de la 6B")
        self.assertContains(reponse, "Devoir lointain")

    def test_seuls_les_devoirs_a_venir_et_les_seances_recentes(self):
        self.seance(contenu="Passé", travail="Devoir passé", remise=-1)  # la date de remise est passée
        self.seance(jour=-30, contenu="Très ancienne", travail="", remise=None)  # hors des deux semaines
        self.seance(contenu="Sans devoir", travail="", remise=None)
        aujourdhui = self.seance(contenu="Pour aujourd'hui", travail="Devoir du jour", remise=0)
        famille, = devoirs_des_familles(self.parent)
        self.assertEqual(famille["a_rendre"], [aujourdhui])  # remise aujourd'hui : encore à rendre
        titres = {s.contenu for s in famille["recentes"]}
        self.assertIn("Sans devoir", titres)
        self.assertNotIn("Très ancienne", titres)

    def test_l_eleve_voit_les_siens_et_un_autre_parent_n_a_rien(self):
        self.seance(travail="Devoir de la 6A", remise=2)
        self.client.force_login(self.e1)
        self.assertContains(self.client.get(reverse("pedagogie:devoirs")), "Devoir de la 6A")
        autre = creer_compte(Role.PARENT, "autre@cahier.test", self.ecole, telephone="70150003")
        self.client.force_login(autre)
        reponse = self.client.get(reverse("pedagogie:devoirs"))
        self.assertEqual(reponse.context["familles"], [])
        self.assertNotContains(reponse, "Devoir de la 6A")

    def test_deux_enfants_deux_classes(self):
        self.e4.parents_lies.add(self.parent)  # e4 est en 6B
        self.seance(travail="Devoir 6A", remise=2)
        self.seance(self.maths_6b, travail="Devoir 6B", remise=2)
        familles = devoirs_des_familles(self.parent)
        self.assertEqual({f["eleve"] for f in familles}, {self.e1, self.e4})
        pour = {f["classe"]: [s.travail_a_faire for s in f["a_rendre"]] for f in familles}
        self.assertEqual(pour, {self.c6a: ["Devoir 6A"], self.c6b: ["Devoir 6B"]})

    def test_un_enfant_sans_inscription_en_cours_est_ignore(self):
        Inscription.objects.filter(eleve=self.e1).update(statut=Inscription.Statut.ABANDON)
        self.assertEqual(devoirs_des_familles(self.parent), [])
        self.client.force_login(self.parent)
        self.assertContains(self.client.get(reverse("pedagogie:devoirs")), "pas de cahier de textes")

    def test_la_page_est_reservee_aux_familles(self):
        for compte in (self.t1, self.fondateur, self.comptable, self.secretaire):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertEqual(self.client.get(reverse("pedagogie:devoirs")).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("pedagogie:devoirs")).status_code, 302)

    def test_les_liens(self):
        url = reverse("pedagogie:devoirs")
        for compte, attendu in ((self.parent, True), (self.e1, True), (self.t1, False), (self.fondateur, False)):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                page = self.client.get(reverse("comptes:redirection_tableau_de_bord"), follow=True).content.decode()
                self.assertEqual(url in page, attendu)
        self.client.force_login(self.parent)
        self.assertIn(url, self.client.get(reverse("comptes:portail_parent")).content.decode())
        self.client.force_login(self.t1)
        page = self.client.get(reverse("pedagogie:mes_classes")).content.decode()
        self.assertIn(self.url_cahier, page)
        self.assertIn(self.url_programme, page)


class ProgrammeTests(CahierBase):
    donnees = {"titre": "  Les   fractions ", "date_prevue": "", "pourcentage": 40, "difficultes": "Les dénominateurs"}

    def test_l_enseignant_ajoute_des_chapitres_dans_l_ordre(self):
        self.client.force_login(self.t1)
        self.assertRedirects(self.client.post(self.url_programme, self.donnees), self.url_programme)
        self.client.post(self.url_programme, {**self.donnees, "titre": "Les décimaux", "pourcentage": 0})
        premier, second = ChapitreProgramme.objects.order_by("ordre")
        self.assertEqual((premier.titre, premier.pourcentage, premier.ordre, second.ordre), ("Les fractions", 40, 1, 2))
        self.assertTrue(JournalAudit.objects.filter(action="ajout_chapitre_programme").exists())

    def test_les_erreurs_sont_expliquees(self):
        self.client.force_login(self.t1)
        for champs, erreur in (({"pourcentage": 101}, "inférieure ou égale à 100"), ({"pourcentage": -1}, "supérieure ou égale à 0"), ({"titre": ""}, "obligatoire")):
            with self.subTest(erreur=erreur):
                self.assertContains(self.client.post(self.url_programme, {**self.donnees, **champs}), erreur)
        self.assertEqual(ChapitreProgramme.objects.count(), 0)

    def test_un_chapitre_est_en_retard_s_il_est_depasse_et_pas_termine(self):
        self.assertTrue(self.chapitre(pourcentage=80, date_prevue=jours(-1)).en_retard)
        self.assertFalse(self.chapitre(pourcentage=100, date_prevue=jours(-10)).en_retard)  # terminé
        self.assertFalse(self.chapitre(pourcentage=10, date_prevue=jours(5)).en_retard)  # pas encore l'heure
        self.assertFalse(self.chapitre(pourcentage=10).en_retard)  # pas de date prévue
        self.assertFalse(self.chapitre(pourcentage=10, date_prevue=AUJOURDHUI).en_retard)  # le jour même : encore à temps

    def test_le_resume(self):
        self.assertEqual(resume_du_programme([]), {"nombre": 0, "avancement": 0, "en_retard": 0})
        chapitres = [self.chapitre(pourcentage=100), self.chapitre(pourcentage=50, date_prevue=jours(-2)), self.chapitre(pourcentage=0)]
        self.assertEqual(resume_du_programme(chapitres), {"nombre": 3, "avancement": 50, "en_retard": 1})

    def test_le_pourcentage_est_borne_en_base(self):
        from django.db import IntegrityError, transaction

        with self.assertRaises((IntegrityError, ValidationError)), transaction.atomic():
            ChapitreProgramme(affectation=self.maths_6a, titre="x", pourcentage=101).full_clean()
            ChapitreProgramme.objects.create(affectation=self.maths_6a, titre="x", pourcentage=101)

    def test_modifier_et_supprimer_un_chapitre(self):
        chapitre = self.chapitre()
        self.client.force_login(self.t1)
        self.client.post(reverse("pedagogie:modifier_chapitre", args=[chapitre.pk]), {**self.donnees, "pourcentage": 100})
        chapitre.refresh_from_db()
        self.assertEqual(chapitre.pourcentage, 100)
        self.assertEqual(self.client.get(reverse("pedagogie:supprimer_chapitre", args=[chapitre.pk])).status_code, 405)
        self.client.post(reverse("pedagogie:supprimer_chapitre", args=[chapitre.pk]))
        self.assertFalse(ChapitreProgramme.objects.exists())

    def test_la_supervision_lit_mais_ne_modifie_pas(self):
        chapitre = self.chapitre()
        self.client.force_login(self.dir_1er)
        page = self.client.get(self.url_programme)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Vous consultez ce programme")
        self.assertNotContains(page, "Ajouter un chapitre")
        self.assertEqual(self.client.post(self.url_programme, self.donnees).status_code, 403)
        self.assertEqual(self.client.post(reverse("pedagogie:supprimer_chapitre", args=[chapitre.pk])).status_code, 403)
        self.assertEqual(ChapitreProgramme.objects.count(), 1)

    def test_les_autres_n_ont_pas_acces(self):
        for compte in (self.t2, self.t3, self.parent, self.e1, self.comptable):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertEqual(self.client.get(self.url_programme).status_code, 404 if compte == self.t3 else 403)  # t3 : classe hors de son périmètre
        self.client.force_login(self.fondateur_b)
        self.assertEqual(self.client.get(self.url_programme).status_code, 404)

    def test_une_annee_archivee_est_en_lecture_seule(self):
        chapitre = self.chapitre()
        AnneeScolaire.objects.filter(pk=self.annee.pk).update(est_archivee=True)
        self.client.force_login(self.t1)
        self.assertEqual(self.client.post(self.url_programme, self.donnees).status_code, 403)
        self.assertEqual(self.client.post(reverse("pedagogie:modifier_chapitre", args=[chapitre.pk]), self.donnees).status_code, 403)
        self.assertContains(self.client.get(self.url_programme), "lecture seule")


class VueDEnsembleDesProgrammesTests(CahierBase):
    def setUp(self):
        super().setUp()
        self.url = reverse("pedagogie:avancement_programmes")
        self.chapitre("Fractions", 90, affectation=self.maths_6a)
        self.chapitre("Géométrie", 20, date_prevue=jours(-5), affectation=self.francais_6a)  # en retard
        self.chapitre("Grammaire", 10, date_prevue=jours(-1), affectation=self.francais_6a)  # en retard aussi
        self.chapitre("Algèbre", 30, affectation=self.maths_6b)

    def test_les_retards_en_tete_puis_les_moins_avances_puis_les_matieres_sans_programme(self):
        self.client.force_login(self.fondateur)
        lignes = self.client.get(self.url).context["lignes"]
        ordre = [(l["affectation"].classe.nom, l["affectation"].matiere, l["en_retard"]) for l in lignes]
        self.assertEqual(ordre[0], ("6A", "Français", 2))  # deux chapitres en retard : en tête
        sans_programme = [l for l in lignes if l["nombre"] == 0]
        self.assertTrue(sans_programme)
        self.assertEqual(lignes[-len(sans_programme):], sans_programme)  # les matières sans programme à la fin
        avances = [l["avancement"] for l in lignes if l["nombre"] and not l["en_retard"]]
        self.assertEqual(avances, sorted(avances))

    def test_les_totaux(self):
        self.client.force_login(self.fondateur)
        page = self.client.get(self.url)
        self.assertEqual(page.context["total_en_retard"], 2)
        francais = next(l for l in page.context["lignes"] if l["affectation"] == self.francais_6a)
        self.assertEqual((francais["nombre"], francais["avancement"], francais["en_retard"]), (2, 15, 2))

    def test_un_directeur_de_cycle_ne_voit_que_son_cycle(self):
        self.client.force_login(self.dir_1er)
        classes = {l["affectation"].classe.nom for l in self.client.get(self.url).context["lignes"]}
        self.assertTrue(classes <= {"6A", "6B", "5A"})  # les classes du 1er cycle (la 5A est celle de l'année passée)
        self.assertTrue({"6A", "6B"} <= classes)
        self.assertFalse(classes & {"9A", "TSE", "CAP-E"})

    def test_les_annees_archivees_n_y_figurent_pas(self):
        AnneeScolaire.objects.filter(pk__in=[self.annee.pk, self.precedente.pk]).update(est_archivee=True)
        self.client.force_login(self.fondateur)
        self.assertEqual(self.client.get(self.url).context["lignes"], [])

    def test_les_droits(self):
        for compte, code in ((self.fondateur, 200), (self.dir_1er, 200), (self.comptable, 403), (self.t1, 403), (self.parent, 403), (self.e1, 403)):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertEqual(self.client.get(self.url).status_code, code)
        self.client.force_login(self.fondateur_b)
        self.assertEqual(self.client.get(self.url).context["lignes"], [])

    def test_les_liens_du_menu_et_du_suivi_des_cours(self):
        self.client.force_login(self.fondateur)
        page = self.client.get(reverse("comptes:redirection_tableau_de_bord"), follow=True).content.decode()
        self.assertIn(self.url, page)
        suivi = self.client.get(reverse("pedagogie:suivi_des_cours")).content.decode()
        self.assertIn(self.url, suivi)
        self.assertIn(reverse("pedagogie:cahier_classe", args=[self.c6a.pk]), suivi)

    def test_le_nombre_de_requetes_ne_depend_pas_du_nombre_de_matieres(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.client.force_login(self.fondateur)
        with CaptureQueriesContext(connection) as avant:
            self.client.get(self.url)
        for numero in range(8):
            affectation = Affectation.objects.create(enseignant=self.t3, classe=self.ctse, matiere=f"Matière {numero}")
            self.chapitre(f"Chapitre {numero}", 10 * numero, affectation=affectation)
        with CaptureQueriesContext(connection) as apres:
            self.client.get(self.url)
        self.assertLessEqual(len(apres.captured_queries), len(avant.captured_queries) + 1)


class CahierEtProgrammesEnArabeTests(CahierBase):
    def test_les_pages_sont_en_arabe_pur(self):
        Utilisateur.objects.filter(pk=self.t1.pk).update(prenom="Mamadou", nom="Keita", prenom_ar="مامادو", nom_ar="كيتا")
        invalider(self.ecole.pk)
        self.seance(contenu="الكسور", travail="تمارين من ١ إلى ٥")
        self.chapitre("الكسور", 40, date_prevue=jours(-1))
        pages = [
            (self.t1, self.url_cahier), (self.t1, self.url_programme), (self.t1, reverse("pedagogie:mes_classes")),
            (self.fondateur, reverse("pedagogie:cahier_classe", args=[self.c6a.pk])), (self.fondateur, reverse("pedagogie:avancement_programmes")),
            (self.parent, reverse("pedagogie:devoirs")),
        ]
        for compte, adresse in pages:
            reponse = client_en(compte, "ar").get(adresse)
            self.assertEqual(reponse.status_code, 200, adresse)
            with self.subTest(page=adresse):
                self.assertEqual([t for t in restes_latins(reponse.content.decode()) if t != "Français"], [])
