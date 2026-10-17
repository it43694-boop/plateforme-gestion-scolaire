"""
Arabe « pur » : chiffres arabes, noms de personnes, d'école et de classes écrits en lettres arabes.

Les textes de l'application sont traduits par le catalogue (test_traduction) ; ici, ce qui vient des DONNÉES de l'école.
"""
import re

from django.core.cache import cache
from django.test import Client, SimpleTestCase

from comptes.arabisation import (
    Localisateur, arabe_de, chiffres_arabes, chiffres_ascii, construire_index, nom_d_ecole_arabe, nom_de_classe_arabe,
)
from comptes.langues import NOM_COOKIE_LANGUE
from comptes.roles import Role
from comptes.traduction import catalogue_pour, traduire_html
from comptes.transcription import cle, transcrire
from statistiques.test_education import EducationBase, creer_compte


class ChiffresTests(SimpleTestCase):
    def test_les_chiffres_sont_arabes(self):
        self.assertEqual(chiffres_arabes("0123456789"), "٠١٢٣٤٥٦٧٨٩")
        self.assertEqual(chiffres_arabes("16/10/2026"), "١٦/١٠/٢٠٢٦")
        self.assertEqual(chiffres_arabes("1 480 000"), "١ ٤٨٠ ٠٠٠")

    def test_la_virgule_decimale_et_le_pour_cent_sont_arabes(self):
        self.assertEqual(chiffres_arabes("13,81/20"), "١٣٫٨١/٢٠")
        self.assertEqual(chiffres_arabes("47 %"), "٤٧٪")
        self.assertEqual(chiffres_arabes("47%"), "٤٧٪")

    def test_une_virgule_de_liste_ou_un_pourcentage_sans_chiffre_ne_change_pas(self):
        self.assertEqual(chiffres_arabes("1, 2, 3"), "١, ٢, ٣")
        self.assertEqual(chiffres_arabes("100 % sûr"), "١٠٠٪ sûr")
        self.assertEqual(chiffres_arabes("% de réussite"), "% de réussite")
        self.assertEqual(chiffres_arabes(""), "")

    def test_ce_qu_on_tape_en_chiffres_arabes_est_compris(self):
        self.assertEqual(chiffres_ascii("٢٠٢٦٢٢٨٥٩"), "202622859")
        self.assertEqual(chiffres_ascii("۱۲۳"), "123")  # chiffres persans, parfois produits par un clavier
        self.assertEqual(chiffres_ascii("Mamadou 12"), "Mamadou 12")
        self.assertEqual(chiffres_ascii(None), None)


class TranscriptionTests(SimpleTestCase):
    def test_noms_du_dictionnaire(self):
        attendus = {
            "Mamadou Keïta": "محمدو كيتا", "Aïssata Maïga": "عائشة مايغا", "Abdoul Karim Coulibaly": "عبد الكريم كوليبالي",
            "SANGARE Fatoumata": "سانغاري فاطمة", "Ibrahim Touré": "إبراهيم توري", "Kadiatou Sangaré": "خديجة سانغاري",
        }
        for latin, arabe in attendus.items():
            with self.subTest(latin=latin):
                self.assertEqual(transcrire(latin), arabe)

    def test_nom_inconnu_lu_a_la_francaise(self):
        self.assertEqual(transcrire("Samassekou"), "ساماسيكو")
        self.assertEqual(transcrire("Bamba"), "بامبا")
        self.assertEqual(transcrire("Tiécoura"), "تيكورا")
        self.assertEqual(transcrire("Tchiaka"), "تشياكا")

    def test_les_consonnes_doublees_n_en_font_qu_une(self):
        self.assertEqual(transcrire("Zannarra"), transcrire("Zanara"))

    def test_majuscules_accents_et_apostrophes_ne_changent_rien(self):
        self.assertEqual(transcrire("KEÏTA"), transcrire("keita"))
        self.assertEqual(transcrire("N'Diaye"), transcrire("Ndiaye"))
        self.assertEqual(cle("Keïta"), cle("KEITA"))

    def test_un_nom_deja_en_arabe_ou_vide_reste_tel_quel(self):
        self.assertEqual(transcrire("محمد علي"), "محمد علي")
        self.assertEqual(transcrire(""), "")
        self.assertEqual(transcrire("   "), "")

    def test_le_nom_saisi_passe_avant_la_proposition(self):
        self.assertEqual(arabe_de("Mamadou", "محمد"), "محمد")
        self.assertEqual(arabe_de("Mamadou", ""), "محمدو")
        self.assertEqual(arabe_de("Mamadou", "   "), "محمدو")

    def test_aucune_lettre_latine_ne_reste_dans_une_transcription(self):
        for nom in ("Jean-Pierre Dembélé", "Ouologuem", "Niamoye", "Gnagna", "Dioncounda", "Zoé", "Xavier"):
            with self.subTest(nom=nom):
                self.assertIsNone(re.search(r"[A-Za-z]", transcrire(nom)), transcrire(nom))


class LocalisateurTests(SimpleTestCase):
    def setUp(self):
        self.loc = Localisateur({
            cle("Mamadou"): "محمدو", cle("Keïta"): "كيتا", cle("6ème A"): "السنة السادسة أ", cle("Abdoul Karim"): "عبد الكريم",
            cle("Groupe Scolaire Les Étoiles de Bamako"): "مجموعة نجوم باماكو",
        })

    def test_prenom_et_nom_sont_remplaces(self):
        self.assertEqual(self.loc.remplacer("Bonjour, Mamadou Keïta !"), "Bonjour, محمدو كيتا !")
        self.assertEqual(self.loc.remplacer("KEITA Mamadou"), "كيتا محمدو")

    def test_sans_distinction_de_majuscules_ni_d_accents(self):
        self.assertEqual(self.loc.remplacer("Keita"), "كيتا")
        self.assertEqual(self.loc.remplacer("KEÏTA"), "كيتا")

    def test_un_mot_courant_en_minuscule_n_est_pas_un_nom(self):
        loc = Localisateur({cle("Bien"): "جيد", cle("Mamadou"): "محمدو"})
        self.assertEqual(loc.remplacer("très bien, mamadou"), "très bien, mamadou")
        # sauf si la base l'écrit exactement ainsi (nom saisi en minuscules)
        loc = Localisateur({cle("Mamadou"): "محمدو", cle("keita"): "كيتا"}, formes={"keita"})
        self.assertEqual(loc.remplacer("mamadou keita"), "mamadou كيتا")

    def test_les_adresses_email_et_les_liens_sont_intacts(self):
        texte = "Écrire à mamadou.keita@ecole.ml ou Mamadou@ecole.ml, voir https://exemple.ml/Mamadou"
        self.assertEqual(self.loc.remplacer(texte), "Écrire à mamadou.keita@ecole.ml ou Mamadou@ecole.ml, voir https://exemple.ml/Mamadou")

    def test_un_groupe_de_mots_passe_avant_les_mots_seuls(self):
        self.assertEqual(self.loc.remplacer("Abdoul Karim"), "عبد الكريم")
        self.assertEqual(self.loc.remplacer("Groupe Scolaire Les Étoiles de Bamako"), "مجموعة نجوم باماكو")

    def test_une_classe_et_son_annee(self):
        self.assertEqual(self.loc.remplacer("6ème A (2026-2027)"), "السنة السادسة أ (2026-2027)")

    def test_une_phrase_sans_nom_ne_change_pas(self):
        self.assertEqual(self.loc.remplacer("Aucun élève inscrit."), "Aucun élève inscrit.")
        self.assertEqual(Localisateur({}).remplacer("Mamadou"), "Mamadou")

    def test_un_nom_coupe_par_un_autre_mot_n_est_pas_reuni(self):
        self.assertEqual(self.loc.remplacer("Abdoul et Karim"), "Abdoul et Karim")

    def test_un_nom_compose_avec_trait_d_union(self):
        loc = Localisateur({"jean pierre": "جان بيير"})
        self.assertEqual(loc.remplacer("Jean-Pierre"), "جان بيير")
        self.assertEqual(loc.remplacer("Jean Pierre"), "جان بيير")

    def test_noms_de_classes_et_d_ecoles_proposes(self):
        self.assertEqual(nom_de_classe_arabe("6ème A"), "السنة السادسة أ")
        self.assertEqual(nom_de_classe_arabe("9ème année B"), "السنة التاسعة ب")
        self.assertEqual(nom_de_classe_arabe("12ème"), "السنة الثانية عشرة")
        self.assertEqual(nom_de_classe_arabe("Terminale TSE"), "السنة النهائية العلوم الدقيقة")
        self.assertEqual(nom_de_classe_arabe("CAP-E"), "")  # forme inconnue : pas de proposition
        self.assertEqual(nom_d_ecole_arabe("Groupe Scolaire Les Étoiles de Bamako"), "المجموعة المدرسية نجوم باماكو")
        self.assertIsNone(re.search(r"[A-Za-z]", nom_d_ecole_arabe("Collège Horizon de Ségou")))


class MoteurTests(SimpleTestCase):
    def setUp(self):
        self.catalogue = catalogue_pour("ar")
        self.loc = Localisateur({cle("Mamadou"): "محمدو", cle("Keïta"): "كيتا"})

    def traduire(self, page):
        return traduire_html(page, self.catalogue, localisateur=self.loc, chiffres=chiffres_arabes)

    def test_les_noms_et_les_chiffres_des_textes_sont_convertis(self):
        self.assertEqual(self.traduire("<td>Mamadou Keïta</td><td>27</td><td>1 480 000</td>"), "<td>محمدو كيتا</td><td>٢٧</td><td>١ ٤٨٠ ٠٠٠</td>")

    def test_les_attributs_lisibles_aussi(self):
        sortie = self.traduire('<a title="Mamadou Keïta" aria-label="3">٣</a>')
        self.assertIn('title="محمدو كيتا"', sortie)
        self.assertIn('aria-label="٣"', sortie)

    def test_les_valeurs_des_champs_les_adresses_les_scripts_ne_sont_pas_touches(self):
        page = (
            '<input type="text" name="prenom" value="Mamadou"><input type="number" value="12"><a href="/eleves/202622859/dossier/">رابط</a>'
            '<script>var n = 12; var p = "Mamadou";</script><textarea>Mamadou 12</textarea><style>.a{width:12px}</style>'
        )
        self.assertEqual(self.traduire(page), page)

    def test_une_liste_deroulante_garde_ses_valeurs_et_change_son_texte(self):
        sortie = self.traduire('<option value="12">Mamadou Keïta - 6ème</option>')
        self.assertIn('value="12"', sortie)
        self.assertIn("محمدو كيتا", sortie)
        self.assertNotIn("Mamadou", sortie)

    def test_un_texte_inchange_garde_ses_entites(self):
        page = "<p>&amp; &#x27; &lt;</p>"
        self.assertEqual(traduire_html(page, self.catalogue, localisateur=self.loc, chiffres=chiffres_arabes), page)

    def test_la_protection_translate_no_reste_valable(self):
        page = '<span translate="no">Mamadou 12</span>'
        self.assertEqual(self.traduire(page), page)

    def test_sans_arabe_pur_la_traduction_ne_change_pas(self):
        self.assertEqual(
            traduire_html("<td>Mamadou Keïta</td><td>27</td>", self.catalogue),
            "<td><bdi>Mamadou Keïta</bdi></td><td>27</td>",
        )


class IndexEtPagesTests(EducationBase):
    def setUp(self):
        cache.clear()
        self.direction = creer_compte(Role.FONDATEUR, "arabisation@test.test", self.ecole)
        self.client = Client()
        self.client.force_login(self.direction)

    def page_en_arabe(self, adresse, **parametres):
        self.client.cookies[NOM_COOKIE_LANGUE] = "ar"
        return self.client.get(adresse, parametres).content.decode()

    def test_l_index_contient_les_personnes_l_ecole_et_les_classes_de_l_ecole_seulement(self):
        index = construire_index(self.ecole.pk)["cles"]
        self.assertIn(cle(self.e5.prenom), index)
        self.assertIn(cle(self.ecole.nom), index)
        self.assertEqual(index[cle("9A")], "السنة التاسعة أ")  # la classe 9A de l'école
        self.assertNotIn(cle(self.ecole_b.nom), index)  # l'autre école n'y est pas
        self.assertIn("fondateur", index)
        self.assertNotIn("fondateur b", index)  # ni les personnes de l'autre école

    def test_l_ecriture_saisie_passe_avant_la_proposition(self):
        self.e5.prenom, self.e5.prenom_ar = "Mamadou", "محمد"
        self.e5.save()
        self.assertEqual(construire_index(self.ecole.pk)["cles"][cle("Mamadou")], "محمد")

    def test_une_page_en_arabe_montre_les_noms_saisis_et_les_chiffres_arabes(self):
        self.e5.prenom_ar, self.e5.nom_ar = "اختبار", "خامس"
        self.e5.save()
        page = self.page_en_arabe("/scolarite/eleves/")
        self.assertIn("اختبار خامس", page)
        self.assertIn(chiffres_arabes(self.e5.matricule), page)
        self.assertNotIn(f">{self.e5.matricule}<", page)

    def test_changer_un_nom_met_la_page_a_jour_tout_de_suite(self):
        self.e5.prenom_ar, self.e5.nom_ar = "اختبار", "خامس"
        self.e5.save()
        self.assertIn("اختبار خامس", self.page_en_arabe("/scolarite/eleves/"))
        self.e5.prenom_ar = "تجربة"
        self.e5.save()
        page = self.page_en_arabe("/scolarite/eleves/")
        self.assertIn("تجربة خامس", page)
        self.assertNotIn("اختبار خامس", page)

    def test_le_francais_ne_change_pas(self):
        self.e5.prenom_ar = "اختبار"
        self.e5.save()
        self.client.cookies[NOM_COOKIE_LANGUE] = "fr"
        page = self.client.get("/scolarite/eleves/").content.decode()
        self.assertIn(self.e5.nom_complet, page)
        self.assertNotIn("اختبار", page)

    def test_la_barre_du_haut_montre_le_nom_du_compte_en_arabe(self):
        self.direction.prenom_ar, self.direction.nom_ar = "مدير", "المدرسة"
        self.direction.save()
        page = self.page_en_arabe("/comptes/tableau-de-bord/")
        self.assertIn("مدير المدرسة", page)
        self.assertNotIn(self.direction.nom_complet, page)
