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
            {"nom": "Nouveau nom", "devise": "Nouvelle devise", "code_devise": "FCFA", "pas_montant": "5000"},
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
