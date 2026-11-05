"""
Référencement : robots.txt, plan du site (sitemap.xml) et adresse secondaire non indexée.

Seule l'adresse publique (URL_PUBLIQUE) doit être référencée. Le site répond aussi à l'adresse de l'hébergeur (onrender.com), que des cartes
imprimées ou des signets peuvent encore utiliser : on ne la ferme pas, mais ses réponses portent « X-Robots-Tag: noindex ».
"""
import re
import xml.etree.ElementTree as ET

from django.test import TestCase, override_settings
from django.urls import get_resolver, reverse

from comptes.roles import Role
from vitrine.test_pages_legales import compte
from vitrine.views import PAGES_A_REFERENCER, PREFIXES_NON_PARCOURUS

HOTES = ["yelenova.com", "www.yelenova.com", "plateforme-gestion-scolaire.onrender.com"]
ESPACE_SITEMAP = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


class RobotsTests(TestCase):
    def texte(self):
        reponse = self.client.get("/robots.txt")
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(reponse["Content-Type"].startswith("text/plain"))
        return reponse.content.decode("utf-8")

    def test_prive_ferme_public_ouvert(self):
        lignes = self.texte().splitlines()
        self.assertEqual(lignes[0], "User-agent: *")
        for prefixe in ("/comptes/", "/scolarite/", "/finances/", "/admin/", "/verifier/", "/e/"):
            self.assertIn(f"Disallow: {prefixe}", lignes)
        # tout le site n'est pas fermé : la présentation, le style et les pages légales (qui portent « noindex ») restent lisibles
        for interdit in ("Disallow: /", "Disallow: /presentation/", "Disallow: /static/", "Disallow: /mentions-legales/", "Disallow: /confidentialite/"):
            self.assertNotIn(interdit, lignes)

    def test_annonce_le_plan_du_site_a_l_adresse_publique(self):
        self.assertIn("Sitemap: https://yelenova.com/sitemap.xml", self.texte().splitlines())

    @override_settings(URL_PUBLIQUE="https://exemple.test")
    def test_l_adresse_du_plan_vient_de_la_configuration(self):
        self.assertIn("Sitemap: https://exemple.test/sitemap.xml", self.texte().splitlines())

    def test_chaque_partie_privee_de_l_application_est_fermee(self):
        """Une future application (un nouveau « path(..., include(...)) » dans config/urls.py) ne doit pas échapper à robots.txt."""
        oubliees = []
        for motif in get_resolver().url_patterns:
            route = str(motif.pattern)
            if not route or "vitrine" in getattr(motif, "app_name", "") or route in ("",):
                continue
            if "/" + route not in PREFIXES_NON_PARCOURUS:
                oubliees.append(route)
        self.assertEqual(oubliees, [], "À ajouter à PREFIXES_NON_PARCOURUS (vitrine/views.py) : " + ", ".join(oubliees))

    def test_le_proprietaire_de_la_plateforme_n_est_pas_renvoye_ailleurs(self):
        proprietaire = compte("owner-referencement@example.com", Role.DEVELOPPEUR, is_superuser=True)
        self.client.force_login(proprietaire)
        for adresse in ("/robots.txt", "/sitemap.xml"):
            self.assertEqual(self.client.get(adresse).status_code, 200, adresse)


class PlanDuSiteTests(TestCase):
    def adresses(self):
        reponse = self.client.get("/sitemap.xml")
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(reponse["Content-Type"].startswith("application/xml"))
        racine = ET.fromstring(reponse.content)  # XML valide
        self.assertEqual(racine.tag, ESPACE_SITEMAP + "urlset")
        return [url.find(ESPACE_SITEMAP + "loc").text for url in racine]

    def test_liste_l_accueil_et_la_presentation_a_l_adresse_publique(self):
        self.assertEqual(self.adresses(), ["https://yelenova.com/", "https://yelenova.com/presentation/"])

    @override_settings(URL_PUBLIQUE="https://exemple.test")
    def test_l_adresse_vient_de_la_configuration(self):
        self.assertEqual(self.adresses(), ["https://exemple.test/", "https://exemple.test/presentation/"])

    def test_ne_liste_que_des_pages_indexables(self):
        """Une page du plan du site ne doit ni être fermée par robots.txt ni porter « noindex » (les pages légales, qui le portent, n'y figurent pas)."""
        self.assertEqual(PAGES_A_REFERENCER, ("vitrine:accueil", "vitrine:presentation"))
        for nom in PAGES_A_REFERENCER:
            chemin = reverse(nom)
            reponse = self.client.get(chemin)
            self.assertEqual(reponse.status_code, 200, chemin)
            self.assertNotIn(b"noindex", reponse.content, chemin)
            self.assertFalse(any(chemin.startswith(prefixe) for prefixe in PREFIXES_NON_PARCOURUS if prefixe != "/"), chemin)
        contenu = "\n".join(self.adresses())
        for legale in ("mentions-legales", "conditions-d-utilisation", "confidentialite"):
            self.assertNotIn(legale, contenu)


@override_settings(ALLOWED_HOSTS=HOTES + ["testserver"], URL_PUBLIQUE="https://yelenova.com")
class AdresseSecondaireTests(TestCase):
    def entete(self, adresse, hote):
        return self.client.get(adresse, HTTP_HOST=hote).get("X-Robots-Tag")

    def test_l_adresse_publique_et_son_www_sont_indexables(self):
        for hote in ("yelenova.com", "www.yelenova.com"):
            for adresse in ("/", "/presentation/", "/robots.txt", "/sitemap.xml"):
                with self.subTest(hote=hote, adresse=adresse):
                    self.assertIsNone(self.entete(adresse, hote))

    def test_l_adresse_de_l_hebergeur_porte_noindex_sur_toutes_les_pages(self):
        for adresse in ("/", "/presentation/", "/mentions-legales/", "/comptes/connexion/", "/robots.txt", "/sitemap.xml"):
            with self.subTest(adresse=adresse):
                self.assertEqual(self.entete(adresse, "plateforme-gestion-scolaire.onrender.com"), "noindex")

    def test_l_adresse_de_l_hebergeur_reste_ouverte(self):
        """Elle n'est pas fermée : des cartes imprimées et des signets peuvent encore l'utiliser."""
        reponse = self.client.get("/presentation/", HTTP_HOST="plateforme-gestion-scolaire.onrender.com")
        self.assertEqual(reponse.status_code, 200)

    def test_un_port_ne_change_rien(self):
        self.assertIsNone(self.entete("/presentation/", "yelenova.com:443"))
        self.assertEqual(self.entete("/presentation/", "plateforme-gestion-scolaire.onrender.com:10000"), "noindex")

    def test_les_pages_de_presentation_garde_leur_adresse_canonique_sur_l_adresse_de_l_hebergeur(self):
        contenu = self.client.get("/presentation/", HTTP_HOST="plateforme-gestion-scolaire.onrender.com").content.decode("utf-8")
        self.assertIn('<link rel="canonical" href="https://yelenova.com/presentation/">', contenu)
        self.assertIsNone(re.search(r'<meta name="robots" content="noindex"', contenu))  # c'est l'en-tête qui écarte cette adresse, pas la page
