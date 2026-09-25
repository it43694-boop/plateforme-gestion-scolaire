from django.test import TestCase
from django.urls import reverse

from comptes.models import Utilisateur
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
