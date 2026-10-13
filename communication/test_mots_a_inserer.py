"""
Page « Messages aux familles » : les mots remplacés pour chaque famille s'ajoutent avec des boutons clairs (« Nom de l'élève »,
« Classe »...), plus avec une liste de codes entre accolades affichée à l'utilisateur.
"""
from django.urls import reverse

from communication.test_diffusion import DiffusionBase, URL

MOTS = {
    "{eleve}": "Nom de l'élève", "{prenom}": "Prénom de l'élève", "{classe}": "Classe", "{ecole}": "Nom de l'école",
    "{date}": "Date", "{solde}": "Montant dû",
}


class MotsAInsererTests(DiffusionBase):
    def page(self, **parametres):
        self.client.force_login(self.fondateur)
        return self.client.get(reverse(URL), parametres)

    def test_plus_de_liste_de_codes_techniques(self):
        page = self.page()
        self.assertNotContains(page, "Mots remplacés pour chaque famille")
        for mot in MOTS:
            self.assertNotContains(page, f"<code>{mot}</code>")

    def test_un_bouton_clair_par_information(self):
        page = self.page()
        for mot, libelle in MOTS.items():
            self.assertContains(page, f'data-inserer-mot="{mot}"')
            self.assertContains(page, f">{libelle}</button>")

    def test_l_explication_est_en_francais_simple(self):
        page = self.page()
        self.assertContains(page, "Ajouter dans le message")
        self.assertContains(page, "remplace pour chaque famille")
        self.assertContains(page, "devient")
        self.assertContains(page, "votre enfant")
        self.assertContains(page, "c'est normal")  # les accolades visibles dans le message ne sont pas une erreur

    def test_les_boutons_sont_caches_tant_que_le_script_n_est_pas_charge(self):
        contenu = self.page().content.decode()
        debut = contenu.index("data-mots-a-inserer")
        balise = contenu[contenu.rfind("<div", 0, debut):contenu.index(">", debut)]
        self.assertIn("hidden", balise)
        self.assertIn('data-cible-insertion="champ-texte"', balise)
        self.assertIn('data-selecteur-type="champ-type"', balise)

    def test_le_montant_du_n_est_propose_que_pour_la_relance(self):
        contenu = self.page().content.decode()
        bouton = contenu[contenu.index('data-inserer-mot="{solde}"'):]
        bouton = bouton[:bouton.index(">")]
        self.assertIn('data-types="paiement"', bouton)
        self.assertIn("hidden", bouton)

    def test_le_champ_message_et_le_type_ont_les_identifiants_attendus_par_le_script(self):
        page = self.page()
        self.assertContains(page, 'id="champ-texte"')
        self.assertContains(page, 'id="champ-type"')

    def test_les_codes_restent_les_memes_pour_le_serveur(self):
        """Les boutons insèrent exactement les mots que le serveur remplace (rien d'autre n'a changé)."""
        from communication.diffusion import appliquer_modele

        valeurs = {"eleve": "Awa KEITA", "prenom": "Awa", "classe": "6A", "ecole": "École X", "date": "03/11/2026", "solde": "5 000 FCFA"}
        resultat = appliquer_modele(" ".join(MOTS), valeurs)
        for valeur in valeurs.values():
            self.assertIn(valeur, resultat)
        self.assertNotIn("{", resultat)

    def test_les_roles_sans_droit_ne_voient_pas_la_page(self):
        self.client.force_login(self.t1)
        self.assertEqual(self.client.get(reverse(URL)).status_code, 403)
