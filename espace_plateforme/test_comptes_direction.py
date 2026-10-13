"""
Création d'un fondateur ou d'un administrateur général par le propriétaire de la plateforme, sans passer par la console.

Le mot de passe est généré, affiché une seule fois (jamais au journal d'audit), à remplacer dès la première connexion ; la
double authentification est imposée à ces rôles ; seuls ces deux rôles sont créables, et seulement par le propriétaire.
"""
from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from comptes.models import JournalAudit, Utilisateur
from comptes.roles import ROLES_2FA_OBLIGATOIRE, Role, StatutCompte
from comptes.utils import DUREE_MOT_DE_PASSE_PROVISOIRE_HEURES, generer_mot_de_passe_provisoire
from espace_plateforme.tests import creer_utilisateur_actif
from etablissement.models import Etablissement


def donnees(role="fondateur", email="Directeur@Ecole-Test.local", **extra):
    return {"role": role, "prenom": "Awa", "nom": "Keita", "email": email, **extra}


class DirectionBase(TestCase):
    def setUp(self):
        cache.clear()
        self.ecole = Etablissement.objects.create(nom="École de la direction")
        self.autre_ecole = Etablissement.objects.create(nom="Autre école")
        self.proprietaire = creer_utilisateur_actif("owner-direction@example.com", Role.DEVELOPPEUR, is_superuser=True)
        self.client.force_login(self.proprietaire)

    def url_creer(self, ecole=None):
        return reverse("espace_plateforme:creer_compte_direction", args=[(ecole or self.ecole).pk])

    def creer(self, **champs):
        return self.client.post(self.url_creer(), donnees(**champs))

    def url_renouveler(self, compte, ecole=None):
        return reverse("espace_plateforme:mot_de_passe_direction", args=[(ecole or self.ecole).pk, compte.pk])


class AccesTests(DirectionBase):
    def test_seul_le_proprietaire_ouvre_la_page_et_peut_creer(self):
        self.assertEqual(self.client.get(self.url_creer()).status_code, 200)
        non_proprietaires = {
            "développeur de l'école": creer_utilisateur_actif("dev@direction.test", Role.DEVELOPPEUR, self.ecole),
            "fondateur": creer_utilisateur_actif("fond@direction.test", Role.FONDATEUR, self.ecole),
            "secrétaire": creer_utilisateur_actif("sec@direction.test", Role.SECRETAIRE, self.ecole),
        }
        for libelle, compte in non_proprietaires.items():
            self.client.force_login(compte)
            with self.subTest(compte=libelle):
                self.assertEqual(self.client.get(self.url_creer()).status_code, 302)
                self.assertEqual(self.client.post(self.url_creer(), donnees()).status_code, 302)
        self.assertFalse(Utilisateur.objects.filter(email="directeur@ecole-test.local").exists())

    def test_visiteur_anonyme_redirige(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url_creer()).status_code, 302)

    def test_ecole_inexistante_introuvable(self):
        self.assertEqual(self.client.get(reverse("espace_plateforme:creer_compte_direction", args=[999999])).status_code, 404)

    def test_le_bouton_est_sur_la_page_des_comptes(self):
        reponse = self.client.get(reverse("espace_plateforme:voir_comptes_etablissement", args=[self.ecole.pk]))
        self.assertContains(reponse, self.url_creer())


class CreationTests(DirectionBase):
    def test_creation_d_un_fondateur(self):
        reponse = self.creer()
        self.assertEqual(reponse.status_code, 200)  # le mot de passe s'affiche tout de suite, pas de redirection
        compte = Utilisateur.objects.get(email="directeur@ecole-test.local")  # email mis en minuscules
        self.assertEqual((compte.role, compte.etablissement), (Role.FONDATEUR, self.ecole))
        self.assertEqual((compte.prenom, compte.nom), ("Awa", "Keita"))
        self.assertTrue(compte.is_active)
        self.assertEqual(compte.statut, StatutCompte.ACTIF)
        self.assertTrue(compte.email_verifie)
        self.assertFalse(compte.is_superuser or compte.is_staff)
        self.assertContains(reponse, "Ce mot de passe ne sera plus affiché")

    def test_creation_d_un_administrateur_general(self):
        self.creer(role="administrateur_general", email="admin@ecole-test.local")
        self.assertEqual(Utilisateur.objects.get(email="admin@ecole-test.local").role, Role.ADMINISTRATEUR_GENERAL)

    def test_le_mot_de_passe_affiche_est_le_bon_provisoire_et_expire(self):
        reponse = self.creer()
        mot_de_passe = reponse.context["mot_de_passe"]
        compte = Utilisateur.objects.get(email="directeur@ecole-test.local")
        self.assertTrue(compte.check_password(mot_de_passe))
        self.assertRegex(mot_de_passe, r"^[A-Za-z2-9]{4}-[A-Za-z2-9]{4}-[A-Za-z2-9]{4}$")  # 12 caractères : accès total
        self.assertContains(reponse, mot_de_passe)
        self.assertTrue(compte.doit_changer_mot_de_passe)
        ecart = compte.mot_de_passe_provisoire_expire_le - (timezone.now() + timedelta(hours=DUREE_MOT_DE_PASSE_PROVISOIRE_HEURES))
        self.assertLess(abs(ecart), timedelta(minutes=2))

    def test_le_mot_de_passe_n_est_jamais_conserve_ni_journalise(self):
        reponse = self.creer()
        mot_de_passe = reponse.context["mot_de_passe"]
        entree = JournalAudit.objects.get(action="creation_compte_direction")
        self.assertEqual(entree.acteur, self.proprietaire)
        self.assertEqual(entree.cible, "directeur@ecole-test.local")
        self.assertEqual(entree.details["role"], "fondateur")
        self.assertEqual(entree.details["etablissement"], self.ecole.nom)
        self.assertNotIn(mot_de_passe, f"{entree.cible} {entree.details}")
        self.assertNotIn(mot_de_passe, str(list(self.client.session.items())))
        # une seconde visite de la page ne le remontre pas
        self.assertNotContains(self.client.get(self.url_creer()), mot_de_passe)

    def test_email_deja_utilise_refuse_sans_tenir_compte_de_la_casse(self):
        creer_utilisateur_actif("existe@direction.test", Role.ENSEIGNANT, self.autre_ecole)
        reponse = self.creer(email="EXISTE@direction.TEST")
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Un compte existe déjà avec cet email")
        self.assertEqual(Utilisateur.objects.filter(email__iexact="existe@direction.test").count(), 1)
        self.assertFalse(JournalAudit.objects.filter(action="creation_compte_direction").exists())

    def test_seuls_ces_deux_roles_sont_creables(self):
        for role in ("developpeur", "enseignant", "parent", "eleve", "super_administrateur", "comptable", "n_importe_quoi", ""):
            with self.subTest(role=role):
                reponse = self.creer(role=role, email=f"{role or 'vide'}@direction.test")
                self.assertEqual(reponse.status_code, 200)
                self.assertFalse(Utilisateur.objects.filter(email=f"{role or 'vide'}@direction.test").exists())

    def test_champs_obligatoires(self):
        reponse = self.client.post(self.url_creer(), {"role": "fondateur", "prenom": "", "nom": "", "email": "pas-un-email"})
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(Utilisateur.objects.filter(role=Role.FONDATEUR).count(), 0)

    def test_le_compte_est_rattache_a_l_ecole_de_l_url(self):
        self.client.post(self.url_creer(self.autre_ecole), donnees(email="autre@direction.test"))
        self.assertEqual(Utilisateur.objects.get(email="autre@direction.test").etablissement, self.autre_ecole)

    def test_ces_roles_ont_la_double_authentification_obligatoire(self):
        self.assertIn(Role.FONDATEUR, ROLES_2FA_OBLIGATOIRE)
        self.assertIn(Role.ADMINISTRATEUR_GENERAL, ROLES_2FA_OBLIGATOIRE)

    def test_la_premiere_connexion_oblige_a_changer_le_mot_de_passe(self):
        reponse = self.creer()
        mot_de_passe = reponse.context["mot_de_passe"]
        self.client.logout()
        connexion = self.client.post(reverse("comptes:connexion"), {"email": "directeur@ecole-test.local", "mot_de_passe": mot_de_passe})
        self.assertEqual(connexion.status_code, 302)
        page = self.client.get(reverse("comptes:redirection_tableau_de_bord"), follow=True)
        self.assertEqual(page.status_code, 200)
        chemins = " ".join(url for url, _ in page.redirect_chain)
        self.assertTrue("changer-mot-de-passe" in chemins or "2fa" in chemins, chemins)  # jamais le tableau de bord directement


class RenouvellementTests(DirectionBase):
    def setUp(self):
        super().setUp()
        self.creer()
        self.compte = Utilisateur.objects.get(email="directeur@ecole-test.local")
        self.ancien = "ancien-mot-de-passe-Z9!"
        self.compte.set_password(self.ancien)
        self.compte.tentatives_connexion_echouees = 4
        self.compte.verrouille_jusqu_a = timezone.now() + timedelta(minutes=10)
        self.compte.mot_de_passe_provisoire_expire_le = timezone.now() - timedelta(hours=1)  # expiré
        self.compte.save()

    def test_nouveau_mot_de_passe_provisoire(self):
        reponse = self.client.post(self.url_renouveler(self.compte))
        self.assertEqual(reponse.status_code, 200)
        mot_de_passe = reponse.context["mot_de_passe"]
        self.compte.refresh_from_db()
        self.assertTrue(self.compte.check_password(mot_de_passe))
        self.assertFalse(self.compte.check_password(self.ancien))
        self.assertTrue(self.compte.doit_changer_mot_de_passe)
        self.assertGreater(self.compte.mot_de_passe_provisoire_expire_le, timezone.now())
        self.assertEqual(self.compte.tentatives_connexion_echouees, 0)
        self.assertIsNone(self.compte.verrouille_jusqu_a)  # un compte verrouillé redevient utilisable
        entree = JournalAudit.objects.get(action="mot_de_passe_provisoire_direction")
        self.assertNotIn(mot_de_passe, f"{entree.cible} {entree.details}")

    def test_refuse_pour_un_autre_role_ou_une_autre_ecole(self):
        enseignant = creer_utilisateur_actif("prof@direction.test", Role.ENSEIGNANT, self.ecole)
        developpeur = creer_utilisateur_actif("dev2@direction.test", Role.DEVELOPPEUR, self.ecole)
        for cible in (enseignant, developpeur, self.proprietaire):
            with self.subTest(role=cible.role):
                self.assertEqual(self.client.post(self.url_renouveler(cible)).status_code, 404)
        self.assertEqual(self.client.post(self.url_renouveler(self.compte, self.autre_ecole)).status_code, 404)
        enseignant.refresh_from_db()
        self.assertTrue(enseignant.check_password("MotDePasse#2026"))  # intact

    def test_post_seulement_et_proprietaire_seulement(self):
        self.assertEqual(self.client.get(self.url_renouveler(self.compte)).status_code, 405)
        dev = creer_utilisateur_actif("dev3@direction.test", Role.DEVELOPPEUR, self.ecole)
        self.client.force_login(dev)
        self.assertEqual(self.client.post(self.url_renouveler(self.compte)).status_code, 302)
        self.compte.refresh_from_db()
        self.assertTrue(self.compte.check_password(self.ancien))

    def test_le_bouton_n_est_propose_que_pour_les_comptes_de_direction(self):
        creer_utilisateur_actif("prof2@direction.test", Role.ENSEIGNANT, self.ecole)
        page = self.client.get(reverse("espace_plateforme:voir_comptes_etablissement", args=[self.ecole.pk]))
        self.assertContains(page, self.url_renouveler(self.compte))
        self.assertContains(page, "Nouveau mot de passe provisoire", count=1)


class GenerateurTests(TestCase):
    def test_format_par_defaut_inchange(self):
        self.assertRegex(generer_mot_de_passe_provisoire(), r"^[A-Za-z2-9]{4}-[A-Za-z2-9]{4}$")

    def test_trois_groupes(self):
        self.assertRegex(generer_mot_de_passe_provisoire(groupes=3), r"^[A-Za-z2-9]{4}-[A-Za-z2-9]{4}-[A-Za-z2-9]{4}$")


class MessageDExpirationTests(DirectionBase):
    """Un mot de passe provisoire expiré : on dit à qui s'adresser selon le rôle, une fois le mot de passe vérifié."""

    def expirer_et_se_connecter(self, compte, mot_de_passe):
        compte.doit_changer_mot_de_passe = True
        compte.mot_de_passe_provisoire_expire_le = timezone.now() - timedelta(hours=1)
        compte.set_password(mot_de_passe)
        compte.save()
        self.client.logout()
        return self.client.post(reverse("comptes:connexion"), {"email": compte.email, "mot_de_passe": mot_de_passe})

    def test_un_compte_de_direction_est_renvoye_vers_l_administrateur_de_la_plateforme(self):
        for role in ("fondateur", "administrateur_general"):
            self.client.force_login(self.proprietaire)
            self.creer(role=role, email=f"{role}@expire.test")
            compte = Utilisateur.objects.get(email=f"{role}@expire.test")
            with self.subTest(role=role):
                reponse = self.expirer_et_se_connecter(compte, "Mot-de-passe-Expire-9!")
                self.assertContains(reponse, "a expiré")
                self.assertContains(reponse, "administrateur de la plateforme")
                self.assertNotContains(reponse, "secrétariat")

    def test_un_eleve_est_renvoye_vers_le_secretariat(self):
        eleve = creer_utilisateur_actif("eleve@expire.test", Role.ELEVE, self.ecole, matricule="EXP-1")
        reponse = self.expirer_et_se_connecter(eleve, "Mot-de-passe-Expire-9!")
        self.assertContains(reponse, "Demandez-en un nouveau au secrétariat")
        self.assertNotContains(reponse, "administrateur de la plateforme")

    def test_un_mauvais_mot_de_passe_ne_revele_rien(self):
        self.creer()
        compte = Utilisateur.objects.get(email="directeur@ecole-test.local")
        self.expirer_et_se_connecter(compte, "Mot-de-passe-Expire-9!")
        reponse = self.client.post(reverse("comptes:connexion"), {"email": compte.email, "mot_de_passe": "faux"})
        self.assertContains(reponse, "Email ou mot de passe incorrect")
        self.assertNotContains(reponse, "expiré")
