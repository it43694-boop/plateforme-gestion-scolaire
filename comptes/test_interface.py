"""
Finition de l'interface : une icône par lien du menu, pastille et cloche de notifications, sections repliables, zones
« contenu principal », étiquettes des filtres, tableaux en cartes sur téléphone, tailles de texte et contrastes.

Les comportements qui demandent un vrai navigateur (repli mémorisé, bouton œil, cartes) sont vérifiés à part dans un navigateur ;
ici on garde ce que le serveur produit et les règles de style qui ne doivent plus régresser.
"""
import os
import re

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from comptes.context_processors import ICONES_DES_LIENS
from comptes.models import Notification
from comptes.roles import Role
from comptes.templatetags.icones import _TRACES
from etablissement.models import Etablissement
from statistiques.test_education import EducationBase, creer_compte

RACINE = settings.BASE_DIR
CSS = os.path.join(RACINE, "static", "css", "toumai.css")
TABLEAU_DE_BORD = "/comptes/tableau-de-bord/"


class IconesDuMenuTests(EducationBase):
    def test_chaque_icone_du_menu_existe(self):
        for adresse, icone in ICONES_DES_LIENS.items():
            with self.subTest(adresse=adresse):
                self.assertIn(icone, _TRACES)

    def test_tous_les_liens_de_tous_les_roles_ont_leur_icone(self):
        """Un nouveau lien de menu sans icône (simple point) doit se voir : il faut l'ajouter à ICONES_DES_LIENS."""
        for role in Role:
            compte = creer_compte(role, f"{role.value}@menu.test", self.ecole)
            self.client.force_login(compte)
            reponse = self.client.get(TABLEAU_DE_BORD, follow=True)
            if reponse.status_code != 200 or "sections_navigation" not in reponse.context:
                continue
            for section in reponse.context["sections_navigation"]:
                for lien in section["liens"]:
                    with self.subTest(role=role.value, lien=lien["url"]):
                        self.assertIn(lien["icone"], _TRACES)
                        self.assertNotEqual(lien["icone"], "point", f"icône à choisir pour {lien['url']}")

    def test_le_proprietaire_de_la_plateforme_a_aussi_ses_icones(self):
        proprietaire = creer_compte(Role.DEVELOPPEUR, "proprietaire@menu.test", None, is_superuser=True, is_staff=True)
        self.client.force_login(proprietaire)
        reponse = self.client.get(reverse("espace_plateforme:liste_etablissements"))
        liens = [lien for section in reponse.context["sections_navigation"] for lien in section["liens"]]
        self.assertEqual({lien["url"] for lien in liens}, {
            "comptes:liste_notifications", "espace_plateforme:liste_etablissements", "espace_plateforme:effectifs", "espace_plateforme:abonnements",
        })
        self.assertTrue(all(lien["icone"] in _TRACES and lien["icone"] != "point" for lien in liens))

    def test_chaque_lien_affiche_son_icone_dans_la_page(self):
        self.client.force_login(creer_compte(Role.FONDATEUR, "fondateur@menu.test", self.ecole))
        page = self.client.get(TABLEAU_DE_BORD).content.decode()
        liens = re.findall(r'<a class="nav-lien[^"]*"[^>]*>(.*?)</a>', page, flags=re.S)
        self.assertGreaterEqual(len(liens), 10)
        for contenu in liens:
            self.assertIn("<svg", contenu)
            self.assertIn("nav-lien-texte", contenu)


class SectionsRepliablesTests(EducationBase):
    def test_les_sections_sont_des_blocs_repliables_ouverts_par_defaut(self):
        self.client.force_login(creer_compte(Role.FONDATEUR, "fondateur2@menu.test", self.ecole))
        page = self.client.get(TABLEAU_DE_BORD).content.decode()
        sections = re.findall(r'<details class="nav-section" data-nav-section="([^"]+)" open>', page)
        self.assertIn("eleves-classes", sections)
        self.assertIn("finances", sections)
        self.assertEqual(len(sections), len(set(sections)))  # un identifiant unique par section : c'est la clé de la mémoire
        self.assertEqual(page.count("<summary class=\"nav-section-titre\">"), len(sections))

    def test_le_bouton_du_menu_mobile_annonce_son_etat(self):
        self.client.force_login(creer_compte(Role.FONDATEUR, "fondateur3@menu.test", self.ecole))
        page = self.client.get(TABLEAU_DE_BORD).content.decode()
        self.assertIn('aria-controls="sidebar" aria-expanded="false"', page)


class NotificationsDuMenuTests(EducationBase):
    def setUp(self):
        self.compte = creer_compte(Role.FONDATEUR, "notif@menu.test", self.ecole)
        self.client.force_login(self.compte)

    def notifier(self, nombre, lues=0):
        for numero in range(nombre):
            Notification.objects.create(
                destinataire=self.compte, etablissement=self.ecole, titre=f"Titre {numero}", message="Message",
                lue_le=None,
            )
        deja_lues = list(Notification.objects.filter(destinataire=self.compte).order_by("id").values_list("id", flat=True)[:lues])
        Notification.objects.filter(id__in=deja_lues).update(lue_le=timezone.now())

    def test_sans_notification_ni_pastille_ni_chiffre(self):
        page = self.client.get(TABLEAU_DE_BORD).content.decode()
        self.assertNotIn("nav-pastille", page)
        self.assertIn('aria-label="Notifications"', page)  # la cloche, sans compteur
        liens = [lien for s in self.client.get(TABLEAU_DE_BORD).context["sections_navigation"] for lien in s["liens"]]
        notifications = next(lien for lien in liens if lien["url"] == "comptes:liste_notifications")
        self.assertEqual((notifications["label"], notifications["compteur"]), ("Notifications", 0))

    def test_la_pastille_compte_les_non_lues_dans_le_menu_et_sur_la_cloche(self):
        self.notifier(3, lues=1)
        page = self.client.get(TABLEAU_DE_BORD).content.decode()
        self.assertEqual(page.count('class="nav-pastille'), 2)  # le menu et la cloche
        self.assertIn('aria-label="2 non lues"', page)
        self.assertIn('aria-label="Notifications : 2 non lues"', page)
        self.assertNotIn("Notifications (2)", page)  # le chiffre n'est plus dans le libellé

    def test_une_seule_non_lue_au_singulier(self):
        self.notifier(1)
        page = self.client.get(TABLEAU_DE_BORD).content.decode()
        self.assertIn('aria-label="1 non lue"', page)
        self.assertIn('aria-label="Notifications : 1 non lue"', page)

    def test_au_dela_de_99_la_pastille_affiche_99_plus(self):
        self.notifier(101)
        page = self.client.get(TABLEAU_DE_BORD).content.decode()
        self.assertIn(">99+<", page)
        self.assertNotIn(">101<", page)

    def test_la_cloche_ne_montre_que_les_notifications_du_compte(self):
        autre = creer_compte(Role.COMPTABLE, "autre@menu.test", self.ecole)
        Notification.objects.create(destinataire=autre, etablissement=self.ecole, titre="Pour un autre", message="x")
        page = self.client.get(TABLEAU_DE_BORD).content.decode()
        self.assertNotIn("nav-pastille", page)


class ZonePrincipaleTests(TestCase):
    def test_les_pages_publiques_et_la_connexion_ont_une_zone_contenu_principal(self):
        ecole = Etablissement.objects.create(nom="École visiteur")
        for adresse in (reverse("vitrine:accueil"), reverse("comptes:connexion"), f"/e/{ecole.slug}/"):
            with self.subTest(adresse=adresse):
                reponse = self.client.get(adresse, follow=True)
                self.assertEqual(reponse.status_code, 200)
                self.assertEqual(reponse.content.decode().count("<main"), 1)

    def test_sans_aucune_ecole_la_page_d_attente_a_aussi_sa_zone_principale(self):
        reponse = self.client.get(reverse("vitrine:accueil"))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "<main")


class PagesDeListeTests(EducationBase):
    def setUp(self):
        self.client.force_login(creer_compte(Role.FONDATEUR, "listes@menu.test", self.ecole))

    def test_les_filtres_ont_un_nom_pour_les_lecteurs_d_ecran(self):
        for adresse in (reverse("scolarite:liste_eleves"), reverse("finances:suivi_paiements")):
            with self.subTest(adresse=adresse):
                page = self.client.get(adresse)
                self.assertContains(page, 'aria-label="Filtrer par classe"')
        self.assertContains(self.client.get(reverse("finances:suivi_paiements")), 'aria-label="Filtrer par statut"')

    def test_les_listes_se_transforment_en_cartes_sur_telephone(self):
        for adresse in (
            reverse("scolarite:liste_eleves"), reverse("scolarite:liste_classes"), reverse("finances:suivi_paiements"),
        ):
            with self.subTest(adresse=adresse):
                self.assertContains(self.client.get(adresse), '<table class="table table-cartes')

    def test_l_entete_des_classes_donne_le_nombre_de_classes(self):
        page = self.client.get(reverse("scolarite:liste_classes"))
        nombre = len(page.context["classes"])
        self.assertGreater(nombre, 0)
        self.assertContains(page, f"{nombre} classe")
        self.assertContains(page, " visible")


class AccessibiliteDesGabaritsTests(SimpleTestCase):
    def test_aucun_en_tete_de_colonne_vide(self):
        """Un <th></th> n'est annoncé par aucun lecteur d'écran : on y met « Actions » (visually-hidden)."""
        fautifs = []
        dossier = os.path.join(RACINE, "templates")
        for chemin, _, fichiers in os.walk(dossier):
            for fichier in fichiers:
                if not fichier.endswith(".html"):
                    continue
                complet = os.path.join(chemin, fichier)
                contenu = open(complet, encoding="utf-8").read()
                for entete in re.findall(r"<thead>.*?</thead>", contenu, flags=re.S):
                    if "<th></th>" in entete or re.search(r"<th[^>]*></th>", entete):
                        fautifs.append(os.path.relpath(complet, dossier))
        self.assertEqual(sorted(set(fautifs)), [])


def luminance(couleur):
    couleur = couleur.lstrip("#")
    composantes = [int(couleur[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lineaire = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in composantes]
    return 0.2126 * lineaire[0] + 0.7152 * lineaire[1] + 0.0722 * lineaire[2]


def contraste(a, b):
    clair, sombre = sorted((luminance(a), luminance(b)), reverse=True)
    return (clair + 0.05) / (sombre + 0.05)


class FeuilleDeStyleTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.css = open(CSS, encoding="utf-8").read()

    def valeurs(self, jeton):
        return re.findall(rf"{re.escape(jeton)}:\s*(#[0-9A-Fa-f]{{6}})", self.css)

    def test_aucun_texte_sous_12_pixels(self):
        """La base fait 15 px : 0,8 rem = 12 px. En dessous, une pastille ou un en-tête devient pénible à lire."""
        trop_petits = []
        for taille, unite in re.findall(r"font-size:\s*(\d*\.?\d+)(rem|px)", self.css):
            pixels = float(taille) * (15 if unite == "rem" else 1)
            if pixels < 11.99:
                trop_petits.append(f"{taille}{unite}")
        self.assertEqual(trop_petits, [])

    def test_les_gris_et_l_or_discrets_respectent_le_contraste_AA_en_mode_clair(self):
        gris, or_fonce = self.valeurs("--ink-300")[0], self.valeurs("--gold-600")[0]
        for nom, couleur in (("gris discret", gris), ("or foncé", or_fonce)):
            for fond in ("#FFFFFF", "#F1F2F4"):
                with self.subTest(couleur=nom, fond=fond):
                    self.assertGreaterEqual(contraste(couleur, fond), 4.5)

    def test_le_gris_discret_du_mode_sombre_respecte_aussi_le_contraste(self):
        for couleur in self.valeurs("--ink-300")[1:]:
            for fond in ("#16233A", "#0C1524"):
                with self.subTest(couleur=couleur, fond=fond):
                    self.assertGreaterEqual(contraste(couleur, fond), 4.5)
        self.assertGreaterEqual(len(self.valeurs("--ink-300")), 3)  # clair + les deux blocs sombres

    def test_les_liens_et_titres_du_menu_sont_lisibles_sur_le_fond_marine(self):
        for couleur, minimum in (("#C7CFE3", 7), ("#8B96B5", 4.5), ("#F3DFA9", 7)):
            with self.subTest(couleur=couleur):
                self.assertGreaterEqual(contraste(couleur, "#12203D"), minimum)
