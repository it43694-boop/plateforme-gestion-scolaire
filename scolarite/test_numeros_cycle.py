"""
Un numéro (matricule) par cycle : le 1er cycle, le 2ème cycle, le lycée et le professionnel donnent chacun le leur.

Le matricule d'origine ne change jamais (identifiant de connexion, clé du dossier) ; le numéro d'un cycle s'imprime sur les documents de ce
cycle, et un cycle sans numéro propre garde le matricule d'origine. Jeu de données de EducationBase : e5 est en 9A (2ème cycle) ; on lui
donne une inscription de l'an dernier en 5A (1er cycle) pour qu'il ait traversé deux cycles.
"""
import datetime
import json
from unittest import mock

from django.db import IntegrityError, transaction
from django.urls import reverse

from comptes.models import JournalAudit, generer_matricule
from comptes.outils_test_arabe import CaptureHtmlDuPdf, client_en, restes_hors_textes_saisis
from comptes.roles import Role
from permissions_matrix.models import PermissionMatrix
from permissions_matrix.modules import Module
from scolarite.forms import InscrireEleveForm
from scolarite.models import (
    AnneeScolaire, Classe, Cycle, Inscription, NumeroCycle, TypeDocumentVerifiable, VerificationDocument,
)
from scolarite.numeros_cycle import numero_du_cycle
from scolarite.test_dossier_complet import StockageTemporaire
from statistiques.test_education import creer_compte


class NumerosBase(StockageTemporaire):
    def setUp(self):
        Inscription.objects.create(eleve=self.e5, classe=self.classe_5a, statut=Inscription.Statut.ADMIS)
        self.dir_2eme = creer_compte(Role.DIRECTEUR_2EME_CYCLE, "dir2@stat.test", self.ecole)

    def accorder_les_modules(self, *comptes):
        """Même si l'école accorde les modules Élèves et Classes à ces rôles, ils ne gagnent pas le droit de changer des numéros."""
        for compte in comptes:
            for module in (Module.ELEVES, Module.CLASSES):
                PermissionMatrix.objects.update_or_create(
                    etablissement=self.ecole, role=compte.role, module=module, defaults={"autorise": True},
                )

    def url(self, classe=None):
        return reverse("scolarite:saisir_numeros_cycle", args=[(classe or self.c9a).pk])

    def poster(self, valeurs, classe=None):
        return self.client.post(self.url(classe), {f"numero_{eleve.pk}": texte for eleve, texte in valeurs.items()})

    def numero(self, eleve, cycle=Cycle.DEUXIEME_CYCLE):
        ligne = NumeroCycle.objects.filter(eleve=eleve, cycle=cycle).first()
        return ligne.numero if ligne else None


class ModeleTests(NumerosBase):
    def test_sans_numero_propre_le_matricule_reprend_sa_place(self):
        self.assertEqual(numero_du_cycle(self.e5, Cycle.DEUXIEME_CYCLE), self.e5.matricule)
        self.assertEqual(numero_du_cycle(self.e5, Cycle.LYCEE), self.e5.matricule)

    def test_un_numero_propre_ne_vaut_que_pour_son_cycle(self):
        NumeroCycle.objects.create(eleve=self.e5, cycle=Cycle.DEUXIEME_CYCLE, numero="DEF-0001")
        self.assertEqual(numero_du_cycle(self.e5, Cycle.DEUXIEME_CYCLE), "DEF-0001")
        self.assertEqual(numero_du_cycle(self.e5, Cycle.PREMIER_CYCLE), self.e5.matricule)

    def test_l_ecole_est_recopiee_de_l_eleve(self):
        ligne = NumeroCycle.objects.create(eleve=self.e5, cycle=Cycle.DEUXIEME_CYCLE, numero="DEF-0001")
        self.assertEqual(ligne.etablissement_id, self.ecole.pk)

    def test_un_seul_numero_par_eleve_et_par_cycle(self):
        NumeroCycle.objects.create(eleve=self.e5, cycle=Cycle.DEUXIEME_CYCLE, numero="A1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            NumeroCycle.objects.create(eleve=self.e5, cycle=Cycle.DEUXIEME_CYCLE, numero="A2")

    def test_un_numero_est_unique_dans_un_cycle_de_l_ecole_mais_pas_d_un_cycle_a_l_autre(self):
        NumeroCycle.objects.create(eleve=self.e5, cycle=Cycle.DEUXIEME_CYCLE, numero="A1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            NumeroCycle.objects.create(eleve=self.e6, cycle=Cycle.DEUXIEME_CYCLE, numero="A1")
        NumeroCycle.objects.create(eleve=self.e1, cycle=Cycle.PREMIER_CYCLE, numero="A1")  # autre cycle : permis


class SaisieDesNumerosTests(NumerosBase):
    def test_l_administration_de_la_classe_peut_ouvrir_la_page(self):
        for compte, classe in ((self.fondateur, self.c9a), (self.secretaire, self.c9a), (self.dir_2eme, self.c9a), (self.dir_1er, self.c6a)):
            self.client.force_login(compte)
            with self.subTest(role=compte.role, classe=classe.nom):
                self.assertEqual(self.client.get(self.url(classe)).status_code, 200)

    def test_les_autres_roles_sont_refuses_meme_si_les_modules_leur_sont_accordes(self):
        self.accorder_les_modules(self.comptable, self.censeur, self.t2, self.parent, self.e5)
        for compte in (self.comptable, self.censeur, self.t2, self.parent, self.e5):
            self.client.force_login(compte)
            with self.subTest(role=compte.role):
                self.assertEqual(self.client.get(self.url()).status_code, 403)
                self.assertEqual(self.poster({self.e5: "PIRATE-1"}).status_code, 403)
        self.assertFalse(NumeroCycle.objects.exists())

    def test_un_directeur_de_cycle_ne_touche_que_son_cycle(self):
        self.client.force_login(self.dir_1er)
        self.assertEqual(self.client.get(self.url(self.c9a)).status_code, 404)
        self.assertEqual(self.poster({self.e5: "PIRATE-1"}).status_code, 404)
        self.assertFalse(NumeroCycle.objects.exists())

    def test_une_classe_d_une_autre_ecole_est_introuvable(self):
        self.client.force_login(self.fondateur_b)
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.assertEqual(self.poster({self.e5: "PIRATE-1"}).status_code, 404)

    def test_visiteur_anonyme_redirige(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url()).status_code, 302)

    def test_les_numeros_sont_enregistres_pour_le_cycle_de_la_classe(self):
        self.client.force_login(self.secretaire)
        reponse = self.poster({self.e5: "DEF-0001", self.e6: "DEF-0002"})
        self.assertRedirects(reponse, self.url())
        self.assertEqual((self.numero(self.e5), self.numero(self.e6)), ("DEF-0001", "DEF-0002"))
        self.assertIsNone(self.numero(self.e5, Cycle.PREMIER_CYCLE))
        self.e5.refresh_from_db()
        self.assertTrue(self.e5.matricule)  # le matricule d'origine n'a pas bougé

    def test_la_page_montre_les_numeros_saisis_et_le_matricule_d_origine(self):
        NumeroCycle.objects.create(eleve=self.e5, cycle=Cycle.DEUXIEME_CYCLE, numero="DEF-0001")
        self.client.force_login(self.secretaire)
        page = self.client.get(self.url())
        self.assertContains(page, 'value="DEF-0001"')
        self.assertContains(page, self.e5.matricule)
        self.assertContains(page, f'placeholder="{self.e6.matricule}"')

    def test_un_champ_vide_ou_egal_au_matricule_retire_le_numero_propre(self):
        NumeroCycle.objects.create(eleve=self.e5, cycle=Cycle.DEUXIEME_CYCLE, numero="DEF-0001")
        NumeroCycle.objects.create(eleve=self.e6, cycle=Cycle.DEUXIEME_CYCLE, numero="DEF-0002")
        self.client.force_login(self.secretaire)
        self.poster({self.e5: "", self.e6: self.e6.matricule})
        self.assertIsNone(self.numero(self.e5))
        self.assertIsNone(self.numero(self.e6))

    def test_deux_eleves_peuvent_echanger_leurs_numeros(self):
        NumeroCycle.objects.create(eleve=self.e5, cycle=Cycle.DEUXIEME_CYCLE, numero="A1")
        NumeroCycle.objects.create(eleve=self.e6, cycle=Cycle.DEUXIEME_CYCLE, numero="A2")
        self.client.force_login(self.secretaire)
        self.poster({self.e5: "A2", self.e6: "A1"})
        self.assertEqual((self.numero(self.e5), self.numero(self.e6)), ("A2", "A1"))

    def test_le_meme_numero_dans_un_autre_cycle_est_permis(self):
        NumeroCycle.objects.create(eleve=self.e1, cycle=Cycle.PREMIER_CYCLE, numero="A1")
        self.client.force_login(self.secretaire)
        self.poster({self.e5: "A1"})
        self.assertEqual(self.numero(self.e5), "A1")

    def test_un_numero_saisi_deux_fois_est_refuse_et_rien_n_est_ecrit(self):
        self.client.force_login(self.secretaire)
        page = self.poster({self.e5: "A1", self.e6: "a1"})
        self.assertContains(page, "saisi deux fois")
        self.assertContains(page, "Rien n")
        self.assertFalse(NumeroCycle.objects.exists())

    def test_un_numero_deja_pris_dans_le_cycle_est_refuse(self):
        NumeroCycle.objects.create(eleve=self.e6, cycle=Cycle.DEUXIEME_CYCLE, numero="A1")
        autre = creer_compte(Role.ELEVE, "autre9a@stat.test", self.ecole)
        Inscription.objects.create(eleve=autre, classe=self.c9a)
        self.client.force_login(self.secretaire)
        page = self.poster({self.e5: "A1"})
        self.assertContains(page, "déjà celui d&#x27;un autre élève")
        self.assertIsNone(self.numero(self.e5))

    def test_le_matricule_d_un_autre_eleve_est_refuse(self):
        self.client.force_login(self.secretaire)
        page = self.poster({self.e5: self.e6.matricule})
        self.assertContains(page, "matricule d&#x27;un autre élève")
        self.assertIsNone(self.numero(self.e5))

    def test_le_matricule_d_un_eleve_d_une_autre_classe_n_est_pas_signale(self):
        """Un refus dirait à la personne qu'un matricule existe dans un autre cycle, alors que cet élève ne la concerne pas."""
        self.client.force_login(self.secretaire)
        page = self.poster({self.e5: self.e1.matricule})  # e1 est en 6A, e5 en 9A
        self.assertRedirects(page, self.url())
        self.assertEqual(self.numero(self.e5), self.e1.matricule)

    def test_une_forme_invalide_est_refusee(self):
        self.client.force_login(self.secretaire)
        for texte in ("=1+1", "<b>x</b>", "A" * 21, "-1", "é1"):
            with self.subTest(texte=texte):
                self.assertContains(self.poster({self.e5: texte}), "Chiffres, lettres")
        self.assertFalse(NumeroCycle.objects.exists())

    def test_les_espaces_en_trop_sont_retires(self):
        self.client.force_login(self.secretaire)
        self.poster({self.e5: "  DEF   0001  "})
        self.assertEqual(self.numero(self.e5), "DEF 0001")

    def test_un_eleve_d_une_autre_classe_est_ignore(self):
        self.client.force_login(self.secretaire)
        self.poster({self.e1: "PIRATE-1", self.e5: "DEF-0001"})  # e1 est en 6A, pas en 9A
        self.assertIsNone(self.numero(self.e1, Cycle.DEUXIEME_CYCLE))
        self.assertIsNone(self.numero(self.e1, Cycle.PREMIER_CYCLE))
        self.assertEqual(self.numero(self.e5), "DEF-0001")

    def test_un_eleve_qui_a_quitte_l_ecole_ne_figure_pas_dans_la_liste(self):
        self.i["e6"].statut = Inscription.Statut.TRANSFERE
        self.i["e6"].save(update_fields=["statut"])
        self.client.force_login(self.secretaire)
        self.assertNotContains(self.client.get(self.url()), f'name="numero_{self.e6.pk}"')
        self.poster({self.e6: "DEF-0002"})
        self.assertIsNone(self.numero(self.e6))

    def test_le_journal_compte_les_changements_sans_ecrire_les_numeros(self):
        self.client.force_login(self.secretaire)
        self.poster({self.e5: "DEF-0001", self.e6: "DEF-0002"})
        entree = JournalAudit.objects.get(action="numeros_cycle_saisis")
        self.assertEqual(entree.details, {"ajoutes": 2, "modifies": 0, "supprimes": 0})
        self.assertNotIn("DEF-000", f"{entree.cible} {entree.details}")

    def test_sans_changement_rien_n_est_ecrit_au_journal(self):
        self.client.force_login(self.secretaire)
        self.poster({self.e5: "", self.e6: ""})
        self.assertFalse(JournalAudit.objects.filter(action="numeros_cycle_saisis").exists())

    def test_l_action_est_proposee_dans_le_menu_des_classes_a_ceux_qui_peuvent(self):
        self.client.force_login(self.secretaire)
        self.assertContains(self.client.get(reverse("scolarite:liste_classes")), self.url())
        self.accorder_les_modules(self.t2)
        self.client.force_login(self.t2)
        reponse = self.client.get(reverse("scolarite:liste_classes"))
        self.assertEqual(reponse.status_code, 200)
        self.assertNotContains(reponse, self.url())


class AffichageDesNumerosTests(NumerosBase):
    def setUp(self):
        super().setUp()
        NumeroCycle.objects.create(eleve=self.e5, cycle=Cycle.DEUXIEME_CYCLE, numero="DEF-0001")
        NumeroCycle.objects.create(eleve=self.e5, cycle=Cycle.PREMIER_CYCLE, numero="PRIM-0009")
        self.client.force_login(self.secretaire)

    def html_du_pdf(self, adresse):
        with CaptureHtmlDuPdf() as capture:
            reponse = self.client.get(adresse)
        self.assertEqual(reponse.status_code, 200)
        return capture.html

    def test_la_carte_porte_le_numero_du_cycle_de_la_classe(self):
        html = self.html_du_pdf(reverse("scolarite:cartes_classe_pdf", args=[self.c9a.pk]))
        self.assertIn("DEF-0001", html)
        self.assertNotIn("PRIM-0009", html)
        self.assertNotIn(self.e5.matricule, html)
        html = self.html_du_pdf(reverse("scolarite:carte_eleve_pdf", args=[self.e5.matricule]))
        self.assertIn("DEF-0001", html)

    def test_la_carte_d_un_eleve_sans_numero_propre_garde_le_matricule(self):
        html = self.html_du_pdf(reverse("scolarite:cartes_classe_pdf", args=[self.c9a.pk]))
        self.assertIn(self.e6.matricule, html)

    def test_l_attestation_de_scolarite(self):
        html = self.html_du_pdf(reverse("scolarite:generer_attestation_scolarite", args=[self.e5.matricule]))
        self.assertIn("DEF-0001", html)
        self.assertNotIn(self.e5.matricule, html)

    def test_les_certificats(self):
        html = self.html_du_pdf(reverse("scolarite:document_officiel", args=[self.e5.matricule, "certificat-scolarite"]))
        self.assertIn("DEF-0001", html)
        self.assertNotIn(self.e5.matricule, html)

    def test_le_bulletin(self):
        self.client.force_login(self.fondateur)
        html = self.html_du_pdf(reverse("pedagogie:exporter_bulletin_pdf", args=[self.e5.matricule]))
        self.assertIn("DEF-0001", html)
        self.assertNotIn(self.e5.matricule, html)
        page = self.client.get(reverse("pedagogie:bulletin_eleve", args=[self.e5.matricule]))
        self.assertContains(page, "Matricule : DEF-0001")

    def test_la_liste_de_la_classe_et_ses_exports(self):
        page = self.client.get(reverse("scolarite:liste_eleves"), {"classe": self.c9a.pk})
        self.assertContains(page, "<td>DEF-0001</td>")
        self.assertContains(page, f"<td>{self.e6.matricule}</td>")
        self.client.force_login(self.fondateur)
        csv = self.client.get(reverse("scolarite:exporter_liste_classe_csv", args=[self.c9a.pk])).content.decode("utf-8-sig")
        self.assertIn("DEF-0001", csv)
        self.assertNotIn(self.e5.matricule, csv)

    def test_la_page_publique_de_verification(self):
        verification = VerificationDocument.objects.create(
            type_document=TypeDocumentVerifiable.CARTE_ELEVE, eleve=self.e5, inscription=self.i["e5"],
        )
        self.client.logout()
        donnees = json.loads(self.client.get(reverse("scolarite:verifier_document", args=[verification.jeton])).content)
        self.assertEqual(donnees["matricule"], "DEF-0001")
        page = self.client.get(reverse("vitrine:verifier"), {"code": verification.code})
        self.assertContains(page, "DEF-0001")
        self.assertNotContains(page, self.e5.matricule)

    def test_le_dossier_montre_le_numero_actuel_et_l_historique(self):
        page = self.client.get(reverse("scolarite:dossier_eleve", args=[self.e5.matricule]))
        self.assertContains(page, "Numéro du cycle actuel : DEF-0001")
        self.assertContains(page, "PRIM-0009")  # l'administration voit toutes les classes
        self.assertContains(page, f"Matricule {self.e5.matricule}")

    def test_le_dossier_ne_montre_pas_le_numero_d_un_cycle_hors_du_perimetre(self):
        self.client.force_login(self.dir_2eme)
        page = self.client.get(reverse("scolarite:dossier_eleve", args=[self.e5.matricule]))
        self.assertContains(page, "DEF-0001")
        self.assertNotContains(page, "PRIM-0009")  # la classe 5A est du 1er cycle

    def test_la_recherche_trouve_par_le_numero_du_cycle_dans_le_perimetre_de_chacun(self):
        page = self.client.get(reverse("scolarite:recherche_globale"), {"q": "DEF-0001"})
        self.assertContains(page, self.e5.nom_complet)
        self.assertContains(page, "<td>DEF-0001</td>")
        # le numéro du 1er cycle ne désigne plus l'élève dans sa classe actuelle : on le retrouve par son matricule
        self.assertNotContains(self.client.get(reverse("scolarite:recherche_globale"), {"q": "PRIM-0009"}), self.e5.nom_complet)
        self.client.force_login(self.dir_1er)  # le 1er cycle ne voit pas les classes du 2ème
        reponse = self.client.get(reverse("scolarite:recherche_globale"), {"q": "DEF-0001"})
        self.assertNotContains(reponse, self.e5.nom_complet)
        self.assertNotContains(reponse, "DEF-0001</td>")

    def test_le_conseil_de_classe_et_les_resultats_d_examen(self):
        page = self.client.get(reverse("scolarite:saisir_resultats_examen", args=[self.c9a.pk]))
        self.assertContains(page, "<td>DEF-0001</td>")
        self.assertNotContains(page, f"<td>{self.e5.matricule}</td>")


class PassageEtGardeFousTests(NumerosBase):
    def preparer_passage(self, classe_cycle):
        annee = AnneeScolaire.objects.create(
            etablissement=self.ecole, libelle="2027-2028", date_debut=datetime.date(2027, 10, 1), date_fin=datetime.date(2028, 7, 31),
        )
        return annee, Classe.objects.create(nom="Suite", cycle=classe_cycle, niveau="", annee_scolaire=annee)

    def test_un_passage_vers_un_autre_cycle_rappelle_de_saisir_les_nouveaux_numeros(self):
        annee, suite = self.preparer_passage(Cycle.DEUXIEME_CYCLE)
        self.client.force_login(self.fondateur)
        reponse = self.client.post(
            reverse("scolarite:passage_de_classe", args=[self.c6a.pk]), {"annee_destination": annee.pk, "classe_admis": suite.pk}, follow=True,
        )
        self.assertContains(reponse, "changent de cycle")
        self.assertContains(reponse, "Numéros du cycle")

    def test_un_passage_dans_le_meme_cycle_ne_rappelle_rien(self):
        annee, suite = self.preparer_passage(Cycle.PREMIER_CYCLE)
        self.client.force_login(self.fondateur)
        reponse = self.client.post(
            reverse("scolarite:passage_de_classe", args=[self.c6a.pk]), {"annee_destination": annee.pk, "classe_admis": suite.pk}, follow=True,
        )
        self.assertNotContains(reponse, "changent de cycle")

    def test_le_passage_affiche_le_numero_du_cycle_de_la_classe_de_depart(self):
        NumeroCycle.objects.create(eleve=self.e5, cycle=Cycle.DEUXIEME_CYCLE, numero="DEF-0001")
        annee, _ = self.preparer_passage(Cycle.LYCEE)
        self.client.force_login(self.fondateur)
        page = self.client.get(reverse("scolarite:passage_de_classe", args=[self.c9a.pk]), {"annee_destination": annee.pk})
        self.assertContains(page, "(DEF-0001)")

    def test_un_matricule_genere_ne_reprend_jamais_un_numero_de_cycle(self):
        annee = datetime.date.today().year
        NumeroCycle.objects.create(eleve=self.e5, cycle=Cycle.DEUXIEME_CYCLE, numero=f"{annee}12345")
        with mock.patch("comptes.models.random.randint", side_effect=[12345, 54321]):
            self.assertEqual(generer_matricule(), f"{annee}54321")

    def test_un_matricule_saisi_a_l_inscription_ne_reprend_pas_un_numero_de_cycle(self):
        NumeroCycle.objects.create(eleve=self.e5, cycle=Cycle.DEUXIEME_CYCLE, numero="DEF-0001")
        donnees = {
            "prenom": "Nouvelle", "nom": "Eleve", "sexe": "F", "date_naissance": "2016-05-20", "matricule": "def-0001",
            "classe": self.c9a.pk, "parent_email_1": "parent@stat.test",
        }
        formulaire = InscrireEleveForm(donnees, classes_disponibles=Classe.objects.all(), etablissement=self.ecole)
        self.assertFalse(formulaire.is_valid())  # DEF-0001 est le numéro d'un élève du 2ème cycle, et la classe choisie est du 2ème cycle
        self.assertIn("matricule", formulaire.errors)
        donnees["classe"] = self.c6a.pk  # classe du 1er cycle : le numéro d'un autre cycle ne concerne pas la personne qui inscrit
        formulaire = InscrireEleveForm(donnees, classes_disponibles=Classe.objects.all(), etablissement=self.ecole)
        self.assertTrue(formulaire.is_valid(), formulaire.errors)
        donnees.update({"matricule": "DEF-0002", "classe": self.c9a.pk})
        formulaire = InscrireEleveForm(donnees, classes_disponibles=Classe.objects.all(), etablissement=self.ecole)
        self.assertTrue(formulaire.is_valid(), formulaire.errors)

    def test_l_anonymisation_efface_aussi_les_numeros_de_cycle(self):
        from espace_developpeur.retrait_eleve import anonymiser_eleve

        NumeroCycle.objects.create(eleve=self.e5, cycle=Cycle.DEUXIEME_CYCLE, numero="DEF-0001")
        NumeroCycle.objects.create(eleve=self.e6, cycle=Cycle.DEUXIEME_CYCLE, numero="DEF-0002")
        anonymiser_eleve(self.e5)
        self.assertFalse(NumeroCycle.objects.filter(eleve=self.e5).exists())
        self.assertTrue(NumeroCycle.objects.filter(eleve=self.e6).exists())

    def test_la_page_est_en_arabe_pur(self):
        NumeroCycle.objects.create(eleve=self.e5, cycle=Cycle.DEUXIEME_CYCLE, numero="DEF-0001")
        client = client_en(self.secretaire, "ar")
        page = client.get(self.url())
        self.assertEqual(page.status_code, 200)
        saisis = {"DEF-0001", self.e5.matricule, self.e6.matricule, "9A", self.ecole.nom, "2026-2027", "Français"}  # « Français » : le bouton de langue
        self.assertEqual(restes_hors_textes_saisis(page.content.decode(), saisis), [])
        reponse = client.post(self.url(), {f"numero_{self.e5.pk}": "=1+1"}, follow=True)
        self.assertEqual(restes_hors_textes_saisis(reponse.content.decode(), saisis | {"=1+1"}), [])
