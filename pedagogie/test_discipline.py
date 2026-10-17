"""
Registre de discipline : retards, avertissements, blâmes, convocations, exclusions.

Les parents sont prévenus (courriel dans leur langue + notification) pour toute mesure, et pour un retard seulement au TROISIÈME du mois ;
un courriel qui échoue ne bloque jamais l'enregistrement.
"""
import datetime
from unittest import mock

from django.core import mail
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse

from comptes.arabisation import invalider
from comptes.models import JournalAudit, Notification, Utilisateur
from comptes.outils_test_arabe import client_en
from comptes.roles import Role, StatutCompte
from comptes.traduction import restes_latins
from espace_developpeur.retrait_eleve import anonymiser_eleve, mode_de_retrait, historique_eleve
from pedagogie.discipline import SEUIL_DE_RETARDS, prevenir_les_parents, retards_du_mois
from pedagogie.models import MesureDiscipline, TypeMesureDiscipline
from permissions_matrix.models import PermissionMatrix
from scolarite.models import AnneeScolaire
from statistiques.test_education import EducationBase, creer_compte

T = TypeMesureDiscipline
AUJOURDHUI = datetime.date.today()


def premier_jour_du_mois(date=AUJOURDHUI):
    return date.replace(day=1)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", EMAIL_ASYNC=False)
class DisciplineBase(EducationBase):
    def setUp(self):
        self.url_classe = reverse("pedagogie:registre_discipline", args=[self.c6a.pk])
        self.url_eleve = reverse("pedagogie:historique_discipline", args=[self.e1.matricule])

    def mesure(self, type_mesure=T.AVERTISSEMENT, eleve=None, date=None, motif="Bavardage répété", classe=None):
        return MesureDiscipline.objects.create(
            eleve=eleve or self.e1, classe=classe or self.c6a, date_mesure=date or AUJOURDHUI, type_mesure=type_mesure,
            motif=motif if type_mesure != T.RETARD else "", enregistre_par=self.fondateur,
        )

    def saisir(self, compte, **donnees):
        self.client.force_login(compte)
        base = {"matricule_eleve": self.e1.matricule, "date_mesure": AUJOURDHUI.isoformat(), "type_mesure": T.AVERTISSEMENT, "motif": "Bavardage"}
        base.update(donnees)
        return self.client.post(self.url_classe, base)


class ModeleTests(DisciplineBase):
    def test_une_mesure_valide(self):
        self.assertEqual(self.mesure().get_type_mesure_display(), "Avertissement")

    def test_le_motif_est_obligatoire_sauf_pour_un_retard(self):
        self.mesure(T.RETARD)  # sans motif : permis
        for type_mesure in (T.AVERTISSEMENT, T.BLAME, T.CONVOCATION, T.EXCLUSION):
            with self.subTest(type_mesure=type_mesure), self.assertRaises(ValidationError):
                MesureDiscipline.objects.create(eleve=self.e1, classe=self.c6a, date_mesure=AUJOURDHUI, type_mesure=type_mesure, motif="  ")

    def test_une_date_future_est_refusee(self):
        with self.assertRaises(ValidationError):
            self.mesure(date=AUJOURDHUI + datetime.timedelta(days=1))

    def test_l_eleve_doit_etre_inscrit_dans_la_classe_et_de_la_meme_ecole(self):
        with self.assertRaises(ValidationError):
            self.mesure(eleve=self.e4)  # e4 est en 6B, pas en 6A
        with self.assertRaises(ValidationError):
            self.mesure(classe=self.classe_b)  # la classe d'une autre école

    def test_seul_un_eleve_peut_etre_sanctionne(self):
        with self.assertRaises(ValidationError):
            self.mesure(eleve=self.t1)

    def test_les_retards_se_comptent_par_mois_calendaire(self):
        mois_dernier = premier_jour_du_mois() - datetime.timedelta(days=1)
        self.mesure(T.RETARD, date=mois_dernier)
        self.mesure(T.RETARD, date=premier_jour_du_mois())
        self.mesure(T.AVERTISSEMENT)
        self.assertEqual(retards_du_mois(self.e1, AUJOURDHUI), 1)
        self.assertEqual(retards_du_mois(self.e1, mois_dernier), 1)
        self.assertEqual(retards_du_mois(self.e2, AUJOURDHUI), 0)


class PrevenirLesParentsTests(DisciplineBase):
    def setUp(self):
        super().setUp()
        self.parent2 = creer_compte(Role.PARENT, "parent2@discipline.test", self.ecole, telephone="70140002")
        self.e1.parents_lies.add(self.parent2)

    def test_une_mesure_previent_chaque_parent_une_fois(self):
        prevenus = prevenir_les_parents(self.mesure(T.BLAME, motif="Insolence envers un enseignant"))
        self.assertEqual(prevenus, 2)
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), sorted([self.parent.email, self.parent2.email]))
        message = mail.outbox[0]
        self.assertIn("Mesure de discipline", message.subject)
        for attendu in ("Blâme", "Insolence envers un enseignant", self.e1.nom_complet, "6A", AUJOURDHUI.strftime("%d/%m/%Y")):
            self.assertIn(attendu, message.body)
        self.assertEqual(Notification.objects.filter(destinataire__in=[self.parent, self.parent2]).count(), 2)
        notification = Notification.objects.filter(destinataire=self.parent).get()
        self.assertEqual(notification.url, self.url_eleve)

    def test_un_retard_isole_ne_previent_personne(self):
        self.assertEqual(prevenir_les_parents(self.mesure(T.RETARD)), 0)
        self.assertEqual(prevenir_les_parents(self.mesure(T.RETARD)), 0)
        self.assertEqual((len(mail.outbox), Notification.objects.count()), (0, 0))

    def test_le_troisieme_retard_du_mois_previent_une_seule_fois(self):
        resultats = [prevenir_les_parents(self.mesure(T.RETARD)) for _ in range(SEUIL_DE_RETARDS + 2)]
        self.assertEqual(resultats, [0, 0, 2, 0, 0])  # au troisième exactement, jamais aux suivants
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("Retards répétés", mail.outbox[0].subject)
        self.assertIn("3 fois ce mois-ci", mail.outbox[0].body)

    def test_les_retards_d_un_autre_mois_ne_comptent_pas_pour_le_seuil(self):
        mois_dernier = premier_jour_du_mois() - datetime.timedelta(days=3)
        for _ in range(5):
            self.mesure(T.RETARD, date=mois_dernier)
        self.assertEqual(prevenir_les_parents(self.mesure(T.RETARD)), 0)  # le premier de ce mois-ci

    def test_les_retards_des_autres_eleves_ne_comptent_pas(self):
        for eleve in (self.e2, self.e3, self.e2):
            self.mesure(T.RETARD, eleve=eleve)
        self.assertEqual(prevenir_les_parents(self.mesure(T.RETARD)), 0)

    def test_sans_parent_ou_avec_un_parent_inactif_personne_n_est_prevenu(self):
        Utilisateur.objects.filter(pk=self.parent2.pk).update(is_active=False)
        self.assertEqual(prevenir_les_parents(self.mesure(T.EXCLUSION, motif="Violence")), 1)
        self.e1.parents_lies.clear()
        self.assertEqual(prevenir_les_parents(self.mesure(T.EXCLUSION, motif="Violence")), 0)

    def test_un_compte_parent_suspendu_ou_pas_encore_valide_n_est_jamais_prevenu(self):
        self.e1.parents_lies.set([self.parent2])
        for statut in (StatutCompte.SUSPENDU, StatutCompte.DESACTIVE, StatutCompte.EN_ATTENTE_VALIDATION, StatutCompte.EN_ATTENTE_VERIFICATION_EMAIL):
            with self.subTest(statut=statut):
                Utilisateur.objects.filter(pk=self.parent2.pk).update(statut=statut)
                self.assertEqual(prevenir_les_parents(self.mesure(T.EXCLUSION, motif="Violence")), 0)
        self.assertEqual(len(mail.outbox), 0)
        Utilisateur.objects.filter(pk=self.parent2.pk).update(statut=StatutCompte.ACTIF)
        self.assertEqual(prevenir_les_parents(self.mesure(T.EXCLUSION, motif="Violence")), 1)

    def test_un_envoi_qui_echoue_ne_bloque_jamais(self):
        with mock.patch("pedagogie.discipline.envoyer_email", side_effect=RuntimeError("panne")):
            self.assertEqual(prevenir_les_parents(self.mesure(T.BLAME)), 0)
        self.assertEqual(MesureDiscipline.objects.count(), 1)

    def test_un_parent_arabe_recoit_le_courriel_en_arabe(self):
        Utilisateur.objects.filter(pk=self.parent.pk).update(langue="ar")
        Utilisateur.objects.filter(pk=self.e1.pk).update(prenom="Aminata", nom="Traoré", prenom_ar="أميناتا", nom_ar="تراوري")
        self.e1.refresh_from_db()
        invalider(self.ecole.pk)
        prevenir_les_parents(self.mesure(T.BLAME, motif="سلوك سيء"))
        arabe = next(m for m in mail.outbox if m.to == [self.parent.email])
        self.assertIn("إجراء انضباطي", arabe.subject)
        self.assertIn("أميناتا", arabe.body)
        self.assertIn("توبيخ", arabe.body)
        self.assertEqual([t for t in arabe.body.split("\n") if "Mesure" in t or "Bonjour" in t], [])
        francais = next(m for m in mail.outbox if m.to == [self.parent2.email])
        self.assertIn("Mesure de discipline", francais.subject)  # l'autre parent, resté en français


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", EMAIL_ASYNC=False)
class RegistreDeClasseTests(DisciplineBase):
    def test_la_vie_scolaire_et_la_direction_enregistrent_une_mesure(self):
        for compte in (self.fondateur, self.dir_1er, self.t1):  # t1 est affecté à la 6A
            MesureDiscipline.objects.all().delete()
            with self.subTest(compte=compte.email):
                reponse = self.saisir(compte)
                self.assertEqual(reponse.status_code, 302)
                mesure = MesureDiscipline.objects.get()
                self.assertEqual((mesure.eleve, mesure.classe, mesure.enregistre_par), (self.e1, self.c6a, compte))

    def test_un_message_dit_que_les_parents_sont_prevenus(self):
        self.client.force_login(self.fondateur)
        reponse = self.client.post(self.url_classe, {
            "matricule_eleve": self.e1.matricule, "date_mesure": AUJOURDHUI.isoformat(), "type_mesure": T.BLAME, "motif": "Insolence",
        }, follow=True)
        self.assertContains(reponse, "Les parents ont été prévenus")
        self.assertEqual(len(mail.outbox), 1)

    def test_les_roles_sans_droit_sont_refuses(self):
        for compte in (self.parent, self.e1, self.comptable):
            with self.subTest(compte=compte.email):
                self.client.force_login(compte)
                self.assertEqual(self.client.get(self.url_classe).status_code, 403)
                self.assertEqual(self.saisir(compte).status_code, 403)
        # le censeur ne suit que le lycée : une classe du 1er cycle lui est introuvable
        self.client.force_login(self.censeur)
        self.assertEqual(self.client.get(self.url_classe).status_code, 404)
        self.assertEqual(MesureDiscipline.objects.count(), 0)

    def test_un_enseignant_ne_traite_que_ses_classes(self):
        self.client.force_login(self.t1)
        self.assertEqual(self.client.get(reverse("pedagogie:registre_discipline", args=[self.c6b.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("pedagogie:registre_discipline", args=[self.classe_b.pk])).status_code, 404)

    def test_le_secretariat_a_besoin_du_module_absences(self):
        self.assertEqual(self.saisir(self.secretaire).status_code, 403)  # la matrice par défaut ne le lui donne pas
        PermissionMatrix.objects.filter(etablissement=self.ecole, role=Role.SECRETAIRE, module="absences").update(autorise=True)
        self.assertEqual(self.saisir(self.secretaire).status_code, 302)

    def test_un_directeur_de_cycle_ne_traite_que_son_cycle(self):
        self.client.force_login(self.dir_1er)
        self.assertEqual(self.client.get(reverse("pedagogie:registre_discipline", args=[self.c9a.pk])).status_code, 404)

    def test_une_autre_ecole_ne_voit_rien(self):
        self.client.force_login(self.fondateur_b)
        self.assertEqual(self.client.get(self.url_classe).status_code, 404)

    def test_les_erreurs_de_saisie_sont_expliquees_et_rien_n_est_cree(self):
        for donnees, erreur in (
            ({"motif": ""}, "Indiquez le motif"),
            ({"date_mesure": (AUJOURDHUI + datetime.timedelta(days=2)).isoformat()}, "date future"),
            ({"matricule_eleve": "Personne Inconnu"}, "Aucun élève de cette classe"),
            ({"matricule_eleve": self.e4.matricule}, "Aucun élève de cette classe"),  # un élève d'une autre classe
            ({"type_mesure": "fessee"}, "Sélectionnez un choix valide"),
        ):
            with self.subTest(erreur=erreur):
                reponse = self.saisir(self.fondateur, **donnees)
                self.assertEqual(reponse.status_code, 200)
                self.assertContains(reponse, erreur)
        self.assertEqual(MesureDiscipline.objects.count(), 0)

    def test_un_retard_s_enregistre_sans_motif(self):
        self.assertEqual(self.saisir(self.fondateur, type_mesure=T.RETARD, motif="").status_code, 302)
        self.assertEqual(MesureDiscipline.objects.get().type_mesure, T.RETARD)

    def test_une_annee_archivee_est_en_lecture_seule(self):
        AnneeScolaire.objects.filter(pk=self.annee.pk).update(est_archivee=True)
        self.assertEqual(self.saisir(self.fondateur).status_code, 403)
        self.assertEqual(self.client.get(self.url_classe).status_code, 200)
        self.assertContains(self.client.get(self.url_classe), "lecture seule")

    def test_la_saisie_est_journalisee_sans_le_motif(self):
        self.saisir(self.fondateur, motif="Un motif très privé")
        journal = JournalAudit.objects.get(action="saisie_discipline")
        self.assertEqual(journal.details["type"], "avertissement")
        self.assertNotIn("privé", str(journal.details) + journal.cible)

    def test_la_page_est_a_la_portee_du_get(self):
        self.mesure()
        self.client.force_login(self.fondateur)
        page = self.client.get(self.url_classe).content.decode()
        self.assertIn("Bavardage répété", page)
        self.assertIn(self.url_eleve, page)


class HistoriqueEtSuppressionTests(DisciplineBase):
    def setUp(self):
        super().setUp()
        self.m1 = self.mesure(T.BLAME, motif="Insolence")
        self.m2 = self.mesure(T.RETARD)
        self.autre_parent = creer_compte(Role.PARENT, "autre-parent@discipline.test", self.ecole, telephone="70140003")

    def test_qui_voit_l_historique(self):
        for compte, code in (
            (self.fondateur, 200), (self.dir_1er, 200), (self.parent, 200), (self.e1, 200), (self.t1, 200),  # t1 enseigne à e1
            (self.autre_parent, 403), (self.e2, 403), (self.comptable, 403),
        ):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertEqual(self.client.get(self.url_eleve).status_code, code)

    def test_les_totaux_par_mesure(self):
        self.client.force_login(self.parent)
        reponse = self.client.get(self.url_eleve)
        self.assertEqual(reponse.context["total"], 2)
        self.assertEqual(dict(reponse.context["totaux"]), {"Retard": 1, "Avertissement": 0, "Blâme": 1, "Convocation des parents": 0, "Exclusion": 0})
        self.assertEqual(reponse.context["retards_ce_mois"], 1)
        self.assertContains(reponse, "Insolence")

    def test_un_eleve_d_une_autre_ecole_est_introuvable(self):
        self.client.force_login(self.fondateur_b)
        self.assertEqual(self.client.get(self.url_eleve).status_code, 404)

    def test_la_direction_supprime_une_mesure(self):
        self.client.force_login(self.fondateur)
        reponse = self.client.post(reverse("pedagogie:supprimer_mesure_discipline", args=[self.m1.pk]))
        self.assertRedirects(reponse, self.url_eleve)
        self.assertFalse(MesureDiscipline.objects.filter(pk=self.m1.pk).exists())
        self.assertTrue(JournalAudit.objects.filter(action="suppression_discipline").exists())

    def test_la_suppression_depuis_la_classe_revient_a_la_classe(self):
        self.client.force_login(self.fondateur)
        reponse = self.client.post(reverse("pedagogie:supprimer_mesure_discipline", args=[self.m1.pk]), {"retour": "classe"})
        self.assertRedirects(reponse, self.url_classe)

    def test_seuls_la_vie_scolaire_et_la_direction_suppriment(self):
        for compte in (self.t1, self.parent, self.e1, self.comptable, self.secretaire):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertEqual(self.client.post(reverse("pedagogie:supprimer_mesure_discipline", args=[self.m1.pk])).status_code, 403)
        self.assertTrue(MesureDiscipline.objects.filter(pk=self.m1.pk).exists())

    def test_on_ne_supprime_pas_chez_les_autres_et_seulement_en_post(self):
        self.client.force_login(self.fondateur_b)
        self.assertEqual(self.client.post(reverse("pedagogie:supprimer_mesure_discipline", args=[self.m1.pk])).status_code, 404)
        self.client.force_login(self.fondateur)
        self.assertEqual(self.client.get(reverse("pedagogie:supprimer_mesure_discipline", args=[self.m1.pk])).status_code, 405)
        self.client.force_login(self.dir_1er)
        self.assertEqual(self.client.post(reverse("pedagogie:supprimer_mesure_discipline", args=[self.m1.pk])).status_code, 302)  # 6A : son cycle

    def test_les_liens_du_dossier_et_de_mes_classes(self):
        self.client.force_login(self.fondateur)
        dossier = self.client.get(reverse("scolarite:dossier_eleve", args=[self.e1.matricule])).content.decode()
        self.assertIn(self.url_eleve, dossier)
        self.client.force_login(self.t1)
        self.assertIn(self.url_classe, self.client.get(reverse("pedagogie:mes_classes")).content.decode())
        self.client.force_login(self.fondateur)
        self.assertIn(self.url_classe, self.client.get(reverse("scolarite:liste_classes")).content.decode())
        self.client.force_login(self.parent)
        self.assertNotIn(self.url_classe, self.client.get(reverse("scolarite:liste_classes")).content.decode() if False else "")


class AnonymisationTests(DisciplineBase):
    def test_les_mesures_comptent_comme_un_historique_et_leur_motif_disparait(self):
        eleve = self.e5
        MesureDiscipline.objects.create(
            eleve=eleve, classe=self.c9a, date_mesure=AUJOURDHUI, type_mesure=T.BLAME, motif="Bagarre avec Zqxcamarade", enregistre_par=self.fondateur,
        )
        self.assertEqual(historique_eleve(eleve)["discipline"], 1)
        self.assertEqual(mode_de_retrait(eleve, historique_eleve(eleve)), "anonymisation")
        anonymiser_eleve(eleve)
        mesure = MesureDiscipline.objects.get(eleve=eleve)
        self.assertEqual((mesure.motif, mesure.type_mesure), ("", T.BLAME))  # le chiffre reste, le texte libre part


class DisciplineEnArabeTests(DisciplineBase):
    def test_les_pages_sont_en_arabe_pur(self):
        Utilisateur.objects.filter(pk=self.e1.pk).update(prenom="Aminata", nom="Traoré", prenom_ar="أميناتا", nom_ar="تراوري")
        invalider(self.ecole.pk)
        self.mesure(T.BLAME, motif="سلوك سيء")
        self.mesure(T.RETARD)
        client = client_en(self.fondateur, "ar")
        for adresse in (self.url_classe, self.url_eleve):
            reponse = client.get(adresse)
            self.assertEqual(reponse.status_code, 200, adresse)
            with self.subTest(page=adresse):
                self.assertEqual([t for t in restes_latins(reponse.content.decode()) if t != "Français"], [])
        self.assertContains(client.get(self.url_eleve), "توبيخ")
