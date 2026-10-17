"""
Langue d'affichage : français (par défaut) ou arabe (de droite à gauche), choisie avec le bouton de langue.

Ordre de choix : le compte connecté, sinon le cookie du visiteur, sinon la langue par défaut de l'école, sinon le français. Le bouton
est ouvert aux visiteurs et à tout compte (même pendant une activation 2FA ou un changement de mot de passe obligatoire) et ne suit
jamais un retour qui sort du site.
"""
import json
import re

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from comptes.langues import NOM_COOKIE_LANGUE
from comptes.models import Utilisateur
from comptes.roles import Role
from comptes.traduction import catalogue_pour, chaines_non_traduites
from pedagogie.models import Affectation
from statistiques.test_education import EducationBase, creer_compte

TABLEAU_DE_BORD = "/comptes/tableau-de-bord/"
LANGUE_FR = re.compile(r'<html lang="fr" dir="ltr">')
LANGUE_AR = re.compile(r'<html lang="ar" dir="rtl">')
MOIS_ARABES = ("يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر")


class ResolutionDeLaLangueTests(EducationBase):
    def setUp(self):
        self.compte = creer_compte(Role.FONDATEUR, "langue@test.test", self.ecole)

    def page(self, cookie=None, connecte=False, adresse=None):
        client = Client()
        if connecte:
            client.force_login(self.compte)
        if cookie:
            client.cookies[NOM_COOKIE_LANGUE] = cookie
        return client.get(adresse or (TABLEAU_DE_BORD if connecte else reverse("comptes:connexion")))

    def test_visiteur_sans_choix_en_francais(self):
        page = self.page()
        self.assertRegex(page.content.decode(), LANGUE_FR)
        self.assertEqual(page["Content-Language"], "fr")

    def test_le_cookie_du_visiteur(self):
        page = self.page(cookie="ar")
        self.assertRegex(page.content.decode(), LANGUE_AR)
        self.assertEqual(page["Content-Language"], "ar")

    def test_un_cookie_invalide_est_ignore(self):
        for valeur in ("de", "", "AR", "ar;fr", "<script>"):
            with self.subTest(valeur=valeur):
                self.assertRegex(self.page(cookie=valeur).content.decode(), LANGUE_FR)

    def test_la_langue_du_compte_passe_avant_le_cookie(self):
        Utilisateur.objects.filter(pk=self.compte.pk).update(langue="ar")
        self.assertRegex(self.page(cookie="fr", connecte=True).content.decode(), LANGUE_AR)
        Utilisateur.objects.filter(pk=self.compte.pk).update(langue="fr")
        self.assertRegex(self.page(cookie="ar", connecte=True).content.decode(), LANGUE_FR)

    def test_sans_choix_du_compte_le_cookie_puis_l_ecole(self):
        self.ecole.langue_par_defaut = "ar"
        self.ecole.save()
        self.assertRegex(self.page(connecte=True).content.decode(), LANGUE_AR)  # langue par défaut de l'école
        self.assertRegex(self.page(cookie="fr", connecte=True).content.decode(), LANGUE_FR)  # le cookie passe avant l'école

    def test_l_ecole_choisie_sur_la_page_de_connexion_donne_sa_langue_au_visiteur(self):
        self.ecole.langue_par_defaut = "ar"
        self.ecole.save()
        client = Client()
        client.get(f"/e/{self.ecole.slug}/", follow=True)
        self.assertEqual(client.session.get("etablissement_id"), self.ecole.pk)
        self.assertRegex(client.get(reverse("comptes:connexion")).content.decode(), LANGUE_AR)
        autre = Client()
        autre.get(f"/e/{self.ecole_b.slug}/", follow=True)  # une autre école reste en français
        self.assertRegex(autre.get(reverse("comptes:connexion")).content.decode(), LANGUE_FR)

    def test_la_langue_par_defaut_d_une_ecole_ne_touche_pas_les_autres(self):
        self.ecole.langue_par_defaut = "ar"
        self.ecole.save()
        compte_b = creer_compte(Role.FONDATEUR, "langue-b@test.test", self.ecole_b)
        client = Client()
        client.force_login(compte_b)
        self.assertRegex(client.get(TABLEAU_DE_BORD).content.decode(), LANGUE_FR)


class BoutonDeLangueTests(EducationBase):
    def test_le_bouton_est_sur_la_connexion_l_accueil_et_l_application(self):
        compte = creer_compte(Role.FONDATEUR, "bouton@test.test", self.ecole)
        client = Client()
        for adresse in (reverse("comptes:connexion"), reverse("vitrine:accueil"), reverse("vitrine:mentions_legales")):
            with self.subTest(adresse=adresse):
                page = client.get(adresse, follow=True).content.decode()
                self.assertIn('class="bouton-langue"', page)
                self.assertIn('name="langue" value="ar"', page)
        client.force_login(compte)
        page = client.get(TABLEAU_DE_BORD).content.decode()
        self.assertIn('class="bouton-langue"', page)
        self.assertIn(f'name="next" value="{TABLEAU_DE_BORD}"', page)
        self.assertIn(f'action="{reverse("comptes:changer_langue")}"', page)

    def test_en_arabe_le_bouton_propose_le_francais_et_n_est_pas_traduit(self):
        client = Client()
        client.cookies[NOM_COOKIE_LANGUE] = "ar"
        page = client.get(reverse("comptes:connexion")).content.decode()
        self.assertIn('name="langue" value="fr"', page)
        self.assertIn('<span translate="no">Français</span>', page)  # jamais « اللغة الفرنسية »
        client.cookies[NOM_COOKIE_LANGUE] = "fr"
        self.assertIn('<span translate="no">العربية</span>', client.get(reverse("comptes:connexion")).content.decode())

    def test_le_bouton_garde_la_page_courante_avec_sa_recherche(self):
        compte = creer_compte(Role.FONDATEUR, "bouton2@test.test", self.ecole)
        client = Client()
        client.force_login(compte)
        page = client.get(reverse("scolarite:liste_eleves"), {"classe": self.c9a.pk}).content.decode()
        self.assertIn(f'name="next" value="{reverse("scolarite:liste_eleves")}?classe={self.c9a.pk}"', page)


class ChangementDeLangueTests(EducationBase):
    def setUp(self):
        self.compte = creer_compte(Role.FONDATEUR, "change@test.test", self.ecole)
        self.autre = creer_compte(Role.COMPTABLE, "autre@test.test", self.ecole)
        self.adresse = reverse("comptes:changer_langue")

    def changer(self, client, langue, suivant=None):
        donnees = {"langue": langue}
        if suivant is not None:
            donnees["next"] = suivant
        return client.post(self.adresse, donnees)

    def test_seulement_en_post(self):
        for methode in ("get", "put", "delete"):
            with self.subTest(methode=methode):
                self.assertEqual(getattr(Client(), methode)(self.adresse).status_code, 405)

    def test_une_langue_inconnue_est_refusee(self):
        for langue in ("de", "", "AR", "ar,fr"):
            with self.subTest(langue=langue):
                reponse = self.changer(Client(), langue)
                self.assertEqual(reponse.status_code, 400)
                self.assertNotIn(NOM_COOKIE_LANGUE, reponse.cookies)

    def test_un_visiteur_change_de_langue_par_cookie(self):
        reponse = self.changer(Client(), "ar", "/comptes/connexion/")
        self.assertRedirects(reponse, "/comptes/connexion/", fetch_redirect_response=False)
        cookie = reponse.cookies[NOM_COOKIE_LANGUE]
        self.assertEqual(cookie.value, "ar")
        self.assertEqual(cookie["max-age"], 365 * 24 * 3600)
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertTrue(cookie["httponly"])

    def test_un_compte_connecte_garde_son_choix_et_les_autres_comptes_ne_changent_pas(self):
        client = Client()
        client.force_login(self.compte)
        self.changer(client, "ar", TABLEAU_DE_BORD)
        self.compte.refresh_from_db()
        self.autre.refresh_from_db()
        self.assertEqual((self.compte.langue, self.autre.langue), ("ar", ""))
        self.assertRegex(client.get(TABLEAU_DE_BORD).content.decode(), LANGUE_AR)
        # même sans cookie (autre navigateur) : le compte se souvient
        autre_navigateur = Client()
        autre_navigateur.force_login(self.compte)
        self.assertRegex(autre_navigateur.get(TABLEAU_DE_BORD).content.decode(), LANGUE_AR)
        self.changer(client, "fr", TABLEAU_DE_BORD)
        self.compte.refresh_from_db()
        self.assertEqual(self.compte.langue, "fr")
        self.assertRegex(client.get(TABLEAU_DE_BORD).content.decode(), LANGUE_FR)

    def test_le_retour_ne_sort_jamais_du_site(self):
        for suivant in ("https://evil.example/", "//evil.example/x", "http://evil.example", "javascript:alert(1)", "\\\\evil.example"):
            with self.subTest(suivant=suivant):
                reponse = self.changer(Client(), "ar", suivant)
                self.assertEqual(reponse.status_code, 302)
                self.assertEqual(reponse["Location"], reverse("vitrine:accueil"))
        client = Client()
        client.force_login(self.compte)
        self.assertEqual(self.changer(client, "ar", "https://evil.example/")["Location"], reverse("comptes:redirection_tableau_de_bord"))
        self.assertEqual(self.changer(client, "ar", "")["Location"], reverse("comptes:redirection_tableau_de_bord"))

    def test_un_retour_du_site_est_suivi_avec_sa_recherche(self):
        suivant = reverse("scolarite:liste_eleves") + "?classe=3"
        self.assertEqual(self.changer(Client(), "ar", suivant)["Location"], suivant)

    def test_la_protection_csrf_est_active(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(self.adresse, {"langue": "ar"}).status_code, 403)

    def test_le_bouton_marche_pendant_un_changement_de_mot_de_passe_obligatoire(self):
        Utilisateur.objects.filter(pk=self.compte.pk).update(
            doit_changer_mot_de_passe=True, mot_de_passe_provisoire_expire_le=timezone.now() + timezone.timedelta(hours=5),
        )
        client = Client()
        client.force_login(self.compte)
        self.assertEqual(client.get(TABLEAU_DE_BORD).status_code, 302)  # le changement de mot de passe barre la route
        reponse = self.changer(client, "ar", reverse("comptes:changer_mot_de_passe"))
        self.assertEqual(reponse["Location"], reverse("comptes:changer_mot_de_passe"))
        self.compte.refresh_from_db()
        self.assertEqual(self.compte.langue, "ar")
        self.assertRegex(client.get(reverse("comptes:changer_mot_de_passe")).content.decode(), LANGUE_AR)

    @override_settings(TESTING=False)
    def test_le_bouton_marche_pendant_une_activation_2fa_obligatoire(self):
        client = Client()
        client.force_login(self.compte)
        self.assertEqual(client.get(TABLEAU_DE_BORD)["Location"], reverse("comptes:activer_2fa"))  # la 2FA barre la route
        reponse = self.changer(client, "ar", reverse("comptes:activer_2fa"))
        self.assertEqual(reponse["Location"], reverse("comptes:activer_2fa"))
        self.compte.refresh_from_db()
        self.assertEqual(self.compte.langue, "ar")

    def test_le_proprietaire_de_la_plateforme_change_aussi_de_langue(self):
        proprietaire = creer_compte(Role.DEVELOPPEUR, "proprietaire@test.test", None, is_superuser=True, is_staff=True)
        client = Client()
        client.force_login(proprietaire)
        reponse = self.changer(client, "ar", reverse("espace_plateforme:liste_etablissements"))
        self.assertEqual(reponse["Location"], reverse("espace_plateforme:liste_etablissements"))
        self.assertRegex(client.get(reverse("espace_plateforme:liste_etablissements")).content.decode(), LANGUE_AR)


class PagesEnArabeTests(EducationBase):
    def setUp(self):
        self.compte = creer_compte(Role.FONDATEUR, "arabe@test.test", self.ecole)
        self.client = Client()
        self.client.force_login(self.compte)

    def en(self, langue, adresse=TABLEAU_DE_BORD, **parametres):
        self.client.cookies[NOM_COOKIE_LANGUE] = langue
        return self.client.get(adresse, parametres)

    def test_en_arabe_la_page_est_de_droite_a_gauche_avec_ses_feuilles_de_style(self):
        page = self.en("ar").content.decode()
        self.assertRegex(page, LANGUE_AR)
        self.assertIn("bootstrap.rtl.min.css", page)
        self.assertIn("toumai-rtl.css", page)
        self.assertNotIn("css/bootstrap.min.css", page)

    def test_en_francais_rien_ne_change(self):
        page = self.en("fr").content.decode()
        self.assertRegex(page, LANGUE_FR)
        self.assertIn("css/bootstrap.min.css", page)
        self.assertNotIn("toumai-rtl.css", page)
        self.assertIn("Tableau de bord", page)
        self.assertNotIn("لوحة التحكم", page)

    def test_le_menu_et_les_titres_sont_en_arabe(self):
        page = self.en("ar").content.decode()
        for attendu in ("لوحة التحكم", "الإشعارات", "التلاميذ والأقسام", "المدفوعات", "تسجيل الخروج", "الوضع الداكن"):
            with self.subTest(attendu=attendu):
                self.assertIn(attendu, page)
        for interdit in (">Tableau de bord<", ">Notifications<", ">Déconnexion<", ">Paiements<"):
            self.assertNotIn(interdit, page)

    def test_les_dates_sont_ecrites_en_arabe_par_django(self):
        page = self.en("ar").content.decode()
        self.assertTrue(any(mois in page for mois in MOIS_ARABES))

    def test_les_noms_et_les_chiffres_des_donnees_sont_ecrits_en_arabe(self):
        """Une école arabe ne veut ni lettre latine ni chiffre occidental : le nom saisi en arabe remplace le nom latin, les chiffres sont arabes."""
        Utilisateur.objects.filter(pk=self.e5.pk).update(prenom_ar="سالم", nom_ar="كيتا")
        from comptes.arabisation import chiffres_arabes, invalider
        invalider(self.ecole.pk)
        page = self.en("ar", reverse("scolarite:liste_eleves")).content.decode()
        self.assertIn("سالم كيتا", page)
        self.assertNotIn(self.e5.nom_complet, page)
        self.assertIn(chiffres_arabes(self.e5.matricule), page)
        self.assertNotIn(f">{self.e5.matricule}<", page)

    def test_en_francais_les_noms_et_les_chiffres_ne_changent_pas(self):
        page = self.en("fr", reverse("scolarite:liste_eleves")).content.decode()
        self.assertIn(self.e5.nom_complet, page)
        self.assertIn(self.e5.matricule, page)

    def test_les_pdf_et_le_json_ne_sont_pas_touches(self):
        reponse = self.en("ar", reverse("pedagogie:exporter_bulletin_pdf", args=[self.e5.matricule]))
        self.assertEqual(reponse["Content-Type"], "application/pdf")
        self.assertTrue(reponse.content.startswith(b"%PDF"))
        reponse = self.en("ar", reverse("assistant:rechercher_eleve_json"), q=self.e5.nom)
        self.assertIn("application/json", reponse["Content-Type"])
        json.loads(reponse.content)

    def test_la_longueur_annoncee_suit_le_texte_traduit(self):
        reponse = self.en("ar")
        if reponse.has_header("Content-Length"):
            self.assertEqual(int(reponse["Content-Length"]), len(reponse.content))

    def test_les_textes_du_javascript_suivent_la_langue(self):
        def textes(langue):
            page = self.en(langue).content.decode()
            return json.loads(re.search(r'<script id="textes-js" type="application/json">(.*?)</script>', page, re.S).group(1))

        self.assertEqual(textes("fr"), {})
        arabe = textes("ar")
        self.assertEqual(arabe["Mode sombre"], "الوضع الداكن")
        self.assertEqual(arabe["Copié"], "تم النسخ")

    def test_la_langue_par_defaut_de_l_ecole_se_regle_dans_les_parametres(self):
        from espace_developpeur.forms import ParametresEtablissementForm

        self.assertIn("langue_par_defaut", ParametresEtablissementForm(instance=self.ecole).fields)
        donnees = {
            "nom": self.ecole.nom, "devise": "", "code_devise": "FCFA", "pas_montant": 5000, "coefficient_conduite": 1,
            "taux_inps_salarie": "3.6", "taux_inps_employeur": "20", "taux_amo_salarie": "3.06", "taux_amo_employeur": "3.5",
        }
        formulaire = ParametresEtablissementForm({**donnees, "langue_par_defaut": "ar"}, instance=self.ecole)
        self.assertTrue(formulaire.is_valid(), formulaire.errors)
        self.assertEqual(formulaire.save().langue_par_defaut, "ar")
        for envoi in ({}, {"langue_par_defaut": ""}):  # absente ou vide : la valeur actuelle est gardée
            formulaire = ParametresEtablissementForm({**donnees, **envoi}, instance=self.ecole)
            self.assertTrue(formulaire.is_valid(), formulaire.errors)
            self.assertEqual(formulaire.save().langue_par_defaut, "ar")
        self.assertFalse(ParametresEtablissementForm({**donnees, "langue_par_defaut": "de"}, instance=self.ecole).is_valid())


MOTS_FRANCAIS = re.compile(
    r"\b(le|la|les|des|du|de|et|ou|pour|vous|votre|vos|un|une|ce|cette|est|sont|aucun|aucune|pas|dans|sur|avec|par|ne|nous)\b", re.I,
)


def phrases_francaises(restes):
    """Parmi les textes sans traduction, ceux qui ressemblent à une phrase d'interface (pas un nom ni une donnée)."""
    return [texte for texte in restes if len(texte.split()) >= 3 and MOTS_FRANCAIS.search(texte)]


class CouvertureDuCatalogueTests(EducationBase):
    """Les écrans essentiels n'ont plus de phrase française sans traduction (les noms et données ne comptent pas)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.fondateur = creer_compte(Role.FONDATEUR, "couverture@test.test", cls.ecole)
        cls.catalogue = catalogue_pour("ar")

    def restes(self, compte, adresses):
        client = Client()
        client.force_login(compte)
        client.cookies[NOM_COOKIE_LANGUE] = "fr"
        resultat = {}
        for adresse in adresses:
            reponse = client.get(adresse, follow=True)
            self.assertEqual(reponse.status_code, 200, adresse)
            for texte in phrases_francaises(chaines_non_traduites(reponse.content.decode(), self.catalogue)):
                resultat.setdefault(texte, adresse)
        return resultat

    def test_pages_de_la_direction(self):
        affectation = Affectation.objects.get(enseignant=self.t2, classe=self.c9a)
        adresses = [
            TABLEAU_DE_BORD, reverse("comptes:liste_notifications"), reverse("comptes:changer_mot_de_passe"), reverse("comptes:changer_email"),
            reverse("scolarite:liste_eleves"), reverse("scolarite:inscrire_eleve"), reverse("scolarite:liste_classes"),
            reverse("scolarite:creer_classe"), reverse("scolarite:liste_matieres"), reverse("scolarite:affecter_enseignant"),
            reverse("scolarite:dossier_eleve", args=[self.e5.matricule]), reverse("scolarite:corriger_dossier_eleve", args=[self.e5.matricule]),
            reverse("scolarite:recherche_globale") + "?q=Test", reverse("pedagogie:bulletin_eleve", args=[self.e5.matricule]),
            reverse("pedagogie:historique_absences", args=[self.e5.matricule]), reverse("pedagogie:saisir_note", args=[affectation.pk]),
            reverse("pedagogie:saisir_absence", args=[self.c9a.pk]), reverse("pedagogie:suivi_des_cours"),
            reverse("finances:suivi_paiements"), reverse("finances:liste_paiements"), reverse("finances:enregistrer_paiement"),
            reverse("finances:registre_caisse"), reverse("finances:liste_salaires"), reverse("comptes:comptes_en_attente"),
            reverse("communication:liste_annonces"), reverse("communication:messages_a_envoyer"), reverse("bibliotheque:liste_documents"),
            reverse("assistant:poser_question"), reverse("statistiques:vue_ensemble"),
            reverse("statistiques:statistiques_classe", args=[self.c9a.pk]), reverse("statistiques:statistiques_finances"),
        ]
        self.assertEqual(self.restes(self.fondateur, adresses), {})

    def test_pages_de_l_enseignant(self):
        affectation = Affectation.objects.get(enseignant=self.t2, classe=self.c9a)
        adresses = [
            TABLEAU_DE_BORD, reverse("pedagogie:mes_classes"), reverse("pedagogie:saisir_note", args=[affectation.pk]),
            reverse("pedagogie:saisir_absence", args=[self.c9a.pk]),
        ]
        self.assertEqual(self.restes(self.t2, adresses), {})

    def test_pages_du_parent_et_de_l_eleve(self):
        parent = creer_compte(Role.PARENT, "parent-couverture@test.test", self.ecole)
        self.e5.parents_lies.add(parent)
        self.assertEqual(self.restes(parent, [reverse("comptes:portail_parent"), reverse("comptes:liste_notifications")]), {})
        self.assertEqual(self.restes(self.e5, [TABLEAU_DE_BORD, reverse("pedagogie:bulletin_eleve", args=[self.e5.matricule])]), {})

    def test_pages_publiques(self):
        client = Client()
        client.cookies[NOM_COOKIE_LANGUE] = "fr"
        for adresse in (reverse("comptes:connexion"), reverse("comptes:mot_de_passe_oublie"), reverse("comptes:inscription"), reverse("vitrine:accueil")):
            with self.subTest(adresse=adresse):
                reponse = client.get(adresse, follow=True)
                self.assertEqual(phrases_francaises(chaines_non_traduites(reponse.content.decode(), self.catalogue)), [])


class MenuDeChaqueRoleTests(EducationBase):
    """Le menu latéral est entièrement traduit pour chacun des rôles (seul le nom du compte, une donnée, reste tel quel)."""

    MARQUE = "Nexora"

    def restes_du_menu(self, menu, compte):
        """Textes du menu sans traduction, hors données : nom du compte, nom de l'école (et sa première lettre) et nom de la marque."""
        donnees = (compte.nom, compte.prenom, self.ecole.nom, self.ecole.nom[:1], self.MARQUE)
        return [t for t in chaines_non_traduites(menu, catalogue_pour("ar")) if t not in donnees and not any(d in t for d in donnees[:3])]

    def test_menu_traduit_pour_chaque_role(self):
        for role in Role:
            if role == Role.DEVELOPPEUR:
                continue  # sans école, c'est le propriétaire ; son espace est vérifié plus bas
            with self.subTest(role=role.value):
                compte = creer_compte(role, f"menu-{role.value}@test.test", self.ecole)
                client = Client()
                client.force_login(compte)
                client.cookies[NOM_COOKIE_LANGUE] = "fr"
                page = client.get(TABLEAU_DE_BORD, follow=True).content.decode()
                menu = re.search(r"<aside.*?</aside>", page, re.S)
                self.assertIsNotNone(menu, role.value)
                self.assertEqual(self.restes_du_menu(menu.group(0), compte), [], role.value)

    def test_menu_traduit_pour_le_developpeur_et_le_proprietaire(self):
        comptes = [
            creer_compte(Role.DEVELOPPEUR, "menu-dev@test.test", self.ecole),
            creer_compte(Role.DEVELOPPEUR, "menu-proprio@test.test", None, is_superuser=True, is_staff=True),
        ]
        for compte in comptes:
            with self.subTest(compte=compte.email):
                client = Client()
                client.force_login(compte)
                client.cookies[NOM_COOKIE_LANGUE] = "fr"
                page = client.get(TABLEAU_DE_BORD, follow=True).content.decode()
                menu = re.search(r"<aside.*?</aside>", page, re.S)
                self.assertIsNotNone(menu)
                self.assertEqual(self.restes_du_menu(menu.group(0), compte), [])
