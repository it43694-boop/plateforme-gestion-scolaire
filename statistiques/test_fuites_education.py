"""
Audit de fuites sur les données ajoutées par les statistiques de l'éducation : handicap, déplacement,
résultats d'examen, fiche annuelle, infrastructures, situation de l'école.

Chaque test dit QUI doit voir une donnée et vérifie dans les deux sens : ceux qui doivent la voir la voient
(sinon la fonction est cassée), tous les autres ne la voient pas.
"""
import datetime
import json
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse

from comptes.models import JournalAudit, Utilisateur
from comptes.roles import Role
from pedagogie.models import VerificationBulletin
from scolarite.models import Cycle, Inscription, TypeDocumentVerifiable, VerificationDocument
from statistiques.fiche import construire_fiche
from statistiques.test_education import EducationBase, creer_compte, lignes_attendues, lignes_du_classeur

PHRASES_SENSIBLES = ("Situation de handicap :", "Situation de déplacement :", "Résultats aux examens")

# Administration scolaire autorisée à voir les renseignements sensibles de e2 (6ème année, 1er cycle).
ROLES_AUTORISES_POUR_E2 = {
    Role.FONDATEUR, Role.ADMINISTRATEUR_GENERAL, Role.DEVELOPPEUR, Role.SUPER_ADMINISTRATEUR, Role.SECRETAIRE,
    Role.DIRECTEUR_1ER_CYCLE,  # le cycle de e2 ; pas les directeurs du 2ème cycle et du lycée
}


class FuitesBase(EducationBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.parent_e2 = creer_compte(Role.PARENT, "parent-e2@stat.test", cls.ecole, telephone="70999002")
        cls.e2.parents_lies.add(cls.parent_e2)
        # e2 cumule les deux renseignements sensibles (la base ne lui donnait que le handicap)
        Utilisateur.objects.filter(pk=cls.e2.pk).update(statut_deplacement="deplace_interne")

    def dossier(self, eleve):
        return reverse("scolarite:dossier_eleve", args=[eleve.matricule])

    def phrases_vues(self, compte, eleve):
        self.client.force_login(compte)
        reponse = self.client.get(self.dossier(eleve))
        if reponse.status_code != 200:
            return set(), reponse.status_code
        texte = reponse.content.decode()
        return {phrase for phrase in PHRASES_SENSIBLES if phrase in texte}, 200


class DossierSensibleParRoleTests(FuitesBase):
    def test_matrice_complete_des_roles(self):
        """Les 17 rôles de l'école, un par un : seule l'administration autorisée voit le handicap et les résultats."""
        comptes = {role: creer_compte(role, f"matrice-{role.value}@stat.test", self.ecole, **(
            {"telephone": "70999777"} if role == Role.PARENT else {}
        )) for role in Role}
        ecarts = []
        for role, compte in comptes.items():
            phrases, statut = self.phrases_vues(compte, self.e2)
            attendu = set(PHRASES_SENSIBLES) if role in ROLES_AUTORISES_POUR_E2 else set()
            if phrases != attendu:
                ecarts.append(f"{role.value} (HTTP {statut}) voit {sorted(phrases)}, attendu {sorted(attendu)}")
        self.assertEqual(ecarts, [], "\n".join(ecarts))

    def test_l_eleve_et_son_parent_voient_les_leurs_et_personne_d_autre(self):
        for compte, eleve, doit_voir in [
            (self.e2, self.e2, True),            # l'élève lui-même
            (self.parent_e2, self.e2, True),     # son parent
            (self.parent, self.e2, False),       # le parent d'un autre élève
            (self.e1, self.e2, False),           # un autre élève
            (self.e2, self.e1, False),           # l'élève regarde le dossier d'un camarade
        ]:
            with self.subTest(acteur=compte.email, eleve=eleve.email):
                phrases, _ = self.phrases_vues(compte, eleve)
                self.assertEqual(phrases, set(PHRASES_SENSIBLES) if doit_voir else set())

    def test_directeur_du_lycee_n_atteint_pas_un_eleve_du_fondamental(self):
        directeur = creer_compte(Role.DIRECTEUR_LYCEE, "dirl-fuite@stat.test", self.ecole)
        self.client.force_login(directeur)
        self.assertIn(self.client.get(self.dossier(self.e2)).status_code, (403, 404))

    def test_autre_ecole_n_atteint_aucun_dossier(self):
        self.client.force_login(self.fondateur_b)
        for eleve in (self.e2, self.e5, self.e9):
            self.assertIn(self.client.get(self.dossier(eleve)).status_code, (403, 404))


class PagesPubliquesTests(FuitesBase):
    """Visiteur non connecté : jamais une donnée sensible ni la situation de l'école."""

    def setUp(self):
        from etablissement.models import Etablissement
        Etablissement.objects.filter(pk=self.ecole.pk).update(situation_fonctionnement="ferme", motif_fermeture="insecurite")
        self.client.logout()

    def test_accueil_annuaire_et_connexion_ne_montrent_ni_fermeture_ni_motif(self):
        pages = ["/", f"/e/{self.ecole.slug}/", reverse("comptes:connexion"), reverse("manifeste_pwa")]
        for url in pages:
            with self.subTest(url=url):
                reponse = self.client.get(url, follow=True)
                texte = reponse.content.decode().lower()
                for interdit in ("insécurité", "fermé temporairement", "relocalis", "handicap", "réfugié", "ml-001", "koulikoro"):
                    self.assertNotIn(interdit, texte)

    def test_verification_publique_d_un_document_n_expose_qu_une_liste_blanche(self):
        verification = VerificationDocument.objects.create(
            eleve=self.e2, inscription=self.i["e2"], type_document=TypeDocumentVerifiable.ATTESTATION_SCOLARITE,
        )
        donnees = self.client.get(reverse("scolarite:verifier_document", args=[verification.jeton])).json()
        self.assertEqual(
            set(donnees), {"valide", "type_document", "eleve", "matricule", "classe", "etablissement", "emis_le"},
        )
        brut = json.dumps(donnees).lower()
        for interdit in ("moteur", "handicap", "déplac", "lieu_naissance", "acte"):
            self.assertNotIn(interdit, brut)

    def test_verification_publique_d_un_bulletin_n_expose_qu_une_liste_blanche(self):
        verification = VerificationBulletin.objects.create(eleve=self.e2, inscription=self.i["e2"])
        donnees = self.client.get(reverse("pedagogie:verifier_bulletin", args=[verification.jeton])).json()
        self.assertEqual(set(donnees), {"valide", "eleve", "matricule", "classe", "etablissement", "emis_le"})

    def test_pages_de_statistiques_fermees_aux_anonymes(self):
        for nom in (
            "fiche_annuelle", "exporter_fiche_annuelle_csv", "exporter_fiche_annuelle_xlsx", "resultats_examens",
            "infrastructures",
        ):
            self.assertEqual(self.client.get(reverse(f"statistiques:{nom}")).status_code, 302)
        self.assertEqual(
            self.client.get(reverse("scolarite:saisir_resultats_examen", args=[self.c9a.id])).status_code, 302,
        )


class ExportsEtRecherchesTests(FuitesBase):
    def test_le_csv_de_la_fiche_ne_contient_les_chiffres_sensibles_que_pour_l_administration(self):
        def csv_de(compte):
            self.client.force_login(compte)
            return self.client.get(
                reverse("statistiques:exporter_fiche_annuelle_csv"), {"annee": self.annee.id},
            ).content.decode("utf-8")

        self.assertIn("ÉLÈVES EN SITUATION DE HANDICAP", csv_de(self.fondateur))
        self.assertNotIn("ÉLÈVES EN SITUATION DE HANDICAP", csv_de(self.comptable))
        self.assertNotIn("DÉPLACÉS", csv_de(self.comptable))
        self.assertNotIn("ÉLÈVES EN SITUATION DE HANDICAP", csv_de(self.censeur))

    def test_l_export_excel_suit_les_memes_regles_que_le_csv(self):
        """Même contenu que le CSV pour chaque rôle : rien de plus, et les chiffres sensibles réservés à l'administration."""
        for compte, sensible in ((self.fondateur, True), (self.comptable, False), (self.censeur, False)):
            with self.subTest(role=compte.role):
                self.client.force_login(compte)
                reponse = self.client.get(reverse("statistiques:exporter_fiche_annuelle_xlsx"), {"annee": self.annee.id})
                self.assertEqual(reponse.status_code, 200)
                lignes = lignes_du_classeur(reponse.content)
                self.assertEqual(lignes, lignes_attendues(construire_fiche(compte, self.annee)))
                titres = {ligne[0] for ligne in lignes if ligne}
                self.assertEqual("ÉLÈVES EN SITUATION DE HANDICAP" in titres, sensible)
                self.assertEqual("ÉLÈVES DÉPLACÉS OU RÉFUGIÉS" in titres, sensible)

    def test_l_export_excel_ne_contient_aucun_nom_d_eleve_ni_matricule(self):
        self.client.force_login(self.fondateur)
        lignes = lignes_du_classeur(
            self.client.get(reverse("statistiques:exporter_fiche_annuelle_xlsx"), {"annee": self.annee.id}).content,
        )
        texte = " ".join(str(valeur) for ligne in lignes for valeur in ligne)
        for eleve in (self.e1, self.e2, self.e3, self.e5, self.e9):
            self.assertNotIn(eleve.matricule, texte)
            self.assertNotIn(eleve.nom, texte)
        for enseignant in (self.t1, self.t2, self.t3):
            self.assertNotIn(enseignant.email, texte)

    def test_le_csv_ne_contient_aucun_nom_d_eleve_ni_matricule(self):
        self.client.force_login(self.fondateur)
        contenu = self.client.get(
            reverse("statistiques:exporter_fiche_annuelle_csv"), {"annee": self.annee.id},
        ).content.decode("utf-8")
        for eleve in (self.e1, self.e2, self.e3, self.e5, self.e9):
            self.assertNotIn(eleve.matricule, contenu)
            self.assertNotIn(eleve.nom, contenu)
        for enseignant in (self.t1, self.t2, self.t3):
            self.assertNotIn(enseignant.email, contenu)

    def test_la_page_de_la_fiche_ne_contient_aucun_nom_d_eleve(self):
        self.client.force_login(self.fondateur)
        page = self.client.get(reverse("statistiques:fiche_annuelle"), {"annee": self.annee.id}).content.decode()
        for eleve in (self.e1, self.e2, self.e5):
            self.assertNotIn(eleve.matricule, page)

    def test_recherche_json_d_eleves_et_d_employes_limitee_a_l_ecole_et_aux_champs_prevus(self):
        self.client.force_login(self.comptable)
        reponse = self.client.get(reverse("finances:rechercher_eleve_json"), {"q": "eleve"}).json()
        self.assertTrue(reponse["resultats"])
        for ligne in reponse["resultats"]:
            self.assertEqual(set(ligne), {"matricule", "nom_complet"})
        employes = self.client.get(reverse("finances:rechercher_employe_json"), {"q": "t1"}).json()
        for ligne in employes["resultats"]:
            self.assertEqual(set(ligne), {"email", "nom_complet"})
        # un compte de l'autre école n'apparaît jamais
        intrus = creer_compte(Role.ENSEIGNANT, "t1-autre-ecole@stat.test", self.ecole_b)
        emails = [ligne["email"] for ligne in self.client.get(reverse("finances:rechercher_employe_json"), {"q": "t1"}).json()["resultats"]]
        self.assertNotIn(intrus.email, emails)


class JournalEtAssistantTests(FuitesBase):
    SENSIBLES = ("moteur", "visuel", "refugie", "deplace_interne", "intellectuel")

    def test_le_journal_d_audit_ne_garde_ni_nom_d_eleve_ni_renseignement_sensible(self):
        self.client.force_login(self.secretaire)
        self.client.post(reverse("scolarite:inscrire_eleve"), {
            "prenom": "Awa", "nom": "Zqxjournalfuite", "sexe": "F", "classe": self.c6a.id,
            "parent_email_1": "pj-fuite@stat.test", "handicap": "intellectuel", "statut_deplacement": "refugie",
        })
        self.client.post(reverse("scolarite:saisir_resultats_examen", args=[self.c9a.id]), {
            "examen": "def", f"resultat_{self.i['e5'].id}": "ajourne",
        })
        self.client.force_login(self.fondateur)
        self.client.get(reverse("statistiques:exporter_fiche_annuelle_csv"), {"annee": self.annee.id})
        self.client.post(f"{reverse('statistiques:infrastructures')}?annee={self.annee.id}", {
            "salles_classe": 10, "salles_bon_etat": 8, "salles_provisoires": 2, "places_assises": 300, "points_eau": 2,
            "latrines": 6, "latrines_fonctionnelles": 4, "manuels_lecture": 18, "manuels_calcul": 9,
            "cantine_beneficiaires": 0,
        })
        noms = [e.nom for e in (self.e1, self.e2, self.e3, self.e5, self.e6)] + ["Zqxjournalfuite"]
        nouvelles_actions = {"resultats_examen_saisis", "export_fiche_statistique_annuelle", "modification_fiche_infrastructures"}
        for entree in JournalAudit.objects.all():
            texte = f"{entree.cible} {entree.details}".lower()
            # Aucun renseignement sensible dans AUCUNE entrée (y compris l'inscription d'un élève)...
            for interdit in self.SENSIBLES:
                self.assertNotIn(interdit, texte, f"{entree.action} contient « {interdit} »")
            # ...et aucun nom d'élève dans les entrées des nouvelles fonctions (le journal de l'inscription note
            # volontairement « nom (matricule) » : comportement existant, hors de ces fonctions).
            if entree.action in nouvelles_actions:
                for nom in noms:
                    self.assertNotIn(nom.lower(), texte, f"{entree.action} contient « {nom} »")
        self.assertTrue(JournalAudit.objects.filter(action__in=nouvelles_actions).count() >= 3)

    @override_settings(GROQ_API_KEY="cle-de-test-factice")
    def test_l_assistant_n_envoie_a_l_ia_aucun_renseignement_sensible(self):
        Utilisateur.objects.filter(pk=self.e2.pk).update(lieu_naissance="Zqxlieu", numero_acte_naissance="Zqxacte")
        with patch("assistant.views.repondre_avec_ia", return_value="Réponse simulée.") as ia:
            self.client.force_login(self.fondateur)
            self.client.get(reverse("assistant:poser_question"), {"matricule": self.e2.matricule, "question": "Résume"})
        envoye = ia.call_args.kwargs["donnees_autorisees"]
        self.assertLessEqual(
            set(envoye), {"eleve", "dossier_complet", "classe", "dernieres_notes", "total_absences", "derniers_paiements"},
        )
        # Ni nom ni matricule : « eleve » n'est plus qu'une mention fixe (l'IA est un service externe, hors du Mali).
        self.assertIsInstance(envoye["eleve"], str)
        brut = json.dumps(envoye, default=str).lower()
        for interdit in (
            "moteur", "handicap", "zqxlieu", "zqxacte", "déplac", "examen", "admis",
            self.e2.matricule.lower(), self.e2.prenom.lower(), self.e2.nom.lower(),
        ):
            self.assertNotIn(interdit, brut)

    def test_les_pages_connectees_ne_sont_jamais_mises_en_cache(self):
        self.client.force_login(self.fondateur)
        for url in (
            self.dossier(self.e2), reverse("statistiques:fiche_annuelle"), reverse("statistiques:exporter_fiche_annuelle_csv"),
            reverse("statistiques:exporter_fiche_annuelle_xlsx"),
            reverse("statistiques:infrastructures"), reverse("scolarite:saisir_resultats_examen", args=[self.c9a.id]),
        ):
            with self.subTest(url=url):
                self.assertIn("no-store", self.client.get(url)["Cache-Control"])
