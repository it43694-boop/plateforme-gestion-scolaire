from django.test import TestCase
from django.urls import reverse

from comptes.models import Utilisateur
from comptes.roles import Role, StatutCompte
from etablissement.models import Etablissement


def creer_utilisateur_actif(email, role, etablissement=None, is_superuser=False, **kwargs):
    utilisateur = Utilisateur(
        email=email, prenom="Test", nom="Utilisateur", role=role, etablissement=etablissement,
        is_superuser=is_superuser, is_staff=is_superuser, **kwargs,
    )
    utilisateur.set_password("MotDePasse#2026")
    utilisateur.statut = StatutCompte.ACTIF
    utilisateur.is_active = True
    utilisateur.full_clean(exclude=["password"])
    utilisateur.save()
    return utilisateur


class AccesEspacePlateformeTests(TestCase):
    def test_superutilisateur_a_acces(self):
        proprietaire = creer_utilisateur_actif("owner@example.com", Role.DEVELOPPEUR, is_superuser=True)
        self.client.force_login(proprietaire)
        reponse = self.client.get(reverse("espace_plateforme:liste_etablissements"))
        self.assertEqual(reponse.status_code, 200)

    def test_developpeur_normal_na_pas_acces(self):
        etablissement = Etablissement.objects.create(nom="École normale")
        developpeur = creer_utilisateur_actif(
            "dev-normal@example.com", Role.DEVELOPPEUR, etablissement=etablissement, is_superuser=False,
        )
        self.client.force_login(developpeur)
        reponse = self.client.get(reverse("espace_plateforme:liste_etablissements"))
        self.assertEqual(reponse.status_code, 302)  # redirigé par user_passes_test (pas connecté en tant que superuser)

    def test_anonyme_redirige(self):
        reponse = self.client.get(reverse("espace_plateforme:liste_etablissements"))
        self.assertEqual(reponse.status_code, 302)


class CreerEtablissementTests(TestCase):
    def setUp(self):
        self.proprietaire = creer_utilisateur_actif("owner2@example.com", Role.DEVELOPPEUR, is_superuser=True)

    def test_creation_etablissement_et_premier_developpeur(self):
        self.client.force_login(self.proprietaire)
        reponse = self.client.post(reverse("espace_plateforme:creer_etablissement"), {
            "nom": "Nouvelle École", "devise": "En avant",
            "prenom_developpeur": "Fatoumata", "nom_developpeur": "Keita",
            "email_developpeur": "fatoumata-dev@example.com",
            "mot_de_passe_developpeur": "MotDePasse#2026",
        })
        self.assertEqual(reponse.status_code, 302)
        etablissement = Etablissement.objects.get(nom="Nouvelle École")
        developpeur = Utilisateur.objects.get(email="fatoumata-dev@example.com")
        self.assertEqual(developpeur.role, Role.DEVELOPPEUR)
        self.assertEqual(developpeur.etablissement, etablissement)
        self.assertTrue(developpeur.is_active)

    def test_email_deja_utilise_refuse(self):
        Etablissement.objects.create(nom="École existante")
        creer_utilisateur_actif("deja-pris-plateforme@example.com", Role.ENSEIGNANT)
        self.client.force_login(self.proprietaire)
        self.client.post(reverse("espace_plateforme:creer_etablissement"), {
            "nom": "Autre École", "devise": "",
            "prenom_developpeur": "X", "nom_developpeur": "Y",
            "email_developpeur": "deja-pris-plateforme@example.com",
            "mot_de_passe_developpeur": "MotDePasse#2026",
        })
        self.assertFalse(Etablissement.objects.filter(nom="Autre École").exists())

    def test_non_superuser_ne_peut_pas_creer(self):
        etablissement = Etablissement.objects.create(nom="École C")
        developpeur = creer_utilisateur_actif(
            "dev-c@example.com", Role.DEVELOPPEUR, etablissement=etablissement, is_superuser=False,
        )
        self.client.force_login(developpeur)
        reponse = self.client.post(reverse("espace_plateforme:creer_etablissement"), {
            "nom": "École Interdite", "devise": "",
            "prenom_developpeur": "X", "nom_developpeur": "Y",
            "email_developpeur": "interdit@example.com",
            "mot_de_passe_developpeur": "MotDePasse#2026",
        })
        self.assertFalse(Etablissement.objects.filter(nom="École Interdite").exists())


class BasculerActifTests(TestCase):
    def setUp(self):
        self.proprietaire = creer_utilisateur_actif("owner3@example.com", Role.DEVELOPPEUR, is_superuser=True)
        self.etablissement = Etablissement.objects.create(nom="École à basculer")

    def test_desactiver_puis_reactiver(self):
        self.client.force_login(self.proprietaire)
        self.client.post(reverse("espace_plateforme:basculer_actif", args=[self.etablissement.id]))
        self.etablissement.refresh_from_db()
        self.assertFalse(self.etablissement.actif)

        self.client.post(reverse("espace_plateforme:basculer_actif", args=[self.etablissement.id]))
        self.etablissement.refresh_from_db()
        self.assertTrue(self.etablissement.actif)

    def test_non_superuser_ne_peut_pas_basculer(self):
        developpeur = creer_utilisateur_actif(
            "dev-bascule@example.com", Role.DEVELOPPEUR, etablissement=self.etablissement, is_superuser=False,
        )
        self.client.force_login(developpeur)
        self.client.post(reverse("espace_plateforme:basculer_actif", args=[self.etablissement.id]))
        self.etablissement.refresh_from_db()
        self.assertTrue(self.etablissement.actif)  # inchangé


class ModifierEtablissementParPlateformeTests(TestCase):
    def setUp(self):
        self.proprietaire = creer_utilisateur_actif("owner-modif@example.com", Role.DEVELOPPEUR, is_superuser=True)
        self.etablissement = Etablissement.objects.create(nom="École à modifier")

    def test_proprietaire_peut_modifier_le_nom(self):
        self.client.force_login(self.proprietaire)
        reponse = self.client.post(
            reverse("espace_plateforme:modifier_etablissement", args=[self.etablissement.id]),
            {
                "nom": "Nouveau nom", "devise": "Nouvelle devise", "code_devise": "FCFA", "pas_montant": "5000",
                "taux_inps_salarie": "3.6", "taux_inps_employeur": "20.0",
                "taux_amo_salarie": "3.06", "taux_amo_employeur": "3.5",
            },
        )
        self.assertEqual(reponse.status_code, 302)
        self.etablissement.refresh_from_db()
        self.assertEqual(self.etablissement.nom, "Nouveau nom")

    def test_non_superuser_ne_peut_pas_modifier(self):
        developpeur = creer_utilisateur_actif(
            "dev-non-super@example.com", Role.DEVELOPPEUR, etablissement=self.etablissement, is_superuser=False,
        )
        self.client.force_login(developpeur)
        reponse = self.client.post(
            reverse("espace_plateforme:modifier_etablissement", args=[self.etablissement.id]),
            {"nom": "Nom interdit", "devise": ""},
        )
        self.assertEqual(reponse.status_code, 302)  # redirigé par user_passes_test
        self.etablissement.refresh_from_db()
        self.assertEqual(self.etablissement.nom, "École à modifier")


class ModifierPlanTests(TestCase):
    """
    Seul le propriétaire de la plateforme change la formule d'abonnement
    (cycles couverts) d'un établissement - jamais l'établissement lui-même,
    pour empêcher une école de s'auto-attribuer un cycle non souscrit.
    """

    def setUp(self):
        from etablissement.models import PlanEtablissement
        self.PlanEtablissement = PlanEtablissement
        self.proprietaire = creer_utilisateur_actif("owner-plan@example.com", Role.DEVELOPPEUR, is_superuser=True)
        self.etablissement = Etablissement.objects.create(nom="École à faire évoluer", plan=PlanEtablissement.PREMIER_CYCLE)

    def test_proprietaire_peut_changer_le_plan(self):
        self.client.force_login(self.proprietaire)
        reponse = self.client.post(
            reverse("espace_plateforme:modifier_plan", args=[self.etablissement.id]),
            {"plan": self.PlanEtablissement.TOUS_CYCLES.value},
        )
        self.assertEqual(reponse.status_code, 302)
        self.etablissement.refresh_from_db()
        self.assertEqual(self.etablissement.plan, self.PlanEtablissement.TOUS_CYCLES)

    def test_non_superuser_ne_peut_pas_changer_le_plan(self):
        developpeur = creer_utilisateur_actif(
            "dev-plan@example.com", Role.DEVELOPPEUR, etablissement=self.etablissement, is_superuser=False,
        )
        self.client.force_login(developpeur)
        self.client.post(
            reverse("espace_plateforme:modifier_plan", args=[self.etablissement.id]),
            {"plan": self.PlanEtablissement.TOUS_CYCLES.value},
        )
        self.etablissement.refresh_from_db()
        self.assertEqual(self.etablissement.plan, self.PlanEtablissement.PREMIER_CYCLE)  # inchangé

    def test_parametres_etablissement_developpeur_ne_peut_pas_changer_le_plan(self):
        """Le formulaire d'identité de l'établissement (espace_developpeur, celui de l'école elle-même) n'expose pas le plan."""
        from espace_developpeur.forms import ParametresEtablissementForm
        formulaire = ParametresEtablissementForm(instance=self.etablissement)
        self.assertNotIn("plan", formulaire.fields)

    def test_proprietaire_peut_activer_le_professionnel_independamment_du_plan(self):
        """
        inclut_professionnel est un réglage indépendant de la formule (voir
        scolarite.models.cycles_autorises_pour) - l'activer ne doit pas
        changer le plan, et inversement (voir les deux formulaires de
        templates/espace_plateforme/liste_etablissements.html, chacun avec
        un champ caché pour préserver l'autre réglage).
        """
        self.client.force_login(self.proprietaire)
        self.client.post(
            reverse("espace_plateforme:modifier_plan", args=[self.etablissement.id]),
            {"plan": self.PlanEtablissement.PREMIER_CYCLE.value, "inclut_professionnel": "True"},
        )
        self.etablissement.refresh_from_db()
        self.assertTrue(self.etablissement.inclut_professionnel)
        self.assertEqual(self.etablissement.plan, self.PlanEtablissement.PREMIER_CYCLE)

        # Changer uniquement le plan (comme le fait le premier mini-formulaire,
        # avec son champ caché) ne doit pas réinitialiser inclut_professionnel.
        self.client.post(
            reverse("espace_plateforme:modifier_plan", args=[self.etablissement.id]),
            {"plan": self.PlanEtablissement.TOUS_CYCLES.value, "inclut_professionnel": "True"},
        )
        self.etablissement.refresh_from_db()
        self.assertTrue(self.etablissement.inclut_professionnel)
        self.assertEqual(self.etablissement.plan, self.PlanEtablissement.TOUS_CYCLES)


class VoirComptesEtablissementTests(TestCase):
    def setUp(self):
        self.proprietaire = creer_utilisateur_actif("owner-comptes@example.com", Role.DEVELOPPEUR, is_superuser=True)
        self.ecole_a = Etablissement.objects.create(nom="École Comptes A")
        self.ecole_b = Etablissement.objects.create(nom="École Comptes B")
        self.compte_a = creer_utilisateur_actif("compte-a-plateforme@example.com", Role.ENSEIGNANT, etablissement=self.ecole_a)
        self.compte_b = creer_utilisateur_actif("compte-b-plateforme@example.com", Role.ENSEIGNANT, etablissement=self.ecole_b)

    def test_proprietaire_voit_les_comptes_de_lecole_choisie(self):
        self.client.force_login(self.proprietaire)
        reponse = self.client.get(reverse("espace_plateforme:voir_comptes_etablissement", args=[self.ecole_a.id]))
        emails = [c.email for c in reponse.context["comptes"]]
        self.assertIn("compte-a-plateforme@example.com", emails)
        self.assertNotIn("compte-b-plateforme@example.com", emails)


class ProprietaireSansEtablissementTests(TestCase):
    """
    Le propriétaire de la plateforme (superutilisateur sans établissement) gère
    les écoles depuis l'espace Plateforme, mais n'a aucune école à lui : les
    pages métier filtrées par établissement le feraient tomber sur
    `etablissement IS NULL` (lignes orphelines) - elles lui sont donc fermées
    (comptes.middleware.ProprietairePlateformeMiddleware).
    """

    PAGES_METIER = [
        "scolarite:liste_eleves", "scolarite:liste_classes", "scolarite:creer_classe", "scolarite:inscrire_eleve",
        "scolarite:recherche_globale", "finances:suivi_paiements", "finances:liste_paiements",
        "finances:liste_salaires", "finances:registre_caisse", "finances:journal_caisse_syscohada_csv",
        "finances:rechercher_eleve_json", "pedagogie:suivi_des_cours", "tests_niveau:liste_candidats",
        "assistant:poser_question", "bibliotheque:liste_documents", "bibliotheque:exporter_zip",
        "communication:liste_annonces", "communication:publier_annonce", "statistiques:vue_ensemble",
        "statistiques:exporter_finances_csv", "espace_developpeur:liste_comptes", "comptes:comptes_en_attente",
    ]

    def setUp(self):
        import datetime
        from scolarite.models import AnneeScolaire, Classe, Cycle

        self.proprietaire = creer_utilisateur_actif("owner-cloison@example.com", Role.DEVELOPPEUR, is_superuser=True)
        # Ligne orpheline (aucun établissement), telle qu'en laissent les anciennes installations.
        annee = AnneeScolaire.objects.create(
            libelle="2026-2027", date_debut=datetime.date(2026, 10, 1), date_fin=datetime.date(2027, 7, 31),
        )
        Classe.objects.create(nom="Classe orpheline", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=annee)

    def test_pages_metier_fermees_au_proprietaire(self):
        self.client.force_login(self.proprietaire)
        for nom in self.PAGES_METIER:
            with self.subTest(page=nom):
                reponse = self.client.get(reverse(nom))
                self.assertRedirects(
                    reponse, reverse("espace_plateforme:liste_etablissements"), fetch_redirect_response=False,
                )

    def test_donnees_orphelines_jamais_affichees_au_proprietaire(self):
        self.client.force_login(self.proprietaire)
        reponse = self.client.get(reverse("scolarite:liste_classes"), follow=True)
        self.assertNotContains(reponse, "Classe orpheline")

    def test_tableau_de_bord_redirige_vers_la_plateforme(self):
        self.client.force_login(self.proprietaire)
        reponse = self.client.get(reverse("comptes:redirection_tableau_de_bord"))
        self.assertRedirects(
            reponse, reverse("espace_plateforme:liste_etablissements"), fetch_redirect_response=False,
        )

    def test_espace_plateforme_et_compte_personnel_restent_accessibles(self):
        self.client.force_login(self.proprietaire)
        for nom in ["espace_plateforme:liste_etablissements", "comptes:liste_notifications",
                    "comptes:changer_mot_de_passe"]:
            with self.subTest(page=nom):
                self.assertEqual(self.client.get(reverse(nom)).status_code, 200)

    def test_verification_publique_de_document_reste_ouverte(self):
        import uuid
        self.client.force_login(self.proprietaire)
        reponse = self.client.get(reverse("scolarite:verifier_document", args=[uuid.uuid4()]))
        self.assertNotEqual(reponse.status_code, 302)  # pas de redirection vers la plateforme

    def test_barre_laterale_reduite_a_compte_et_plateforme(self):
        self.client.force_login(self.proprietaire)
        reponse = self.client.get(reverse("espace_plateforme:liste_etablissements"))
        titres = [section["titre"] for section in reponse.context["sections_navigation"]]
        self.assertEqual(titres, ["Compte", "Plateforme"])
        self.assertFalse(reponse.context["peut_rechercher_eleves"])

    def test_utilisateur_dun_etablissement_non_concerne(self):
        etablissement = Etablissement.objects.create(nom="École cloisonnement")
        from permissions_matrix.models import PermissionMatrix
        PermissionMatrix.seed_pour(etablissement)
        fondateur = creer_utilisateur_actif("fondateur-cloison@example.com", Role.FONDATEUR, etablissement=etablissement)
        self.client.force_login(fondateur)
        self.assertEqual(self.client.get(reverse("scolarite:liste_classes")).status_code, 200)
        reponse = self.client.get(reverse("scolarite:liste_classes"))
        self.assertNotContains(reponse, "Classe orpheline")
        titres = [section["titre"] for section in reponse.context["sections_navigation"]]
        self.assertIn("Élèves & classes", titres)
