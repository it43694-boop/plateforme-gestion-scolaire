"""
Pré-inscription en ligne : le lien secret d'une campagne, le formulaire public (protégé), la réponse du secrétariat (convocation ou refus) et
la décision après le test. La famille est prévenue par courriel, dans sa langue.
"""
import datetime

from django.core import mail
from django.core.cache import cache
from django.test import Client, override_settings
from django.urls import reverse

from comptes.arabisation import invalider
from comptes.langues import NOM_COOKIE_LANGUE
from comptes.models import JournalAudit, Notification
from comptes.outils_test_arabe import client_en
from comptes.roles import Role
from comptes.traduction import restes_latins
from etablissement.models import Etablissement
from scolarite.models import AnneeScolaire
from statistiques.test_education import EducationBase, creer_compte
from tests_niveau.models import Candidat, CampagnePreinscription, Decision, StatutDemande
from tests_niveau.preinscription import classes_proposees, deposer_une_demande

D = datetime.date
AUJOURDHUI = D.today()


def jours(n):
    return AUJOURDHUI + datetime.timedelta(days=n)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", EMAIL_ASYNC=False)
class PreinscriptionBase(EducationBase):
    def setUp(self):
        cache.clear()  # les limites de débit ne doivent pas passer d'un test à l'autre
        self.campagne = CampagnePreinscription.objects.create(
            etablissement=self.ecole, titre="Pré-inscriptions 2026-2027", annee_scolaire=self.annee, message_accueil="Apportez l'extrait de naissance.",
        )
        self.url = reverse("tests_niveau:preinscription", args=[self.campagne.jeton])
        self.url_merci = reverse("tests_niveau:preinscription_merci", args=[self.campagne.jeton])
        self.visiteur = Client()

    def donnees(self, **extra):
        base = {
            "prenom": "Aminata", "nom": "Zqxtraore", "date_naissance": "2015-03-02", "sexe": "F", "classe_visee": self.c6a.pk,
            "nom_parent": "Bakary Zqxtraore", "email": "Parent@Famille.test", "telephone": "70 12 34 56", "message": "", "consentement": "on",
        }
        base.update(extra)
        return base

    def deposer(self, client=None, **extra):
        return (client or self.visiteur).post(self.url, self.donnees(**extra))

    def demande(self, **extra):
        defauts = {"prenom": "Awa", "nom": "Zqxdiarra", "date_naissance": D(2015, 5, 5), "classe_visee": self.c6a, "email": "awa@famille.test", "telephone": "", "sexe": "F"}
        defauts.update(extra)
        candidat, _ = deposer_une_demande(self.campagne, defauts, langue=defauts.pop("langue", "fr"))
        return candidat


class CampagneTests(PreinscriptionBase):
    def test_les_dates_et_l_etat_d_une_campagne(self):
        c = self.campagne
        self.assertTrue(c.est_ouverte())
        c.active = False
        self.assertFalse(c.est_ouverte())
        c.active, c.date_ouverture = True, jours(1)
        self.assertFalse(c.est_ouverte())  # pas encore ouverte
        c.date_ouverture, c.date_cloture = jours(-5), jours(-1)
        self.assertFalse(c.est_ouverte())  # déjà fermée
        c.date_cloture = AUJOURDHUI
        self.assertTrue(c.est_ouverte())  # le dernier jour compte encore
        c.date_ouverture = AUJOURDHUI
        self.assertTrue(c.est_ouverte())  # le premier jour aussi

    def test_une_annee_archivee_ferme_la_campagne(self):
        AnneeScolaire.objects.filter(pk=self.annee.pk).update(est_archivee=True)
        self.campagne.refresh_from_db()
        self.assertFalse(CampagnePreinscription.objects.get(pk=self.campagne.pk).est_ouverte())

    def test_le_lien_est_un_jeton_impossible_a_deviner(self):
        autre = CampagnePreinscription.objects.create(etablissement=self.ecole, titre="x", annee_scolaire=self.annee)
        self.assertNotEqual(self.campagne.jeton, autre.jeton)
        self.assertGreaterEqual(len(self.campagne.jeton), 20)

    def test_les_classes_proposees_sont_celles_de_l_annee_de_la_campagne(self):
        classes = set(classes_proposees(self.campagne))
        self.assertIn(self.c6a, classes)
        self.assertNotIn(self.classe_5a, classes)  # une autre année
        self.assertNotIn(self.classe_b, classes)  # une autre école


class FormulairePublicTests(PreinscriptionBase):
    def test_le_formulaire_s_affiche_a_un_visiteur_non_connecte(self):
        reponse = self.visiteur.get(self.url)
        self.assertEqual(reponse.status_code, 200)
        page = reponse.content.decode()
        for attendu in (self.ecole.nom, "Pré-inscriptions 2026-2027", "extrait de naissance", "6A", "9A", "Envoyer la demande"):
            self.assertIn(attendu, page)
        self.assertNotIn("5A", page)  # une classe d'une autre année n'est pas proposée
        self.assertIn("piege-robot", page)  # le piège à robots existe, caché des personnes
        self.assertEqual(self.visiteur.session["etablissement_id"], self.ecole.pk)

    def test_un_lien_inconnu_est_introuvable(self):
        self.assertEqual(self.visiteur.get(reverse("tests_niveau:preinscription", args=["n-existe-pas"])).status_code, 404)
        self.assertEqual(self.visiteur.get(reverse("tests_niveau:preinscription_merci", args=["n-existe-pas"])).status_code, 404)

    def test_une_campagne_fermee_ne_recoit_rien(self):
        for fermeture in (
            {"active": False}, {"date_cloture": jours(-1)}, {"date_ouverture": jours(2)},
        ):
            CampagnePreinscription.objects.filter(pk=self.campagne.pk).update(active=True, date_ouverture=None, date_cloture=None)
            CampagnePreinscription.objects.filter(pk=self.campagne.pk).update(**fermeture)
            with self.subTest(fermeture=fermeture):
                self.assertContains(self.visiteur.get(self.url), "ne sont pas ouvertes")
                self.assertContains(self.deposer(), "ne sont pas ouvertes")
        self.assertEqual(Candidat.objects.count(), 0)

    def test_une_ecole_suspendue_ferme_son_formulaire(self):
        Etablissement.objects.filter(pk=self.ecole.pk).update(actif=False)
        self.assertContains(self.visiteur.get(self.url), "ne sont pas ouvertes")

    def test_une_demande_valide(self):
        reponse = self.deposer()
        self.assertRedirects(reponse, self.url_merci)
        self.assertContains(self.visiteur.get(self.url_merci), "bien été envoyée")
        candidat = Candidat.objects.get()
        self.assertEqual(
            (candidat.prenom, candidat.nom, candidat.date_naissance, candidat.classe_visee, candidat.campagne, candidat.statut_demande, candidat.date_test, candidat.decision),
            ("Aminata", "Zqxtraore", D(2015, 3, 2), self.c6a, self.campagne, StatutDemande.RECUE, None, Decision.EN_ATTENTE),
        )
        self.assertEqual((candidat.email_contact, candidat.telephone_contact, candidat.nom_parent, candidat.langue), ("parent@famille.test", "70 12 34 56", "Bakary Zqxtraore", "fr"))
        self.assertIsNotNone(candidat.demande_le)

    def test_la_famille_recoit_un_accuse_de_reception(self):
        self.deposer()
        message, = mail.outbox
        self.assertEqual(message.to, ["parent@famille.test"])
        self.assertIn("Demande de pré-inscription reçue", message.subject)
        self.assertIn("Aminata Zqxtraore", message.body)
        self.assertIn("6A", message.body)

    def test_le_secretariat_et_la_direction_sont_prevenus_et_personne_d_autre(self):
        direction = creer_compte(Role.FONDATEUR, "fondateur@preinsc.test", self.ecole)
        developpeur = creer_compte(Role.DEVELOPPEUR, "dev@preinsc.test", self.ecole)
        self.deposer()
        destinataires = set(Notification.objects.filter(titre="Nouvelle demande de pré-inscription").values_list("destinataire_id", flat=True))
        self.assertIn(self.secretaire.pk, destinataires)
        self.assertIn(direction.pk, destinataires)
        for exclu in (self.parent, self.t1, self.comptable, developpeur, self.fondateur_b):
            self.assertNotIn(exclu.pk, destinataires)
        notification = Notification.objects.get(destinataire=self.secretaire)
        self.assertEqual(notification.url, f"{reverse('tests_niveau:liste_candidats')}?demande=recue")

    def test_sans_email_la_demande_est_enregistree_sans_courriel(self):
        self.deposer(email="")
        self.assertEqual(Candidat.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_avec_l_email_seulement(self):
        self.assertRedirects(self.deposer(telephone=""), self.url_merci)

    def test_il_faut_un_moyen_de_repondre(self):
        reponse = self.deposer(email="", telephone="")
        self.assertContains(reponse, "au moins une adresse email")
        self.assertEqual(Candidat.objects.count(), 0)

    def test_les_erreurs_de_saisie(self):
        for champs, erreur in (
            ({"telephone": "12"}, "Numéro invalide"),
            ({"email": "pas-un-email"}, "courriel valide"),
            ({"date_naissance": jours(5).isoformat()}, "en âge d"),
            ({"date_naissance": "2026-06-01"}, "en âge d"),  # un nourrisson
            ({"date_naissance": "1990-01-01"}, "en âge d"),  # un adulte
            ({"classe_visee": self.classe_b.pk}, "Sélectionnez un choix valide"),  # la classe d'une autre école
            ({"classe_visee": self.classe_5a.pk}, "Sélectionnez un choix valide"),  # une classe d'une autre année
            ({"consentement": ""}, "Vous devez accepter"),
            ({"prenom": ""}, "obligatoire"),
            ({"sexe": "X"}, "Sélectionnez un choix valide"),
        ):
            with self.subTest(erreur=erreur, champs=champs):
                reponse = self.deposer(**champs)
                self.assertEqual(reponse.status_code, 200)
                self.assertContains(reponse, erreur)
        self.assertEqual(Candidat.objects.count(), 0)

    def test_les_espaces_inutiles_sont_retires(self):
        self.deposer(prenom="  Aminata   Fatou ", nom=" Zqxtraore ", message="  Bonjour   à  tous ")
        candidat = Candidat.objects.get()
        self.assertEqual((candidat.prenom, candidat.nom, candidat.message), ("Aminata Fatou", "Zqxtraore", "Bonjour à tous"))

    def test_le_piege_a_robots_repond_comme_une_personne_sans_rien_enregistrer(self):
        reponse = self.deposer(site_web="http://spam.example")
        self.assertRedirects(reponse, self.url_merci)
        self.assertEqual((Candidat.objects.count(), len(mail.outbox), Notification.objects.count()), (0, 0, 0))

    def test_la_meme_demande_deux_fois_n_est_enregistree_qu_une_fois(self):
        self.assertRedirects(self.deposer(), self.url_merci)
        self.assertRedirects(self.deposer(), self.url_merci)  # la famille ne voit aucune différence
        self.assertEqual((Candidat.objects.count(), len(mail.outbox)), (1, 1))
        self.deposer(prenom="Moussa")  # un autre enfant de la même famille : une nouvelle demande
        self.assertEqual(Candidat.objects.count(), 2)

    def test_un_texte_piege_est_affiche_sans_etre_execute(self):
        piege = "<script>alert('x')</script>"
        self.deposer(message=piege, nom_parent="<b>Parent</b>")
        self.client.force_login(self.secretaire)
        page = self.client.get(reverse("tests_niveau:liste_candidats")).content.decode()
        self.assertNotIn("<script>alert", page)
        self.assertNotIn("<b>Parent</b>", page)
        self.assertIn("&lt;b&gt;Parent&lt;/b&gt;", page)

    def test_le_formulaire_exige_le_jeton_de_securite(self):
        strict = Client(enforce_csrf_checks=True)
        self.assertEqual(strict.post(self.url, self.donnees()).status_code, 403)
        self.assertEqual(Candidat.objects.count(), 0)

    def test_trop_de_demandes_depuis_la_meme_adresse_sont_refusees(self):
        for numero in range(5):
            self.assertRedirects(self.deposer(prenom=f"Enfant{numero}"), self.url_merci)
        reponse = self.deposer(prenom="Enfant5")
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Trop de demandes")
        self.assertEqual(Candidat.objects.count(), 5)

    def test_une_campagne_pleine_se_ferme(self):
        from unittest import mock

        with mock.patch("tests_niveau.preinscription.DEMANDES_MAXIMALES_PAR_CAMPAGNE", 1):
            self.assertRedirects(self.deposer(), self.url_merci)
            self.assertContains(self.deposer(prenom="Moussa"), "ne sont pas ouvertes")
        self.assertEqual(Candidat.objects.count(), 1)

    def test_les_pages_internes_restent_fermees_aux_visiteurs(self):
        for nom in ("liste_candidats", "campagnes"):
            self.assertEqual(self.visiteur.get(reverse(f"tests_niveau:{nom}")).status_code, 302)
        self.assertEqual(self.visiteur.post(reverse("tests_niveau:refuser_demande", args=[self.demande().pk])).status_code, 302)

    def test_en_arabe_la_page_et_les_courriels_sont_en_arabe(self):
        arabe = Client()
        arabe.cookies[NOM_COOKIE_LANGUE] = "ar"
        reponse = arabe.get(self.url)
        restes = [t for t in restes_latins(reponse.content.decode()) if t != "Français" and not t.startswith(("Pré-inscriptions", "Apportez"))]
        self.assertEqual(restes, [])  # (le titre et le message d'accueil sont ceux que l'école a saisis)
        self.assertContains(reponse, "إرسال الطلب")
        self.deposer(client=arabe)
        candidat = Candidat.objects.get()
        self.assertEqual(candidat.langue, "ar")
        self.assertIn("تم استلام طلب التسجيل المسبق", mail.outbox[0].subject)
        merci = arabe.get(self.url_merci)
        self.assertEqual([t for t in restes_latins(merci.content.decode()) if t != "Français" and not t.startswith("Pré-inscriptions")], [])


class ReponseDuSecretariatTests(PreinscriptionBase):
    def url_de(self, nom, candidat):
        return reverse(f"tests_niveau:{nom}", args=[candidat.pk])

    def test_la_liste_montre_les_demandes_et_celles_a_traiter(self):
        self.demande(prenom="Awa")
        manuel = Candidat.objects.create(prenom="Manuel", nom="Zqxmanuel", classe_visee=self.c6a, cree_par=self.secretaire)
        self.client.force_login(self.secretaire)
        reponse = self.client.get(reverse("tests_niveau:liste_candidats"))
        self.assertEqual(reponse.context["a_traiter"], 1)
        self.assertEqual({c.prenom for c in reponse.context["candidats"]}, {"Awa", "Manuel"})
        recues = self.client.get(reverse("tests_niveau:liste_candidats"), {"demande": "recue"}).context["candidats"]
        self.assertEqual([c.prenom for c in recues], ["Awa"])
        self.assertEqual(self.client.get(reverse("tests_niveau:liste_candidats"), {"demande": "n-importe-quoi"}).context["demande"], "")
        self.assertEqual(manuel.statut_demande, StatutDemande.TRAITEE)  # un candidat saisi à la main reste « traité »

    def test_convoquer_une_demande(self):
        candidat = self.demande()
        self.client.force_login(self.secretaire)
        reponse = self.client.post(self.url_de("convoquer_candidat", candidat), {"date_test": jours(10).isoformat()})
        self.assertRedirects(reponse, reverse("tests_niveau:liste_candidats"))
        candidat.refresh_from_db()
        self.assertEqual((candidat.statut_demande, candidat.date_test), (StatutDemande.CONVOQUE, jours(10)))
        message, = mail.outbox
        self.assertEqual(message.to, ["awa@famille.test"])
        self.assertIn("Convocation au test de niveau", message.subject)
        self.assertIn(jours(10).strftime("%d/%m/%Y"), message.body)
        journal = JournalAudit.objects.get(action="convocation_candidat")
        self.assertTrue(journal.details["famille_prevenue"])

    def test_la_date_du_test_ne_peut_pas_etre_passee(self):
        candidat = self.demande()
        self.client.force_login(self.secretaire)
        self.assertContains(self.client.post(self.url_de("convoquer_candidat", candidat), {"date_test": jours(-1).isoformat()}), "dans le passé")
        candidat.refresh_from_db()
        self.assertEqual(candidat.statut_demande, StatutDemande.RECUE)

    def test_on_peut_changer_la_date_d_un_candidat_convoque(self):
        candidat = self.demande()
        self.client.force_login(self.secretaire)
        self.client.post(self.url_de("convoquer_candidat", candidat), {"date_test": jours(10).isoformat()})
        self.client.post(self.url_de("convoquer_candidat", candidat), {"date_test": jours(12).isoformat()})
        candidat.refresh_from_db()
        self.assertEqual(candidat.date_test, jours(12))
        self.assertEqual(len(mail.outbox), 2)  # la famille reçoit la nouvelle date

    def test_refuser_une_demande(self):
        candidat = self.demande()
        self.client.force_login(self.secretaire)
        self.assertEqual(self.client.get(self.url_de("refuser_demande", candidat)).status_code, 405)
        self.client.post(self.url_de("refuser_demande", candidat))
        candidat.refresh_from_db()
        self.assertEqual(candidat.statut_demande, StatutDemande.REFUSEE)
        self.assertIn("Réponse à votre demande", mail.outbox[0].subject)
        self.assertIn("ne pouvons pas donner suite", mail.outbox[0].body)

    def test_les_etats_incompatibles_sont_refuses_avec_un_message(self):
        refusee = self.demande(prenom="Refusee")
        Candidat.objects.filter(pk=refusee.pk).update(statut_demande=StatutDemande.REFUSEE)
        self.client.force_login(self.secretaire)
        self.assertContains(self.client.get(self.url_de("convoquer_candidat", refusee), follow=True), "ne peut plus être convoquée")
        convoquee = self.demande(prenom="Convoquee")
        Candidat.objects.filter(pk=convoquee.pk).update(statut_demande=StatutDemande.CONVOQUE)
        self.assertContains(self.client.post(self.url_de("refuser_demande", convoquee), follow=True), "Seule une demande reçue")

    def test_la_decision_vient_apres_la_convocation(self):
        candidat = self.demande()
        self.client.force_login(self.secretaire)
        reponse = self.client.post(reverse("tests_niveau:decider_candidat", args=[candidat.pk, "admis"]), follow=True)
        self.assertContains(reponse, "Convoquez d")
        candidat.refresh_from_db()
        self.assertEqual(candidat.decision, Decision.EN_ATTENTE)
        self.assertEqual(len(mail.outbox), 0)

    def test_apres_le_test_la_decision_est_annoncee_a_la_famille(self):
        for decision, attendu in (("admis", "est admis(e)"), ("refuse", "n'a pas été admis(e)")):
            Candidat.objects.all().delete()
            mail.outbox.clear()
            candidat = self.demande(prenom=f"Enfant{decision}")
            self.client.force_login(self.secretaire)
            self.client.post(self.url_de("convoquer_candidat", candidat), {"date_test": jours(3).isoformat()})
            mail.outbox.clear()
            self.client.post(reverse("tests_niveau:decider_candidat", args=[candidat.pk, decision]))
            candidat.refresh_from_db()
            with self.subTest(decision=decision):
                self.assertEqual((candidat.decision, candidat.statut_demande), (decision, StatutDemande.TRAITEE))
                self.assertIn(attendu, mail.outbox[0].body)
                self.assertIn("Résultat du test de niveau", mail.outbox[0].subject)

    def test_un_candidat_saisi_a_la_main_decide_comme_avant_sans_courriel(self):
        manuel = Candidat.objects.create(prenom="Manuel", nom="Zqxmanuel", classe_visee=self.c6a, cree_par=self.secretaire)
        self.client.force_login(self.secretaire)
        self.client.post(reverse("tests_niveau:decider_candidat", args=[manuel.pk, "admis"]))
        manuel.refresh_from_db()
        self.assertEqual(manuel.decision, Decision.ADMIS)
        self.assertEqual(len(mail.outbox), 0)

    def test_un_courriel_qui_echoue_ne_bloque_pas_le_secretariat(self):
        from unittest import mock

        candidat = self.demande()
        self.client.force_login(self.secretaire)
        with mock.patch("tests_niveau.preinscription.envoyer_email", side_effect=RuntimeError("panne")):
            self.client.post(self.url_de("refuser_demande", candidat))
        candidat.refresh_from_db()
        self.assertEqual(candidat.statut_demande, StatutDemande.REFUSEE)

    def test_les_droits_et_le_cloisonnement(self):
        candidat = self.demande()
        for compte in (self.parent, self.e1, self.comptable, self.t1):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertEqual(self.client.post(self.url_de("refuser_demande", candidat)).status_code, 403)
                self.assertEqual(self.client.get(self.url_de("convoquer_candidat", candidat)).status_code, 403)
        self.client.force_login(self.fondateur_b)
        self.assertEqual(self.client.post(self.url_de("refuser_demande", candidat)).status_code, 404)
        self.client.force_login(self.dir_1er)  # la 6A est de son cycle
        self.assertEqual(self.client.get(self.url_de("convoquer_candidat", candidat)).status_code, 200)
        autre = self.demande(prenom="Lycee", classe_visee=self.ctse)
        self.assertEqual(self.client.get(self.url_de("convoquer_candidat", autre)).status_code, 404)  # le lycée n'est pas son cycle
        candidat.refresh_from_db()
        self.assertEqual(candidat.statut_demande, StatutDemande.RECUE)


class GestionDesCampagnesTests(PreinscriptionBase):
    donnees_campagne = {"titre": "  Rentrée   2027 ", "message_accueil": "Bienvenue", "date_ouverture": "", "date_cloture": ""}

    def url_campagnes(self):
        return reverse("tests_niveau:campagnes")

    def test_la_direction_ouvre_une_campagne_et_voit_son_lien(self):
        self.client.force_login(self.fondateur)
        reponse = self.client.post(self.url_campagnes(), {**self.donnees_campagne, "annee_scolaire": self.annee.pk})
        self.assertRedirects(reponse, self.url_campagnes())
        nouvelle = CampagnePreinscription.objects.exclude(pk=self.campagne.pk).get()
        self.assertEqual((nouvelle.titre, nouvelle.etablissement, nouvelle.cree_par), ("Rentrée 2027", self.ecole, self.fondateur))
        page = self.client.get(self.url_campagnes())
        self.assertContains(page, reverse("tests_niveau:preinscription", args=[nouvelle.jeton]))
        self.assertTrue(JournalAudit.objects.filter(action="creation_campagne_preinscription").exists())

    def test_les_erreurs_de_la_campagne(self):
        self.client.force_login(self.fondateur)
        for champs, erreur in (
            ({"date_ouverture": "2026-12-01", "date_cloture": "2026-11-01"}, "ne peut pas précéder"),
            ({"titre": ""}, "obligatoire"),
            ({"annee_scolaire": self.annee_b.pk}, "Sélectionnez un choix valide"),  # l'année d'une autre école
        ):
            with self.subTest(erreur=erreur):
                reponse = self.client.post(self.url_campagnes(), {**self.donnees_campagne, "annee_scolaire": self.annee.pk, **champs})
                self.assertContains(reponse, erreur)
        self.assertEqual(CampagnePreinscription.objects.count(), 1)

    def test_seule_la_direction_gere_les_campagnes(self):
        for compte in (self.secretaire, self.dir_1er, self.t1, self.parent, self.comptable):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertEqual(self.client.get(self.url_campagnes()).status_code, 403)
                self.assertEqual(self.client.post(self.url_campagnes(), {**self.donnees_campagne, "annee_scolaire": self.annee.pk}).status_code, 403)
                self.assertEqual(self.client.post(reverse("tests_niveau:basculer_campagne", args=[self.campagne.pk])).status_code, 403)
        self.assertEqual(CampagnePreinscription.objects.count(), 1)

    def test_fermer_et_rouvrir_une_campagne(self):
        self.client.force_login(self.fondateur)
        basculer = reverse("tests_niveau:basculer_campagne", args=[self.campagne.pk])
        self.assertEqual(self.client.get(basculer).status_code, 405)
        self.client.post(basculer)
        self.assertContains(Client().get(self.url), "ne sont pas ouvertes")
        self.client.post(basculer)
        self.assertContains(Client().get(self.url), "Envoyer la demande")
        actions = list(JournalAudit.objects.values_list("action", flat=True))
        self.assertIn("fermeture_campagne_preinscription", actions)
        self.assertIn("ouverture_campagne_preinscription", actions)

    def test_une_autre_ecole_ne_voit_ni_ne_touche_mes_campagnes(self):
        self.client.force_login(self.fondateur_b)
        self.assertNotContains(self.client.get(self.url_campagnes()), self.campagne.jeton)
        self.assertEqual(self.client.post(reverse("tests_niveau:basculer_campagne", args=[self.campagne.pk])).status_code, 404)

    def test_le_lien_est_propose_depuis_la_liste_des_candidats(self):
        self.client.force_login(self.fondateur)
        self.assertContains(self.client.get(reverse("tests_niveau:liste_candidats")), self.url_campagnes())
        self.client.force_login(self.secretaire)
        self.assertNotContains(self.client.get(reverse("tests_niveau:liste_candidats")), self.url_campagnes())


class PagesDuSecretariatEnArabeTests(PreinscriptionBase):
    def test_les_pages_sont_en_arabe_pur(self):
        candidat = self.demande(prenom="Awa", nom="Diarra")
        invalider(self.ecole.pk)
        pages = [
            (self.fondateur, reverse("tests_niveau:liste_candidats")), (self.fondateur, reverse("tests_niveau:campagnes")),
            (self.secretaire, reverse("tests_niveau:convoquer_candidat", args=[candidat.pk])),
        ]
        for compte, adresse in pages:
            reponse = client_en(compte, "ar").get(adresse)
            self.assertEqual(reponse.status_code, 200, adresse)
            restes = [t for t in restes_latins(reponse.content.decode()) if t not in {"Français"} and self.campagne.jeton not in t and not t.startswith("Pré-inscriptions")]
            with self.subTest(page=adresse):
                self.assertEqual(restes, [])
