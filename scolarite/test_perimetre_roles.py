"""Chacun ne voit que ce qui le concerne : classes, recherche d'élèves, annonces, tableau de bord, chiffres de l'assistant et affectation des enseignants, par rôle."""
import datetime

from django.test import override_settings
from django.urls import reverse

from assistant.views import construire_donnees_generales
from communication.models import Annonce, Portee
from comptes.roles import Role
from pedagogie.models import Absence
from permissions_matrix.models import PermissionMatrix
from permissions_matrix.modules import Module
from scolarite.models import Affectation, classes_visibles_pour
from statistiques.test_education import EducationBase


def noms(classes):
    return sorted(classe.nom for classe in classes)


class PerimetreBase(EducationBase):
    def accorder(self, role, *modules):
        """L'école coche ces modules pour ce rôle (la matrice de permissions est réglable par chaque école)."""
        for module in modules:
            PermissionMatrix.objects.update_or_create(
                etablissement=self.ecole, role=role.value, module=module.value, defaults={"autorise": True},
            )

    def absences(self):
        """e1 : 1 absence, e2 : 2 (classe 6A) ; e5 : 1 (classe 9A)."""
        for eleve, classe, nombre in ((self.e1, self.c6a, 1), (self.e2, self.c6a, 2), (self.e5, self.c9a, 1)):
            for jour in range(nombre):
                Absence.objects.create(eleve=eleve, classe=classe, date_absence=datetime.date(2026, 11, 2 + jour), enregistre_par=self.t1)

    def indicateurs(self, compte):
        self.client.force_login(compte)
        reponse = self.client.get(reverse("comptes:redirection_tableau_de_bord"))
        self.assertEqual(reponse.status_code, 200)
        return {ligne["label"]: ligne["valeur"] for ligne in reponse.context["indicateurs"]}, reponse


class ClassesVisiblesTests(PerimetreBase):
    def test_un_enseignant_ne_voit_que_les_classes_ou_il_est_affecte(self):
        self.assertEqual(noms(classes_visibles_pour(self.t1)), ["6A"])
        self.assertEqual(noms(classes_visibles_pour(self.t2)), ["6B", "9A"])
        self.assertEqual(noms(classes_visibles_pour(self.t3)), ["TSE"])
        self.assertEqual(noms(classes_visibles_pour(self.t_ancien)), ["5A"])  # sa classe de l'année précédente

    def test_un_parent_ne_voit_que_les_classes_de_ses_enfants(self):
        self.assertEqual(noms(classes_visibles_pour(self.parent)), ["5A", "6A"])  # e1 : 6A cette année, 5A l'année précédente

    def test_un_eleve_ne_voit_que_ses_propres_classes(self):
        self.assertEqual(noms(classes_visibles_pour(self.e1)), ["5A", "6A"])
        self.assertEqual(noms(classes_visibles_pour(self.e4)), ["6B"])
        self.assertEqual(noms(classes_visibles_pour(self.e9)), ["CAP-E"])

    def test_les_directeurs_de_cycle_gardent_leur_cycle_et_l_administration_toute_l_ecole(self):
        self.assertEqual(noms(classes_visibles_pour(self.dir_1er)), ["5A", "6A", "6B"])
        self.assertEqual(noms(classes_visibles_pour(self.censeur)), ["TSE"])
        toutes = ["5A", "6A", "6B", "9A", "CAP-E", "TSE"]
        for compte in (self.fondateur, self.secretaire, self.comptable):
            self.assertEqual(noms(classes_visibles_pour(compte)), toutes, compte.role)

    def test_jamais_une_classe_d_une_autre_ecole(self):
        self.assertEqual(noms(classes_visibles_pour(self.fondateur_b)), ["6A"])  # la 6A de l'école B, pas celle de l'école A
        self.assertNotIn(self.classe_b.pk, classes_visibles_pour(self.fondateur).values_list("pk", flat=True))


class RechercheDesEleveTests(PerimetreBase):
    """Quelqu'un qui tape un nom ne trouve que les élèves qui le concernent : ses classes, ses enfants, lui-même."""

    def trouves(self, compte, adresse):
        self.client.force_login(compte)
        page = self.client.get(adresse)
        self.assertEqual(page.status_code, 200)
        return page.content.decode()

    def test_la_recherche_d_un_enseignant_ne_montre_que_les_eleves_de_ses_classes(self):
        self.accorder(Role.ENSEIGNANT, Module.ELEVES)
        page = self.trouves(self.t1, reverse("scolarite:recherche_globale") + "?q=eleve")
        for present in ("eleve1", "eleve2", "eleve3"):
            self.assertIn(present, page)
        for absent in ("eleve4", "eleve5", "eleve6", "eleve7", "eleve8", "eleve9"):
            self.assertNotIn(absent, page)
        page = self.trouves(self.t2, reverse("scolarite:recherche_globale") + "?q=eleve")
        self.assertTrue(all(nom in page for nom in ("eleve4", "eleve5", "eleve6")))
        self.assertTrue(all(nom not in page for nom in ("eleve1", "eleve2", "eleve3", "eleve7", "eleve9")))

    def test_la_liste_des_eleves_d_un_enseignant_ne_propose_que_ses_classes(self):
        self.accorder(Role.ENSEIGNANT, Module.ELEVES)
        self.client.force_login(self.t1)
        page = self.client.get(reverse("scolarite:liste_eleves"))
        self.assertEqual(noms(page.context["classes"]), ["6A"])
        self.assertEqual({i.eleve.pk for i in page.context["page_obj"]}, {self.e1.pk, self.e2.pk, self.e3.pk})

    def test_la_recherche_en_direct_de_l_assistant_ne_propose_que_les_eleves_de_ses_classes(self):
        self.client.force_login(self.t1)
        reponse = self.client.get(reverse("assistant:rechercher_eleve_json") + "?q=eleve")
        matricules = {resultat["matricule"] for resultat in reponse.json()["resultats"]}
        self.assertEqual(matricules, {self.e1.matricule, self.e2.matricule, self.e3.matricule})

    def test_un_parent_ne_trouve_que_ses_enfants_et_ne_voit_que_leurs_classes(self):
        page = self.trouves(self.parent, reverse("scolarite:recherche_globale") + "?q=eleve")
        self.assertIn("eleve1", page)
        for absent in ("eleve2", "eleve3", "eleve4", "eleve9"):
            self.assertNotIn(absent, page)
        self.client.force_login(self.parent)
        liste = self.client.get(reverse("scolarite:liste_eleves"))
        self.assertEqual(noms(liste.context["classes"]), ["5A", "6A"])  # pas toutes les classes de l'école

    def test_un_eleve_ne_se_trouve_que_lui_meme_et_ne_voit_que_ses_classes(self):
        page = self.trouves(self.e1, reverse("scolarite:recherche_globale") + "?q=eleve")
        self.assertIn("eleve1", page)
        for absent in ("eleve2", "eleve3", "eleve4"):
            self.assertNotIn(absent, page)
        self.client.force_login(self.e1)
        self.assertEqual(noms(self.client.get(reverse("scolarite:liste_eleves")).context["classes"]), ["5A", "6A"])


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", EMAIL_ASYNC=False)
class AnnoncesParRoleTests(PerimetreBase):
    def setUp(self):
        self.toute = Annonce.objects.create(titre="Annonce pour toute l'ecole", contenu="c", portee=Portee.TOUTE_ECOLE, auteur=self.fondateur, etablissement=self.ecole)
        self.pour = {}
        for nom, classe in (("6A", self.c6a), ("6B", self.c6b), ("9A", self.c9a)):
            self.pour[nom] = Annonce.objects.create(
                titre=f"Annonce de la classe {nom}", contenu="c", portee=Portee.MA_CLASSE, classe_ciblee=classe, auteur=self.secretaire, etablissement=self.ecole,
            )

    def titres_vus(self, compte):
        self.client.force_login(compte)
        page = self.client.get(reverse("communication:liste_annonces"))
        self.assertEqual(page.status_code, 200)
        return {annonce.titre for annonce in page.context["annonces"]}

    def test_un_enseignant_ne_lit_que_les_annonces_de_toute_l_ecole_et_de_ses_classes(self):
        self.assertEqual(self.titres_vus(self.t1), {self.toute.titre, self.pour["6A"].titre})
        self.assertEqual(self.titres_vus(self.t2), {self.toute.titre, self.pour["6B"].titre, self.pour["9A"].titre})
        self.assertEqual(self.titres_vus(self.t3), {self.toute.titre})  # classe TSE : aucune annonce

    def test_un_enseignant_lit_aussi_les_annonces_qu_il_a_publiees(self):
        ancienne = Annonce.objects.create(titre="Mon annonce", contenu="c", portee=Portee.MA_CLASSE, classe_ciblee=self.c6a, auteur=self.t2, etablissement=self.ecole)
        self.assertIn(ancienne.titre, self.titres_vus(self.t2))  # il l'a écrite, même s'il n'enseigne plus dans cette classe

    def test_un_parent_et_un_eleve_ne_lisent_que_celles_de_leur_classe(self):
        self.assertEqual(self.titres_vus(self.parent), {self.toute.titre, self.pour["6A"].titre})
        self.assertEqual(self.titres_vus(self.e1), {self.toute.titre, self.pour["6A"].titre})
        self.assertEqual(self.titres_vus(self.e4), {self.toute.titre, self.pour["6B"].titre})

    def test_la_direction_de_cycle_lit_son_cycle_et_la_direction_generale_tout(self):
        self.assertEqual(self.titres_vus(self.dir_1er), {self.toute.titre, self.pour["6A"].titre, self.pour["6B"].titre})  # pas la 9A (2ème cycle)
        self.assertEqual(self.titres_vus(self.fondateur), {self.toute.titre, *(annonce.titre for annonce in self.pour.values())})
        self.assertEqual(self.titres_vus(self.secretaire), {self.toute.titre, *(annonce.titre for annonce in self.pour.values())})

    def test_un_enseignant_ne_peut_cibler_que_ses_propres_classes(self):
        self.client.force_login(self.t1)
        page = self.client.get(reverse("communication:publier_annonce"))
        self.assertEqual(noms(page.context["formulaire"].fields["classe_ciblee"].queryset), ["6A"])
        envoi = {"titre": "Intrus", "contenu": "Bonjour", "portee": Portee.MA_CLASSE.value}
        refus = self.client.post(reverse("communication:publier_annonce"), {**envoi, "classe_ciblee": self.c6b.pk})
        self.assertEqual(refus.status_code, 200)  # le formulaire est refusé : cette classe n'est pas la sienne
        self.assertFalse(Annonce.objects.filter(titre="Intrus").exists())
        accepte = self.client.post(reverse("communication:publier_annonce"), {**envoi, "titre": "Pour ma classe", "classe_ciblee": self.c6a.pk})
        self.assertEqual(accepte.status_code, 302)
        self.assertTrue(Annonce.objects.filter(titre="Pour ma classe", classe_ciblee=self.c6a).exists())

    def test_le_chiffre_des_annonces_de_l_assistant_suit_la_meme_regle(self):
        valeurs = {item["cle"]: item["valeur"] for item in construire_donnees_generales(self.t1)}
        self.assertEqual(valeurs["annonces_publiees"], 2)  # toute l'école et la 6A
        valeurs = {item["cle"]: item["valeur"] for item in construire_donnees_generales(self.fondateur)}
        self.assertEqual(valeurs["annonces_publiees"], 4)


class TableauDeBordParRoleTests(PerimetreBase):
    def setUp(self):
        self.absences()

    def test_un_enseignant_ne_voit_que_les_chiffres_de_ses_classes(self):
        self.accorder(Role.ENSEIGNANT, Module.ELEVES)
        chiffres, _ = self.indicateurs(self.t1)
        self.assertEqual(chiffres["Élèves inscrits"], 3)  # e1, e2, e3 : la 6A, pas les 9 élèves de l'école
        self.assertEqual(chiffres["Absences enregistrées"], 3)  # celles de la 6A
        chiffres, _ = self.indicateurs(self.t2)
        self.assertEqual((chiffres["Élèves inscrits"], chiffres["Absences enregistrées"]), (3, 1))  # 6B : e4 ; 9A : e5, e6

    def test_un_eleve_ne_voit_que_ses_propres_absences_et_aucun_effectif(self):
        chiffres, reponse = self.indicateurs(self.e1)
        self.assertNotIn("Élèves inscrits", chiffres)
        self.assertNotIn("Classes actives", chiffres)
        self.assertEqual(chiffres["Absences enregistrées"], 1)  # les siennes, pas celles de ses camarades ni de l'école
        self.assertNotIn("effectifs", reponse.context["graphiques"])
        chiffres, _ = self.indicateurs(self.e2)
        self.assertEqual(chiffres["Absences enregistrées"], 2)

    def test_la_direction_garde_les_chiffres_de_toute_l_ecole(self):
        chiffres, _ = self.indicateurs(self.fondateur)
        self.assertEqual((chiffres["Élèves inscrits"], chiffres["Absences enregistrées"]), (9, 4))

    def test_le_directeur_de_cycle_garde_ceux_de_son_cycle(self):
        chiffres, _ = self.indicateurs(self.dir_1er)
        self.assertEqual((chiffres["Élèves inscrits"], chiffres["Absences enregistrées"]), (4, 3))

    def test_les_encaissements_de_l_ecole_ne_sont_montres_ni_a_un_enseignant_ni_a_un_eleve_meme_avec_le_module(self):
        self.accorder(Role.ENSEIGNANT, Module.FINANCES)
        self.accorder(Role.ELEVE, Module.FINANCES)
        for compte in (self.t1, self.e1):
            chiffres, reponse = self.indicateurs(compte)
            self.assertNotIn("Encaissements", chiffres, compte.role)
            self.assertNotIn("encaissements", reponse.context["graphiques"], compte.role)
        chiffres, reponse = self.indicateurs(self.comptable)
        self.assertIn("Encaissements", chiffres)
        self.assertIn("encaissements", reponse.context["graphiques"])


class ChiffresDeLAssistantTests(PerimetreBase):
    def setUp(self):
        self.absences()

    def donnees(self, compte):
        return {item["cle"]: item["valeur"] for item in construire_donnees_generales(compte)}

    def test_un_enseignant_n_a_que_les_chiffres_de_ses_classes(self):
        self.accorder(Role.ENSEIGNANT, Module.ELEVES, Module.ENSEIGNANTS, Module.CLASSES)
        valeurs = self.donnees(self.t1)
        self.assertEqual((valeurs["eleves_inscrits"], valeurs["classes_actives"], valeurs["enseignants"], valeurs["absences_enregistrees"]), (3, 1, 1, 3))

    def test_un_eleve_ou_un_parent_n_a_aucun_chiffre_de_l_ecole(self):
        for role in (Role.ELEVE, Role.PARENT):
            self.accorder(role, Module.ELEVES, Module.ENSEIGNANTS, Module.CLASSES, Module.CAISSE, Module.SALAIRES, Module.FINANCES)
        for compte, absences in ((self.e1, 1), (self.parent, 1)):
            valeurs = self.donnees(compte)
            self.assertEqual(valeurs["absences_enregistrees"], absences, compte.role)  # les siennes, celles de son enfant
            for interdit in ("eleves_inscrits", "classes_actives", "enseignants", "solde_caisse", "salaires_en_attente", "total_encaissements"):
                self.assertNotIn(interdit, valeurs, f"{compte.role} : {interdit}")

    def test_un_directeur_de_cycle_ne_compte_que_les_enseignants_de_son_cycle(self):
        valeurs = self.donnees(self.dir_1er)
        self.assertEqual(valeurs["enseignants"], 3)  # t1 (6A), t2 (6B) et l'ancien (5A) : pas t3, qui n'enseigne qu'au lycée
        self.assertEqual(self.donnees(self.fondateur)["enseignants"], 4)


class AffectationDesEnseignantsTests(PerimetreBase):
    def champs(self, compte):
        self.client.force_login(compte)
        page = self.client.get(reverse("scolarite:affecter_enseignant"))
        self.assertEqual(page.status_code, 200)
        formulaire = page.context["formulaire"]
        return sorted(e.email for e in formulaire.fields["enseignant"].queryset), noms(formulaire.fields["classe"].queryset)

    def test_un_enseignant_a_qui_l_ecole_donne_ce_module_ne_voit_que_ses_collegues_et_ses_classes(self):
        self.accorder(Role.ENSEIGNANT, Module.CLASSES)
        Affectation.objects.create(enseignant=self.t3, classe=self.c6b, matiere="Francais")  # t3 enseigne aussi en 6B, avec t2
        self.assertEqual(self.champs(self.t1), (["t1@stat.test"], ["6A"]))
        enseignants, classes = self.champs(self.t2)
        self.assertEqual((enseignants, classes), (["t2@stat.test", "t3@stat.test"], ["6B", "9A"]))  # pas t1, ni l'ancien

    def test_la_direction_voit_tous_les_enseignants_de_l_ecole(self):
        enseignants, classes = self.champs(self.fondateur)
        self.assertEqual(enseignants, ["t1@stat.test", "t2@stat.test", "t3@stat.test", "tancien@stat.test"])
        self.assertEqual(len(classes), 6)

    def test_un_parent_n_a_aucun_enseignant_a_affecter(self):
        self.accorder(Role.PARENT, Module.CLASSES)
        enseignants, classes = self.champs(self.parent)
        self.assertEqual(enseignants, [])
        self.assertEqual(classes, ["5A", "6A"])
