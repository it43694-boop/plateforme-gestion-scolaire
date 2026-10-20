"""Notifications sur le téléphone (Web Push) : éteintes sans clés, abonnement des appareils, envoi, nettoyage des appareils perdus, absence, annonce et paiement."""
import base64
import datetime
import json
import os
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from py_vapid import Vapid

from comptes import push
from comptes.models import AbonnementPush, Notification
from comptes.roles import Role
from pedagogie.models import Absence
from scolarite.models import Affectation
from statistiques.test_education import EducationBase, creer_compte


def _b64(octets):
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode()


def _cles_vapid():
    sortie = StringIO()
    call_command("generer_cles_push", stdout=sortie)
    return dict(ligne.split("=", 1) for ligne in sortie.getvalue().splitlines() if ligne.startswith(("VAPID_PUBLIC_KEY=", "VAPID_PRIVATE_KEY=")))


CLES = _cles_vapid()
EN_SERVICE = override_settings(
    PUSH_ACTIF=True, VAPID_PUBLIC_KEY=CLES["VAPID_PUBLIC_KEY"], VAPID_PRIVATE_KEY=CLES["VAPID_PRIVATE_KEY"], VAPID_ADMIN_EMAIL="contact@exemple.test", PUSH_ASYNC=False,
)


def un_telephone():
    """Les clés qu'un navigateur donne à l'abonnement : sa clé publique et son secret d'authentification."""
    cle = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return {"p256dh": _b64(cle), "auth": _b64(os.urandom(16))}


def abonnement_json(adresse="https://push.exemple.test/appareil-1"):
    return {"endpoint": adresse, "keys": un_telephone()}


class PushBase(EducationBase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        push._cle_privee.cache_clear()
        self.addCleanup(push._cle_privee.cache_clear)

    def abonner(self, utilisateur, adresse="https://push.exemple.test/appareil-1"):
        donnees = abonnement_json(adresse)
        return AbonnementPush.objects.create(utilisateur=utilisateur, endpoint=adresse, cle_p256dh=donnees["keys"]["p256dh"], cle_auth=donnees["keys"]["auth"])

    def poster(self, adresse, donnees, compte=None):
        self.client.force_login(compte or self.parent)
        corps = donnees if isinstance(donnees, (bytes, str)) else json.dumps(donnees)
        return self.client.post(reverse(adresse), corps, content_type="application/json")


class PushEteintTests(PushBase):
    def test_sans_cles_il_n_y_a_ni_carte_ni_script_ni_envoi(self):
        self.client.force_login(self.parent)
        page = self.client.get(reverse("comptes:liste_notifications"))
        self.assertNotContains(page, "data-push-carte")
        self.assertNotContains(page, "cle-push")
        self.assertNotContains(page, "push.js")
        self.assertEqual(self.poster("comptes:abonner_push", abonnement_json()).status_code, 404)
        self.abonner(self.parent)
        with mock.patch("pywebpush.webpush") as envoi:
            Notification.objects.create(destinataire=self.parent, titre="Test", message="Bonjour")
        envoi.assert_not_called()


@EN_SERVICE
class CarteEtAbonnementTests(PushBase):
    def test_la_page_des_notifications_propose_d_activer_les_notifications(self):
        self.client.force_login(self.parent)
        page = self.client.get(reverse("comptes:liste_notifications"))
        for attendu in ("data-push-carte", "Notifications sur ce téléphone", "Activer les notifications", "Désactiver les notifications", "push.js", 'id="cle-push"', CLES["VAPID_PUBLIC_KEY"]):
            self.assertContains(page, attendu)
        self.assertNotContains(page, CLES["VAPID_PRIVATE_KEY"])  # la clé privée ne sort jamais du serveur

    def test_un_visiteur_non_connecte_ne_voit_rien(self):
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("vitrine:accueil")), "cle-push")
        reponse = self.client.post(reverse("comptes:abonner_push"), json.dumps(abonnement_json()), content_type="application/json")
        self.assertEqual(reponse.status_code, 302)

    def test_abonner_un_appareil(self):
        donnees = abonnement_json()
        reponse = self.poster("comptes:abonner_push", donnees)
        self.assertEqual((reponse.status_code, reponse.json()), (200, {"ok": True}))
        appareil = AbonnementPush.objects.get()
        self.assertEqual((appareil.utilisateur, appareil.endpoint, appareil.cle_p256dh, appareil.cle_auth), (self.parent, donnees["endpoint"], donnees["keys"]["p256dh"], donnees["keys"]["auth"]))

    def test_le_meme_appareil_n_est_enregistre_qu_une_fois(self):
        donnees = abonnement_json()
        self.poster("comptes:abonner_push", donnees)
        self.poster("comptes:abonner_push", donnees)
        self.assertEqual(AbonnementPush.objects.count(), 1)

    def test_un_appareil_partage_passe_a_la_personne_suivante(self):
        donnees = abonnement_json()
        self.poster("comptes:abonner_push", donnees, compte=self.parent)
        self.poster("comptes:abonner_push", donnees, compte=self.t1)  # même navigateur, une autre personne s'est connectée
        self.assertEqual(AbonnementPush.objects.get().utilisateur, self.t1)

    def test_les_abonnements_invalides_sont_refuses(self):
        valide = abonnement_json()
        for libelle, corps in (
            ("pas du JSON", "ceci n'est pas du JSON"), ("pas un objet", "[1, 2]"), ("sans clés", {"endpoint": valide["endpoint"]}),
            ("adresse non sécurisée", {**valide, "endpoint": "http://push.exemple.test/x"}), ("adresse trop longue", {**valide, "endpoint": "https://push.exemple.test/" + "a" * 700}),
            ("adresse absente", {"keys": valide["keys"]}), ("clé trop courte", {**valide, "keys": {**valide["keys"], "p256dh": "abc"}}),
            ("secret trop court", {**valide, "keys": {**valide["keys"], "auth": "a"}}), ("clé qui n'est pas du texte", {**valide, "keys": {"p256dh": 5, "auth": 6}}),
        ):
            with self.subTest(libelle):
                self.assertEqual(self.poster("comptes:abonner_push", corps).status_code, 400)
        self.assertFalse(AbonnementPush.objects.exists())

    def test_on_ne_s_abonne_que_par_post(self):
        self.client.force_login(self.parent)
        self.assertEqual(self.client.get(reverse("comptes:abonner_push")).status_code, 405)
        self.assertEqual(self.client.get(reverse("comptes:desabonner_push")).status_code, 405)

    def test_soixante_abonnements_par_heure_au_plus(self):
        for numero in range(60):
            self.assertEqual(self.poster("comptes:abonner_push", abonnement_json(f"https://push.exemple.test/a{numero}")).status_code, 200)
        self.assertEqual(self.poster("comptes:abonner_push", abonnement_json("https://push.exemple.test/de-trop")).status_code, 429)

    def test_se_desabonner_ne_retire_que_ses_propres_appareils(self):
        mien, autre = self.abonner(self.parent, "https://push.exemple.test/mien"), self.abonner(self.t1, "https://push.exemple.test/autre")
        self.assertEqual(self.poster("comptes:desabonner_push", {"endpoint": autre.endpoint}).status_code, 200)  # l'appareil d'un autre : rien ne se passe
        self.assertTrue(AbonnementPush.objects.filter(pk=autre.pk).exists())
        self.assertEqual(self.poster("comptes:desabonner_push", {"endpoint": mien.endpoint}).status_code, 200)
        self.assertFalse(AbonnementPush.objects.filter(pk=mien.pk).exists())
        self.assertEqual(self.poster("comptes:desabonner_push", {"endpoint": "http://pas-valable"}).status_code, 400)

    def test_les_textes_du_script_sont_traduits_en_arabe(self):
        from comptes.outils_test_arabe import client_en

        page = client_en(self.parent, "ar").get(reverse("comptes:liste_notifications")).content.decode()
        self.assertIn("textes-js", page)
        self.assertNotIn("Notifications sur ce téléphone", page)
        self.assertNotIn("Activer les notifications", page)


@EN_SERVICE
class EnvoiTests(PushBase):
    def test_une_notification_part_sur_chaque_appareil_de_son_destinataire(self):
        mien1, mien2 = self.abonner(self.parent, "https://push.exemple.test/m1"), self.abonner(self.parent, "https://push.exemple.test/m2")
        self.abonner(self.t1, "https://push.exemple.test/autre")  # l'appareil d'une autre personne ne reçoit rien
        with mock.patch("pywebpush.webpush") as envoi:
            notification = Notification.objects.create(destinataire=self.parent, titre="Absence de Aminata", message="x" * 400, url="/pedagogie/absences/historique/1/")
        self.assertEqual(envoi.call_count, 2)
        adresses = {appel.kwargs["subscription_info"]["endpoint"] for appel in envoi.call_args_list}
        self.assertEqual(adresses, {mien1.endpoint, mien2.endpoint})
        appel = envoi.call_args_list[0]
        charge = json.loads(appel.kwargs["data"])
        self.assertEqual((charge["titre"], charge["url"], charge["id"]), ("Absence de Aminata", "/pedagogie/absences/historique/1/", notification.pk))
        self.assertEqual(len(charge["message"]), push.LONGUEUR_MAXIMALE_DU_MESSAGE)  # court : lisible sur l'écran verrouillé
        self.assertEqual(appel.kwargs["vapid_claims"], {"sub": "mailto:contact@exemple.test"})
        par_adresse = {mien1.endpoint: mien1, mien2.endpoint: mien2}
        appareil = par_adresse[appel.kwargs["subscription_info"]["endpoint"]]
        self.assertEqual(appel.kwargs["subscription_info"]["keys"], {"p256dh": appareil.cle_p256dh, "auth": appareil.cle_auth})

    def test_sans_appareil_rien_n_est_envoye(self):
        with mock.patch("pywebpush.webpush") as envoi:
            Notification.objects.create(destinataire=self.parent, titre="Test", message="Bonjour")
        envoi.assert_not_called()

    def test_une_adresse_qui_n_est_pas_de_notre_site_est_remplacee(self):
        self.abonner(self.parent)
        for adresse in ("https://autre-site.test/piege", "//autre-site.test/piege", "javascript:alert(1)", ""):
            with self.subTest(adresse=adresse), mock.patch("pywebpush.webpush") as envoi:
                Notification.objects.create(destinataire=self.parent, titre="Test", message="Bonjour", url=adresse)
            self.assertEqual(json.loads(envoi.call_args.kwargs["data"])["url"], "/comptes/notifications/")

    def test_un_appareil_desabonne_est_retire(self):
        appareil = self.abonner(self.parent)
        erreur = push_erreur(410)
        with mock.patch("pywebpush.webpush", side_effect=erreur):
            Notification.objects.create(destinataire=self.parent, titre="Test", message="Bonjour")
        self.assertFalse(AbonnementPush.objects.filter(pk=appareil.pk).exists())

    def test_un_appareil_qui_echoue_cinq_fois_est_retire(self):
        appareil = self.abonner(self.parent)
        for essai in range(1, push.ECHECS_MAXIMUM):
            with mock.patch("pywebpush.webpush", side_effect=push_erreur(500)):
                Notification.objects.create(destinataire=self.parent, titre="Test", message="Bonjour")
            appareil.refresh_from_db()
            self.assertEqual(appareil.echecs, essai)
        with mock.patch("pywebpush.webpush", side_effect=push_erreur(503)):
            Notification.objects.create(destinataire=self.parent, titre="Test", message="Bonjour")
        self.assertFalse(AbonnementPush.objects.filter(pk=appareil.pk).exists())

    def test_un_envoi_reussi_remet_les_echecs_a_zero(self):
        appareil = self.abonner(self.parent)
        AbonnementPush.objects.filter(pk=appareil.pk).update(echecs=3)
        with mock.patch("pywebpush.webpush"):
            Notification.objects.create(destinataire=self.parent, titre="Test", message="Bonjour")
        appareil.refresh_from_db()
        self.assertEqual(appareil.echecs, 0)
        self.assertIsNotNone(appareil.dernier_succes)

    def test_un_envoi_qui_plante_ne_fait_jamais_echouer_la_creation(self):
        self.abonner(self.parent)
        with mock.patch("pywebpush.webpush", side_effect=RuntimeError("panne")):
            notification = Notification.objects.create(destinataire=self.parent, titre="Test", message="Bonjour")
        self.assertTrue(Notification.objects.filter(pk=notification.pk).exists())
        self.assertEqual(AbonnementPush.objects.get().echecs, 1)

    def test_notifier_cree_une_notification_par_destinataire_et_les_envoie(self):
        self.abonner(self.parent), self.abonner(self.t1, "https://push.exemple.test/t1")
        with mock.patch("pywebpush.webpush") as envoi:
            creees = push.notifier([self.parent, self.t1, self.parent, self.fondateur], titre="Annonce", message="Bonjour", url="/communication/", etablissement=self.ecole)
        self.assertEqual(len(creees), 3)  # le même destinataire n'est pas notifié deux fois
        self.assertEqual(Notification.objects.filter(titre="Annonce").count(), 3)
        self.assertEqual(envoi.call_count, 2)  # seuls deux d'entre eux ont un appareil

    def test_l_adresse_sure(self):
        self.assertEqual(push.adresse_sure("/finances/"), "/finances/")
        for mauvaise in ("", None, "//x.test", "https://x.test", "finances/"):
            self.assertEqual(push.adresse_sure(mauvaise), "/comptes/notifications/")

    def test_le_chiffrement_et_la_signature_sont_ceux_de_la_norme(self):
        """Sans réseau : la vraie bibliothèque chiffre et signe, avec la clé du serveur chargée depuis l'environnement."""
        self.abonner(self.parent)
        reponse = mock.Mock(status_code=201, ok=True, text="")
        with mock.patch("requests.post", return_value=reponse) as envoi:
            Notification.objects.create(destinataire=self.parent, titre="Test", message="Bonjour")
        self.assertTrue(envoi.called)
        en_tetes = {cle.lower(): valeur for cle, valeur in envoi.call_args.kwargs["headers"].items()}
        self.assertTrue(en_tetes["authorization"].startswith("vapid t="))
        self.assertEqual(en_tetes["content-encoding"], "aes128gcm")
        self.assertNotIn(b"Bonjour", envoi.call_args.kwargs["data"])  # le contenu voyage chiffré
        self.assertIsNotNone(AbonnementPush.objects.get().dernier_succes)


def push_erreur(statut):
    from pywebpush import WebPushException

    return WebPushException("refusé", response=SimpleNamespace(status_code=statut))


class CleTests(PushBase):
    def test_la_commande_donne_une_paire_de_cles_utilisable(self):
        publique, privee = CLES["VAPID_PUBLIC_KEY"], CLES["VAPID_PRIVATE_KEY"]
        self.assertEqual(len(base64.urlsafe_b64decode(publique + "==")), 65)  # clé publique non compressée
        self.assertEqual(len(base64.urlsafe_b64decode(privee + "==")), 32)
        recharge = Vapid.from_raw(privee.encode())
        self.assertEqual(_b64(recharge.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)), publique)
        autre = _cles_vapid()
        self.assertNotEqual(autre["VAPID_PRIVATE_KEY"], privee)  # chaque appel donne une nouvelle paire

    def test_les_deux_cles_sont_necessaires(self):
        with override_settings(PUSH_ACTIF=False):
            self.assertFalse(push.push_actif())
        with EN_SERVICE:
            self.assertTrue(push.push_actif())


@EN_SERVICE
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", EMAIL_ASYNC=False)
class ProducteursTests(PushBase):
    def setUp(self):
        super().setUp()
        patcheur = mock.patch("pywebpush.webpush")  # jamais d'envoi réel : on compte les appels
        self.envoi = patcheur.start()
        self.addCleanup(patcheur.stop)
        self.abonner(self.parent, "https://push.exemple.test/parent")
        self.parent.email = "parent-push@example.com"
        self.parent.save(update_fields=["email"])

    def signaler_une_absence(self, eleve=None, jour=None):
        self.client.force_login(self.t1)  # t1 enseigne en 6A
        return self.client.post(reverse("pedagogie:saisir_absence", args=[self.c6a.pk]), {
            "matricule_eleve": (eleve or self.e1).matricule, "date_absence": (jour or timezone.localdate()).isoformat(), "motif": "",
        })

    def test_une_absence_signalee_previent_les_parents(self):
        reponse = self.signaler_une_absence()
        self.assertEqual(reponse.status_code, 302)
        notification = Notification.objects.get(destinataire=self.parent)
        self.assertEqual(notification.titre, f"Absence de {self.e1.prenom}")
        self.assertIn(self.e1.nom_complet, notification.message)
        self.assertEqual(notification.url, reverse("pedagogie:historique_absences", args=[self.e1.matricule]))
        self.assertEqual(self.envoi.call_count, 1)  # et sur son téléphone

    def test_seuls_les_parents_de_l_eleve_sont_prevenus(self):
        autre = creer_compte(Role.PARENT, "parent-e2@stat.test", self.ecole, telephone="70999003")
        self.e2.parents_lies.add(autre)
        self.signaler_une_absence()
        self.assertTrue(Notification.objects.filter(destinataire=self.parent).exists())
        self.assertFalse(Notification.objects.filter(destinataire=autre).exists())
        self.assertFalse(Notification.objects.filter(destinataire=self.t1).exists())

    def test_une_absence_mise_a_jour_ou_ancienne_ne_previent_pas_de_nouveau(self):
        self.signaler_une_absence()
        self.signaler_une_absence()  # la même absence, saisie une seconde fois : mise à jour
        self.assertEqual(Notification.objects.filter(destinataire=self.parent).count(), 1)
        self.signaler_une_absence(jour=timezone.localdate() - datetime.timedelta(days=10))  # rattrapage du registre
        self.assertEqual(Notification.objects.filter(destinataire=self.parent).count(), 1)
        self.assertEqual(Absence.objects.filter(eleve=self.e1).count(), 2)

    def test_une_annonce_de_classe_previent_les_eleves_et_leurs_parents(self):
        self.client.force_login(self.fondateur)
        reponse = self.client.post(reverse("communication:publier_annonce"), {"titre": "Sortie", "contenu": "RDV lundi", "portee": "ma_classe", "classe_ciblee": self.c6a.pk})
        self.assertEqual(reponse.status_code, 302)
        destinataires = set(Notification.objects.filter(titre="Sortie").values_list("destinataire_id", flat=True))
        self.assertEqual(destinataires, {self.e1.pk, self.e2.pk, self.e3.pk, self.parent.pk})  # la 6A et le parent de e1, pas la 6B ni l'auteur
        self.assertTrue(Notification.objects.get(destinataire=self.parent, titre="Sortie").url, reverse("communication:liste_annonces"))

    def test_une_annonce_de_toute_l_ecole_previent_tout_le_monde_sauf_l_auteur(self):
        from comptes.models import Utilisateur
        from comptes.roles import StatutCompte

        self.client.force_login(self.fondateur)
        self.client.post(reverse("communication:publier_annonce"), {"titre": "Rentrée", "contenu": "Bienvenue", "portee": "toute_ecole"})
        attendus = set(Utilisateur.objects.filter(etablissement=self.ecole, is_active=True, statut=StatutCompte.ACTIF).exclude(pk=self.fondateur.pk).values_list("pk", flat=True))
        self.assertEqual(set(Notification.objects.filter(titre="Rentrée").values_list("destinataire_id", flat=True)), attendus)
        self.assertFalse(Notification.objects.filter(destinataire=self.fondateur_b).exists())  # jamais une autre école

    def test_un_paiement_enregistre_previent_le_parent(self):
        self.client.force_login(self.comptable)
        self.client.post(reverse("finances:enregistrer_paiement"), {"matricule_eleve": self.e1.matricule, "tranche": "versement", "montant": "5000", "mode_paiement": "especes"})
        notification = Notification.objects.get(destinataire=self.parent, titre="Paiement enregistré")
        self.assertIn("5000", notification.message)
        self.assertEqual(self.envoi.call_count, 1)
        self.assertEqual(len(mail.outbox), 1)  # le courriel du reçu part toujours

    def test_une_declaration_validee_ne_donne_qu_une_notification(self):
        from finances.declarations import declarer

        declaration = declarer(parent=self.parent, eleve=self.e1, montant=5000, operateur="orange_money", reference="MP261019AB12", date_du_paiement=timezone.localdate())
        self.client.force_login(self.comptable)
        self.client.post(reverse("finances:enregistrer_paiement"), {
            "declaration": declaration.pk, "matricule_eleve": self.e1.matricule, "tranche": "versement", "montant": "5000", "mode_paiement": "mobile_money",
        })
        self.assertEqual(list(Notification.objects.filter(destinataire=self.parent).values_list("titre", flat=True)), ["Paiement validé"])


@EN_SERVICE
class EssaiEtCarteTests(PushBase):
    """La carte reste visible (avec la raison quand le téléphone ne peut pas recevoir) et chacun peut s'envoyer une notification d'essai."""

    def test_la_carte_est_toujours_dans_la_page_et_n_est_plus_cachee(self):
        self.client.force_login(self.parent)
        page = self.client.get(reverse("comptes:liste_notifications")).content.decode()
        self.assertRegex(page, r'<div class="card mb-3" data-push-carte>')
        self.assertIn("Vérification de votre téléphone", page)
        self.assertIn("data-push-essai", page)
        self.assertRegex(page, r"<button[^>]*data-push-essai[^>]*hidden")  # le bouton d'essai n'apparaît qu'une fois les notifications activées

    def test_le_script_dit_pourquoi_quand_le_telephone_ne_peut_pas_recevoir(self):
        from django.contrib.staticfiles import finders

        with open(finders.find("js/push.js"), encoding="utf-8") as fichier:
            script = fichier.read()
        self.assertIn("Ce navigateur ne permet pas les notifications sur téléphone", script)
        self.assertIn("Le téléphone ne répond pas", script)
        from comptes.templatetags.traductions import TEXTES_JS

        for texte in (
            "Ce navigateur ne permet pas les notifications sur téléphone. Ouvrez Yelenova avec Chrome (Android) ou installez l'application sur l'écran d'accueil (iPhone).",
            "Le téléphone ne répond pas : fermez et rouvrez l'application, puis réessayez.",
            "L'essai n'a pas pu être envoyé. Désactivez puis réactivez les notifications.",
            "Trop d'essais : réessayez dans une heure.",
            "Notification d'essai envoyée : elle doit arriver dans quelques secondes.",
        ):
            with self.subTest(texte=texte[:40]):
                self.assertIn(texte, TEXTES_JS)
                self.assertIn(texte, script)

    def test_l_essai_part_sur_les_appareils_de_la_personne_et_sur_eux_seuls(self):
        mien, un_autre = self.abonner(self.parent, "https://push.exemple.test/mien"), self.abonner(self.t1, "https://push.exemple.test/autre")
        with mock.patch("pywebpush.webpush") as envoi:
            reponse = self.poster("comptes:essai_push", {})
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json(), {"ok": True, "appareils": 1, "envoyees": 1})
        self.assertEqual(envoi.call_count, 1)
        self.assertEqual(envoi.call_args.kwargs["subscription_info"]["endpoint"], mien.endpoint)
        self.assertNotEqual(envoi.call_args.kwargs["subscription_info"]["endpoint"], un_autre.endpoint)
        message = json.loads(envoi.call_args.kwargs["data"])
        self.assertEqual(message["message"], "Les notifications fonctionnent sur ce téléphone.")
        self.assertEqual(message["url"], "/comptes/notifications/")
        self.assertFalse(Notification.objects.filter(destinataire=self.parent).exists())  # l'essai n'ajoute rien à l'historique

    def test_l_essai_est_en_arabe_pour_une_page_en_arabe(self):
        from comptes.langues import NOM_COOKIE_LANGUE

        self.abonner(self.parent)
        self.client.force_login(self.parent)
        self.client.cookies[NOM_COOKIE_LANGUE] = "ar"
        with mock.patch("pywebpush.webpush") as envoi:
            self.client.post(reverse("comptes:essai_push"), "{}", content_type="application/json")
        self.assertEqual(json.loads(envoi.call_args.kwargs["data"])["message"], "الإشعارات تعمل على هذا الهاتف.")

    def test_sans_appareil_active_l_essai_dit_non_sans_rien_envoyer(self):
        with mock.patch("pywebpush.webpush") as envoi:
            reponse = self.poster("comptes:essai_push", {})
        self.assertEqual(reponse.json(), {"ok": False, "appareils": 0, "envoyees": 0})
        envoi.assert_not_called()

    def test_un_appareil_qui_refuse_l_essai_est_signale(self):
        from pywebpush import WebPushException

        self.abonner(self.parent)
        with mock.patch("pywebpush.webpush", side_effect=WebPushException("refusé")):
            reponse = self.poster("comptes:essai_push", {})
        self.assertEqual(reponse.json(), {"ok": False, "appareils": 1, "envoyees": 0})

    def test_dix_essais_par_heure_au_plus(self):
        self.abonner(self.parent)
        with mock.patch("pywebpush.webpush"):
            for _ in range(10):
                self.assertEqual(self.poster("comptes:essai_push", {}).status_code, 200)
            self.assertEqual(self.poster("comptes:essai_push", {}).status_code, 429)

    def test_l_essai_ne_s_obtient_que_par_post_et_connecte(self):
        self.client.force_login(self.parent)
        self.assertEqual(self.client.get(reverse("comptes:essai_push")).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(reverse("comptes:essai_push"), "{}", content_type="application/json").status_code, 302)

    def test_la_page_arabe_de_la_carte_est_entierement_en_arabe(self):
        from comptes.outils_test_arabe import client_en, restes_hors_textes_saisis

        page = client_en(self.parent, "ar").get(reverse("comptes:liste_notifications")).content.decode("utf-8")
        self.assertNotIn("Vérification de votre téléphone", page)
        self.assertNotIn("Envoyer une notification d", page)
        self.assertEqual(restes_hors_textes_saisis(page, ("Français",)), [])


class EssaiEteintTests(PushBase):
    def test_sans_cles_l_essai_est_refuse(self):
        self.assertEqual(self.poster("comptes:essai_push", {}).status_code, 404)

    def test_le_developpeur_voit_pourquoi_les_notifications_sont_eteintes(self):
        developpeur = creer_compte(Role.DEVELOPPEUR, "developpeur@essai.test", self.ecole)
        self.client.force_login(developpeur)
        page = self.client.get(reverse("comptes:liste_notifications")).content.decode()
        self.assertIn("sont éteintes sur ce site", page)
        self.assertIn("VAPID_PUBLIC_KEY", page)
        self.assertIn("VAPID_PRIVATE_KEY", page)
        self.assertNotIn("data-push-carte", page)

    def test_les_autres_roles_ne_voient_aucun_message_technique(self):
        for compte in (self.parent, self.fondateur, self.t1, self.comptable):
            with self.subTest(role=compte.role):
                self.client.force_login(compte)
                page = self.client.get(reverse("comptes:liste_notifications")).content.decode()
                self.assertNotIn("VAPID", page)
                self.assertNotIn("sont éteintes sur ce site", page)
                self.assertNotIn("data-push-carte", page)

    def test_le_message_du_developpeur_est_en_arabe_sans_lettre_latine(self):
        from comptes.outils_test_arabe import client_en, restes_hors_textes_saisis

        developpeur = creer_compte(Role.DEVELOPPEUR, "developpeur-ar@essai.test", self.ecole)
        page = client_en(developpeur, "ar").get(reverse("comptes:liste_notifications")).content.decode("utf-8")
        self.assertIn("VAPID_PUBLIC_KEY", page)  # les noms des variables se recopient tels quels
        self.assertNotIn("sont éteintes sur ce site", page)
        restes = [r for r in restes_hors_textes_saisis(page, ("Français",)) if "VAPID" not in r]
        self.assertEqual(restes, [])
