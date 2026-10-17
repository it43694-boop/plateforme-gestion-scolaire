"""
Écran « Noms en arabe » : l'école relit et corrige l'écriture arabe des noms de ses élèves, parents, personnel, classes et d'elle-même.
"""
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from comptes.langues import NOM_COOKIE_LANGUE
from comptes.models import Utilisateur
from comptes.roles import Role
from scolarite.models import Classe, Inscription
from statistiques.test_education import EducationBase, creer_compte


class NomsEnArabeTests(EducationBase):
    def setUp(self):
        cache.clear()
        self.fondateur = creer_compte(Role.FONDATEUR, "fondateur@noms.test", self.ecole)
        self.secretaire = creer_compte(Role.SECRETAIRE, "secretaire@noms.test", self.ecole)
        self.enseignant = creer_compte(Role.ENSEIGNANT, "enseignant@noms.test", self.ecole)
        self.parent = creer_compte(Role.PARENT, "parent@noms.test", self.ecole)
        self.eleve = creer_compte(Role.ELEVE, "eleve@noms.test", self.ecole)
        self.eleve_b = creer_compte(Role.ELEVE, "eleve-b@noms.test", self.ecole_b)
        self.url = reverse("comptes:noms_en_arabe")

    def client_de(self, compte, langue="fr"):
        client = Client()
        client.force_login(compte)
        client.cookies[NOM_COOKIE_LANGUE] = langue
        return client

    def test_la_direction_et_le_secretariat_ouvrent_la_page(self):
        for compte in (self.fondateur, self.secretaire):
            with self.subTest(role=compte.role):
                self.assertEqual(self.client_de(compte).get(self.url).status_code, 200)

    def test_un_enseignant_un_parent_ou_un_eleve_n_y_ont_pas_acces(self):
        for compte in (self.enseignant, self.parent, self.eleve):
            with self.subTest(role=compte.role):
                self.assertEqual(self.client_de(compte).get(self.url).status_code, 403)

    def test_le_secretariat_ne_modifie_ni_le_personnel_ni_les_classes_ni_l_ecole(self):
        client = self.client_de(self.secretaire)
        for groupe in ("personnel", "classes", "ecole"):
            with self.subTest(groupe=groupe):
                self.assertEqual(client.get(self.url, {"groupe": groupe}).status_code, 403)

    def test_la_proposition_automatique_est_dans_la_case_et_marquee(self):
        Utilisateur.objects.filter(pk=self.eleve.pk).update(prenom="Mamadou", nom="Keïta")
        page = self.client_de(self.fondateur).get(self.url, {"groupe": "eleves"}).content.decode()
        self.assertIn(f'name="prenom_ar_{self.eleve.pk}"', page)
        self.assertIn("محمدو", page)
        self.assertIn("Proposition automatique", page)

    def test_on_enregistre_l_ecriture_arabe_d_un_eleve(self):
        client = self.client_de(self.fondateur)
        reponse = client.post(self.url, {
            "groupe": "eleves", f"prenom_ar_{self.eleve.pk}": "سالم", f"nom_ar_{self.eleve.pk}": "كيتا",
        })
        self.assertEqual(reponse.status_code, 302)
        self.eleve.refresh_from_db()
        self.assertEqual((self.eleve.prenom_ar, self.eleve.nom_ar), ("سالم", "كيتا"))
        Inscription.objects.create(eleve=self.eleve, classe=self.c6a)
        page = self.client_de(self.fondateur, "ar").get(reverse("scolarite:liste_eleves")).content.decode()
        self.assertIn("سالم كيتا", page)

    def test_une_lettre_latine_est_refusee_et_rien_n_est_enregistre(self):
        client = self.client_de(self.fondateur)
        reponse = client.post(self.url, {
            "groupe": "eleves", f"prenom_ar_{self.eleve.pk}": "Salem", f"nom_ar_{self.eleve.pk}": "كيتا",
        })
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "lettres arabes")
        self.eleve.refresh_from_db()
        self.assertEqual((self.eleve.prenom_ar, self.eleve.nom_ar), ("", ""))

    def test_on_ne_peut_pas_modifier_un_eleve_d_une_autre_ecole(self):
        client = self.client_de(self.fondateur)
        client.post(self.url, {"groupe": "eleves", f"prenom_ar_{self.eleve_b.pk}": "هاكر"})
        self.eleve_b.refresh_from_db()
        self.assertEqual(self.eleve_b.prenom_ar, "")

    def test_les_noms_d_un_autre_groupe_ne_sont_pas_modifiables_par_le_secretariat(self):
        client = self.client_de(self.secretaire)
        client.post(self.url, {"groupe": "eleves", f"prenom_ar_{self.enseignant.pk}": "أستاذ"})
        self.enseignant.refresh_from_db()
        self.assertEqual(self.enseignant.prenom_ar, "")

    def test_une_classe_est_renommee_pour_toutes_les_annees(self):
        precedente = Classe.objects.create(
            nom="6A", cycle=self.c6a.cycle, niveau=self.c6a.niveau, annee_scolaire=self.precedente,
        )
        client = self.client_de(self.fondateur)
        client.post(self.url, {"groupe": "classes", f"nom_ar_{precedente.pk}": "السادسة أ"})  # une seule ligne par nom : la plus récente
        self.c6a.refresh_from_db()
        precedente.refresh_from_db()
        self.assertEqual(self.c6a.nom_ar, "السادسة أ")
        self.assertEqual(precedente.nom_ar, "السادسة أ")
        autre_ecole = Classe.objects.get(pk=self.classe_b.pk)
        self.assertEqual(autre_ecole.nom_ar, "")

    def test_le_nom_de_l_ecole_et_sa_devise(self):
        client = self.client_de(self.fondateur)
        client.post(self.url, {"groupe": "ecole", f"nom_ar_{self.ecole.pk}": "مدرسة الإحصاء"})
        self.ecole.refresh_from_db()
        self.assertEqual(self.ecole.nom_ar, "مدرسة الإحصاء")
        self.ecole_b.refresh_from_db()
        self.assertEqual(self.ecole_b.nom_ar, "")

    def test_la_recherche_et_le_filtre_des_ecritures_a_revoir(self):
        Utilisateur.objects.filter(pk=self.eleve.pk).update(prenom="Zanga", nom="Unique", prenom_ar="زانغا", nom_ar="أونيك")
        client = self.client_de(self.fondateur)
        page = client.get(self.url, {"groupe": "eleves", "q": "Unique"}).content.decode()
        self.assertIn(f"prenom_ar_{self.eleve.pk}", page)
        page = client.get(self.url, {"groupe": "eleves", "a_revoir": "1"}).content.decode()
        self.assertNotIn(f"prenom_ar_{self.eleve.pk}", page)  # déjà enregistré : plus à revoir

    def test_le_nom_d_origine_reste_en_lettres_latines_meme_en_arabe(self):
        Utilisateur.objects.filter(pk=self.eleve.pk).update(prenom="Zanga", nom="Unique")
        page = self.client_de(self.fondateur, "ar").get(self.url, {"groupe": "eleves"}).content.decode()
        self.assertIn("Zanga Unique", page)  # colonne de référence protégée (translate="no")

    def test_les_chiffres_arabes_tapes_dans_une_recherche_sont_compris(self):
        Utilisateur.objects.filter(pk=self.eleve.pk).update(prenom="Zanga", nom="Unique7")
        page = self.client_de(self.fondateur).get(self.url, {"groupe": "eleves", "q": "Unique٧"}).content.decode()
        self.assertIn(f"prenom_ar_{self.eleve.pk}", page)
