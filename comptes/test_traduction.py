"""
Moteur de traduction (comptes.traduction) et catalogue arabe (comptes/traductions/ar.csv).

Le moteur remplace, dans le HTML déjà produit, les textes qui figurent EXACTEMENT au catalogue ; tout le reste (données, scripts,
textes inconnus) reste tel quel. Le catalogue est vérifié ligne par ligne : une erreur de saisie (valeur {0} perdue, texte vide,
doublon) est refusée ici, avant qu'une page s'affiche de travers.
"""
import csv
import html
import inspect
import importlib
import re

from django.db import models
from django.test import SimpleTestCase, TestCase

from comptes.templatetags.traductions import TEXTES_JS
from comptes.traduction import (
    DOSSIER_CATALOGUES, TROU, Catalogue, catalogue_pour, chaines_non_traduites, normaliser, textes_de_la_page, traduire_html,
)


def catalogue(*entrees):
    return Catalogue(list(entrees))


class NormalisationTests(SimpleTestCase):
    def test_espaces_sauts_de_ligne_et_apostrophes(self):
        self.assertEqual(normaliser("  Bonjour \n\t  l’école  "), "Bonjour l'école")
        self.assertEqual(normaliser("a b c"), "a b c")


class TextesExactsTests(SimpleTestCase):
    def test_un_texte_du_catalogue_est_traduit_sans_tenir_compte_des_espaces(self):
        c = catalogue(("Tableau de bord", "لوحة التحكم"))
        for texte in ("Tableau de bord", "  Tableau   de\nbord ", "Tableau de bord"):
            with self.subTest(texte=texte):
                self.assertEqual(c.traduire(texte), "لوحة التحكم")

    def test_un_texte_inconnu_n_est_pas_traduit(self):
        c = catalogue(("Élèves", "التلاميذ"))
        self.assertIsNone(c.traduire("Élèves inscrits"))  # jamais de correspondance partielle
        self.assertIsNone(c.traduire("Kadidia Bagayoko"))
        self.assertIsNone(c.traduire(""))

    def test_les_apostrophes_courbes_et_droites_sont_equivalentes(self):
        c = catalogue(("L'école", "المدرسة"))
        self.assertEqual(c.traduire("L’école"), "المدرسة")

    def test_les_traductions_vides_sont_ignorees(self):
        self.assertIsNone(catalogue(("Élèves", "  ")).traduire("Élèves"))


class PhrasesATrousTests(SimpleTestCase):
    def test_une_valeur_est_remplacee_et_gardee(self):
        c = catalogue(("{0} élèves inscrits.", "{0} تلميذًا مسجلًا."), ("{0} élève inscrit.", "{0} تلميذ مسجل."))
        self.assertEqual(c.traduire("27 élèves inscrits."), "27 تلميذًا مسجلًا.")
        self.assertEqual(c.traduire("1 élève inscrit."), "1 تلميذ مسجل.")
        self.assertIsNone(c.traduire("élèves inscrits."))

    def test_plusieurs_valeurs_dans_un_autre_ordre(self):
        c = catalogue(("{0} sur {1}", "{1} من {0}"))
        self.assertEqual(c.traduire("3 sur 8"), "8 من 3")

    def test_la_valeur_captee_est_traduite_si_elle_est_connue(self):
        c = catalogue(("Bonjour, {0}", "مرحبًا، {0}"), ("Fondateur", "المؤسس"))
        self.assertEqual(c.traduire("Bonjour, Mamadou"), "مرحبًا، Mamadou")
        self.assertEqual(c.traduire("Bonjour, Fondateur"), "مرحبًا، المؤسس")

    def test_le_motif_le_plus_precis_gagne(self):
        c = catalogue(("{0} : {1}", "{0} : {1}"), ("Adresse actuelle : {0}", "العنوان الحالي : {0}"))
        self.assertEqual(c.traduire("Adresse actuelle : a@b.ml"), "العنوان الحالي : a@b.ml")

    def test_les_caracteres_speciaux_du_texte_ne_cassent_pas_le_motif(self):
        c = catalogue(("{0} élève(s) en risque (urgent) ?", "{0} تلميذ(ة) (عاجل) ؟"))
        self.assertEqual(c.traduire("2 élève(s) en risque (urgent) ?"), "2 تلميذ(ة) (عاجل) ؟")


class MorceauxSepares(SimpleTestCase):
    def test_des_textes_colles_par_un_separateur_sont_traduits_un_par_un(self):
        c = catalogue(("Fondateur", "المؤسس"), ("Garçons", "الذكور"), ("Filles", "الإناث"))
        self.assertEqual(c.traduire("Fondateur · Jeudi 15 octobre"), "المؤسس · Jeudi 15 octobre")
        self.assertEqual(c.traduire("Garçons / Filles"), "الذكور / الإناث")
        self.assertEqual(c.traduire("Élèves - Groupe Scolaire X"), None)  # rien de connu : inchangé
        c2 = catalogue(("Élèves", "التلاميذ"))
        self.assertEqual(c2.traduire("Élèves - Groupe Scolaire X"), "التلاميذ - Groupe Scolaire X")

    def test_un_long_paragraphe_n_est_jamais_decoupe(self):
        c = catalogue(("Élèves", "التلاميذ"))
        long = "Élèves - " + "mot " * 80
        self.assertIsNone(c.traduire(long))


class PageHtmlTests(SimpleTestCase):
    C = catalogue(
        ("Élèves", "التلاميذ"), ("Rechercher un élève...", "ابحث عن تلميذ..."), ("Fermer", "إغلاق"), ("Enregistrer", "حفظ"),
        ("Supprimer ce paiement ?", "حذف هذه الدفعة؟"), ("Dossier", "الملف"), ("R&D", "البحث والتطوير"), ("Français", "اللغة الفرنسية"),
    )

    def traduire(self, contenu):
        return traduire_html(contenu, self.C)

    def test_les_textes_de_la_page_sont_traduits_et_la_mise_en_forme_conservee(self):
        entree = '<main>\n  <h1 class="titre">Élèves</h1>\n  <p>Élèves <b>Dossier</b></p>\n</main>'
        sortie = self.traduire(entree)
        self.assertEqual(sortie, '<main>\n  <h1 class="titre">التلاميذ</h1>\n  <p>التلاميذ <b>الملف</b></p>\n</main>')

    def test_les_attributs_lisibles_sont_traduits(self):
        entree = (
            '<input type="search" placeholder="Rechercher un élève..." aria-label="Fermer" class="x">'
            '<a href="/x/" title="Enregistrer" data-confirmer="Supprimer ce paiement ?">lien</a><img src="a.png" alt="Dossier">'
        )
        sortie = self.traduire(entree)
        for attendu in ('placeholder="ابحث عن تلميذ..."', 'aria-label="إغلاق"', 'title="حفظ"', 'data-confirmer="حذف هذه الدفعة؟"', 'alt="الملف"'):
            with self.subTest(attendu=attendu):
                self.assertIn(attendu, sortie)
        self.assertIn('href="/x/"', sortie)
        self.assertIn('class="x"', sortie)

    def test_la_valeur_d_un_bouton_est_traduite_mais_pas_celle_d_un_champ_de_saisie(self):
        entree = '<input type="submit" value="Enregistrer"><input type="text" name="nom" value="Enregistrer"><input type="hidden" value="Fermer">'
        sortie = self.traduire(entree)
        self.assertIn('type="submit" value="حفظ"', sortie)
        self.assertIn('type="text" name="nom" value="Enregistrer"', sortie)  # ce qu'un utilisateur a tapé n'est jamais traduit
        self.assertIn('type="hidden" value="Fermer"', sortie)

    def test_les_attributs_composes_ne_sont_pas_confondus(self):
        sortie = self.traduire('<div data-title="Fermer" xtitle="Fermer" title="Fermer"></div>')
        self.assertIn('data-title="Fermer"', sortie)
        self.assertIn('xtitle="Fermer"', sortie)
        self.assertIn('title="إغلاق"', sortie)

    def test_scripts_styles_et_commentaires_restent_intacts(self):
        entree = (
            '<script>var a = "Élèves"; if (1 < 2) {}</script><style>.x::after { content: "Élèves"; }</style>'
            '<!-- Élèves --><p>Élèves</p>'
        )
        sortie = self.traduire(entree)
        self.assertIn('var a = "Élèves"; if (1 < 2) {}', sortie)
        self.assertIn('content: "Élèves"', sortie)
        self.assertIn("<!-- Élèves -->", sortie)
        self.assertIn("<p>التلاميذ</p>", sortie)

    def test_un_textarea_garde_son_contenu_mais_son_placeholder_se_traduit(self):
        sortie = self.traduire('<textarea placeholder="Fermer" name="m">Élèves</textarea>')
        self.assertIn('placeholder="إغلاق"', sortie)
        self.assertIn(">Élèves</textarea>", sortie)

    def test_les_entites_html_sont_comprises_et_la_sortie_est_echappee(self):
        self.assertEqual(self.traduire("<p>R&amp;D</p>"), "<p>البحث والتطوير</p>")
        c = catalogue(("Test", "a < b & c"))
        self.assertEqual(traduire_html("<p>Test</p>", c), "<p>a &lt; b &amp; c</p>")
        c = catalogue(("Test", 'dit "oui"'))
        self.assertIn('title="dit &quot;oui&quot;"', traduire_html('<a title="Test">x</a>', c))

    def test_translate_no_protege_un_texte_et_ce_qu_il_contient(self):
        entree = '<button><span translate="no">Français</span> Élèves</button><b>Français</b>'
        sortie = self.traduire(entree)
        self.assertIn('<span translate="no">Français</span>', sortie)
        self.assertIn("<b>اللغة الفرنسية</b>", sortie)
        self.assertIn("التلاميذ</button>", sortie)

    def test_translate_no_imbrique_et_balises_sans_fermeture(self):
        entree = '<div translate="no"><div>Élèves</div><input placeholder="Fermer"><br>Élèves</div><p>Élèves</p>'
        sortie = self.traduire(entree)
        self.assertIn('<div translate="no"><div>Élèves</div><input placeholder="Fermer"><br>Élèves</div>', sortie)
        self.assertTrue(sortie.endswith("<p>التلاميذ</p>"))
        sortie = self.traduire('<input translate="no" placeholder="Fermer"><p>Élèves</p>')
        self.assertEqual(sortie, '<input translate="no" placeholder="Fermer"><p>التلاميذ</p>')

    def test_traduire_deux_fois_ne_change_rien(self):
        une = self.traduire("<h1>Élèves</h1>")
        self.assertEqual(self.traduire(une), une)

    def test_un_catalogue_vide_rend_la_page_telle_quelle(self):
        page = "<p>Élèves</p>"
        self.assertEqual(traduire_html(page, Catalogue([])), page)

    def test_les_espaces_autour_d_un_texte_sont_conserves(self):
        self.assertEqual(self.traduire("<p>\n    Élèves\n</p>"), "<p>\n    التلاميذ\n</p>")

    def test_textes_de_la_page_et_textes_sans_traduction(self):
        page = '<title>Élèves - École X</title><p>Élèves</p><input placeholder="Inconnu ici"><p>12</p><p>مرحبا</p>'
        self.assertEqual(textes_de_la_page(page), ["Élèves - École X", "Élèves", "Inconnu ici", "12", "مرحبا"])
        self.assertEqual(chaines_non_traduites(page, self.C), ["Inconnu ici"])  # connu (morceau), nombre et arabe exclus


class CatalogueArabeTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with open(DOSSIER_CATALOGUES / "ar.csv", encoding="utf-8-sig", newline="") as fichier:
            lecteur = csv.DictReader(fichier)
            cls.colonnes = lecteur.fieldnames
            cls.lignes = list(lecteur)
        cls.catalogue = catalogue_pour("ar")

    def test_les_colonnes(self):
        self.assertEqual(self.colonnes, ["francais", "arabe", "note"])
        self.assertGreater(len(self.lignes), 700)

    def test_aucun_doublon(self):
        cles = [normaliser(ligne["francais"]) for ligne in self.lignes]
        doublons = sorted({cle for cle in cles if cles.count(cle) > 1})
        self.assertEqual(doublons, [])

    def test_chaque_ligne_est_complete_et_propre(self):
        problemes = []
        for ligne in self.lignes:
            francais, arabe = ligne["francais"], ligne["arabe"]
            if not arabe.strip():
                problemes.append(f"vide : {francais}")
            if arabe != arabe.strip() or "  " in arabe or "\n" in arabe:
                problemes.append(f"espaces : {francais}")
            if re.search(r"<[^>]+>", arabe):
                problemes.append(f"balise HTML : {francais}")
            if sorted(TROU.findall(francais)) != sorted(TROU.findall(arabe)):
                problemes.append(f"valeurs {{n}} différentes : {francais}")
            if len(set(TROU.findall(francais))) != len(TROU.findall(francais)):
                problemes.append(f"valeur répétée : {francais}")
            if not re.search(r"[؀-ۿ]", arabe) and normaliser(arabe) != normaliser(francais) and re.search(r"[^\W\d_]", re.sub(r"\{\d+\}", "", arabe)):
                problemes.append(f"aucune lettre arabe : {francais} -> {arabe}")
        self.assertEqual(problemes, [])

    def test_le_catalogue_charge_toutes_ses_lignes(self):
        self.assertEqual(len(self.catalogue), len(self.lignes))

    def test_les_textes_ecrits_par_le_javascript_sont_traduits(self):
        for texte in TEXTES_JS:
            with self.subTest(texte=texte):
                self.assertIsNotNone(self.catalogue.traduire(texte))

    def test_tous_les_libelles_de_choix_de_l_application_sont_traduits(self):
        """Rôles, statuts, modes de paiement, cycles... : un nouveau libellé de choix doit recevoir sa traduction arabe."""
        from django.apps import apps

        manquants = set()
        for modele in apps.get_models():
            for champ in modele._meta.get_fields():
                for _, libelle in getattr(champ, "choices", None) or []:
                    if libelle and self.catalogue.traduire(str(libelle)) is None and not re.search(r"[؀-ۿ]", str(libelle)):
                        manquants.add(str(libelle))
        for nom in (
            "comptes.roles", "finances.models", "scolarite.models", "pedagogie.models", "etablissement.models",
            "communication.models", "permissions_matrix.modules", "comptabilite.models",
        ):
            module = importlib.import_module(nom)
            for _, classe in inspect.getmembers(module, inspect.isclass):
                if issubclass(classe, models.Choices):
                    for membre in classe:
                        if self.catalogue.traduire(str(membre.label)) is None and not re.search(r"[؀-ۿ]", str(membre.label)):
                            manquants.add(str(membre.label))
        self.assertEqual(sorted(manquants), [])

    def test_les_termes_scolaires_cles(self):
        attendus = {
            "Élèves": "التلاميذ", "Bulletin": "كشف النقاط", "Moyenne générale": "المعدل العام", "Fondateur": "المؤسس",
            "Tableau de bord": "لوحة التحكم", "Enseignant": "المدرّس", "Parent": "ولي الأمر",
        }
        for francais, arabe in attendus.items():
            with self.subTest(francais=francais):
                self.assertEqual(self.catalogue.traduire(francais), arabe)

    def test_le_nom_d_une_langue_n_est_pas_dans_le_catalogue_arabe_sous_sa_forme_de_bouton(self):
        """« Français » désigne la matière dans les données ; le bouton de langue est protégé par translate="no"."""
        self.assertEqual(self.catalogue.traduire("Français"), "اللغة الفرنسية")

    def test_une_phrase_a_trous_du_catalogue_se_traduit(self):
        self.assertEqual(self.catalogue.traduire("27 élèves inscrits."), "27 تلميذًا مسجلًا.")
        self.assertEqual(self.catalogue.traduire("Bonjour, Mamadou"), "مرحبًا، Mamadou")
        self.assertEqual(self.catalogue.traduire("35 000 FCFA"), "35 000 فرنك CFA")
        self.assertEqual(self.catalogue.traduire("mai : 0 FCFA"), "مايو : 0 فرنك CFA")
