from django.test import TestCase
from django.urls import reverse

from comptes.models import Utilisateur
from comptes.roles import Role, StatutCompte
from etablissement.models import Etablissement


def creer_utilisateur_actif(email, role, etablissement=None, **kwargs):
    utilisateur = Utilisateur(
        email=email, prenom="Test", nom="Utilisateur", role=role, etablissement=etablissement, **kwargs,
    )
    utilisateur.set_password("MotDePasse#2026")
    utilisateur.statut = StatutCompte.ACTIF
    utilisateur.is_active = True
    utilisateur.full_clean(exclude=["password"])
    utilisateur.save()
    return utilisateur


class EtablissementModeleTests(TestCase):
    def test_slug_genere_automatiquement(self):
        etablissement = Etablissement.objects.create(nom="Lycée Moderne")
        self.assertEqual(etablissement.slug, "lycee-moderne")

    def test_slug_unique_meme_nom(self):
        premier = Etablissement.objects.create(nom="Collège Sahel")
        second = Etablissement.objects.create(nom="Collège Sahel")
        self.assertNotEqual(premier.slug, second.slug)
        self.assertTrue(second.slug.startswith("college-sahel"))

    def test_actif_et_visible_par_defaut(self):
        etablissement = Etablissement.objects.create(nom="École Test")
        self.assertTrue(etablissement.actif)
        self.assertTrue(etablissement.visible_dans_annuaire)

    def test_initiale_est_la_premiere_lettre_du_nom_en_majuscule(self):
        etablissement = Etablissement(nom="lycée moderne")
        self.assertEqual(etablissement.initiale, "L")

    def test_plusieurs_etablissements_coexistent(self):
        Etablissement.objects.create(nom="École A")
        Etablissement.objects.create(nom="École B")
        self.assertEqual(Etablissement.objects.count(), 2)


class ParametresEtablissementVueTests(TestCase):
    def setUp(self):
        self.etablissement = Etablissement.objects.create(nom="Institut Test")
        self.developpeur = creer_utilisateur_actif(
            "dev-etab@example.com", Role.DEVELOPPEUR, etablissement=self.etablissement,
        )
        self.fondateur = creer_utilisateur_actif(
            "fondateur-etab@example.com", Role.FONDATEUR, etablissement=self.etablissement,
        )

    def test_developpeur_peut_modifier_son_etablissement(self):
        self.client.force_login(self.developpeur)
        reponse = self.client.post(reverse("espace_developpeur:parametres_etablissement"), {
            "nom": "Collège Sahel", "devise": "Réussir ensemble",
            "code_devise": "EUR", "pas_montant": "100",
        })
        self.assertEqual(reponse.status_code, 302)
        self.etablissement.refresh_from_db()
        self.assertEqual(self.etablissement.nom, "Collège Sahel")
        self.assertEqual(self.etablissement.devise, "Réussir ensemble")
        self.assertEqual(self.etablissement.code_devise, "EUR")
        self.assertEqual(self.etablissement.pas_montant, 100)

    def test_fondateur_na_pas_acces_malgre_acces_total_aux_modules(self):
        self.client.force_login(self.fondateur)
        reponse = self.client.get(reverse("espace_developpeur:parametres_etablissement"))
        self.assertEqual(reponse.status_code, 403)


class ConnexionMonoEtablissementTests(TestCase):
    """En mono-établissement, le comportement historique (avant le multi-tenant) est préservé."""

    def test_nom_etablissement_apparait_sur_la_page_de_connexion(self):
        Etablissement.objects.create(nom="Institut Kénédougou")
        reponse = self.client.get(reverse("comptes:connexion"))
        self.assertContains(reponse, "Institut Kénédougou")


class ConnexionEtablissementBloqueTests(TestCase):
    def test_connexion_refusee_si_etablissement_desactive(self):
        etablissement = Etablissement.objects.create(nom="École Suspendue", actif=False)
        utilisateur = creer_utilisateur_actif(
            "bloque@example.com", Role.ENSEIGNANT, etablissement=etablissement,
        )
        reponse = self.client.post(reverse("comptes:connexion"), {
            "email": "bloque@example.com", "mot_de_passe": "MotDePasse#2026",
        })
        self.assertFalse(reponse.wsgi_request.user.is_authenticated)

    def test_connexion_reussit_si_etablissement_actif(self):
        etablissement = Etablissement.objects.create(nom="École Active")
        creer_utilisateur_actif("actif-etab@example.com", Role.ENSEIGNANT, etablissement=etablissement)
        reponse = self.client.post(reverse("comptes:connexion"), {
            "email": "actif-etab@example.com", "mot_de_passe": "MotDePasse#2026",
        }, follow=True)
        self.assertTrue(reponse.wsgi_request.user.is_authenticated)


class AnnuairePublicTests(TestCase):
    def test_un_seul_etablissement_pas_dannuaire(self):
        Etablissement.objects.create(nom="École Unique")
        reponse = self.client.get(reverse("vitrine:accueil"))
        self.assertTemplateUsed(reponse, "vitrine/accueil.html")

    def test_plusieurs_etablissements_affiche_meme_template_en_mode_multi(self):
        Etablissement.objects.create(nom="École Un")
        Etablissement.objects.create(nom="École Deux")
        reponse = self.client.get(reverse("vitrine:accueil"))
        self.assertTemplateUsed(reponse, "vitrine/accueil.html")
        self.assertTrue(reponse.context["mode_multi"])
        self.assertContains(reponse, "École Un")
        self.assertContains(reponse, "École Deux")

    def test_etablissement_non_visible_absent_de_lannuaire(self):
        Etablissement.objects.create(nom="École Publique")
        Etablissement.objects.create(nom="École Cachée", visible_dans_annuaire=False)
        reponse = self.client.get(reverse("vitrine:accueil"))
        self.assertNotContains(reponse, "École Cachée")

    def test_choisir_etablissement_redirige_vers_connexion_avec_bonne_identite(self):
        etablissement = Etablissement.objects.create(nom="École Choisie")
        Etablissement.objects.create(nom="Autre École")
        reponse = self.client.get(
            reverse("vitrine:choisir_etablissement", args=[etablissement.slug]), follow=True,
        )
        self.assertContains(reponse, "École Choisie")

    def test_aucun_etablissement_page_dediee(self):
        reponse = self.client.get(reverse("vitrine:accueil"))
        self.assertTemplateUsed(reponse, "vitrine/aucun_etablissement.html")
