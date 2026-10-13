"""
Entretien quotidien : messages de plus de 30 jours et sessions expirées effacés, rien d'autre.

Jeu de données de EducationBase (statistiques.test_education) : école A (classe 6A avec e1, e2, e3 ; parent `parent` lié à e1 ;
enseignant t1 qui enseigne en 6A), école B vide.
"""
import io
from datetime import timedelta
from unittest import mock

from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.core.management import call_command
from django.template import Context, Template
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from communication.models import Annonce, FilEquipe, Message, MessageEquipe, Portee, PorteeEquipe
from comptes.entretien import (
    CLE_CACHE_ENTRETIEN, entretien_quotidien, entretien_si_du, purger_messages_anciens, purger_sessions_expirees,
)
from comptes.models import JournalAudit, Notification
from comptes.roles import Role
from statistiques.test_education import EducationBase, creer_compte

SECRET = "texte-secret-du-message"
PAGE = reverse("communication:liste_conversations")  # une page quelconque d'un utilisateur connecté


class EntretienBase(EducationBase):
    def setUp(self):
        cache.clear()
        self.maintenant = timezone.now()
        self.fil = FilEquipe.objects.create(
            etablissement=self.ecole, annee_scolaire=self.annee, portee=PorteeEquipe.CLASSE, classe=self.c6a,
        )

    def message(self, age_jours, contenu=SECRET, lu=False):
        message = Message.objects.create(
            etablissement=self.ecole, eleve=self.e1, expediteur=self.parent, destinataire=self.t1, contenu=contenu,
        )
        Message.objects.filter(pk=message.pk).update(
            envoye_le=self.maintenant - timedelta(days=age_jours), lu_le=self.maintenant if lu else None,
        )
        return message

    def message_equipe(self, age_jours):
        message = MessageEquipe.objects.create(fil=self.fil, auteur=self.t1, contenu=SECRET)
        MessageEquipe.objects.filter(pk=message.pk).update(envoye_le=self.maintenant - timedelta(days=age_jours))
        return message

    def session(self, expiree):
        cle = f"{'e' if expiree else 'v'}{Session.objects.count():031d}"
        return Session.objects.create(
            session_key=cle, session_data="x",
            expire_date=self.maintenant + (timedelta(days=-1) if expiree else timedelta(minutes=20)),
        )


@override_settings(DUREE_CONSERVATION_MESSAGES_JOURS=30)
class PurgeDesMessagesTests(EntretienBase):
    def test_les_messages_de_plus_de_30_jours_sont_effaces_les_autres_restent(self):
        vieux, limite_ancienne, limite_recente, recent = (self.message(40), self.message(30.01), self.message(29.9), self.message(1))
        vieux_equipe, recent_equipe = self.message_equipe(45), self.message_equipe(2)
        resultat = purger_messages_anciens(maintenant=self.maintenant)
        self.assertEqual(resultat, {"messages": 2, "messages_equipe": 1, "notifications_de_messages": 0})
        self.assertEqual(set(Message.objects.values_list("pk", flat=True)), {limite_recente.pk, recent.pk})
        self.assertEqual(list(MessageEquipe.objects.values_list("pk", flat=True)), [recent_equipe.pk])

    def test_lus_ou_non_lus_ils_sont_effaces(self):
        self.message(60, lu=True)
        self.message(60, lu=False)
        self.assertEqual(purger_messages_anciens(maintenant=self.maintenant)["messages"], 2)

    def test_une_duree_a_zero_n_efface_jamais(self):
        self.message(400)
        self.message_equipe(400)
        with override_settings(DUREE_CONSERVATION_MESSAGES_JOURS=0):
            self.assertEqual(purger_messages_anciens(maintenant=self.maintenant), {"messages": 0, "messages_equipe": 0, "notifications_de_messages": 0})
        self.assertEqual((Message.objects.count(), MessageEquipe.objects.count()), (1, 1))
        self.assertEqual(purger_messages_anciens(jours=-5, maintenant=self.maintenant)["messages"], 0)

    def test_la_duree_peut_etre_donnee_a_l_appel(self):
        self.message(10)
        self.assertEqual(purger_messages_anciens(jours=7, maintenant=self.maintenant)["messages"], 1)

    def test_la_simulation_compte_sans_effacer(self):
        self.message(40)
        self.message_equipe(40)
        self.assertEqual(purger_messages_anciens(maintenant=self.maintenant, simulation=True), {"messages": 1, "messages_equipe": 1, "notifications_de_messages": 0})
        self.assertEqual((Message.objects.count(), MessageEquipe.objects.count()), (1, 1))

    def test_les_annonces_et_les_notifications_anciennes_ne_sont_pas_touchees(self):
        annonce = Annonce.objects.create(
            etablissement=self.ecole, auteur=self.fondateur, titre="Annonce ancienne", contenu="x", portee=Portee.TOUTE_ECOLE,
        )
        notification = Notification.objects.create(destinataire=self.parent, titre="Ancienne", message="x", url="/")
        Annonce.objects.filter(pk=annonce.pk).update(date_publication=self.maintenant - timedelta(days=90))
        Notification.objects.filter(pk=notification.pk).update(cree_le=self.maintenant - timedelta(days=90))
        self.message(40)
        purger_messages_anciens(maintenant=self.maintenant)
        self.assertTrue(Annonce.objects.filter(pk=annonce.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=notification.pk).exists())


class PurgeDesSessionsTests(EntretienBase):
    def test_seules_les_sessions_expirees_sont_effacees(self):
        expiree, valide = self.session(expiree=True), self.session(expiree=False)
        self.assertEqual(purger_sessions_expirees(maintenant=self.maintenant), 1)
        self.assertFalse(Session.objects.filter(pk=expiree.pk).exists())
        self.assertTrue(Session.objects.filter(pk=valide.pk).exists())

    def test_personne_n_est_deconnecte(self):
        self.client.force_login(self.t1)
        self.session(expiree=True)
        purger_sessions_expirees()
        self.assertEqual(self.client.get(PAGE).status_code, 200)

    def test_la_simulation_ne_supprime_rien(self):
        self.session(expiree=True)
        self.assertEqual(purger_sessions_expirees(maintenant=self.maintenant, simulation=True), 1)
        self.assertEqual(Session.objects.count(), 1)


@override_settings(DUREE_CONSERVATION_MESSAGES_JOURS=30)
class EntretienQuotidienTests(EntretienBase):
    def test_le_journal_note_des_compteurs_sans_le_texte_des_messages(self):
        self.message(40)
        self.session(expiree=True)
        entretien_quotidien()
        entree = JournalAudit.objects.get(action="entretien_quotidien")
        self.assertEqual(entree.details, {"messages": 1, "messages_equipe": 0, "notifications_de_messages": 0, "sessions": 1})
        self.assertIsNone(entree.acteur)
        self.assertNotIn(SECRET, f"{entree.cible} {entree.details}")

    def test_rien_a_effacer_rien_au_journal(self):
        self.message(1)
        entretien_quotidien()
        self.assertFalse(JournalAudit.objects.filter(action="entretien_quotidien").exists())

    def test_la_simulation_n_ecrit_pas_au_journal(self):
        self.message(40)
        entretien_quotidien(simulation=True)
        self.assertFalse(JournalAudit.objects.filter(action="entretien_quotidien").exists())
        self.assertEqual(Message.objects.count(), 1)

    def test_une_seule_fois_par_jour(self):
        self.message(40)
        self.assertEqual(entretien_si_du()["messages"], 1)
        self.message(40)
        self.assertIsNone(entretien_si_du())  # déjà fait aujourd'hui
        self.assertEqual(Message.objects.count(), 1)
        cache.delete(CLE_CACHE_ENTRETIEN)  # « demain »
        self.assertEqual(entretien_si_du()["messages"], 1)

    def test_l_entretien_automatique_peut_etre_coupe(self):
        self.message(40)
        with override_settings(ENTRETIEN_AUTOMATIQUE=False):
            self.assertIsNone(entretien_si_du())
        self.assertEqual(Message.objects.count(), 1)

    def test_un_echec_n_est_pas_retente_avant_demain_et_ne_leve_pas(self):
        with mock.patch("comptes.entretien.entretien_quotidien", side_effect=RuntimeError("base en panne")) as faux:
            self.assertIsNone(entretien_si_du())
            self.assertIsNone(entretien_si_du())
        self.assertEqual(faux.call_count, 1)


@override_settings(DUREE_CONSERVATION_MESSAGES_JOURS=30)
class DeclenchementAutomatiqueTests(EntretienBase):
    def test_la_premiere_page_d_un_utilisateur_connecte_declenche_l_entretien(self):
        self.message(40)
        self.client.force_login(self.t1)
        self.assertEqual(self.client.get(PAGE).status_code, 200)
        self.assertFalse(Message.objects.filter(contenu=SECRET).exists())

    def test_un_visiteur_anonyme_ne_le_declenche_pas(self):
        self.message(40)
        self.client.get(reverse("comptes:connexion"))
        self.assertEqual(Message.objects.count(), 1)

    def test_une_panne_de_l_entretien_ne_casse_pas_la_page(self):
        self.client.force_login(self.t1)
        with mock.patch("comptes.entretien.entretien_quotidien", side_effect=RuntimeError("panne")):
            self.assertEqual(self.client.get(PAGE).status_code, 200)

    def test_pas_de_nouvel_entretien_a_la_page_suivante(self):
        self.client.force_login(self.t1)
        self.client.get(PAGE)
        self.message(40)
        self.client.get(PAGE)
        self.assertEqual(Message.objects.count(), 1)


@override_settings(DUREE_CONSERVATION_MESSAGES_JOURS=30)
class CommandeEntretienTests(EntretienBase):
    def lancer(self, *arguments):
        sortie = io.StringIO()
        call_command("entretien", *arguments, stdout=sortie)
        return sortie.getvalue()

    def test_commande_efface_et_rend_compte(self):
        self.message(40)
        self.session(expiree=True)
        texte = self.lancer()
        self.assertIn("effacés : 1 (messagerie), 0 (fils d'équipe)", texte)
        self.assertIn("Sessions de connexion expirées effacés : 1", texte)
        self.assertEqual((Message.objects.count(), Session.objects.count()), (0, 0))

    def test_commande_en_simulation(self):
        self.message(40)
        texte = self.lancer("--simulation")
        self.assertIn("seraient effacés : 1", texte)
        self.assertEqual(Message.objects.count(), 1)

    def test_commande_avec_une_autre_duree(self):
        self.message(10)
        self.lancer("--jours", "7")
        self.assertEqual(Message.objects.count(), 0)

    def test_commande_avec_duree_zero(self):
        self.message(400)
        self.assertIn("désactivé", self.lancer("--jours", "0"))
        self.assertEqual(Message.objects.count(), 1)


@override_settings(DUREE_CONSERVATION_MESSAGES_JOURS=30)
class RappelAuxUtilisateursTests(EntretienBase):
    def rendu(self):
        return Template(
            "{% load conservation %}{% duree_conservation_messages_jours as jours %}{{ jours }}"
        ).render(Context({}))

    def test_le_nombre_de_jours_est_disponible_dans_les_gabarits(self):
        self.assertEqual(self.rendu(), "30")
        with override_settings(DUREE_CONSERVATION_MESSAGES_JOURS=0):
            self.assertEqual(self.rendu(), "0")

    def test_les_pages_de_messagerie_rappellent_l_effacement(self):
        self.client.force_login(self.t1)
        for adresse in (reverse("communication:liste_conversations"), reverse("communication:liste_equipes")):
            with self.subTest(page=adresse):
                self.assertContains(self.client.get(adresse), "effacés automatiquement après 30 jours")
        conversation = reverse("communication:conversation", args=[self.e1.pk, self.parent.pk])
        self.assertContains(self.client.get(conversation), "effacés automatiquement après 30 jours")
        self.assertContains(self.client.get(reverse("communication:fil_equipe", args=[self.fil.pk])), "effacés automatiquement après 30 jours")

    def test_pas_de_rappel_quand_les_messages_sont_conserves(self):
        self.client.force_login(self.t1)
        with override_settings(DUREE_CONSERVATION_MESSAGES_JOURS=0):
            self.assertNotContains(self.client.get(reverse("communication:liste_conversations")), "effacés automatiquement")
