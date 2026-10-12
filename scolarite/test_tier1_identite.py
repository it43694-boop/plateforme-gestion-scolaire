"""
Tests des ajouts « identité administrative » (école, état civil élève, fiche personnel).

Chaque champ nouveau est facultatif et ne doit apparaître que là où il est prévu :
- école : modifiable depuis l'espace développeur de SA propre école seulement, jamais
  affichée sur une page publique ;
- état civil élève : visible de l'élève, de ses parents liés et de la direction/gestion,
  jamais d'un enseignant, d'un autre parent, d'un camarade ni d'une autre école ;
- fiche personnel : modifiable par le développeur de l'école seulement, absente des
  comptes parent/élève.
"""
import datetime
import uuid

from django.test import TestCase
from django.urls import reverse

from comptes.models import JournalAudit, Utilisateur, generer_matricule
from comptes.roles import Role, StatutCompte
from etablissement.models import Etablissement
from permissions_matrix.models import PermissionMatrix
from scolarite.models import (
    Affectation, AnneeScolaire, Classe, Cycle, Inscription, TypeDocumentVerifiable, VerificationDocument,
    peut_voir_etat_civil_eleve,
)

LIEU = "Zqxlieunaissanceunique"
ACTE = "Zqxacteunique98765"
DIPLOME = "Zqxdiplomeunique"
CODE_ECOLE = "Zqxcodeecoleunique"
NUMERO_AGREMENT = "Zqxagrementunique"

_telephones = iter(range(60000000, 69999999))


def creer_compte(role, email, ecole, **extra):
    compte = Utilisateur(
        email=email, prenom="Zq", nom=f"Nom{role.value}".replace("_", ""), role=role, etablissement=ecole,
        statut=StatutCompte.ACTIF, is_active=True, email_verifie=True,
        telephone=str(next(_telephones)) if role == Role.PARENT else None, **extra,
    )
    if role == Role.ELEVE:
        compte.matricule = generer_matricule()
    compte.set_unusable_password()
    compte.save()
    return compte


def creer_ecole(nom):
    ecole = Etablissement.objects.create(nom=nom)
    PermissionMatrix.seed_pour(ecole)
    annee = AnneeScolaire.objects.create(
        etablissement=ecole, libelle=f"{nom}-a", date_debut=datetime.date(2026, 10, 1),
        date_fin=datetime.date(2027, 7, 31), est_active=True,
    )
    classe = Classe.objects.create(nom=f"{nom}-6e", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=annee)
    return ecole, classe


class VisibiliteEtatCivilEleveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ecole, cls.classe = creer_ecole("EcoleA")
        cls.autre_ecole, cls.autre_classe = creer_ecole("EcoleB")

        cls.eleve = creer_compte(Role.ELEVE, "e1@t.test", cls.ecole, lieu_naissance=LIEU, numero_acte_naissance=ACTE)
        cls.camarade = creer_compte(Role.ELEVE, "e2@t.test", cls.ecole)
        cls.parent = creer_compte(Role.PARENT, "p1@t.test", cls.ecole)
        cls.autre_parent = creer_compte(Role.PARENT, "p2@t.test", cls.ecole)
        cls.eleve.parents_lies.add(cls.parent)
        cls.prof = creer_compte(Role.ENSEIGNANT, "prof@t.test", cls.ecole)
        cls.secretaire = creer_compte(Role.SECRETAIRE, "sec@t.test", cls.ecole)
        cls.direction = creer_compte(Role.DIRECTEUR_1ER_CYCLE, "dir@t.test", cls.ecole)
        cls.biblio = creer_compte(Role.BIBLIOTHECAIRE, "bib@t.test", cls.ecole)
        cls.secretaire_b = creer_compte(Role.SECRETAIRE, "secb@t.test", cls.autre_ecole)

        Inscription.objects.create(eleve=cls.eleve, classe=cls.classe)
        Inscription.objects.create(eleve=cls.camarade, classe=cls.classe)
        Affectation.objects.create(enseignant=cls.prof, classe=cls.classe, matiere="Maths", coefficient=2)
        cls.url = reverse("scolarite:dossier_eleve", args=[cls.eleve.matricule])

    def page(self, compte):
        self.client.force_login(compte)
        return self.client.get(self.url)

    def test_voient_etat_civil_eleve_parent_lie_et_gestion(self):
        for compte in (self.eleve, self.parent, self.secretaire, self.direction):
            reponse = self.page(compte)
            self.assertEqual(reponse.status_code, 200, compte.role)
            self.assertContains(reponse, LIEU, msg_prefix=compte.role)
            self.assertContains(reponse, ACTE, msg_prefix=compte.role)
            self.assertTrue(peut_voir_etat_civil_eleve(compte, self.eleve))

    def test_enseignant_qui_enseigne_a_leleve_voit_le_dossier_mais_pas_letat_civil(self):
        reponse = self.page(self.prof)
        # Si l'enseignant atteint le dossier (cas déjà géré par eleve_visible_pour), l'état civil n'y figure pas.
        if reponse.status_code == 200:
            self.assertNotContains(reponse, LIEU)
            self.assertNotContains(reponse, ACTE)
        self.assertFalse(peut_voir_etat_civil_eleve(self.prof, self.eleve))

    def test_aucune_fuite_vers_les_autres(self):
        for libelle, compte in {
            "camarade": self.camarade, "autre parent": self.autre_parent, "bibliothécaire": self.biblio,
            "secrétaire d'une autre école": self.secretaire_b,
        }.items():
            reponse = self.page(compte)
            self.assertNotEqual(reponse.status_code, 200, libelle)
            self.assertNotContains(reponse, LIEU, status_code=reponse.status_code, msg_prefix=libelle)
            self.assertNotContains(reponse, ACTE, status_code=reponse.status_code, msg_prefix=libelle)
            self.assertFalse(peut_voir_etat_civil_eleve(compte, self.eleve), libelle)

    def test_dossier_sans_etat_civil_affiche_rien_de_parasite(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.get(reverse("scolarite:dossier_eleve", args=[self.camarade.matricule]))
        self.assertEqual(reponse.status_code, 200)
        self.assertNotContains(reponse, "Acte de naissance")
        self.assertNotContains(reponse, "Né(e) à")

    def test_roles_de_surveillance_ne_voient_pas_lacte_meme_sils_voient_le_dossier(self):
        lycee = Classe.objects.create(
            nom="10e A", cycle=Cycle.LYCEE, annee_scolaire=self.classe.annee_scolaire,
        )
        eleve_lycee = creer_compte(
            Role.ELEVE, "eleve-lycee-etat-civil@example.test", self.ecole,
            lieu_naissance=LIEU, numero_acte_naissance=ACTE,
        )
        Inscription.objects.create(eleve=eleve_lycee, classe=lycee)
        censeur = creer_compte(Role.CENSEUR, "censeur-etat-civil@example.test", self.ecole)
        surveillant = creer_compte(Role.SURVEILLANT_GENERAL, "surveillant-etat-civil@example.test", self.ecole)
        url = reverse("scolarite:dossier_eleve", args=[eleve_lycee.matricule])
        for compte in (censeur, surveillant):
            with self.subTest(role=compte.role):
                self.client.force_login(compte)
                reponse = self.client.get(url)
                self.assertEqual(reponse.status_code, 200)
                self.assertNotContains(reponse, LIEU)
                self.assertNotContains(reponse, ACTE)


class InscriptionEleveEtatCivilTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ecole, cls.classe = creer_ecole("EcoleI")
        cls.secretaire = creer_compte(Role.SECRETAIRE, "seci@t.test", cls.ecole)

    def donnees(self, **extra):
        base = {
            "prenom": "Aminata", "nom": "Zqxtraore", "sexe": "F", "classe": self.classe.id,
            "parent_email_1": "parent-insc@t.test",
        }
        base.update(extra)
        return base

    def test_inscription_enregistre_lieu_et_acte(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.post(
            reverse("scolarite:inscrire_eleve"), self.donnees(lieu_naissance=LIEU, numero_acte_naissance=ACTE),
        )
        self.assertEqual(reponse.status_code, 302)
        eleve = Utilisateur.objects.get(nom="Zqxtraore")
        self.assertEqual((eleve.lieu_naissance, eleve.numero_acte_naissance), (LIEU, ACTE))

    def test_inscription_reste_possible_sans_ces_champs(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.post(reverse("scolarite:inscrire_eleve"), self.donnees())
        self.assertEqual(reponse.status_code, 302)
        eleve = Utilisateur.objects.get(nom="Zqxtraore")
        self.assertEqual((eleve.lieu_naissance, eleve.numero_acte_naissance), ("", ""))

    def test_message_et_journal_ne_contiennent_pas_letat_civil(self):
        self.client.force_login(self.secretaire)
        self.client.post(
            reverse("scolarite:inscrire_eleve"), self.donnees(lieu_naissance=LIEU, numero_acte_naissance=ACTE),
            follow=True,
        )
        for entree in JournalAudit.objects.all():
            self.assertNotIn(LIEU, f"{entree.cible} {entree.details}")
            self.assertNotIn(ACTE, f"{entree.cible} {entree.details}")


class PagesPubliquesNExposentRienTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ecole, cls.classe = creer_ecole("EcolePublique")
        for champ, valeur in {
            "code_etablissement": CODE_ECOLE, "numero_agrement": NUMERO_AGREMENT, "region": "Zqxregion",
            "cercle": "Zqxcercle", "commune": "Zqxcommune", "rattachement_administratif": "Zqxcap",
        }.items():
            setattr(cls.ecole, champ, valeur)
        cls.ecole.statut_juridique, cls.ecole.milieu = "prive_laic", "urbain"
        cls.ecole.save()
        cls.eleve = creer_compte(Role.ELEVE, "pub@t.test", cls.ecole, lieu_naissance=LIEU, numero_acte_naissance=ACTE)
        cls.inscription = Inscription.objects.create(eleve=cls.eleve, classe=cls.classe)
        cls.verification = VerificationDocument.objects.create(
            eleve=cls.eleve, inscription=cls.inscription, type_document=list(TypeDocumentVerifiable)[0],
        )

    def test_annuaire_connexion_et_verification_publique(self):
        urls = [
            reverse("vitrine:accueil"),
            reverse("scolarite:verifier_document", args=[self.verification.jeton]),
            reverse("comptes:connexion"),
            reverse("vitrine:choisir_etablissement", args=[self.ecole.slug]),
        ]
        interdits = [
            LIEU, ACTE, CODE_ECOLE, NUMERO_AGREMENT, "Zqxregion", "Zqxcercle", "Zqxcommune", "Zqxcap",
        ]
        for url in urls:
            reponse = self.client.get(url, follow=True)
            contenu = reponse.content.decode("utf-8", errors="ignore")
            for valeur in interdits:
                self.assertNotIn(valeur, contenu, f"{valeur} visible sur {url}")


class ParametresEcoleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ecole, _ = creer_ecole("EcoleP")
        cls.ecole_b, _ = creer_ecole("EcolePB")
        cls.dev = creer_compte(Role.DEVELOPPEUR, "devp@t.test", cls.ecole)
        cls.dev_b = creer_compte(Role.DEVELOPPEUR, "devpb@t.test", cls.ecole_b)
        cls.secretaire = creer_compte(Role.SECRETAIRE, "secp@t.test", cls.ecole)

    def donnees(self, **extra):
        base = {
            "nom": "EcoleP", "devise": "", "code_devise": "FCFA", "pas_montant": 5000,
            "taux_inps_salarie": "3.6", "taux_inps_employeur": "20.0",
            "taux_amo_salarie": "3.06", "taux_amo_employeur": "3.5",
        }
        base.update(extra)
        return base

    def test_le_developpeur_enregistre_lidentite_de_sa_propre_ecole(self):
        self.client.force_login(self.dev)
        reponse = self.client.post(reverse("espace_developpeur:parametres_etablissement"), self.donnees(
            code_etablissement=CODE_ECOLE, statut_juridique="communautaire", region="Koulikoro",
            cercle="Kati", commune="Kati", milieu="rural", rattachement_administratif="CAP Kati",
            numero_agrement=NUMERO_AGREMENT,
        ))
        self.assertEqual(reponse.status_code, 302)
        self.ecole.refresh_from_db()
        self.ecole_b.refresh_from_db()
        self.assertEqual((self.ecole.code_etablissement, self.ecole.statut_juridique, self.ecole.milieu),
                         (CODE_ECOLE.upper(), "communautaire", "rural"))
        self.assertEqual((self.ecole_b.code_etablissement, self.ecole_b.region, self.ecole_b.numero_agrement),
                         ("", "", ""))

    def test_valeurs_hors_liste_refusees(self):
        self.client.force_login(self.dev)
        reponse = self.client.post(
            reverse("espace_developpeur:parametres_etablissement"),
            self.donnees(statut_juridique="n_importe_quoi", milieu="banlieue"),
        )
        self.assertEqual(reponse.status_code, 200)
        self.ecole.refresh_from_db()
        self.assertEqual((self.ecole.statut_juridique, self.ecole.milieu), ("", ""))

    def test_un_secretaire_ne_peut_ni_voir_ni_modifier(self):
        self.client.force_login(self.secretaire)
        url = reverse("espace_developpeur:parametres_etablissement")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, self.donnees(code_etablissement=CODE_ECOLE)).status_code, 403)
        self.ecole.refresh_from_db()
        self.assertEqual(self.ecole.code_etablissement, "")

    def test_formulaire_ne_montre_que_les_donnees_de_sa_propre_ecole(self):
        self.ecole_b.code_etablissement = "Zqxcodeautreecole"
        self.ecole_b.save()
        self.client.force_login(self.dev)
        reponse = self.client.get(reverse("espace_developpeur:parametres_etablissement"))
        self.assertNotContains(reponse, "Zqxcodeautreecole")

    def test_deux_ecoles_peuvent_porter_le_meme_code_sans_erreur(self):
        # Pas d'unicité : sinon l'erreur « déjà utilisé » révélerait le code d'une autre école.
        self.ecole_b.code_etablissement = CODE_ECOLE
        self.ecole_b.save()
        self.client.force_login(self.dev)
        reponse = self.client.post(
            reverse("espace_developpeur:parametres_etablissement"), self.donnees(code_etablissement=CODE_ECOLE),
        )
        self.assertEqual(reponse.status_code, 302)
        self.assertNotIn("déjà", reponse.content.decode("utf-8", errors="ignore"))


class FichePersonnelEtEleveParDeveloppeurTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ecole, cls.classe = creer_ecole("EcoleF")
        cls.ecole_b, _ = creer_ecole("EcoleFB")
        cls.dev = creer_compte(Role.DEVELOPPEUR, "devf@t.test", cls.ecole)
        cls.dev_b = creer_compte(Role.DEVELOPPEUR, "devfb@t.test", cls.ecole_b)
        cls.prof = creer_compte(Role.ENSEIGNANT, "proff@t.test", cls.ecole)
        cls.parent = creer_compte(Role.PARENT, "parf@t.test", cls.ecole)
        cls.eleve = creer_compte(Role.ELEVE, "elef@t.test", cls.ecole)
        cls.prof_b = creer_compte(Role.ENSEIGNANT, "profb@t.test", cls.ecole_b)

    def url(self, compte):
        return reverse("espace_developpeur:modifier_compte", args=[compte.id])

    def test_fiche_personnel_enregistree_et_journalisee_sans_valeurs(self):
        self.client.force_login(self.dev)
        reponse = self.client.post(self.url(self.prof), {
            "role": Role.ENSEIGNANT.value, "statut": StatutCompte.ACTIF.value,
            "statut_personnel": "fonctionnaire", "diplome": DIPLOME, "discipline": "Mathématiques",
        })
        self.assertEqual(reponse.status_code, 302)
        self.prof.refresh_from_db()
        self.assertEqual((self.prof.statut_personnel, self.prof.diplome, self.prof.discipline),
                         ("fonctionnaire", DIPLOME, "Mathématiques"))
        entree = JournalAudit.objects.filter(action="modification_compte_espace_developpeur").latest("horodatage")
        self.assertNotIn(DIPLOME, f"{entree.cible} {entree.details}")
        self.assertIn("diplome", entree.details["champs_administratifs_modifies"])

    def test_statut_personnel_hors_liste_refuse(self):
        self.client.force_login(self.dev)
        reponse = self.client.post(self.url(self.prof), {
            "role": Role.ENSEIGNANT.value, "statut": StatutCompte.ACTIF.value, "statut_personnel": "roi",
        })
        self.assertEqual(reponse.status_code, 200)
        self.prof.refresh_from_db()
        self.assertEqual(self.prof.statut_personnel, "")

    def test_champs_personnel_absents_et_ignores_pour_parent_et_eleve(self):
        self.client.force_login(self.dev)
        for compte in (self.parent, self.eleve):
            reponse = self.client.get(self.url(compte))
            self.assertNotContains(reponse, "Diplôme le plus élevé")
            self.assertNotContains(reponse, "Discipline enseignée")
            self.client.post(self.url(compte), {
                "role": compte.role, "statut": StatutCompte.ACTIF.value, "diplome": DIPLOME, "discipline": "X",
            })
            compte.refresh_from_db()
            self.assertEqual((compte.diplome, compte.discipline), ("", ""))

    def test_etat_civil_eleve_modifiable_seulement_pour_un_eleve(self):
        self.client.force_login(self.dev)
        self.assertContains(self.client.get(self.url(self.eleve)), "Lieu de naissance")
        self.assertNotContains(self.client.get(self.url(self.prof)), "Lieu de naissance")
        self.client.post(self.url(self.eleve), {
            "role": Role.ELEVE.value, "statut": StatutCompte.ACTIF.value,
            "lieu_naissance": LIEU, "numero_acte_naissance": ACTE,
        })
        self.eleve.refresh_from_db()
        self.assertEqual((self.eleve.lieu_naissance, self.eleve.numero_acte_naissance), (LIEU, ACTE))
        # Le POST sur un enseignant ne doit jamais écrire un état civil
        self.client.post(self.url(self.prof), {
            "role": Role.ENSEIGNANT.value, "statut": StatutCompte.ACTIF.value, "lieu_naissance": LIEU,
        })
        self.prof.refresh_from_db()
        self.assertEqual(self.prof.lieu_naissance, "")

    def test_developpeur_dune_autre_ecole_ne_peut_rien_toucher(self):
        self.client.force_login(self.dev_b)
        reponse = self.client.post(self.url(self.prof), {
            "role": Role.ENSEIGNANT.value, "statut": StatutCompte.ACTIF.value, "diplome": DIPLOME,
        })
        self.assertEqual(reponse.status_code, 404)
        self.prof.refresh_from_db()
        self.assertEqual(self.prof.diplome, "")

    def test_non_developpeur_refuse(self):
        self.client.force_login(self.prof)
        self.assertEqual(self.client.get(self.url(self.prof)).status_code, 403)

    def test_liste_comptes_naffiche_pas_les_champs_sensibles(self):
        self.prof.diplome = DIPLOME
        self.prof.save()
        self.eleve.numero_acte_naissance = ACTE
        self.eleve.save()
        self.client.force_login(self.dev)
        reponse = self.client.get(reverse("espace_developpeur:liste_comptes"))
        self.assertNotContains(reponse, DIPLOME)
        self.assertNotContains(reponse, ACTE)


class AssistantEtExportsNeRecoiventPasLesNouveauxChampsTests(TestCase):
    """Garde-fou statique : le code de l'Assistant (envoi à un service externe) et des exports
    ne doit pas lire les nouveaux champs. Si quelqu'un les ajoute plus tard, ce test échoue
    et force une décision explicite."""

    CHAMPS = (
        "lieu_naissance", "numero_acte_naissance", "statut_personnel", "diplome", "discipline",
        "code_etablissement", "numero_agrement", "rattachement_administratif",
    )

    def test_modules_sortants_ne_lisent_pas_les_nouveaux_champs(self):
        import pathlib
        racine = pathlib.Path(__file__).resolve().parent.parent
        fichiers = [
            *racine.glob("assistant/*.py"), *racine.glob("statistiques/views.py"),
            *racine.glob("vitrine/*.py"), *racine.glob("comptes/context_processors.py"),
        ]
        fichiers = [f for f in fichiers if not f.name.startswith("test")]
        self.assertTrue(fichiers)
        trouves = []
        for fichier in fichiers:
            contenu = fichier.read_text(encoding="utf-8")
            trouves += [f"{fichier.name}: {c}" for c in self.CHAMPS if c in contenu]
        self.assertEqual(trouves, [])


class ChangementDeRoleEtDoublonsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ecole, _ = creer_ecole("EcoleR")
        cls.ecole_b, _ = creer_ecole("EcoleRB")
        cls.dev = creer_compte(Role.DEVELOPPEUR, "devr@t.test", cls.ecole)
        cls.proprietaire = creer_compte(Role.DEVELOPPEUR, "owner@t.test", None)
        cls.proprietaire.is_superuser = cls.proprietaire.is_staff = True
        cls.proprietaire.save()

    def test_changement_de_role_efface_les_renseignements_devenus_inutiles(self):
        prof = creer_compte(
            Role.ENSEIGNANT, "ancienprof@t.test", self.ecole,
            statut_personnel="fonctionnaire", diplome=DIPLOME, discipline="Maths",
        )
        self.client.force_login(self.dev)
        url = reverse("espace_developpeur:modifier_compte", args=[prof.id])
        # Le formulaire (rôle enseignant) envoie encore le diplôme au moment où le rôle devient parent.
        reponse = self.client.post(url, {
            "role": Role.PARENT.value, "statut": StatutCompte.ACTIF.value,
            "statut_personnel": "fonctionnaire", "diplome": DIPLOME, "discipline": "Maths",
        })
        self.assertEqual(reponse.status_code, 302)
        prof.refresh_from_db()
        self.assertEqual(prof.role, Role.PARENT)
        self.assertEqual((prof.statut_personnel, prof.diplome, prof.discipline), ("", "", ""))
        entree = JournalAudit.objects.filter(action="modification_compte_espace_developpeur").latest("horodatage")
        self.assertNotIn(DIPLOME, str(entree.details))

    def test_rester_dans_le_personnel_conserve_la_fiche(self):
        prof = creer_compte(Role.ENSEIGNANT, "restprof@t.test", self.ecole, diplome=DIPLOME)
        self.client.force_login(self.dev)
        self.client.post(reverse("espace_developpeur:modifier_compte", args=[prof.id]), {
            "role": Role.SECRETAIRE.value, "statut": StatutCompte.ACTIF.value, "diplome": DIPLOME,
        })
        prof.refresh_from_db()
        self.assertEqual((prof.role, prof.diplome), (Role.SECRETAIRE, DIPLOME))

    def test_code_etablissement_normalise(self):
        self.client.force_login(self.dev)
        self.client.post(reverse("espace_developpeur:parametres_etablissement"), {
            "nom": "EcoleR", "devise": "", "code_devise": "FCFA", "pas_montant": 5000,
            "taux_inps_salarie": "3.6", "taux_inps_employeur": "20.0",
            "taux_amo_salarie": "3.06", "taux_amo_employeur": "3.5",
            "code_etablissement": "  ml  001 ",
        })
        self.ecole.refresh_from_db()
        self.assertEqual(self.ecole.code_etablissement, "ML 001")

    def test_le_proprietaire_voit_les_doublons_pas_les_ecoles(self):
        for ecole in (self.ecole, self.ecole_b):
            ecole.code_etablissement = "ML 777"
            ecole.save()
        self.client.force_login(self.proprietaire)
        reponse = self.client.get(reverse("espace_plateforme:liste_etablissements"))
        self.assertContains(reponse, "Code en double", count=2)
        # Une école ne voit ni la liste des écoles ni le code de l'autre.
        self.client.force_login(self.dev)
        self.assertEqual(self.client.get(reverse("espace_plateforme:liste_etablissements")).status_code, 302)
        page = self.client.get(reverse("espace_developpeur:parametres_etablissement"))
        self.assertNotContains(page, "Code en double")

    def test_pas_de_faux_doublon_avec_un_code_vide(self):
        self.client.force_login(self.proprietaire)
        reponse = self.client.get(reverse("espace_plateforme:liste_etablissements"))
        self.assertNotContains(reponse, "Code en double")

    def test_doublons_historiques_detectes_apres_normalisation(self):
        self.ecole.code_etablissement = " ml 777 "
        self.ecole_b.code_etablissement = "ML 777"
        self.ecole.save()
        self.ecole_b.save()
        self.client.force_login(self.proprietaire)
        reponse = self.client.get(reverse("espace_plateforme:liste_etablissements"))
        self.assertContains(reponse, "Code en double", count=2)


class AvertissementChangementDeRoleTests(TestCase):
    """Changer de rôle efface des renseignements : la personne qui le fait doit le savoir, avant et après."""

    @classmethod
    def setUpTestData(cls):
        cls.ecole, _ = creer_ecole("EcoleAvert")
        cls.dev = creer_compte(Role.DEVELOPPEUR, "devavert@t.test", cls.ecole)

    def test_formulaire_previent_avant_l_enregistrement(self):
        prof = creer_compte(Role.ENSEIGNANT, "profavert@t.test", self.ecole, diplome="Licence")
        self.client.force_login(self.dev)
        reponse = self.client.get(reverse("espace_developpeur:modifier_compte", args=[prof.id]))
        self.assertContains(reponse, "efface les informations administratives")

    def test_message_apres_enregistrement_nomme_ce_qui_a_ete_efface(self):
        prof = creer_compte(
            Role.ENSEIGNANT, "profefface@t.test", self.ecole, diplome="Licence", discipline="Maths",
        )
        self.client.force_login(self.dev)
        reponse = self.client.post(reverse("espace_developpeur:modifier_compte", args=[prof.id]), {
            "role": Role.PARENT.value, "statut": StatutCompte.ACTIF.value, "diplome": "Licence", "discipline": "Maths",
        }, follow=True)
        textes = [str(m) for m in reponse.context["messages"]]
        self.assertTrue(any("effacées" in t and "diplôme" in t and "discipline" in t for t in textes), textes)
        entree = JournalAudit.objects.filter(action="modification_compte_espace_developpeur").latest("horodatage")
        self.assertEqual(sorted(entree.details["champs_administratifs_effaces"]), ["diplome", "discipline"])
        self.assertNotIn("Licence", str(entree.details))

    def test_aucun_message_quand_rien_n_est_efface(self):
        prof = creer_compte(Role.ENSEIGNANT, "profrien@t.test", self.ecole)  # fiche vide
        self.client.force_login(self.dev)
        reponse = self.client.post(reverse("espace_developpeur:modifier_compte", args=[prof.id]), {
            "role": Role.PARENT.value, "statut": StatutCompte.ACTIF.value,
        }, follow=True)
        self.assertFalse(any("effacées" in str(m) for m in reponse.context["messages"]))

    def test_aucun_message_quand_on_reste_dans_le_personnel(self):
        prof = creer_compte(Role.ENSEIGNANT, "profreste@t.test", self.ecole, diplome="Licence")
        self.client.force_login(self.dev)
        reponse = self.client.post(reverse("espace_developpeur:modifier_compte", args=[prof.id]), {
            "role": Role.SECRETAIRE.value, "statut": StatutCompte.ACTIF.value, "diplome": "Licence",
        }, follow=True)
        self.assertFalse(any("effacées" in str(m) for m in reponse.context["messages"]))
