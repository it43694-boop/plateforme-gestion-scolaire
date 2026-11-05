"""
Section « Ressources » (/ressources/) : guides pratiques pour les directeurs d'école, écrits pour répondre à ce qu'ils cherchent sur Google.

Chaque article doit être indexable (un seul titre principal, description courte, adresse canonique, données structurées valides), présent dans le plan du site
avec sa date, ouvert à tous, sans style ni script en ligne, et ne promettre que ce que l'application fait. Le corps d'un article reste en français quand la page
est en arabe ; tout le reste de la page (navigation, boutons, pied de page) se lit en arabe sans lettre latine.
"""
import json
import re
from html.parser import HTMLParser

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.html import escape

from comptes.langues import NOM_COOKIE_LANGUE
from comptes.roles import Role
from comptes.traduction import ADRESSES, LETTRE_OU_CHIFFRE_LATIN
from etablissement.models import Etablissement
from vitrine.articles import ARTICLES
from vitrine.test_pages_legales import compte


class TextesHorsContenuFrancais(HTMLParser):
    """Les textes et attributs lisibles d'une page, sans l'en-tête ni les blocs marqués translate="no" (le corps des articles, en français)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.textes, self._profondeur_protegee, self._tag_protege, self._dans_tete = [], 0, None, False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "head":
            self._dans_tete = True
        if self._profondeur_protegee:
            if tag == self._tag_protege:
                self._profondeur_protegee += 1
            return
        if attrs.get("translate") == "no":
            self._profondeur_protegee, self._tag_protege = 1, tag
            return
        if not self._dans_tete:
            self.textes.extend(attrs[nom] for nom in ("alt", "title", "aria-label") if attrs.get(nom))

    def handle_endtag(self, tag):
        if tag == "head":
            self._dans_tete = False
        if self._profondeur_protegee and tag == self._tag_protege:
            self._profondeur_protegee -= 1

    def handle_data(self, data):
        if not self._profondeur_protegee and not self._dans_tete and data.strip():
            self.textes.append(" ".join(data.split()))


def chemin(article):
    return reverse("vitrine:article", kwargs={"slug": article.slug})


class RessourcesTests(TestCase):
    def page(self, adresse, **extra):
        reponse = self.client.get(adresse, **extra)
        self.assertEqual(reponse.status_code, 200, adresse)
        return reponse.content.decode("utf-8")

    def test_liste_indexable_avec_tous_les_articles(self):
        contenu = self.page(reverse("vitrine:ressources"))
        self.assertEqual(len(re.findall(r"<h1[\s>]", contenu)), 1)
        self.assertNotIn("noindex", contenu)
        self.assertIn('<link rel="canonical" href="https://yelenova.com/ressources/">', contenu)
        for article in ARTICLES:
            self.assertIn(f'href="{chemin(article)}"', contenu)
            self.assertIn(escape(article.titre), contenu)

    def test_chaque_article_est_indexable_et_bien_forme(self):
        for article in ARTICLES:
            with self.subTest(article=article.slug):
                contenu = self.page(chemin(article))
                self.assertEqual(len(re.findall(r"<h1[\s>]", contenu)), 1)
                self.assertIn(f"<h1>{escape(article.titre)}</h1>", contenu)
                self.assertNotIn("noindex", contenu)
                self.assertIn(f'<link rel="canonical" href="https://yelenova.com{chemin(article)}">', contenu)
                self.assertRegex(contenu, rf"<title>{re.escape(escape(article.titre))} - Yelenova</title>")
                self.assertLessEqual(len(article.description), 160)
                self.assertIn(f'<meta name="description" content="{escape(article.description)}">', contenu)
                # un vrai texte (plusieurs sous-titres, pas une page vide) et des liens vers les autres articles
                self.assertGreaterEqual(len(re.findall(r"<h2[\s>]", contenu)), 6)
                for autre in ARTICLES:
                    if autre is not article:
                        self.assertIn(f'href="{chemin(autre)}"', contenu)

    def test_donnees_structurees_article_et_fil_d_ariane(self):
        for article in ARTICLES:
            with self.subTest(article=article.slug):
                contenu = self.page(chemin(article))
                bloc = re.search(r'<script type="application/ld\+json">(.*?)</script>', contenu, re.S).group(1)
                donnees = json.loads(bloc)
                types = {element["@type"]: element for element in donnees["@graph"]}
                self.assertEqual(set(types), {"Article", "BreadcrumbList"})
                self.assertEqual(types["Article"]["headline"], article.titre)
                self.assertEqual(types["Article"]["datePublished"], article.publie_le.isoformat())
                self.assertEqual(types["Article"]["dateModified"], article.modifie_le.isoformat())
                self.assertEqual(types["Article"]["mainEntityOfPage"]["@id"], f"https://yelenova.com{chemin(article)}")
                self.assertEqual([e["position"] for e in types["BreadcrumbList"]["itemListElement"]], [1, 2, 3])

    def test_article_inconnu_et_adresse_mal_formee(self):
        self.assertEqual(self.client.get("/ressources/n-existe-pas/").status_code, 404)
        self.assertEqual(self.client.get("/ressources/Article_Majuscule/").status_code, 404)

    def test_les_articles_ont_des_adresses_et_des_titres_uniques(self):
        self.assertEqual(len({a.slug for a in ARTICLES}), len(ARTICLES))
        self.assertEqual(len({a.titre for a in ARTICLES}), len(ARTICLES))
        self.assertEqual(len({a.gabarit for a in ARTICLES}), len(ARTICLES))
        self.assertTrue(all(a.modifie_le >= a.publie_le for a in ARTICLES))

    def test_plan_du_site_avec_la_date_de_chaque_article(self):
        contenu = self.client.get("/sitemap.xml").content.decode("utf-8")
        self.assertIn("<loc>https://yelenova.com/ressources/</loc>", contenu)
        for article in ARTICLES:
            self.assertIn(f"<loc>https://yelenova.com{chemin(article)}</loc><lastmod>{article.modifie_le.isoformat()}</lastmod>", contenu)

    def test_aucun_style_ni_script_en_ligne(self):
        for adresse in [reverse("vitrine:ressources")] + [chemin(a) for a in ARTICLES]:
            with self.subTest(adresse=adresse):
                contenu = self.page(adresse)
                self.assertNotRegex(contenu, r"\sstyle\s*=")
                scripts_en_ligne = [s for s in re.findall(r"<script\b[^>]*>", contenu) if "src=" not in s and "ld+json" not in s]
                self.assertEqual(scripts_en_ligne, [])

    def test_ne_promet_pas_ce_que_l_application_ne_fait_pas(self):
        """Aucun prix, aucune statistique inventée, et les limites de l'application (pas de prélèvement, pas de branchement aux opérateurs) sont dites."""
        for article in ARTICLES:
            contenu = self.page(chemin(article))
            for interdit in ("gratuit", "Gratuit", "garanti", "100 %", "100%", "sans effort"):
                self.assertNotIn(interdit, contenu, f"{article.slug} : {interdit}")
        self.assertIn("n'envoie aucun message WhatsApp toute seule", self.page(chemin(ARTICLES[0])))
        self.assertIn("Yelenova ne prélève pas l'argent", self.page(chemin(ARTICLES[0])))
        self.assertIn("n'est pas reliée aux opérateurs", self.page(chemin(ARTICLES[2])))
        self.assertIn("(14 + 30) ÷ 3 = 14,67", self.page(chemin(ARTICLES[1])))  # l'exemple de calcul est juste
        self.assertIn("154 ÷ 12 = <strong>12,83 sur 20</strong>", self.page(chemin(ARTICLES[1])))

    @override_settings(CONTACT_WHATSAPP="", CONTACT_COURRIEL="")
    def test_pas_de_bouton_whatsapp_sans_contact_configure(self):
        self.assertNotIn("wa.me", self.page(chemin(ARTICLES[0])))

    @override_settings(CONTACT_WHATSAPP="+223 70 00 00 00")
    def test_bouton_whatsapp_quand_le_contact_est_configure(self):
        self.assertIn("https://wa.me/22370000000?text=", self.page(chemin(ARTICLES[0])))

    def test_aucune_donnee_d_ecole_ni_de_personne(self):
        ecole = Etablissement.objects.create(nom="École Confidentielle du Test")
        compte("parent-ressources@example.com", Role.PARENT, ecole)
        for adresse in [reverse("vitrine:ressources")] + [chemin(a) for a in ARTICLES]:
            contenu = self.page(adresse)
            self.assertNotIn("Confidentielle", contenu)
            self.assertNotIn("parent-ressources", contenu)

    def test_ouverte_a_tous_les_profils(self):
        ecole = Etablissement.objects.create(nom="École de ressources")
        enseignant = compte("prof-ressources@example.com", Role.ENSEIGNANT, ecole)
        proprietaire = compte("owner-ressources@example.com", Role.DEVELOPPEUR, is_superuser=True)
        provisoire = compte("eleve-ressources@example.com", Role.ELEVE, ecole, matricule="2026RES1", doit_changer_mot_de_passe=True)
        for utilisateur in (enseignant, proprietaire, provisoire):
            self.client.force_login(utilisateur)
            for adresse in [reverse("vitrine:ressources")] + [chemin(a) for a in ARTICLES]:
                with self.subTest(role=utilisateur.role, adresse=adresse):
                    self.assertEqual(self.client.get(adresse).status_code, 200)

    def test_liens_depuis_l_accueil_les_pages_legales_et_la_presentation(self):
        Etablissement.objects.create(nom="École unique")
        for adresse in ("/", reverse("vitrine:mentions_legales"), reverse("vitrine:presentation")):
            with self.subTest(page=adresse):
                self.assertContains(self.client.get(adresse), f'href="{reverse("vitrine:ressources")}"')

    def test_en_arabe_la_page_se_lit_en_arabe_et_le_corps_reste_en_francais(self):
        self.client.cookies[NOM_COOKIE_LANGUE] = "ar"
        for adresse in [reverse("vitrine:ressources")] + [chemin(a) for a in ARTICLES]:
            with self.subTest(adresse=adresse):
                contenu = self.page(adresse)
                self.assertIn('dir="rtl"', contenu)
                analyseur = TextesHorsContenuFrancais()
                analyseur.feed(contenu)
                restes = [t for t in analyseur.textes if t != "Français" and LETTRE_OU_CHIFFRE_LATIN.search(ADRESSES.sub("", t))]
                self.assertEqual(restes, [])
        article = self.page(chemin(ARTICLES[0]))
        self.assertIn("هذا المقال متوفر بالفرنسية فقط.", article)
        self.assertIn('<article lang="fr" dir="ltr" translate="no"', article)  # le texte de l'article n'est jamais traduit à moitié
        self.assertIn(escape(ARTICLES[0].titre), article)
