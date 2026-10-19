"""Accueil quand les écoles sont nombreuses : école retenue un an, recherche, liste complète seulement tant qu'elle est courte, lien et code QR de l'école."""
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from comptes.langue import NOM_COOKIE_LANGUE
from comptes.models import Utilisateur
from comptes.roles import Role, StatutCompte
from etablissement.models import Etablissement
from vitrine import ecole_memorisee
from vitrine.views import RESULTATS_MAX, SEUIL_LISTE_COMPLETE


def creer_ecoles(nombre, prefixe="Ecole", **champs):
    return [Etablissement.objects.create(nom=f"{prefixe} {chr(65 + i // 26)}{chr(65 + i % 26)}", **champs) for i in range(nombre)]


def compte(role, email, ecole=None, **extra):
    utilisateur = Utilisateur(email=email, prenom="Test", nom="Utilisateur", role=role, etablissement=ecole, statut=StatutCompte.ACTIF, is_active=True, email_verifie=True, **extra)
    utilisateur.set_unusable_password()
    utilisateur.save()
    return utilisateur


class ListeOuRechercheTests(TestCase):
    def accueil(self, **parametres):
        reponse = self.client.get(reverse("vitrine:accueil"), parametres)
        self.assertEqual(reponse.status_code, 200)
        return reponse

    def test_peu_d_ecoles_la_liste_complete_reste_affichee_avec_la_recherche(self):
        ecoles = creer_ecoles(5)
        page = self.accueil()
        for ecole in ecoles:
            self.assertContains(page, ecole.nom)
        self.assertContains(page, "data-recherche-ecole-url")
        self.assertEqual(len(page.context["etablissements"]), 5)

    def test_au_seuil_la_liste_est_encore_affichee_et_au_dela_il_n_y_a_que_la_recherche(self):
        creer_ecoles(SEUIL_LISTE_COMPLETE)
        self.assertEqual(len(self.accueil().context["etablissements"]), SEUIL_LISTE_COMPLETE)
        Etablissement.objects.create(nom="Ecole de trop")
        page = self.accueil()
        self.assertIsNone(page.context["etablissements"])
        self.assertNotContains(page, "Ecole AB")  # plus de liste à parcourir
        self.assertNotContains(page, "Ecole de trop")
        self.assertContains(page, "Tapez le nom de votre établissement ou de sa ville.")
        self.assertContains(page, "data-recherche-ecole-url")

    def test_la_recherche_ignore_les_accents_la_casse_et_l_ordre_des_mots(self):
        creer_ecoles(SEUIL_LISTE_COMPLETE)
        etoiles = Etablissement.objects.create(nom="Groupe Scolaire Les Étoiles", commune="Ségou")
        page = self.accueil(q="segou ETOILES")
        self.assertEqual([e.pk for e in page.context["resultats"]], [etoiles.pk])
        self.assertContains(page, reverse("vitrine:choisir_etablissement", args=[etoiles.slug]))
        self.assertNotContains(page, "Ecole AB")
        self.assertContains(self.accueil(q="inconnu total"), "Aucun établissement trouvé.")

    def test_la_recherche_trouve_aussi_par_la_commune_la_region_ou_le_sigle(self):
        creer_ecoles(SEUIL_LISTE_COMPLETE)
        a = Etablissement.objects.create(nom="Lycée Askia", commune="Gao", region="Gao")
        b = Etablissement.objects.create(nom="Collège du Fleuve", commune="Mopti", region="Mopti", sigle="CDF")
        self.assertEqual([e.pk for e in self.accueil(q="gao").context["resultats"]], [a.pk])
        self.assertEqual([e.pk for e in self.accueil(q="cdf").context["resultats"]], [b.pk])

    def test_la_recherche_ne_montre_que_dix_ecoles(self):
        creer_ecoles(15, prefixe="Alpha")
        self.assertEqual(len(self.accueil(q="alpha").context["resultats"]), RESULTATS_MAX)

    def test_une_ecole_cachee_ou_suspendue_n_est_jamais_trouvee(self):
        creer_ecoles(3)
        Etablissement.objects.create(nom="Secrete Cachee", visible_dans_annuaire=False)
        Etablissement.objects.create(nom="Secrete Suspendue", actif=False)
        visible = Etablissement.objects.create(nom="Secrete Visible")
        self.assertEqual([e.pk for e in self.accueil(q="secrete").context["resultats"]], [visible.pk])
        reponse = self.client.get(reverse("vitrine:rechercher_etablissement"), {"q": "secrete"})
        self.assertEqual([r["nom"] for r in reponse.json()["resultats"]], ["Secrete Visible"])


class RechercheEnDirectTests(TestCase):
    def setUp(self):
        cache.clear()  # la limite par adresse IP se compte dans le cache : chaque test repart de zéro
        self.addCleanup(cache.clear)
        self.adresse = reverse("vitrine:rechercher_etablissement")

    def test_il_faut_au_moins_deux_lettres(self):
        creer_ecoles(3)
        self.assertEqual(self.client.get(self.adresse, {"q": "e"}).json()["resultats"], [])
        self.assertEqual(self.client.get(self.adresse).json()["resultats"], [])
        self.assertEqual(len(self.client.get(self.adresse, {"q": "ec"}).json()["resultats"]), 3)

    def test_chaque_resultat_donne_le_nom_le_lieu_et_le_lien_de_connexion(self):
        ecole = Etablissement.objects.create(nom="Lycée Askia", commune="Gao", region="Gao")
        resultat = self.client.get(self.adresse, {"q": "askia"}).json()["resultats"][0]
        self.assertEqual(resultat["nom"], "Lycée Askia")
        self.assertEqual(resultat["lieu"], "Gao, Gao")
        self.assertEqual(resultat["adresse"], reverse("vitrine:choisir_etablissement", args=[ecole.slug]))
        self.assertEqual(resultat["initiale"], ecole.initiale)

    def test_au_plus_dix_resultats_et_aucune_donnee_privee(self):
        creer_ecoles(15, prefixe="Alpha", region="Koulikoro")
        donnees = self.client.get(self.adresse, {"q": "alpha"}).json()
        self.assertEqual(len(donnees["resultats"]), RESULTATS_MAX)
        self.assertEqual(set(donnees["resultats"][0]), {"nom", "lieu", "logo", "initiale", "adresse"})

    def test_la_limite_par_adresse_ip_vide_les_resultats_au_dela_de_60_demandes_par_minute(self):
        creer_ecoles(3)
        for _ in range(60):
            self.assertEqual(len(self.client.get(self.adresse, {"q": "ecole"}).json()["resultats"]), 3)
        self.assertEqual(self.client.get(self.adresse, {"q": "ecole"}).json()["resultats"], [])

    def test_le_message_d_absence_de_resultat_suit_la_langue(self):
        self.assertEqual(self.client.get(self.adresse, {"q": "zz"}).json()["vide"], "Aucun établissement trouvé.")
        self.client.cookies[NOM_COOKIE_LANGUE] = "ar"
        self.assertEqual(self.client.get(self.adresse, {"q": "zz"}).json()["vide"], "لم يتم العثور على أي مؤسسة.")


class EcoleRetenueTests(TestCase):
    def setUp(self):
        self.ecoles = creer_ecoles(SEUIL_LISTE_COMPLETE + 5)
        self.ecole = self.ecoles[3]

    def test_choisir_une_ecole_la_retient_un_an(self):
        reponse = self.client.get(reverse("vitrine:choisir_etablissement", args=[self.ecole.slug]))
        self.assertRedirects(reponse, reverse("comptes:connexion"), fetch_redirect_response=False)
        cookie = reponse.cookies[ecole_memorisee.NOM_COOKIE]
        self.assertEqual(cookie.value, self.ecole.slug)
        self.assertEqual(int(cookie["max-age"]), 365 * 24 * 3600)
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")

    def test_au_retour_l_accueil_propose_de_continuer_vers_cette_ecole(self):
        self.client.cookies[ecole_memorisee.NOM_COOKIE] = self.ecole.slug
        page = self.client.get(reverse("vitrine:accueil"))
        self.assertContains(page, f"Continuer vers {self.ecole.nom}")
        self.assertContains(page, reverse("vitrine:choisir_etablissement", args=[self.ecole.slug]))
        self.assertContains(page, "Ce n'est pas mon école")
        self.assertNotContains(page, "data-recherche-ecole-url")  # pas de recherche à refaire

    def test_une_recherche_remplace_la_proposition(self):
        self.client.cookies[ecole_memorisee.NOM_COOKIE] = self.ecole.slug
        page = self.client.get(reverse("vitrine:accueil"), {"q": "ecole"})
        self.assertNotContains(page, "Continuer vers")
        self.assertContains(page, "data-recherche-ecole-url")

    def test_une_ecole_inconnue_ou_suspendue_est_ignoree(self):
        for valeur in ("n-existe-pas", "x" * 500):
            self.client.cookies[ecole_memorisee.NOM_COOKIE] = valeur
            self.assertNotContains(self.client.get(reverse("vitrine:accueil")), "Continuer vers")
        Etablissement.objects.filter(pk=self.ecole.pk).update(actif=False)
        self.client.cookies[ecole_memorisee.NOM_COOKIE] = self.ecole.slug
        self.assertNotContains(self.client.get(reverse("vitrine:accueil")), "Continuer vers")

    def test_une_ecole_hors_annuaire_est_retenue_quand_meme(self):
        Etablissement.objects.filter(pk=self.ecole.pk).update(visible_dans_annuaire=False)
        self.client.cookies[ecole_memorisee.NOM_COOKIE] = self.ecole.slug
        self.assertContains(self.client.get(reverse("vitrine:accueil")), f"Continuer vers {self.ecole.nom}")

    def test_ce_n_est_pas_mon_ecole_oublie_le_choix(self):
        self.client.get(reverse("vitrine:choisir_etablissement", args=[self.ecole.slug]))
        reponse = self.client.get(reverse("vitrine:changer_ecole"))
        self.assertRedirects(reponse, reverse("vitrine:accueil") + "#choisir-etablissement", fetch_redirect_response=False)
        self.assertEqual(reponse.cookies[ecole_memorisee.NOM_COOKIE]["max-age"], 0)
        self.assertNotIn("etablissement_id", self.client.session)

    def test_le_cookie_ne_donne_aucun_acces(self):
        self.client.cookies[ecole_memorisee.NOM_COOKIE] = self.ecole.slug
        self.assertEqual(self.client.get(reverse("comptes:redirection_tableau_de_bord")).status_code, 302)  # toujours la connexion

    def test_la_connexion_retient_l_ecole_une_seule_fois(self):
        utilisateur = compte(Role.SECRETAIRE, "secretaire-retenue@example.com", self.ecole)
        self.client.force_login(utilisateur)
        premiere = self.client.get(reverse("comptes:redirection_tableau_de_bord"))
        self.assertEqual(premiere.cookies[ecole_memorisee.NOM_COOKIE].value, self.ecole.slug)
        seconde = self.client.get(reverse("comptes:redirection_tableau_de_bord"))
        self.assertNotIn(ecole_memorisee.NOM_COOKIE, seconde.cookies)  # déjà retenue : rien à réécrire

    def test_le_proprietaire_et_une_ecole_suspendue_ne_retiennent_rien(self):
        proprietaire = compte(Role.DEVELOPPEUR, "proprietaire-retenu@example.com", None, is_superuser=True)
        self.client.force_login(proprietaire)
        self.assertNotIn(ecole_memorisee.NOM_COOKIE, self.client.get(reverse("espace_plateforme:liste_etablissements")).cookies)
        Etablissement.objects.filter(pk=self.ecole.pk).update(actif=False)
        utilisateur = compte(Role.SECRETAIRE, "secretaire-suspendue@example.com", self.ecole)
        self.client.force_login(utilisateur)
        self.assertNotIn(ecole_memorisee.NOM_COOKIE, self.client.get(reverse("comptes:redirection_tableau_de_bord")).cookies)

    def test_la_proposition_et_la_recherche_sont_en_arabe_pur(self):
        self.client.cookies[NOM_COOKIE_LANGUE] = "ar"
        page = self.client.get(reverse("vitrine:accueil")).content.decode()
        for francais in ("Tapez le nom", "Nom de votre établissement", "Rechercher votre établissement"):
            self.assertNotIn(francais, page)
        self.assertIn("اكتب اسم مؤسستك أو اسم مدينتها.", page)
        self.client.cookies[ecole_memorisee.NOM_COOKIE] = self.ecole.slug
        page = self.client.get(reverse("vitrine:accueil")).content.decode()
        for francais in ("Continuer vers", "mon école", "Votre établissement :"):
            self.assertNotIn(francais, page)
        self.assertIn("المتابعة إلى", page)


class LienEtCodeQrTests(TestCase):
    def setUp(self):
        self.ecole, self.autre = creer_ecoles(2)
        self.developpeur = compte(Role.DEVELOPPEUR, "dev-lien@example.com", self.ecole)
        self.client.force_login(self.developpeur)
        self.lien = f"http://testserver{reverse('vitrine:choisir_etablissement', args=[self.ecole.slug])}"

    def test_la_page_donne_le_lien_de_connexion_et_le_code_qr(self):
        page = self.client.get(reverse("espace_developpeur:parametres_etablissement"))
        self.assertContains(page, "Lien de connexion de l")
        self.assertContains(page, f'value="{self.lien}"')
        self.assertContains(page, reverse("espace_developpeur:qr_connexion"))
        self.assertContains(page, f"qr_connexion_{self.ecole.slug}.png")

    def test_le_code_qr_est_une_image_png_propre_a_l_ecole(self):
        reponse = self.client.get(reverse("espace_developpeur:qr_connexion"))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse["Content-Type"], "image/png")
        self.assertTrue(reponse.content.startswith(b"\x89PNG"))
        self.assertIn(f"qr_connexion_{self.ecole.slug}.png", reponse["Content-Disposition"])
        autre = compte(Role.DEVELOPPEUR, "dev-autre@example.com", self.autre)
        self.client.force_login(autre)
        self.assertNotEqual(self.client.get(reverse("espace_developpeur:qr_connexion")).content, reponse.content)

    def test_le_lien_mene_a_la_connexion_de_l_ecole(self):
        self.client.logout()
        reponse = self.client.get(reverse("vitrine:choisir_etablissement", args=[self.ecole.slug]))
        self.assertRedirects(reponse, reverse("comptes:connexion"), fetch_redirect_response=False)
        self.assertEqual(self.client.session["etablissement_id"], self.ecole.pk)

    def test_seul_le_developpeur_de_l_ecole_voit_le_code_qr(self):
        adresse = reverse("espace_developpeur:qr_connexion")
        for role in (Role.FONDATEUR, Role.SECRETAIRE, Role.ENSEIGNANT, Role.PARENT):
            self.client.force_login(compte(role, f"{role.value}-lien@example.com", self.ecole))
            self.assertIn(self.client.get(adresse).status_code, (302, 403), role)
        self.client.logout()
        self.assertEqual(self.client.get(adresse).status_code, 302)

    def test_la_page_est_en_arabe_pur(self):
        from comptes.arabisation import invalider
        from comptes.outils_test_arabe import client_en, restes_hors_textes_saisis

        cache.clear()
        invalider(self.ecole.pk)
        page = client_en(self.developpeur, "ar").get(reverse("espace_developpeur:parametres_etablissement"))
        self.assertEqual(page.status_code, 200)
        self.assertEqual(restes_hors_textes_saisis(page.content.decode(), {self.ecole.nom, self.lien, "Français"}), [])
