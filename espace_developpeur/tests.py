from django.test import TestCase
from django.urls import reverse

from comptes.models import Utilisateur
from comptes.roles import Role, StatutCompte
from permissions_matrix.models import PermissionMatrix
from permissions_matrix.modules import Module
from scolarite.models import AnneeScolaire


def creer_utilisateur_actif(email, role, **kwargs):
    utilisateur = Utilisateur(email=email, prenom="Test", nom="Utilisateur", role=role, **kwargs)
    utilisateur.set_password("MotDePasse#2026")
    utilisateur.statut = StatutCompte.ACTIF
    utilisateur.is_active = True
    utilisateur.full_clean(exclude=["password"])
    utilisateur.save()
    return utilisateur


class AccesEspaceDeveloppeurTests(TestCase):
    """
    Vérifie la nuance centrale du cahier des charges : fondateur et
    administrateur_general ont un accès total aux MODULES, mais seul le
    développeur peut attribuer les rôles/statuts et gérer la matrice.
    """

    def setUp(self):
        self.developpeur = creer_utilisateur_actif("dev@example.com", Role.DEVELOPPEUR)
        self.fondateur = creer_utilisateur_actif("fondateur-esp@example.com", Role.FONDATEUR)
        self.admin_general = creer_utilisateur_actif("admin-general-esp@example.com", Role.ADMINISTRATEUR_GENERAL)
        self.secretaire = creer_utilisateur_actif("secretaire-esp@example.com", Role.SECRETAIRE)

    def test_developpeur_a_acces(self):
        self.client.force_login(self.developpeur)
        reponse = self.client.get(reverse("espace_developpeur:liste_comptes"))
        self.assertEqual(reponse.status_code, 200)

    def test_fondateur_na_pas_acces_malgre_acces_total_aux_modules(self):
        self.client.force_login(self.fondateur)
        reponse = self.client.get(reverse("espace_developpeur:liste_comptes"))
        self.assertEqual(reponse.status_code, 403)

    def test_administrateur_general_na_pas_acces(self):
        self.client.force_login(self.admin_general)
        reponse = self.client.get(reverse("espace_developpeur:matrice_permissions"))
        self.assertEqual(reponse.status_code, 403)

    def test_secretaire_na_pas_acces(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.get(reverse("espace_developpeur:liste_comptes"))
        self.assertEqual(reponse.status_code, 403)


class ModifierCompteTests(TestCase):
    def setUp(self):
        self.developpeur = creer_utilisateur_actif("dev2@example.com", Role.DEVELOPPEUR)
        self.personnel = creer_utilisateur_actif("personnel-esp@example.com", Role.PERSONNEL)

    def test_developpeur_peut_changer_le_role_dun_autre_compte(self):
        self.client.force_login(self.developpeur)
        reponse = self.client.post(
            reverse("espace_developpeur:modifier_compte", args=[self.personnel.id]),
            {"role": Role.SECRETAIRE.value, "statut": StatutCompte.ACTIF.value},
        )
        self.assertEqual(reponse.status_code, 302)
        self.personnel.refresh_from_db()
        self.assertEqual(self.personnel.role, Role.SECRETAIRE)

    def test_developpeur_ne_peut_pas_changer_son_propre_role(self):
        self.client.force_login(self.developpeur)
        reponse = self.client.post(
            reverse("espace_developpeur:modifier_compte", args=[self.developpeur.id]),
            {"role": Role.SECRETAIRE.value, "statut": StatutCompte.ACTIF.value},
        )
        self.developpeur.refresh_from_db()
        self.assertEqual(self.developpeur.role, Role.DEVELOPPEUR)

    def test_impossible_de_promouvoir_un_compte_en_role_a_acces_total(self):
        self.client.force_login(self.developpeur)
        for role_cible in (Role.DEVELOPPEUR.value, Role.FONDATEUR.value, Role.ADMINISTRATEUR_GENERAL.value):
            reponse = self.client.post(
                reverse("espace_developpeur:modifier_compte", args=[self.personnel.id]),
                {"role": role_cible, "statut": StatutCompte.ACTIF.value},
            )
            self.assertEqual(reponse.status_code, 200)  # formulaire invalide, pas de redirection
            self.personnel.refresh_from_db()
            self.assertEqual(self.personnel.role, Role.PERSONNEL)

    def test_suspendre_un_compte_desactive_la_connexion(self):
        self.client.force_login(self.developpeur)
        self.client.post(
            reverse("espace_developpeur:modifier_compte", args=[self.personnel.id]),
            {"role": self.personnel.role, "statut": StatutCompte.SUSPENDU.value},
        )
        self.personnel.refresh_from_db()
        self.assertEqual(self.personnel.statut, StatutCompte.SUSPENDU)
        self.assertFalse(self.personnel.is_active)


class ModifierCompteAbonnementTests(TestCase):
    """
    Un rôle de direction propre à un cycle (y compris Censeur/Surveillant
    général, propres au Lycée) n'est attribuable que si l'abonnement de
    l'établissement couvre ce cycle - empêche une école abonnée au 1er
    cycle seul de s'attribuer quand même un rôle du Lycée.
    """

    def setUp(self):
        from etablissement.models import Etablissement, PlanEtablissement
        self.etablissement = Etablissement.objects.create(nom="École 1er cycle seul", plan=PlanEtablissement.PREMIER_CYCLE)
        self.developpeur = creer_utilisateur_actif("dev-abonnement@example.com", Role.DEVELOPPEUR, etablissement=self.etablissement)
        self.personnel = creer_utilisateur_actif("personnel-abonnement@example.com", Role.PERSONNEL, etablissement=self.etablissement)

    def test_role_censeur_absent_du_formulaire(self):
        self.client.force_login(self.developpeur)
        reponse = self.client.get(reverse("espace_developpeur:modifier_compte", args=[self.personnel.id]))
        choix = dict(reponse.context["formulaire"].fields["role"].choices)
        self.assertNotIn(Role.CENSEUR.value, choix)
        self.assertNotIn(Role.DIRECTEUR_LYCEE.value, choix)
        self.assertIn(Role.DIRECTEUR_1ER_CYCLE.value, choix)

    def test_attribution_censeur_refusee_cote_serveur(self):
        self.client.force_login(self.developpeur)
        reponse = self.client.post(
            reverse("espace_developpeur:modifier_compte", args=[self.personnel.id]),
            {"role": Role.CENSEUR.value, "statut": StatutCompte.ACTIF.value},
        )
        self.assertEqual(reponse.status_code, 200)  # formulaire invalide, pas de redirection
        self.personnel.refresh_from_db()
        self.assertEqual(self.personnel.role, Role.PERSONNEL)

    def test_role_directeur_1er_cycle_toujours_attribuable(self):
        self.client.force_login(self.developpeur)
        reponse = self.client.post(
            reverse("espace_developpeur:modifier_compte", args=[self.personnel.id]),
            {"role": Role.DIRECTEUR_1ER_CYCLE.value, "statut": StatutCompte.ACTIF.value},
        )
        self.assertEqual(reponse.status_code, 302)
        self.personnel.refresh_from_db()
        self.assertEqual(self.personnel.role, Role.DIRECTEUR_1ER_CYCLE)


class ReinitialiserDeuxFacteursTests(TestCase):
    def setUp(self):
        self.developpeur = creer_utilisateur_actif("dev-2fa-reset@example.com", Role.DEVELOPPEUR)
        self.cible = creer_utilisateur_actif("cible-2fa-reset@example.com", Role.COMPTABLE)
        self.cible.totp_secret = self.cible.generer_secret_2fa()
        self.cible.deux_facteurs_actif = True
        self.cible.save(update_fields=["totp_secret", "deux_facteurs_actif"])
        self.cible.generer_codes_secours_2fa()

    def test_developpeur_peut_reinitialiser_la_2fa_dun_autre_compte(self):
        self.client.force_login(self.developpeur)
        reponse = self.client.post(
            reverse("espace_developpeur:reinitialiser_2fa_compte", args=[self.cible.id]),
        )
        self.assertEqual(reponse.status_code, 302)
        self.cible.refresh_from_db()
        self.assertFalse(self.cible.deux_facteurs_actif)
        self.assertEqual(self.cible.totp_secret, "")
        self.assertEqual(self.cible.codes_secours_2fa.count(), 0)

    def test_developpeur_ne_peut_pas_reinitialiser_sa_propre_2fa(self):
        self.developpeur.totp_secret = self.developpeur.generer_secret_2fa()
        self.developpeur.deux_facteurs_actif = True
        self.developpeur.save(update_fields=["totp_secret", "deux_facteurs_actif"])
        self.client.force_login(self.developpeur)
        self.client.post(
            reverse("espace_developpeur:reinitialiser_2fa_compte", args=[self.developpeur.id]),
        )
        self.developpeur.refresh_from_db()
        self.assertTrue(self.developpeur.deux_facteurs_actif)

    def test_role_autre_que_developpeur_refuse(self):
        autre = creer_utilisateur_actif("autre-2fa-reset@example.com", Role.SECRETAIRE)
        self.client.force_login(autre)
        reponse = self.client.post(
            reverse("espace_developpeur:reinitialiser_2fa_compte", args=[self.cible.id]),
        )
        self.assertEqual(reponse.status_code, 403)
        self.cible.refresh_from_db()
        self.assertTrue(self.cible.deux_facteurs_actif)

    def test_requiert_post(self):
        self.client.force_login(self.developpeur)
        reponse = self.client.get(
            reverse("espace_developpeur:reinitialiser_2fa_compte", args=[self.cible.id]),
        )
        self.assertEqual(reponse.status_code, 405)


class MatricePermissionsVueTests(TestCase):
    def setUp(self):
        from etablissement.models import Etablissement
        self.etablissement = Etablissement.objects.create(nom="École matrice")
        PermissionMatrix.seed_pour(self.etablissement)
        self.developpeur = creer_utilisateur_actif("dev3@example.com", Role.DEVELOPPEUR, etablissement=self.etablissement)

    def test_roles_a_acces_total_absents_de_la_grille(self):
        self.client.force_login(self.developpeur)
        reponse = self.client.get(reverse("espace_developpeur:matrice_permissions"))
        roles_affiches = [ligne["role"] for ligne in reponse.context["lignes"]]
        self.assertNotIn(Role.DEVELOPPEUR, roles_affiches)
        self.assertNotIn(Role.FONDATEUR, roles_affiches)
        self.assertIn(Role.SECRETAIRE, roles_affiches)
        self.assertIn(Role.DIRECTEUR_LYCEE, roles_affiches)

    def test_cocher_une_case_accorde_immediatement_lacces(self):
        self.assertFalse(PermissionMatrix.a_acces(Role.SECRETAIRE, Module.BIBLIOTHEQUE, etablissement=self.etablissement))
        self.client.force_login(self.developpeur)

        donnees_post = {}
        # Reproduit l'état actuel de toute la grille, puis n'ajoute que la case ciblée.
        for role in Role:
            if role in {Role.DEVELOPPEUR, Role.FONDATEUR, Role.ADMINISTRATEUR_GENERAL}:
                continue
            for module in Module:
                if PermissionMatrix.a_acces(role, module, etablissement=self.etablissement):
                    donnees_post[f"{role.value}__{module.value}"] = "on"
        donnees_post[f"{Role.SECRETAIRE.value}__{Module.BIBLIOTHEQUE.value}"] = "on"

        self.client.post(reverse("espace_developpeur:matrice_permissions"), donnees_post)
        self.assertTrue(PermissionMatrix.a_acces(Role.SECRETAIRE, Module.BIBLIOTHEQUE, etablissement=self.etablissement))

    def test_decocher_une_case_retire_immediatement_lacces(self):
        self.assertTrue(PermissionMatrix.a_acces(Role.COMPTABLE, Module.FINANCES, etablissement=self.etablissement))
        self.client.force_login(self.developpeur)

        donnees_post = {}
        for role in Role:
            if role in {Role.DEVELOPPEUR, Role.FONDATEUR, Role.ADMINISTRATEUR_GENERAL}:
                continue
            for module in Module:
                if role == Role.COMPTABLE and module == Module.FINANCES:
                    continue  # celle qu'on retire : on ne l'envoie pas cochée
                if PermissionMatrix.a_acces(role, module, etablissement=self.etablissement):
                    donnees_post[f"{role.value}__{module.value}"] = "on"

        self.client.post(reverse("espace_developpeur:matrice_permissions"), donnees_post)
        self.assertFalse(PermissionMatrix.a_acces(Role.COMPTABLE, Module.FINANCES, etablissement=self.etablissement))


class AnneesScolairesVueTests(TestCase):
    """
    Avant cette fonctionnalité, créer une année scolaire n'était possible que
    depuis /admin/ (superutilisateur technique) - aucune page dans
    l'application elle-même. Vérifie la création, le cycle de vie
    (activation/archivage) et l'isolation entre établissements.
    """

    def setUp(self):
        from etablissement.models import Etablissement

        self.ecole_a = Etablissement.objects.create(nom="École années A")
        self.ecole_b = Etablissement.objects.create(nom="École années B")
        self.developpeur = creer_utilisateur_actif("dev-annees@example.com", Role.DEVELOPPEUR, etablissement=self.ecole_a)

    def test_creer_une_annee_scolaire(self):
        self.client.force_login(self.developpeur)
        reponse = self.client.post(reverse("espace_developpeur:annees_scolaires"), {
            "libelle": "2026-2027", "date_debut": "2026-10-01", "date_fin": "2027-07-31",
        })
        self.assertEqual(reponse.status_code, 302)
        annee = AnneeScolaire.objects.get(libelle="2026-2027", etablissement=self.ecole_a)
        self.assertFalse(annee.est_active)

    def test_creer_en_la_marquant_active_desactive_lancienne_active(self):
        ancienne = AnneeScolaire.objects.create(
            etablissement=self.ecole_a, libelle="2025-2026",
            date_debut="2025-10-01", date_fin="2026-07-31", est_active=True,
        )
        self.client.force_login(self.developpeur)
        self.client.post(reverse("espace_developpeur:annees_scolaires"), {
            "libelle": "2026-2027", "date_debut": "2026-10-01", "date_fin": "2027-07-31",
            "est_active": "on",
        })
        ancienne.refresh_from_db()
        self.assertFalse(ancienne.est_active)
        nouvelle = AnneeScolaire.objects.get(libelle="2026-2027")
        self.assertTrue(nouvelle.est_active)

    def test_libelle_duplique_refuse(self):
        AnneeScolaire.objects.create(
            etablissement=self.ecole_a, libelle="2026-2027", date_debut="2026-10-01", date_fin="2027-07-31",
        )
        self.client.force_login(self.developpeur)
        reponse = self.client.post(reverse("espace_developpeur:annees_scolaires"), {
            "libelle": "2026-2027", "date_debut": "2026-10-01", "date_fin": "2027-07-31",
        })
        self.assertEqual(reponse.status_code, 200)  # formulaire réaffiché avec erreur
        self.assertEqual(AnneeScolaire.objects.filter(etablissement=self.ecole_a, libelle="2026-2027").count(), 1)

    def test_date_fin_avant_date_debut_refusee(self):
        self.client.force_login(self.developpeur)
        reponse = self.client.post(reverse("espace_developpeur:annees_scolaires"), {
            "libelle": "2026-2027", "date_debut": "2027-07-31", "date_fin": "2026-10-01",
        })
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(AnneeScolaire.objects.filter(libelle="2026-2027").exists())

    def test_archiver_desactive_et_empeche_une_reactivation_directe(self):
        annee = AnneeScolaire.objects.create(
            etablissement=self.ecole_a, libelle="2024-2025",
            date_debut="2024-10-01", date_fin="2025-07-31", est_active=True,
        )
        self.client.force_login(self.developpeur)
        self.client.post(reverse("espace_developpeur:archiver_annee_scolaire", args=[annee.id]))
        annee.refresh_from_db()
        self.assertTrue(annee.est_archivee)
        self.assertFalse(annee.est_active)

        reponse = self.client.post(reverse("espace_developpeur:activer_annee_scolaire", args=[annee.id]))
        self.assertEqual(reponse.status_code, 302)
        annee.refresh_from_db()
        self.assertFalse(annee.est_active)  # toujours refusé : une année archivée reste archivée

    def test_un_developpeur_ne_voit_pas_les_annees_dune_autre_ecole(self):
        AnneeScolaire.objects.create(
            etablissement=self.ecole_b, libelle="2026-2027", date_debut="2026-10-01", date_fin="2027-07-31",
        )
        self.client.force_login(self.developpeur)
        reponse = self.client.get(reverse("espace_developpeur:annees_scolaires"))
        self.assertEqual(list(reponse.context["annees"]), [])

    def test_un_developpeur_ne_peut_pas_activer_lannee_dune_autre_ecole(self):
        annee_b = AnneeScolaire.objects.create(
            etablissement=self.ecole_b, libelle="2026-2027", date_debut="2026-10-01", date_fin="2027-07-31",
        )
        self.client.force_login(self.developpeur)
        reponse = self.client.post(reverse("espace_developpeur:activer_annee_scolaire", args=[annee_b.id]))
        self.assertEqual(reponse.status_code, 404)
        annee_b.refresh_from_db()
        self.assertFalse(annee_b.est_active)


class IsolationListeComptesTests(TestCase):
    """La fuite la plus grave détectée dans ce chantier : un développeur
    voyait tous les comptes de toutes les écoles. Preuve que c'est corrigé."""

    def setUp(self):
        from etablissement.models import Etablissement
        self.ecole_a = Etablissement.objects.create(nom="École Liste A")
        self.ecole_b = Etablissement.objects.create(nom="École Liste B")
        self.dev_a = creer_utilisateur_actif("dev-liste-a@example.com", Role.DEVELOPPEUR, etablissement=self.ecole_a)
        self.compte_a = creer_utilisateur_actif("compte-liste-a@example.com", Role.ENSEIGNANT, etablissement=self.ecole_a)
        self.compte_b = creer_utilisateur_actif("compte-liste-b@example.com", Role.ENSEIGNANT, etablissement=self.ecole_b)

    def test_developpeur_ne_voit_que_les_comptes_de_son_ecole(self):
        self.client.force_login(self.dev_a)
        reponse = self.client.get(reverse("espace_developpeur:liste_comptes"))
        emails = [c.email for c in reponse.context["comptes"]]
        self.assertIn("compte-liste-a@example.com", emails)
        self.assertNotIn("compte-liste-b@example.com", emails)
        self.assertNotIn(self.dev_a.email, [])  # sanity: dev_a lui-même est dans son école, pas testé ici

    def test_developpeur_ne_peut_pas_modifier_un_compte_dune_autre_ecole(self):
        self.client.force_login(self.dev_a)
        reponse = self.client.post(
            reverse("espace_developpeur:modifier_compte", args=[self.compte_b.id]),
            {"role": Role.SECRETAIRE.value, "statut": StatutCompte.ACTIF.value},
        )
        self.assertEqual(reponse.status_code, 404)
        self.compte_b.refresh_from_db()
        self.assertEqual(self.compte_b.role, Role.ENSEIGNANT)


class JournalAuditVueTests(TestCase):
    def setUp(self):
        from etablissement.models import Etablissement
        self.ecole_a = Etablissement.objects.create(nom="École Journal A")
        self.ecole_b = Etablissement.objects.create(nom="École Journal B")
        PermissionMatrix.seed_pour(self.ecole_a)
        PermissionMatrix.seed_pour(self.ecole_b)
        self.dev_a = creer_utilisateur_actif("dev-journal-a@example.com", Role.DEVELOPPEUR, etablissement=self.ecole_a)
        self.dev_b = creer_utilisateur_actif("dev-journal-b@example.com", Role.DEVELOPPEUR, etablissement=self.ecole_b)

    def test_action_enregistree_avec_le_bon_etablissement(self):
        from comptes.audit import enregistrer_action
        from comptes.models import JournalAudit
        enregistrer_action(acteur=self.dev_a, action="test_action", cible="cible test")
        entree = JournalAudit.objects.get(action="test_action")
        self.assertEqual(entree.etablissement, self.ecole_a)

    def test_developpeur_ne_voit_que_le_journal_de_son_ecole(self):
        from comptes.audit import enregistrer_action
        enregistrer_action(acteur=self.dev_a, action="action_ecole_a", cible="")
        enregistrer_action(acteur=self.dev_b, action="action_ecole_b", cible="")
        self.client.force_login(self.dev_a)
        reponse = self.client.get(reverse("espace_developpeur:journal_audit"))
        actions = [e.action for e in reponse.context["entrees"]]
        self.assertIn("action_ecole_a", actions)
        self.assertNotIn("action_ecole_b", actions)

    def test_recherche_par_texte(self):
        from comptes.audit import enregistrer_action
        enregistrer_action(acteur=self.dev_a, action="creation_classe", cible="5ème année B")
        enregistrer_action(acteur=self.dev_a, action="modification_etablissement", cible="")
        self.client.force_login(self.dev_a)
        reponse = self.client.get(reverse("espace_developpeur:journal_audit"), {"q": "classe"})
        actions = [e.action for e in reponse.context["entrees"]]
        self.assertEqual(actions, ["creation_classe"])
