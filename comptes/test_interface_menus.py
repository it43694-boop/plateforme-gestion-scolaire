"""
Corrections d'interface (phase 78) : menus d'actions des lignes de tableau, grille des chiffres du tableau de bord, recherche dans le menu
latéral et page d'accueil publique (vrai logo, atouts, captures, contact).
"""
import re

from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from comptes.context_processors import MESSAGE_DEMONSTRATION, lien_whatsapp_demonstration
from comptes.roles import Role
from finances.models import TypeTranche, enregistrer_paiement
from statistiques.test_education import EducationBase, creer_compte


def menus(html):
    """Le contenu de chaque panneau de menu d'actions de la page."""
    return re.findall(r'<div class="menu-actions-panneau">(.*?)</div>\s*</details>', html, re.S)


class MenusDesLignesDeTableauTests(EducationBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        enregistrer_paiement(
            eleve=cls.e1, inscription=cls.i["e1"], tranche=TypeTranche.VERSEMENT, montant=15000, mode_paiement="especes",
            enregistre_par=cls.comptable,
        )

    def test_la_liste_des_classes_range_les_actions_dans_un_menu_sans_colonne_excel(self):
        self.client.force_login(self.fondateur)
        reponse = self.client.get(reverse("scolarite:liste_classes"))
        page = reponse.content.decode()
        self.assertNotIn("<th>Excel</th>", page)
        classes = list(reponse.context["classes"])
        panneaux = menus(page)
        self.assertEqual(len(panneaux), len(classes))  # une ligne, un menu
        premier = panneaux[0]
        for texte in ("Emploi du temps", "Statistiques", "Télécharger", "Liste (Excel)", "Bulletins (PDF)", "Absences (Excel)"):
            self.assertIn(texte, premier)
        sans_eleve = sum(1 for classe in classes if classe.effectif == 0)
        self.assertGreater(sans_eleve, 0)
        self.assertEqual(sum("Supprimer" in panneau for panneau in panneaux), sans_eleve)  # seules les classes sans élève se suppriment
        # Les trois boutons d'en-tête restent visibles, hors des menus.
        for texte in ("Créer une classe", "Affecter un enseignant", "Définir les niveaux"):
            self.assertContains(self.client.get(reverse("scolarite:liste_classes")), texte)

    def test_paiements_le_recu_reste_visible_et_la_suppression_est_dans_le_menu_de_la_direction(self):
        self.client.force_login(self.fondateur)
        page = self.client.get(reverse("finances:liste_paiements")).content.decode()
        self.assertEqual(page.count("Reçu PDF"), 1)
        panneau = menus(page)[0]
        self.assertIn("Corriger", panneau)
        self.assertIn("Supprimer", panneau)
        self.assertIn("menu-actions-danger", panneau)
        self.assertIn("reference-val", page)  # la référence ne se coupe pas en deux lignes

    def test_paiements_le_comptable_corrige_mais_ne_supprime_pas(self):
        self.client.force_login(self.comptable)
        page = self.client.get(reverse("finances:liste_paiements")).content.decode()
        panneau = menus(page)[0]
        self.assertIn("Corriger", panneau)
        self.assertNotIn("Supprimer", panneau)

    def test_paiements_le_parent_ne_voit_que_le_recu_sans_menu(self):
        self.client.force_login(self.parent)
        reponse = self.client.get(reverse("finances:liste_paiements"))
        self.assertEqual(reponse.status_code, 200)
        page = reponse.content.decode()
        self.assertIn("Reçu PDF", page)
        self.assertEqual(menus(page), [])
        self.assertNotIn("Supprimer", page)

    def test_dossier_de_l_eleve_les_documents_et_les_actions_sensibles_sont_dans_des_menus(self):
        self.client.force_login(self.fondateur)
        page = self.client.get(reverse("scolarite:dossier_eleve", args=[self.e1.matricule])).content.decode()
        panneaux = menus(page)
        self.assertGreaterEqual(len(panneaux), 2)
        imprimer, plus = panneaux[0], panneaux[1]
        self.assertIn("Attestation de scolarité", imprimer)
        self.assertIn("Clôturer", plus)
        self.assertIn("menu-actions-danger", plus)
        # Les actions de consultation restent visibles.
        for texte in ("Voir le bulletin", "Historique des absences", "Corriger le dossier"):
            self.assertIn(texte, page)

    def test_mes_classes_de_l_enseignant_garde_les_saisies_visibles_et_range_le_reste(self):
        self.client.force_login(self.t1)
        page = self.client.get(reverse("pedagogie:mes_classes")).content.decode()
        panneau = menus(page)[0]
        for texte in ("Programme", "Emploi du temps", "Télécharger", "Liste (PDF)"):
            self.assertIn(texte, panneau)
        hors_menu = page.replace(panneau, "")
        for texte in ("Notes", "Absences", "Cahier de textes"):
            self.assertIn(texte, hors_menu)

    def test_liste_des_eleves_les_exports_de_la_classe_sont_dans_un_menu(self):
        self.client.force_login(self.fondateur)
        page = self.client.get(reverse("scolarite:liste_eleves"), {"classe": self.c6a.pk}).content.decode()
        panneau = menus(page)[0]
        self.assertIn("Exporter la classe (PDF)", panneau)
        self.assertIn("Importer depuis Excel", page)
        self.assertNotIn("Importer depuis Excel", panneau)

    def test_le_choix_de_classe_disparait_quand_il_n_y_a_rien_a_choisir(self):
        eleve_seul = creer_compte(Role.ELEVE, "seul@menus.test", self.ecole)
        from scolarite.models import Inscription
        Inscription.objects.create(eleve=eleve_seul, classe=self.c9a)
        self.client.force_login(eleve_seul)
        reponse = self.client.get(reverse("scolarite:liste_eleves"))
        self.assertEqual(reponse.status_code, 200)
        self.assertNotContains(reponse, 'aria-label="Filtrer par classe"')
        self.client.force_login(self.fondateur)
        self.assertContains(self.client.get(reverse("scolarite:liste_eleves")), 'aria-label="Filtrer par classe"')


class TableauDeBordEtMenuLateralTests(EducationBase):
    def test_les_chiffres_cles_sont_dans_une_grille_qui_connait_leur_nombre(self):
        self.client.force_login(self.fondateur)
        page = self.client.get(reverse("comptes:redirection_tableau_de_bord"), follow=True).content.decode()
        trouve = re.search(r'<div class="grille-indicateurs" data-nombre="(\d+)">', page)
        self.assertIsNotNone(trouve)
        self.assertEqual(page.count('stat-carte-valeur'), int(trouve.group(1)))
        self.assertNotIn("col-xl-3", page)

    def test_le_menu_lateral_a_son_champ_de_recherche(self):
        self.client.force_login(self.fondateur)
        page = self.client.get(reverse("comptes:redirection_tableau_de_bord"), follow=True).content.decode()
        self.assertIn("data-filtre-menu", page)
        self.assertIn("data-filtre-resultats", page)
        self.assertIn('aria-label="Chercher une page du menu"', page)

    def test_la_recherche_du_menu_a_son_message_traduit_pour_le_navigateur(self):
        from comptes.templatetags.traductions import TEXTES_JS
        self.assertIn("Aucune page ne correspond.", TEXTES_JS)


class AccueilPublicTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Sans aucune école, l'accueil affiche une page d'attente : il en faut au moins deux pour voir la page complète.
        from etablissement.models import Etablissement
        Etablissement.objects.create(nom="École accueil A")
        Etablissement.objects.create(nom="École accueil B")

    def test_le_vrai_logo_remplace_la_toque_et_la_bande_qui_defile_a_disparu(self):
        page = self.client.get(reverse("vitrine:accueil")).content.decode()
        self.assertIn("vitrine-decor-centre-logo", page)
        self.assertIn("logo-yelenova-embleme", page)
        self.assertNotIn("vitrine-ticker", page)
        self.assertIn("vitrine-atouts", page)

    def test_les_atouts_et_les_nouvelles_cartes_sont_la(self):
        page = self.client.get(reverse("vitrine:accueil")).content.decode()
        for texte in (
            "En français et en arabe", "Paiement Mobile Money", "Alertes sur le téléphone des parents",
            "Français et arabe", "Cantine &amp; vie scolaire", "Sur téléphone, même sans réseau", "Communication &amp; alertes",
            "L'application en images",
        ):
            self.assertIn(texte, page)
        self.assertNotIn("Notification email automatique", page)

    def test_les_captures_existent_et_sont_annoncees_avec_leurs_dimensions(self):
        page = self.client.get(reverse("vitrine:accueil")).content.decode()
        for nom in ("tableau-de-bord", "portail-parent", "declarer-paiement"):
            with self.subTest(capture=nom):
                self.assertIsNotNone(finders.find(f"img/vitrine/{nom}.webp"))
                self.assertIsNotNone(finders.find(f"img/vitrine/{nom}-ar.webp"))
                self.assertIn(f"img/vitrine/{nom}.webp", page)
                self.assertNotIn(f"img/vitrine/{nom}-ar.webp", page)
        self.assertEqual(len(re.findall(r'class="vitrine-vue ', page)), 3)

    def test_en_arabe_les_captures_sont_celles_de_l_application_en_arabe(self):
        from comptes.langues import NOM_COOKIE_LANGUE
        self.client.cookies[NOM_COOKIE_LANGUE] = "ar"
        page = self.client.get(reverse("vitrine:accueil")).content.decode()
        for nom in ("tableau-de-bord", "portail-parent", "declarer-paiement"):
            with self.subTest(capture=nom):
                self.assertIn(f"img/vitrine/{nom}-ar.webp", page)

    def test_l_apercu_de_partage_porte_le_logo(self):
        page = self.client.get(reverse("vitrine:accueil")).content.decode()
        self.assertRegex(page, r'<meta property="og:image" content="https?://[^"]+logo-yelenova[^"]*\.png">')

    @override_settings(CONTACT_WHATSAPP="", CONTACT_COURRIEL="")
    def test_sans_contact_configure_aucun_bloc_de_contact(self):
        page = self.client.get(reverse("vitrine:accueil")).content.decode()
        self.assertNotIn('id="contact"', page)
        self.assertNotIn("wa.me", page)
        self.assertNotIn("mailto:", page)

    @override_settings(CONTACT_WHATSAPP="+223 70 00 00 00", CONTACT_COURRIEL="contact@exemple.test")
    def test_avec_un_contact_le_bloc_propose_whatsapp_et_le_courriel(self):
        page = self.client.get(reverse("vitrine:accueil")).content.decode()
        self.assertIn('id="contact"', page)
        self.assertIn('href="https://wa.me/22370000000?text=', page)
        self.assertIn('href="mailto:contact@exemple.test"', page)
        self.assertIn('href="#contact"', page)

    @override_settings(CONTACT_WHATSAPP="", CONTACT_COURRIEL="contact@exemple.test")
    def test_le_courriel_seul_suffit_et_ne_cree_pas_de_lien_whatsapp(self):
        page = self.client.get(reverse("vitrine:accueil")).content.decode()
        self.assertIn('id="contact"', page)
        self.assertNotIn("wa.me", page)


class LienWhatsappDeDemonstrationTests(SimpleTestCase):
    def test_seuls_les_chiffres_du_numero_sont_gardes(self):
        lien = lien_whatsapp_demonstration("+223 (70) 00-00-00")
        self.assertTrue(lien.startswith("https://wa.me/22370000000?text="))

    def test_sans_numero_il_n_y_a_pas_de_lien(self):
        self.assertEqual(lien_whatsapp_demonstration(""), "")
        self.assertEqual(lien_whatsapp_demonstration("   "), "")
        self.assertEqual(lien_whatsapp_demonstration(None), "")
        self.assertEqual(lien_whatsapp_demonstration("abc"), "")

    def test_le_message_est_dans_la_langue_de_la_page(self):
        from urllib.parse import quote
        self.assertIn(quote(MESSAGE_DEMONSTRATION["fr"]), lien_whatsapp_demonstration("22370000000", "fr"))
        self.assertIn(quote(MESSAGE_DEMONSTRATION["ar"]), lien_whatsapp_demonstration("22370000000", "ar"))
        self.assertIn(quote(MESSAGE_DEMONSTRATION["fr"]), lien_whatsapp_demonstration("22370000000", "xx"))

    def test_aucun_numero_reel_n_est_ecrit_dans_les_reglages_du_depot(self):
        # Le contact vient de l'environnement (Render), jamais du dépôt public.
        self.assertEqual(getattr(settings, "CONTACT_WHATSAPP", ""), "")
        self.assertEqual(getattr(settings, "CONTACT_COURRIEL", ""), "")


class MenuDActionsStylesEtScriptTests(SimpleTestCase):
    """Le panneau est posé par app.js : les règles dont il dépend doivent rester présentes."""

    def lire(self, chemin):
        with open(finders.find(chemin), encoding="utf-8") as fichier:
            return fichier.read()

    def test_les_regles_du_menu_existent_dans_la_feuille_de_style(self):
        css = self.lire("css/toumai.css")
        for regle in (".menu-actions-panneau", ".menu-actions-entree", ".menu-actions-danger", ".grille-indicateurs", ".nav-filtre", ".vitrine-atouts"):
            self.assertIn(regle, css)
        # Aucun texte du menu sous 12 px.
        for trouve in re.findall(r"\.(?:menu-actions|nav-filtre|nav-aucun|vitrine-atouts)[^{]*\{[^}]*font-size:\s*([0-9.]+)rem", css):
            self.assertGreaterEqual(float(trouve) * 15, 12)

    def test_le_script_gere_l_ouverture_la_fermeture_et_la_recherche(self):
        js = self.lire("js/app.js")
        for morceau in ("menus-actions-js", 'classList.contains("menu-actions")', 'evenement.key === "Escape"', "data-filtre-menu"):
            self.assertIn(morceau, js)
        self.assertNotIn(".innerHTML = recherche", js)  # le texte tapé n'est jamais injecté comme HTML


class RaccourcisEtFinitionsTests(EducationBase):
    def test_l_eleve_a_ses_raccourcis_vers_ses_propres_pages_et_pas_ceux_d_un_autre(self):
        self.client.force_login(self.e1)
        page = self.client.get(reverse("comptes:redirection_tableau_de_bord"), follow=True).content.decode()
        for texte, adresse in (
            ("Mon bulletin", reverse("pedagogie:bulletin_eleve", args=[self.e1.matricule])),
            ("Mes absences", reverse("pedagogie:historique_absences", args=[self.e1.matricule])),
            ("Mes devoirs", reverse("pedagogie:devoirs")),
        ):
            with self.subTest(raccourci=texte):
                self.assertIn(f'href="{adresse}"', page)
                self.assertIn(texte, page)
        self.assertNotIn(self.e2.matricule, page)

    def test_la_direction_garde_ses_raccourcis_habituels(self):
        self.client.force_login(self.fondateur)
        page = self.client.get(reverse("comptes:redirection_tableau_de_bord"), follow=True).content.decode()
        self.assertIn("Inscrire un élève", page)
        self.assertNotIn("Mon bulletin", page)

    def test_la_page_de_connexion_d_une_ecole_garde_l_identite_de_l_ecole_seule(self):
        # Choix de conception : sur la page d'une école, ni le logo ni le nom de la plateforme ne prennent la place de ceux de l'école.
        page = self.client.get(f"/e/{self.ecole.slug}/", follow=True).content.decode()
        self.assertNotIn("logo-yelenova", page)
        self.assertNotIn("Propulsé par", page)


class NomsLibresEtArabeTests(EducationBase):
    def test_un_mot_courant_dans_un_nom_libre_n_est_jamais_pris_pour_un_nom_de_personne(self):
        """« Tuteur de Moussa » : « de » ne doit pas devenir un « nom » (il casserait la traduction de toutes les phrases qui contiennent « de »)."""
        from comptes.arabisation import construire_index
        from comptes.models import Utilisateur

        Utilisateur.objects.filter(pk=self.e1.pk).update(contact_urgence_nom="Tuteur de Moussa Cissé", nom_pere="Ali du Mali")
        cles = construire_index(self.ecole.pk)["cles"]
        self.assertIn("moussa", cles)
        self.assertIn("cisse", cles)
        for mot in ("de", "du", "tuteur"):
            self.assertNotIn(mot, cles)
