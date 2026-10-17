"""
Moteur de traduction et d'arabisation : cas qui ont cassé une page arabe « pure » (ordre des phrases à trous, phrases collées, mots entre
parenthèses, dates, heures, chiffres tapés en arabe, secrets laissés en chiffres latins).
"""
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from comptes.arabisation import Localisateur, finaliser_arabe, chiffres_ascii
from comptes.langues import NOM_COOKIE_LANGUE
from comptes.roles import Role
from comptes.traduction import Catalogue, restes_latins, traduire_html
from statistiques.test_education import EducationBase, creer_compte


class PrioriteDesPhrasesTests(SimpleTestCase):
    def setUp(self):
        self.c = Catalogue([
            ("{0} : {1}", "{0} : {1}"), ("Adresse : {0}", "العنوان : {0}"), ("Modifier {0}", "تعديل {0}"), ("Modifier un compte", "تعديل حساب"),
            ("Enseignant", "المدرّس"), ("Mathématiques", "الرياضيات"), ("Bonjour.", "مرحبًا."), ("Filles", "الإناث"), ("Garçons", "الذكور"),
            ("Dossier complet", "الملف مكتمل"), ("Libellé", "البيان"), ("Matricule : {0}.", "رقم التسجيل : {0}."),
            ("Au revoir.", "إلى اللقاء."), ("Élève inscrit.", "تم تسجيل التلميذ."),
        ])

    def test_la_phrase_la_plus_precise_passe_avant_le_modele_general(self):
        self.assertEqual(self.c.traduire("Adresse : Kati"), "العنوان : Kati")

    def test_un_titre_avec_un_nom_d_ecole_est_decoupe_avant_la_phrase_a_trou(self):
        self.assertEqual(self.c.traduire("Modifier un compte - École X"), "تعديل حساب - École X")

    def test_un_mot_entre_parentheses_se_traduit_a_part(self):
        self.assertEqual(self.c.traduire("Awa Sidibé (Enseignant)"), "Awa Sidibé (المدرّس)")
        self.assertEqual(self.c.traduire("6ème A (Mathématiques)"), "6ème A (الرياضيات)")

    def test_la_virgule_francaise_separe_des_morceaux_et_devient_arabe(self):
        self.assertEqual(self.c.traduire("Garçons, Filles"), "الذكور، الإناث")
        self.assertEqual(self.c.traduire("Garçons : 13 (48 %), Filles : 14 (52 %)"), "الذكور : 13 (48 %)، الإناث : 14 (52 %)")

    def test_le_deux_points_colle_par_django_ne_cache_pas_le_mot(self):
        self.assertEqual(self.c.traduire("Libellé"), "البيان")
        html = '<label for="x">Libellé:</label>'
        self.assertIn("البيان:", traduire_html(html, self.c))

    def test_des_phrases_collees_sont_traduites_une_a_une(self):
        self.assertEqual(self.c.traduire("Élève inscrit. Matricule : 12. Dossier complet."), "تم تسجيل التلميذ. رقم التسجيل : 12. الملف مكتمل.")
        self.assertEqual(self.c.traduire("Bonjour. Texte libre inconnu."), "مرحبًا. Texte libre inconnu.")

    def test_un_texte_sans_rien_de_connu_reste_inchange(self):
        self.assertIsNone(self.c.traduire("Texte libre inconnu. Autre phrase inconnue."))


class DatesEtHeuresTests(SimpleTestCase):
    def test_mois_et_jours_en_arabe(self):
        self.assertEqual(finaliser_arabe("17 octobre 2026"), "١٧ أكتوبر ٢٠٢٦")
        self.assertEqual(finaliser_arabe("Lundi 5 Mars"), "الاثنين ٥ مارس")
        self.assertEqual(finaliser_arabe("17 oct. 2026"), "١٧ أكتوبر ٢٠٢٦")
        self.assertEqual(finaliser_arabe("le samedi à 9h"), "le السبت à ٩:٠٠")
        self.assertEqual(finaliser_arabe("7h30"), "٧:٣٠")

    def test_un_mot_qui_contient_un_nom_de_mois_n_est_pas_touche(self):
        self.assertEqual(finaliser_arabe("maintenant"), "maintenant")
        self.assertEqual(finaliser_arabe("samedis"), "samedis")

    def test_chiffres_ecrits_en_arabe_sont_relus_en_chiffres_latins(self):
        self.assertEqual(chiffres_ascii("٠١٢٣٤٥٦٧٨٩"), "0123456789")
        self.assertEqual(chiffres_ascii("۰۱۲۳۴۵۶۷۸۹"), "0123456789")  # variante persane des claviers
        self.assertEqual(chiffres_ascii("٢٠٢٦-١٠-١٧"), "2026-10-17")


class ClassesEtMotsCourantsTests(SimpleTestCase):
    def setUp(self):
        self.loc = Localisateur({"6eme a": "السنة السادسة أ", "mamadou keita": "محمدو كيتا"}, formes=["6ème", "A", "Mamadou", "Keita"])

    def test_un_a_accentue_n_est_pas_la_lettre_de_la_classe(self):
        self.assertEqual(self.loc.remplacer("de la 6ème à la 7ème année"), "de la 6ème à la 7ème année")
        self.assertEqual(self.loc.remplacer("6ème A"), "السنة السادسة أ")


class ChiffresSaisisTests(EducationBase):
    """Tapés avec un clavier arabe, les chiffres arrivent au reste de l'application en chiffres latins (hors mots de passe)."""

    def setUp(self):
        self.fondateur = creer_compte(Role.FONDATEUR, "fondateur@chiffres.test", self.ecole)
        self.client = Client()
        self.client.force_login(self.fondateur)
        self.client.cookies[NOM_COOKIE_LANGUE] = "ar"

    def test_une_recherche_avec_des_chiffres_arabes_trouve_l_eleve(self):
        eleve = self.e5
        arabes = eleve.matricule.translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))
        reponse = self.client.get(reverse("scolarite:recherche_globale"), {"q": arabes})
        self.assertContains(reponse, arabes)  # trouvé : son numéro s'affiche (en chiffres arabes, comme toute la page)
        self.assertNotContains(reponse, "Aucun élève ne correspond")

    def test_les_champs_de_mot_de_passe_ne_sont_pas_convertis(self):
        from comptes.langue import ChiffresOccidentauxMiddleware
        from django.http import QueryDict
        from django.test import RequestFactory

        requete = RequestFactory().post("/x/", {"password": "mot٣", "nom": "٥٥", "new_password1": "٧", "mot_de_passe_actuel": "٨"})
        recu = {}
        ChiffresOccidentauxMiddleware(lambda r: recu.update(r.POST.dict()) or None)(requete)
        self.assertEqual(recu, {"password": "mot٣", "nom": "55", "new_password1": "٧", "mot_de_passe_actuel": "٨"})


class SecretsEtReferencesTests(TestCase):
    def test_le_secret_2fa_et_les_codes_de_secours_gardent_leurs_chiffres_latins(self):
        html = '<div class="cle-secrete-affichage" translate="no" dir="ltr">ABC7XYZ9</div><p>7 élèves</p>'
        sortie = traduire_html(html, Catalogue([("élèves", "تلاميذ")]), chiffres=finaliser_arabe)
        self.assertIn("ABC7XYZ9", sortie)
        self.assertIn("٧", sortie)

    def test_les_restes_latins_ignorent_le_signe_de_multiplication(self):
        self.assertEqual(restes_latins("<button>×</button><p>٣ ÷ ٤</p>"), [])
