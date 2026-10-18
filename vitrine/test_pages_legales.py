"""
Pages légales : mentions légales, conditions d'utilisation, politique de confidentialité.

Publiques (visiteur anonyme comme utilisateur connecté, propriétaire de la plateforme compris), jamais de donnée
personnelle, jamais de style ni de script en ligne (la politique de sécurité du site les interdit), et ce qui n'est
pas configuré (éditeur, supervision, assistant IA) n'est ni inventé ni affiché.
"""
from django.test import TestCase, override_settings
from django.urls import reverse

from comptes.models import Utilisateur
from comptes.roles import Role, StatutCompte
from etablissement.models import Etablissement

PAGES = {
    "vitrine:mentions_legales": "Mentions légales",
    "vitrine:conditions": "Conditions d'utilisation",
    "vitrine:confidentialite": "Politique de confidentialité",
}


def compte(email, role, etablissement=None, **extra):
    utilisateur = Utilisateur(
        email=email, prenom="Test", nom="Utilisateur", role=role, etablissement=etablissement,
        statut=StatutCompte.ACTIF, is_active=True, **extra,
    )
    utilisateur.set_password("MotDePasse#2026")
    utilisateur.full_clean(exclude=["password"])
    utilisateur.save()
    return utilisateur


class AccesTests(TestCase):
    def test_pages_publiques(self):
        for nom, titre in PAGES.items():
            with self.subTest(page=nom):
                reponse = self.client.get(reverse(nom))
                self.assertEqual(reponse.status_code, 200)
                self.assertContains(reponse, f"<h1>{titre}</h1>", html=True)
                self.assertContains(reponse, "octobre 2026")  # date de dernière mise à jour
                self.assertContains(reponse, 'name="robots" content="noindex"')

    def test_pages_ouvertes_aux_utilisateurs_connectes_et_au_proprietaire(self):
        ecole = Etablissement.objects.create(nom="École légale")
        enseignant = compte("prof-legal@example.com", Role.ENSEIGNANT, ecole)
        proprietaire = compte("owner-legal@example.com", Role.DEVELOPPEUR, is_superuser=True)
        for utilisateur in (enseignant, proprietaire):
            self.client.force_login(utilisateur)
            for nom in PAGES:
                with self.subTest(role=utilisateur.role, page=nom):
                    reponse = self.client.get(reverse(nom))
                    self.assertEqual(reponse.status_code, 200)
                    # le propriétaire n'est pas renvoyé vers « aucun établissement » depuis une page publique
                    self.assertNotContains(reponse, "n'est rattaché à aucun établissement")

    def test_un_mot_de_passe_provisoire_ne_bloque_pas_la_lecture_des_documents_publics(self):
        """Les documents restent lisibles avant de choisir son mot de passe (ils sont publics) : pas de piège à la connexion."""
        ecole = Etablissement.objects.create(nom="École légale")
        eleve = compte("eleve-legal@example.com", Role.ELEVE, ecole, matricule="2026LEGAL1", doit_changer_mot_de_passe=True)
        self.client.force_login(eleve)
        for nom in PAGES:
            self.assertEqual(self.client.get(reverse(nom)).status_code, 200)

    def test_aucun_style_ni_script_en_ligne(self):
        for nom in PAGES:
            contenu = self.client.get(reverse(nom)).content.decode("utf-8")
            with self.subTest(page=nom):
                self.assertNotIn("style=", contenu)
                self.assertNotIn("<script", contenu)
                self.assertNotIn("onclick=", contenu)

    def test_en_tete_de_securite_present(self):
        reponse = self.client.get(reverse("vitrine:confidentialite"))
        self.assertIn("default-src 'self'", reponse["Content-Security-Policy"])


class ContenuTests(TestCase):
    def test_les_documents_se_renvoient_l_un_a_l_autre(self):
        for nom in PAGES:
            contenu = self.client.get(reverse(nom)).content.decode("utf-8")
            for autre in PAGES:
                self.assertIn(reverse(autre), contenu)

    @override_settings(PAGES_LEGALES_VALIDEES=False)
    def test_bandeau_version_provisoire_tant_que_non_valide(self):
        for nom in PAGES:
            self.assertContains(self.client.get(reverse(nom)), "Version provisoire")

    @override_settings(PAGES_LEGALES_VALIDEES=True)
    def test_plus_de_bandeau_une_fois_valide(self):
        for nom in PAGES:
            self.assertNotContains(self.client.get(reverse(nom)), "Version provisoire")

    @override_settings(
        EDITEUR_NOM="Yelenova Test SARL", EDITEUR_STATUT="société à responsabilité limitée", EDITEUR_ADRESSE="Bamako, ACI 2000",
        EDITEUR_EMAIL="contact@exemple.test", EDITEUR_TELEPHONE="+223 70 00 00 00", EDITEUR_IMMATRICULATION="RCCM-ML-BKO-0000",
        DIRECTEUR_PUBLICATION="Awa Test",
    )
    def test_identite_de_l_editeur_affichee_quand_elle_est_configuree(self):
        mentions = self.client.get(reverse("vitrine:mentions_legales"))
        for texte in ("Yelenova Test SARL", "Bamako, ACI 2000", "RCCM-ML-BKO-0000", "+223 70 00 00 00", "Awa Test",
                      "mailto:contact@exemple.test"):
            self.assertContains(mentions, texte)
        self.assertContains(self.client.get(reverse("vitrine:confidentialite")), "mailto:contact@exemple.test")
        self.assertContains(self.client.get(reverse("vitrine:conditions")), "mailto:contact@exemple.test")

    @override_settings(EDITEUR_NOM="", EDITEUR_STATUT="", EDITEUR_ADRESSE="", EDITEUR_EMAIL="", EDITEUR_TELEPHONE="",
                       EDITEUR_IMMATRICULATION="", DIRECTEUR_PUBLICATION="")
    def test_rien_n_est_invente_quand_l_editeur_n_est_pas_configure(self):
        for nom in PAGES:
            reponse = self.client.get(reverse(nom))
            self.assertNotContains(reponse, "mailto:")
            self.assertNotContains(reponse, "RCCM")
        self.assertContains(self.client.get(reverse("vitrine:mentions_legales")), "identité non renseignée")

    @override_settings(SENTRY_DSN="", GROQ_API_KEY="")
    def test_prestataires_facultatifs_absents_s_ils_ne_sont_pas_configures(self):
        for nom in ("vitrine:mentions_legales", "vitrine:confidentialite"):
            reponse = self.client.get(reverse(nom))
            self.assertNotContains(reponse, "Sentry")
            self.assertNotContains(reponse, "Groq")
            self.assertContains(reponse, "Render")
            self.assertContains(reponse, "Supabase")
            self.assertContains(reponse, "Brevo")

    @override_settings(SENTRY_DSN="https://cle@exemple.test/1", GROQ_API_KEY="cle-factice")
    def test_prestataires_facultatifs_cites_s_ils_sont_configures(self):
        for nom in ("vitrine:mentions_legales", "vitrine:confidentialite"):
            reponse = self.client.get(reverse(nom))
            self.assertContains(reponse, "Sentry")
            self.assertContains(reponse, "Groq")
        self.assertContains(self.client.get(reverse("vitrine:confidentialite")), "ni le nom ni le matricule")

    def test_la_politique_cite_les_donnees_sensibles_et_les_droits(self):
        contenu = self.client.get(reverse("vitrine:confidentialite")).content.decode("utf-8")
        for texte in ("handicap", "2013-015", "APDP", "mineurs", "aucun cookie publicitaire", "sous-traitant"):
            self.assertIn(texte, contenu)


class LiensDepuisLesPagesDeLApplicationTests(TestCase):
    def choisir_une_ecole(self):
        """L'inscription et la connexion se font dans une école choisie (page d'accueil ou lien /e/<école>/)."""
        ecole = Etablissement.objects.create(nom="École d'inscription", actif=True, visible_dans_annuaire=True)
        self.client.get(reverse("vitrine:choisir_etablissement", args=[ecole.slug]))
        return ecole

    def test_liens_dans_les_pages_de_connexion_et_d_inscription(self):
        self.choisir_une_ecole()
        for nom in ("comptes:connexion", "comptes:inscription"):
            reponse = self.client.get(reverse(nom))
            self.assertEqual(reponse.status_code, 200)
            contenu = reponse.content.decode("utf-8")
            with self.subTest(page=nom):
                for page in PAGES:
                    self.assertIn(reverse(page), contenu)

    def test_avis_a_l_inscription(self):
        self.choisir_une_ecole()
        reponse = self.client.get(reverse("comptes:inscription"))
        self.assertContains(reponse, "En créant un compte, vous acceptez")

    def test_liens_sur_l_accueil_public(self):
        Etablissement.objects.create(nom="École vitrine", actif=True, visible_dans_annuaire=True)
        contenu = self.client.get(reverse("vitrine:accueil")).content.decode("utf-8")
        for page in PAGES:
            self.assertIn(reverse(page), contenu)

    def test_liens_dans_l_application_connectee(self):
        ecole = Etablissement.objects.create(nom="École légale")
        enseignant = compte("prof-liens@example.com", Role.ENSEIGNANT, ecole)
        self.client.force_login(enseignant)
        contenu = self.client.get(reverse("comptes:redirection_tableau_de_bord"), follow=True).content.decode("utf-8")
        for page in PAGES:
            self.assertIn(reverse(page), contenu)
