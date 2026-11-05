"""
Page de présentation publique (/presentation/) : écrite pour les moteurs de recherche autant que pour les directeurs d'école.

Elle doit être indexable (un seul titre principal, une description, une adresse canonique, des données structurées valides), ouverte à
tous (visiteur, utilisateur connecté, propriétaire de la plateforme), ne montrer aucune donnée d'école ni de personne, n'afficher le contact
que s'il est configuré, ne contenir ni style ni script en ligne (la politique de sécurité du site les interdit) et se lire en arabe sans
lettre latine.
"""
import json
import re

from django.test import TestCase, override_settings
from django.urls import reverse

from comptes.langues import NOM_COOKIE_LANGUE
from comptes.roles import Role
from comptes.traduction import restes_latins
from etablissement.models import Etablissement
from vitrine.test_pages_legales import compte

ADRESSE = "/presentation/"


class PresentationTests(TestCase):
    def page(self, **extra):
        reponse = self.client.get(ADRESSE, **extra)
        self.assertEqual(reponse.status_code, 200)
        return reponse.content.decode("utf-8")

    def test_page_publique_et_indexable(self):
        contenu = self.page()
        self.assertEqual(reverse("vitrine:presentation"), ADRESSE)
        self.assertNotIn("noindex", contenu)  # contrairement aux pages légales, celle-ci est faite pour être trouvée
        self.assertEqual(len(re.findall(r"<h1[\s>]", contenu)), 1)
        self.assertIn("<h1>Logiciel de gestion scolaire pour les écoles du Mali</h1>", contenu)
        self.assertRegex(contenu, r"<title>[^<]*Mali[^<]*Yelenova</title>")

    def test_titres_qui_reprennent_ce_que_l_on_cherche(self):
        contenu = self.page()
        sous_titres = re.findall(r"<h[23][^>]*>(.*?)</h[23]>", contenu, re.S)
        for attendu in ("Paiements, reçus et caisse", "Orange Money et Moov Money", "Conseil de classe", "Notes et bulletins",
                        "Cantine et vente de tenues", "Questions fréquentes", "Pour quelles écoles ?", "Les soucis de chaque jour, réglés",
                        "Prêt en trois étapes", "Un espace pour chacun"):
            self.assertIn(attendu, [t.strip() for t in sous_titres], attendu)

    def test_situations_vecues_et_captures_de_l_application(self):
        contenu = self.page()
        # six situations concrètes, puis la solution
        self.assertEqual(contenu.count("presentation-probleme"), 6)
        for situation in ("Qui a payé ? On ne sait plus.", "Le parent apprend l'absence trop tard.", "Saisir les notes quand le réseau coupe."):
            self.assertIn(situation, contenu)
        # le haut de la page montre l'application elle-même, avec un texte alternatif pour chaque image
        self.assertEqual(len(re.findall(r'<img src="/static/img/vitrine/[^"]+\.webp"[^>]* alt="[^"]{20,}"', contenu)), 3)
        self.assertEqual(len(re.findall(r'class="presentation-etape-numero"', contenu)), 3)

    def test_description_courte_et_adresse_canonique(self):
        contenu = self.page()
        description = re.search(r'<meta name="description" content="([^"]*)"', contenu).group(1)
        self.assertLessEqual(len(description), 170)
        self.assertIn("Mali", description)
        self.assertIn('<link rel="canonical" href="https://yelenova.com/presentation/">', contenu)
        self.assertIn('<meta property="og:url" content="https://yelenova.com/presentation/">', contenu)

    @override_settings(URL_PUBLIQUE="https://exemple.test")
    def test_l_adresse_publique_vient_de_la_configuration(self):
        contenu = self.page()
        self.assertIn('<link rel="canonical" href="https://exemple.test/presentation/">', contenu)
        self.assertNotIn("yelenova.com", contenu.split("</head>")[0])

    def test_donnees_structurees_valides(self):
        contenu = self.page()
        bloc = re.search(r'<script type="application/ld\+json">(.*?)</script>', contenu, re.S).group(1)
        donnees = json.loads(bloc)
        types = {element["@type"]: element for element in donnees["@graph"]}
        self.assertEqual(set(types), {"Organization", "SoftwareApplication"})
        self.assertEqual(types["Organization"]["name"], "Yelenova")
        self.assertEqual(types["SoftwareApplication"]["applicationCategory"], "EducationalApplication")
        self.assertEqual(types["SoftwareApplication"]["inLanguage"], ["fr", "ar"])
        self.assertEqual(types["SoftwareApplication"]["publisher"], {"@id": types["Organization"]["@id"]})
        self.assertNotIn("offers", types["SoftwareApplication"])  # aucun prix n'est publié

    def test_aucun_prix_ni_chiffre_commercial_invente(self):
        contenu = self.page()
        for interdit in ("FCFA", "gratuit", "Gratuit", "essai"):
            self.assertNotIn(interdit, contenu)

    def test_aucun_style_ni_script_en_ligne(self):
        contenu = self.page()
        self.assertNotRegex(contenu, r"\sstyle\s*=")
        scripts_en_ligne = [s for s in re.findall(r"<script\b[^>]*>", contenu) if "src=" not in s and "ld+json" not in s]
        self.assertEqual(scripts_en_ligne, [])

    def test_aucune_donnee_d_ecole_ni_de_personne(self):
        ecole = Etablissement.objects.create(nom="École Confidentielle du Test")
        compte("parent-presentation@example.com", Role.PARENT, ecole)
        contenu = self.page()
        self.assertNotIn("Confidentielle", contenu)
        self.assertNotIn("parent-presentation", contenu)

    def test_ouverte_aux_utilisateurs_connectes_et_au_proprietaire(self):
        ecole = Etablissement.objects.create(nom="École de présentation")
        enseignant = compte("prof-presentation@example.com", Role.ENSEIGNANT, ecole)
        proprietaire = compte("owner-presentation@example.com", Role.DEVELOPPEUR, is_superuser=True)
        provisoire = compte("eleve-presentation@example.com", Role.ELEVE, ecole, matricule="2026PRES1", doit_changer_mot_de_passe=True)
        for utilisateur in (enseignant, proprietaire, provisoire):
            self.client.force_login(utilisateur)
            with self.subTest(role=utilisateur.role):
                reponse = self.client.get(ADRESSE)
                self.assertEqual(reponse.status_code, 200)
                self.assertNotContains(reponse, "n'est rattaché à aucun établissement")

    @override_settings(CONTACT_WHATSAPP="", CONTACT_COURRIEL="")
    def test_pas_de_bloc_de_contact_tant_qu_il_n_est_pas_configure(self):
        contenu = self.page()
        self.assertNotIn("wa.me", contenu)
        self.assertNotIn("mailto:", contenu)
        self.assertNotIn('id="contact"', contenu)

    @override_settings(CONTACT_WHATSAPP="+223 70 00 00 00", CONTACT_COURRIEL="contact@exemple.test")
    def test_contact_affiche_quand_il_est_configure(self):
        contenu = self.page()
        self.assertIn("https://wa.me/22370000000?text=", contenu)
        self.assertIn('mailto:contact@exemple.test', contenu)
        self.assertIn('id="contact"', contenu)

    def test_liee_depuis_l_accueil_et_les_pages_legales(self):
        Etablissement.objects.create(nom="École unique")
        for adresse in ("/", reverse("vitrine:mentions_legales"), reverse("vitrine:confidentialite")):
            with self.subTest(page=adresse):
                self.assertContains(self.client.get(adresse), f'href="{ADRESSE}"')

    def test_en_arabe_aucune_lettre_latine_ne_reste(self):
        self.client.cookies[NOM_COOKIE_LANGUE] = "ar"
        contenu = self.page()
        self.assertIn('dir="rtl"', contenu)
        # Le bouton de langue s'écrit dans la langue vers laquelle il bascule : « Français » est la seule exception (comme dans test_arabe_pur).
        self.assertEqual([t for t in restes_latins(contenu) if t != "Français"], [])
        self.assertIn("برنامج للتسيير المدرسي في مدارس مالي", contenu)
