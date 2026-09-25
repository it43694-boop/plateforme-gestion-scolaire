from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from comptes.models import CodeVerificationEmail, Utilisateur
from comptes.roles import Role, StatutCompte
from permissions_matrix.models import PermissionMatrix
from permissions_matrix.modules import Module


def creer_utilisateur_actif(email, role, **kwargs):
    utilisateur = Utilisateur(email=email, prenom="Test", nom="Utilisateur", role=role, **kwargs)
    utilisateur.set_password("MotDePasse#2026")
    utilisateur.statut = StatutCompte.ACTIF
    utilisateur.is_active = True
    utilisateur.full_clean(exclude=["password"])
    utilisateur.save()
    return utilisateur


class UtilisateurModelTests(TestCase):
    def test_creation_utilisateur_basique(self):
        u = creer_utilisateur_actif("prof@example.com", Role.ENSEIGNANT)
        self.assertTrue(u.check_password("MotDePasse#2026"))
        self.assertEqual(u.nom_complet, "Test Utilisateur")

    def test_matricule_genere_automatiquement_pour_eleve(self):
        eleve = creer_utilisateur_actif("eleve1@example.com", Role.ELEVE)
        self.assertIsNotNone(eleve.matricule)
        self.assertTrue(eleve.matricule.startswith(str(timezone.now().year)))

    def test_matricule_refuse_pour_role_non_eleve(self):
        u = Utilisateur(email="x@example.com", prenom="A", nom="B", role=Role.PARENT, matricule="20260001")
        with self.assertRaises(Exception):
            u.full_clean()

    def test_telephone_unique_dans_toute_la_base(self):
        creer_utilisateur_actif("parent1@example.com", Role.PARENT, telephone="70000001", profession="Commerçant")
        with self.assertRaises(Exception):
            creer_utilisateur_actif("parent2@example.com", Role.PARENT, telephone="70000001", profession="Autre")

    def test_verrouillage_apres_echecs_repetes(self):
        u = creer_utilisateur_actif("verrou@example.com", Role.ENSEIGNANT)
        for _ in range(5):
            u.enregistrer_echec_connexion()
        self.assertTrue(u.verrouille())

    def test_reinitialisation_tentatives(self):
        u = creer_utilisateur_actif("verrou2@example.com", Role.ENSEIGNANT)
        u.enregistrer_echec_connexion()
        u.reinitialiser_tentatives_connexion()
        self.assertEqual(u.tentatives_connexion_echouees, 0)
        self.assertFalse(u.verrouille())


class CodeVerificationTests(TestCase):
    def test_code_expire_apres_delai(self):
        u = creer_utilisateur_actif("code@example.com", Role.ENSEIGNANT)
        code = CodeVerificationEmail.objects.create(
            utilisateur=u, code="123456", expire_le=timezone.now() - timedelta(minutes=1),
        )
        self.assertFalse(code.est_valide())

    def test_code_valide_avant_expiration(self):
        u = creer_utilisateur_actif("code2@example.com", Role.ENSEIGNANT)
        code = CodeVerificationEmail.objects.create(utilisateur=u, code="654321")
        self.assertTrue(code.est_valide())

    def test_code_deja_utilise_est_invalide(self):
        u = creer_utilisateur_actif("code3@example.com", Role.ENSEIGNANT)
        code = CodeVerificationEmail.objects.create(utilisateur=u, code="111111", utilise=True)
        self.assertFalse(code.est_valide())

    def test_code_invalide_apres_cinq_echecs(self):
        u = creer_utilisateur_actif("code4@example.com", Role.ENSEIGNANT)
        code = CodeVerificationEmail.objects.create(utilisateur=u, code="222222")
        for _ in range(5):
            code.enregistrer_echec()
        self.assertFalse(code.est_valide())
        self.assertTrue(code.utilise)


class TableauDeBordAccesAnonymeTests(TestCase):
    """
    Un visiteur non connecté qui accède directement à /comptes/tableau-de-bord/
    doit être redirigé vers la connexion, jamais provoquer une erreur serveur.
    """

    def test_anonyme_redirige_vers_connexion_sans_planter(self):
        reponse = self.client.get(reverse("comptes:redirection_tableau_de_bord"))
        self.assertEqual(reponse.status_code, 302)
        self.assertIn("/comptes/connexion/", reponse.url)


class NavigationProprietairePlateformeTests(TestCase):
    """
    Un développeur sans établissement (le propriétaire de la plateforme)
    ne doit jamais voir de liens vers des pages qui exigent un
    établissement - ils le renverraient systématiquement en erreur.
    """

    def test_proprietaire_sans_etablissement_ne_voit_pas_les_liens_par_ecole(self):
        proprietaire = Utilisateur(
            email="proprio-nav@example.com", prenom="Test", nom="Proprio", role=Role.DEVELOPPEUR,
            is_superuser=True, is_staff=True, statut=StatutCompte.ACTIF, is_active=True,
        )
        proprietaire.set_password("MotDePasse#2026")
        proprietaire.full_clean(exclude=["password"])
        proprietaire.save()
        self.client.force_login(proprietaire)
        reponse = self.client.get(reverse("comptes:redirection_tableau_de_bord"))
        self.assertNotContains(reponse, "Matrice de permissions")
        self.assertNotContains(reponse, "Journal d'audit")

    def test_developpeur_avec_etablissement_voit_les_liens(self):
        from etablissement.models import Etablissement
        from permissions_matrix.models import PermissionMatrix
        etablissement = Etablissement.objects.create(nom="École Nav Test")
        PermissionMatrix.seed_pour(etablissement)
        developpeur = Utilisateur(
            email="dev-nav@example.com", prenom="Test", nom="Dev", role=Role.DEVELOPPEUR,
            etablissement=etablissement, statut=StatutCompte.ACTIF, is_active=True,
        )
        developpeur.set_password("MotDePasse#2026")
        developpeur.full_clean(exclude=["password"])
        developpeur.save()
        self.client.force_login(developpeur)
        reponse = self.client.get(reverse("comptes:redirection_tableau_de_bord"))
        self.assertContains(reponse, "Matrice de permissions")
        self.assertContains(reponse, "Journal d'audit")


class ChangerMotDePasseTests(TestCase):
    def setUp(self):
        self.utilisateur = creer_utilisateur_actif("changer-mdp@example.com", Role.ENSEIGNANT)

    def test_changement_avec_ancien_mot_de_passe_correct(self):
        self.client.force_login(self.utilisateur)
        reponse = self.client.post(reverse("comptes:changer_mot_de_passe"), {
            "old_password": "MotDePasse#2026",
            "new_password1": "NouveauMdp#2027",
            "new_password2": "NouveauMdp#2027",
        })
        self.assertEqual(reponse.status_code, 302)
        self.utilisateur.refresh_from_db()
        self.assertTrue(self.utilisateur.check_password("NouveauMdp#2027"))

    def test_reste_connecte_apres_changement(self):
        self.client.force_login(self.utilisateur)
        self.client.post(reverse("comptes:changer_mot_de_passe"), {
            "old_password": "MotDePasse#2026",
            "new_password1": "NouveauMdp#2027",
            "new_password2": "NouveauMdp#2027",
        })
        reponse = self.client.get(reverse("comptes:redirection_tableau_de_bord"))
        self.assertEqual(reponse.status_code, 200)  # pas redirigé vers la connexion

    def test_ancien_mot_de_passe_incorrect_refuse(self):
        self.client.force_login(self.utilisateur)
        self.client.post(reverse("comptes:changer_mot_de_passe"), {
            "old_password": "MauvaisMotDePasse",
            "new_password1": "NouveauMdp#2027",
            "new_password2": "NouveauMdp#2027",
        })
        self.utilisateur.refresh_from_db()
        self.assertTrue(self.utilisateur.check_password("MotDePasse#2026"))

    def test_non_connecte_redirige_vers_connexion(self):
        reponse = self.client.get(reverse("comptes:changer_mot_de_passe"))
        self.assertEqual(reponse.status_code, 302)
        self.assertIn("/comptes/connexion/", reponse.url)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ChangerEmailTests(TestCase):
    def setUp(self):
        self.utilisateur = creer_utilisateur_actif("ancien-email@example.com", Role.ENSEIGNANT)

    def test_changement_avec_mot_de_passe_correct(self):
        self.client.force_login(self.utilisateur)
        reponse = self.client.post(reverse("comptes:changer_email"), {
            "nouvel_email": "nouveau-email@example.com", "mot_de_passe": "MotDePasse#2026",
        })
        self.assertEqual(reponse.status_code, 302)
        self.utilisateur.refresh_from_db()
        self.assertEqual(self.utilisateur.email, "nouveau-email@example.com")

    def test_notification_envoyee_a_lancienne_adresse(self):
        self.client.force_login(self.utilisateur)
        self.client.post(reverse("comptes:changer_email"), {
            "nouvel_email": "nouveau-email2@example.com", "mot_de_passe": "MotDePasse#2026",
        })
        self.assertEqual(mail.outbox[0].to, ["ancien-email@example.com"])

    def test_mot_de_passe_incorrect_refuse(self):
        self.client.force_login(self.utilisateur)
        self.client.post(reverse("comptes:changer_email"), {
            "nouvel_email": "nouveau-email3@example.com", "mot_de_passe": "MauvaisMotDePasse",
        })
        self.utilisateur.refresh_from_db()
        self.assertEqual(self.utilisateur.email, "ancien-email@example.com")

    def test_email_deja_utilise_refuse(self):
        creer_utilisateur_actif("deja-pris@example.com", Role.ENSEIGNANT)
        self.client.force_login(self.utilisateur)
        self.client.post(reverse("comptes:changer_email"), {
            "nouvel_email": "deja-pris@example.com", "mot_de_passe": "MotDePasse#2026",
        })
        self.utilisateur.refresh_from_db()
        self.assertEqual(self.utilisateur.email, "ancien-email@example.com")


class DeuxFacteursTests(TestCase):
    def setUp(self):
        self.utilisateur = creer_utilisateur_actif("2fa@example.com", Role.DEVELOPPEUR)

    def test_activer_avec_bon_code_active_le_compte(self):
        import pyotp
        self.client.force_login(self.utilisateur)
        self.client.get(reverse("comptes:activer_2fa"))  # génère le secret en attente (session)
        secret = self.client.session["secret_2fa_en_attente"]
        code = pyotp.TOTP(secret).now()

        reponse = self.client.post(reverse("comptes:activer_2fa"), {"code": code})
        self.assertEqual(reponse.status_code, 302)
        self.utilisateur.refresh_from_db()
        self.assertTrue(self.utilisateur.deux_facteurs_actif)
        self.assertEqual(self.utilisateur.totp_secret, secret)

    def test_activer_avec_mauvais_code_najoute_pas(self):
        self.client.force_login(self.utilisateur)
        self.client.get(reverse("comptes:activer_2fa"))
        self.client.post(reverse("comptes:activer_2fa"), {"code": "000000"})
        self.utilisateur.refresh_from_db()
        self.assertFalse(self.utilisateur.deux_facteurs_actif)

    def test_connexion_avec_2fa_active_ne_connecte_pas_avant_le_second_facteur(self):
        import pyotp
        secret = self.utilisateur.generer_secret_2fa()
        self.utilisateur.totp_secret = secret
        self.utilisateur.deux_facteurs_actif = True
        self.utilisateur.save(update_fields=["totp_secret", "deux_facteurs_actif"])

        reponse = self.client.post(reverse("comptes:connexion"), {
            "email": "2fa@example.com", "mot_de_passe": "MotDePasse#2026",
        })
        self.assertFalse(reponse.wsgi_request.user.is_authenticated)
        self.assertRedirects(reponse, reverse("comptes:verifier_2fa"))

        code = pyotp.TOTP(secret).now()
        reponse_2fa = self.client.post(reverse("comptes:verifier_2fa"), {"code": code})
        self.assertEqual(reponse_2fa.status_code, 302)
        self.assertTrue(self.client.session.get("_auth_user_id"))

    def test_connexion_avec_2fa_active_refuse_mauvais_code(self):
        secret = self.utilisateur.generer_secret_2fa()
        self.utilisateur.totp_secret = secret
        self.utilisateur.deux_facteurs_actif = True
        self.utilisateur.save(update_fields=["totp_secret", "deux_facteurs_actif"])

        self.client.post(reverse("comptes:connexion"), {
            "email": "2fa@example.com", "mot_de_passe": "MotDePasse#2026",
        })
        reponse = self.client.post(reverse("comptes:verifier_2fa"), {"code": "000000"})
        self.assertFalse(reponse.wsgi_request.user.is_authenticated)

    def test_desactiver_avec_bon_code(self):
        import pyotp
        secret = self.utilisateur.generer_secret_2fa()
        self.utilisateur.totp_secret = secret
        self.utilisateur.deux_facteurs_actif = True
        self.utilisateur.save(update_fields=["totp_secret", "deux_facteurs_actif"])

        self.client.force_login(self.utilisateur)
        code = pyotp.TOTP(secret).now()
        reponse = self.client.post(reverse("comptes:desactiver_2fa"), {"code": code})
        self.assertEqual(reponse.status_code, 302)
        self.utilisateur.refresh_from_db()
        self.assertFalse(self.utilisateur.deux_facteurs_actif)
        self.assertEqual(self.utilisateur.totp_secret, "")


class PermissionMatrixTests(TestCase):
    def test_developpeur_a_acces_a_tout_meme_sans_ligne_matrice(self):
        self.assertTrue(PermissionMatrix.a_acces(Role.DEVELOPPEUR, Module.ESPACE_DEVELOPPEUR))
        self.assertTrue(PermissionMatrix.a_acces(Role.FONDATEUR, Module.FINANCES))

    def test_comptable_a_acces_aux_finances_par_defaut(self):
        self.assertTrue(PermissionMatrix.a_acces(Role.COMPTABLE, Module.FINANCES))
        self.assertTrue(PermissionMatrix.a_acces(Role.COMPTABLE, Module.CAISSE))

    def test_comptable_na_pas_acces_a_la_bibliotheque_par_defaut(self):
        self.assertFalse(PermissionMatrix.a_acces(Role.COMPTABLE, Module.BIBLIOTHEQUE))

    def test_secretaire_sans_finances_ni_caisse_par_defaut(self):
        self.assertFalse(PermissionMatrix.a_acces(Role.SECRETAIRE, Module.FINANCES))
        self.assertFalse(PermissionMatrix.a_acces(Role.SECRETAIRE, Module.CAISSE))

    def test_eleve_et_parent_ont_acces_aux_absences(self):
        self.assertTrue(PermissionMatrix.a_acces(Role.ELEVE, Module.ABSENCES))
        self.assertTrue(PermissionMatrix.a_acces(Role.PARENT, Module.ABSENCES))

    def test_enseignant_na_pas_acces_au_suivi_des_cours(self):
        self.assertFalse(PermissionMatrix.a_acces(Role.ENSEIGNANT, Module.SUIVI_DES_COURS))
        self.assertTrue(PermissionMatrix.a_acces(Role.RESPONSABLE_PEDAGOGIQUE, Module.SUIVI_DES_COURS))

    def test_personnel_generique_sans_module_par_defaut(self):
        self.assertEqual(PermissionMatrix.modules_autorises(Role.PERSONNEL), [])

    def test_super_administrateur_na_pas_lespace_developpeur(self):
        self.assertFalse(PermissionMatrix.a_acces(Role.SUPER_ADMINISTRATEUR, Module.ESPACE_DEVELOPPEUR))
        self.assertTrue(PermissionMatrix.a_acces(Role.SUPER_ADMINISTRATEUR, Module.FINANCES))

    def test_reglage_developpeur_prend_le_dessus(self):
        # Le développeur active la bibliothèque pour le comptable, sans toucher au code.
        regle, _ = PermissionMatrix.objects.get_or_create(role=Role.COMPTABLE, module=Module.BIBLIOTHEQUE)
        regle.autorise = True
        regle.save()
        self.assertTrue(PermissionMatrix.a_acces(Role.COMPTABLE, Module.BIBLIOTHEQUE))


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ParcoursInscriptionTests(TestCase):
    def setUp(self):
        from etablissement.models import Etablissement
        Etablissement.objects.create(nom="École de test inscription")

    def test_inscription_envoie_un_code_et_cree_un_compte_inactif(self):
        reponse = self.client.post(reverse("comptes:inscription"), {
            "prenom": "Aïcha", "nom": "Traoré", "email": "aicha@example.com",
            "telephone": "70123456", "profession": "Enseignante", "role": Role.PARENT.value,
            "mot_de_passe": "MotDePasse#2026", "confirmation_mot_de_passe": "MotDePasse#2026",
        })
        self.assertEqual(reponse.status_code, 302)
        utilisateur = Utilisateur.objects.get(email="aicha@example.com")
        self.assertFalse(utilisateur.is_active)
        self.assertEqual(utilisateur.statut, StatutCompte.EN_ATTENTE_VERIFICATION_EMAIL)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("code de vérification", mail.outbox[0].body.lower())

    def test_verification_email_passe_le_compte_en_attente_de_validation(self):
        self.client.post(reverse("comptes:inscription"), {
            "prenom": "Moussa", "nom": "Diarra", "email": "moussa@example.com",
            "telephone": "70123457", "profession": "Commerçant", "role": Role.PARENT.value,
            "mot_de_passe": "MotDePasse#2026", "confirmation_mot_de_passe": "MotDePasse#2026",
        })
        utilisateur = Utilisateur.objects.get(email="moussa@example.com")
        code = utilisateur.codes_verification.first().code
        self.client.post(reverse("comptes:verifier_email"), {"code": code})
        utilisateur.refresh_from_db()
        self.assertEqual(utilisateur.statut, StatutCompte.EN_ATTENTE_VALIDATION)

    def test_code_verrouille_apres_cinq_tentatives_incorrectes(self):
        self.client.post(reverse("comptes:inscription"), {
            "prenom": "Fanta", "nom": "Sissoko", "email": "fanta@example.com",
            "telephone": "70123480", "profession": "Institutrice", "role": Role.PARENT.value,
            "mot_de_passe": "MotDePasse#2026", "confirmation_mot_de_passe": "MotDePasse#2026",
        })
        utilisateur = Utilisateur.objects.get(email="fanta@example.com")
        bon_code = utilisateur.codes_verification.first().code
        for _ in range(5):
            self.client.post(reverse("comptes:verifier_email"), {"code": "000000"})
        # Même le bon code ne fonctionne plus : il a été invalidé après 5 échecs.
        self.client.post(reverse("comptes:verifier_email"), {"code": bon_code})
        utilisateur.refresh_from_db()
        self.assertEqual(utilisateur.statut, StatutCompte.EN_ATTENTE_VERIFICATION_EMAIL)

    def test_connexion_refusee_tant_que_compte_non_valide(self):
        u = Utilisateur(
            email="attente@example.com", prenom="A", nom="B", role=Role.PARENT,
            telephone="70123458", profession="X", statut=StatutCompte.EN_ATTENTE_VALIDATION,
        )
        u.set_password("MotDePasse#2026")
        u.full_clean(exclude=["password"])
        u.save()
        reponse = self.client.post(reverse("comptes:connexion"), {
            "email": "attente@example.com", "mot_de_passe": "MotDePasse#2026",
        })
        self.assertFalse(reponse.wsgi_request.user.is_authenticated)


class ValidationCompteTests(TestCase):
    def setUp(self):
        self.secretaire = creer_utilisateur_actif("secretaire@example.com", Role.SECRETAIRE)
        self.en_attente = Utilisateur(
            email="futur@example.com", prenom="Futur", nom="Élève-Parent", role=Role.PARENT,
            telephone="70123459", profession="X", statut=StatutCompte.EN_ATTENTE_VALIDATION,
        )
        self.en_attente.set_password("MotDePasse#2026")
        self.en_attente.full_clean(exclude=["password"])
        self.en_attente.save()

    def test_secretaire_peut_valider_un_compte(self):
        self.client.force_login(self.secretaire)
        self.client.post(reverse("comptes:valider_compte", args=[self.en_attente.id]))
        self.en_attente.refresh_from_db()
        self.assertEqual(self.en_attente.statut, StatutCompte.ACTIF)
        self.assertTrue(self.en_attente.is_active)

    def test_enseignant_ne_peut_pas_valider_un_compte(self):
        enseignant = creer_utilisateur_actif("prof2@example.com", Role.ENSEIGNANT)
        self.client.force_login(enseignant)
        reponse = self.client.post(reverse("comptes:valider_compte", args=[self.en_attente.id]))
        self.assertEqual(reponse.status_code, 403)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class MotDePasseOublieEleveTests(TestCase):
    def test_lien_part_chez_le_parent_jamais_sur_lemail_auto_genere(self):
        parent = creer_utilisateur_actif(
            "parent-eleve@example.com", Role.PARENT, telephone="70123460", profession="X",
        )
        eleve = creer_utilisateur_actif("auto-genere-eleve@example.com", Role.ELEVE)
        eleve.parents_lies.add(parent)

        self.client.post(reverse("comptes:mot_de_passe_oublie"), {"identifiant": eleve.matricule})

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [parent.email])
        self.assertNotIn(eleve.email, mail.outbox[0].to)


class IsolationCompteEnAttenteTests(TestCase):
    def test_secretaire_ne_voit_que_les_demandes_de_son_etablissement(self):
        from etablissement.models import Etablissement

        ecole_a = Etablissement.objects.create(nom="École Attente A")
        ecole_b = Etablissement.objects.create(nom="École Attente B")

        secretaire_a = creer_utilisateur_actif("sec-attente-a@example.com", Role.SECRETAIRE, etablissement=ecole_a)

        demandeur_a = Utilisateur(
            email="demandeur-a@example.com", prenom="A", nom="A", role=Role.PARENT,
            telephone="70999901", profession="X", etablissement=ecole_a,
            statut=StatutCompte.EN_ATTENTE_VALIDATION,
        )
        demandeur_a.set_password("MotDePasse#2026")
        demandeur_a.full_clean(exclude=["password"])
        demandeur_a.save()

        demandeur_b = Utilisateur(
            email="demandeur-b@example.com", prenom="B", nom="B", role=Role.PARENT,
            telephone="70999902", profession="X", etablissement=ecole_b,
            statut=StatutCompte.EN_ATTENTE_VALIDATION,
        )
        demandeur_b.set_password("MotDePasse#2026")
        demandeur_b.full_clean(exclude=["password"])
        demandeur_b.save()

        self.client.force_login(secretaire_a)
        reponse = self.client.get(reverse("comptes:comptes_en_attente"))
        emails = [c.email for c in reponse.context["comptes"]]
        self.assertIn("demandeur-a@example.com", emails)
        self.assertNotIn("demandeur-b@example.com", emails)

    def test_secretaire_ne_peut_pas_valider_un_compte_dune_autre_ecole(self):
        from etablissement.models import Etablissement

        ecole_a = Etablissement.objects.create(nom="École Valid A")
        ecole_b = Etablissement.objects.create(nom="École Valid B")
        secretaire_a = creer_utilisateur_actif("sec-valid-a@example.com", Role.SECRETAIRE, etablissement=ecole_a)

        demandeur_b = Utilisateur(
            email="demandeur-valid-b@example.com", prenom="B", nom="B", role=Role.PARENT,
            telephone="70999903", profession="X", etablissement=ecole_b,
            statut=StatutCompte.EN_ATTENTE_VALIDATION,
        )
        demandeur_b.set_password("MotDePasse#2026")
        demandeur_b.full_clean(exclude=["password"])
        demandeur_b.save()

        self.client.force_login(secretaire_a)
        reponse = self.client.post(reverse("comptes:valider_compte", args=[demandeur_b.id]))
        self.assertEqual(reponse.status_code, 404)
        demandeur_b.refresh_from_db()
        self.assertEqual(demandeur_b.statut, StatutCompte.EN_ATTENTE_VALIDATION)


class FileAttenteEmailsTests(TestCase):
    """
    La file d'attente d'emails (comptes/mail.py + la commande envoyer_emails)
    n'avait aucun test malgré son rôle critique : si elle est cassée, plus
    aucun email ne part en production. Vérifie le comportement réel, pas
    seulement que le code s'exécute sans planter.
    """

    def test_envoyer_email_synchrone_quand_email_async_desactive(self):
        from comptes.mail import envoyer_email
        with override_settings(EMAIL_ASYNC=False):
            envoyer_email(
                sujet="Test sync", contenu="Contenu", expediteur="test@example.com",
                destinataires=["dest@example.com"],
            )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "Test sync")

    def test_envoyer_email_mis_en_file_quand_email_async_active(self):
        from comptes.mail import envoyer_email
        from comptes.models import EmailOutbox
        with override_settings(EMAIL_ASYNC=True):
            envoyer_email(
                sujet="Test async", contenu="Contenu", expediteur="test@example.com",
                destinataires=["dest@example.com"],
            )
        self.assertEqual(len(mail.outbox), 0)  # rien envoyé directement
        self.assertEqual(EmailOutbox.objects.filter(sujet="Test async").count(), 1)

    def test_commande_envoie_un_message_en_attente(self):
        from django.core.management import call_command
        from comptes.models import EmailOutbox
        message = EmailOutbox.objects.create(
            sujet="En attente", contenu="Contenu", expediteur="test@example.com",
            destinataires=["dest@example.com"],
        )
        call_command("envoyer_emails")
        message.refresh_from_db()
        self.assertIsNotNone(message.envoye_le)
        self.assertEqual(len(mail.outbox), 1)

    def test_message_deja_envoye_nest_pas_renvoye(self):
        from django.core.management import call_command
        from comptes.models import EmailOutbox
        EmailOutbox.objects.create(
            sujet="Déjà parti", contenu="Contenu", expediteur="test@example.com",
            destinataires=["dest@example.com"], envoye_le=timezone.now(),
        )
        call_command("envoyer_emails")
        self.assertEqual(len(mail.outbox), 0)

    def test_message_verrouille_recemment_nest_pas_retente(self):
        from django.core.management import call_command
        from comptes.models import EmailOutbox
        EmailOutbox.objects.create(
            sujet="En cours de traitement", contenu="Contenu", expediteur="test@example.com",
            destinataires=["dest@example.com"], verrouille_le=timezone.now(),
        )
        call_command("envoyer_emails")
        self.assertEqual(len(mail.outbox), 0)

    def test_verrou_perime_est_retente(self):
        from django.core.management import call_command
        from comptes.models import EmailOutbox
        message = EmailOutbox.objects.create(
            sujet="Verrou périmé", contenu="Contenu", expediteur="test@example.com",
            destinataires=["dest@example.com"], verrouille_le=timezone.now() - timedelta(minutes=20),
        )
        call_command("envoyer_emails")
        message.refresh_from_db()
        self.assertIsNotNone(message.envoye_le)

    def test_echec_incremente_les_tentatives_avec_delai(self):
        from django.core.management import call_command
        from comptes.models import EmailOutbox
        message = EmailOutbox.objects.create(
            sujet="Va échouer", contenu="Contenu",
            expediteur="test@example.com", destinataires=["dest@invalide"],
        )
        with patch("comptes.management.commands.envoyer_emails.send_mail", side_effect=Exception("SMTP indisponible")):
            call_command("envoyer_emails")
        message.refresh_from_db()
        self.assertEqual(message.tentatives, 1)
        self.assertIsNone(message.envoye_le)
        self.assertIn("SMTP indisponible", message.derniere_erreur)
        self.assertGreater(message.prochaine_tentative, timezone.now())

    def test_arrete_apres_cinq_echecs(self):
        from django.core.management import call_command
        from comptes.models import EmailOutbox
        message = EmailOutbox.objects.create(
            sujet="Échoue toujours", contenu="Contenu", expediteur="test@example.com",
            destinataires=["dest@example.com"], tentatives=5,
            prochaine_tentative=timezone.now() - timedelta(minutes=1),
        )
        call_command("envoyer_emails")
        message.refresh_from_db()
        self.assertEqual(message.tentatives, 5)  # inchangé : plus jamais repris


class IpClientFiableTests(TestCase):
    def test_ignore_le_premier_champ_falsifiable_et_garde_le_dernier(self):
        from django.test import RequestFactory
        from comptes.utils import ip_client_fiable
        request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="1.2.3.4, 9.9.9.9, 203.0.113.5")
        self.assertEqual(ip_client_fiable(request), "203.0.113.5")

    @override_settings(NB_PROXYS_CONFIANCE=2)
    def test_respecte_le_nombre_de_proxys_de_confiance_configure(self):
        from django.test import RequestFactory
        from comptes.utils import ip_client_fiable
        request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="1.2.3.4, 9.9.9.9, 203.0.113.5")
        self.assertEqual(ip_client_fiable(request), "9.9.9.9")

    def test_repli_sur_remote_addr_sans_en_tete(self):
        from django.test import RequestFactory
        from comptes.utils import ip_client_fiable
        request = RequestFactory().get("/")
        self.assertEqual(ip_client_fiable(request), request.META.get("REMOTE_ADDR", ""))


class JournalAuditAdresseIpTests(TestCase):
    def test_connexion_reussie_enregistre_lip_de_confiance_pas_celle_annoncee_par_le_client(self):
        from comptes.models import JournalAudit
        creer_utilisateur_actif("audit_ip@example.com", Role.ENSEIGNANT)
        self.client.post(
            reverse("comptes:connexion"),
            {"email": "audit_ip@example.com", "mot_de_passe": "MotDePasse#2026"},
            HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.9",
        )
        entree = JournalAudit.objects.filter(action="connexion_reussie").latest("horodatage")
        self.assertEqual(entree.adresse_ip, "203.0.113.9")
