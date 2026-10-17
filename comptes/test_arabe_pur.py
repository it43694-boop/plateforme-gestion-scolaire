"""
« Arabe pur » : en arabe, les pages essentielles ne contiennent ni lettre latine ni chiffre occidental, hors les rares exceptions écrites ici
(le bouton « Français » qui ramène à l'autre langue, les identifiants et codes qui se recopient).
"""
import re

from django.test import Client
from django.urls import reverse

from comptes.arabisation import invalider
from comptes.langues import NOM_COOKIE_LANGUE
from comptes.models import Utilisateur
from comptes.roles import Role
from comptes.traduction import restes_latins
from pedagogie.models import Affectation
from scolarite.models import Inscription
from statistiques.test_education import EducationBase, creer_compte

NOMS = [
    "Aminata Traoré", "Moussa Konaté", "Fatoumata Diarra", "Ibrahima Coulibaly", "Mariam Keïta", "Seydou Sissoko", "Awa Doumbia", "Bakary Camara",
    "Kadidia Sangaré", "Oumar Diallo", "Hawa Maïga", "Sékou Touré", "Salimata Cissé", "Modibo Bagayoko", "Nana Haïdara", "Drissa Berthé",
]
AUTORISES = {"Français"}  # le bouton de langue s'écrit dans la langue vers laquelle il bascule
# L'écran « Noms en arabe » montre volontairement le nom d'origine (en lettres latines) à côté du champ arabe, pour que l'on sache de qui il s'agit.
NOMS_DE_REFERENCE = {"comptes:noms_en_arabe": set(NOMS)}
CODE_D_ECOLE = re.compile(r"[A-Z]{2}-(?:[A-Z]{3}-)?[٠-٩0-9]+")  # code officiel de l'établissement : un identifiant qui se recopie


class ArabePurTests(EducationBase):
    def setUp(self):
        self.fondateur = creer_compte(Role.FONDATEUR, "fondateur@pur.test", self.ecole)
        self.developpeur = creer_compte(Role.DEVELOPPEUR, "developpeur@pur.test", self.ecole)
        self.comptable_ar = creer_compte(Role.COMPTABLE, "comptable@pur.test", self.ecole)
        self.parent_ar = creer_compte(Role.PARENT, "parent@pur.test", self.ecole)
        self.e1.parents_lies.add(self.parent_ar)
        # Les comptes de test portent des noms de courriel en minuscules (« parent », « comptable ») : de vrais noms, comme à l'école.
        for rang, compte in enumerate(Utilisateur.objects.filter(etablissement=self.ecole).order_by("pk")):
            prenom, nom = NOMS[rang % len(NOMS)].split()
            Utilisateur.objects.filter(pk=compte.pk).update(prenom=prenom, nom=nom)
        Utilisateur.objects.filter(pk=self.e1.pk).update(prenom_ar="سلمى", nom_ar="كيتا")
        invalider(self.ecole.pk)

    def ouvrir(self, compte, adresse):
        client = Client()
        client.force_login(compte)
        client.cookies[NOM_COOKIE_LANGUE] = "ar"
        reponse = client.get(adresse, follow=True)
        self.assertEqual(reponse.status_code, 200, adresse)
        return reponse.content.decode("utf-8")

    def verifier(self, compte, adresses):
        manques = {}
        permis = {reverse(nom): noms for nom, noms in NOMS_DE_REFERENCE.items()}
        for adresse in adresses:
            for reste in restes_latins(self.ouvrir(compte, adresse)):
                if reste not in AUTORISES and reste not in permis.get(adresse, ()) and not CODE_D_ECOLE.fullmatch(reste):
                    manques.setdefault(reste, adresse)
        self.assertEqual(manques, {}, self.rapport(manques))

    @staticmethod
    def rapport(manques):
        lignes = [f"  {texte[:200]}    <- {page}" for texte, page in manques.items()]
        return "Textes restés en lettres latines ou chiffres occidentaux :" + chr(10) + chr(10).join(lignes)

    def test_pages_de_la_direction(self):
        c6a = self.c6a.pk
        self.verifier(self.fondateur, [
            reverse("comptes:redirection_tableau_de_bord"), reverse("comptes:liste_notifications"), reverse("comptes:changer_mot_de_passe"),
            reverse("comptes:noms_en_arabe"), reverse("comptes:comptes_en_attente"),
            reverse("scolarite:liste_eleves"), reverse("scolarite:inscrire_eleve"), reverse("scolarite:liste_classes"), reverse("scolarite:creer_classe"),
            reverse("scolarite:liste_matieres"), reverse("scolarite:importer_eleves"),
            reverse("finances:suivi_paiements"), reverse("finances:liste_paiements"), reverse("finances:registre_caisse"),
            reverse("finances:liste_salaires"), reverse("finances:liste_contrats"),
            reverse("communication:liste_annonces"), reverse("communication:publier_annonce"), reverse("communication:messages_a_envoyer"),
            reverse("bibliotheque:liste_documents"),
            reverse("statistiques:vue_ensemble"), reverse("statistiques:fiche_annuelle"),
            reverse("comptabilite:accueil"), reverse("comptabilite:journal"), reverse("comptabilite:balance"), reverse("comptabilite:plan_comptable"),
            reverse("comptabilite:exercices"), reverse("comptabilite:saisir_ecriture"),
            reverse("pedagogie:gerer_emploi_du_temps", args=[c6a]), reverse("pedagogie:suivi_des_cours"),
        ])

    def test_pages_du_developpeur(self):
        self.verifier(self.developpeur, [
            reverse("espace_developpeur:parametres_etablissement"), reverse("espace_developpeur:liste_comptes"),
            reverse("espace_developpeur:matrice_permissions"), reverse("espace_developpeur:annees_scolaires"),
            reverse("espace_developpeur:journal_audit"),
        ])

    def test_pages_publiques(self):
        client = Client()
        client.cookies[NOM_COOKIE_LANGUE] = "ar"
        manques = {}
        for adresse in ("/comptes/connexion/", "/comptes/inscription/", "/comptes/mot-de-passe-oublie/", "/conditions-d-utilisation/", "/confidentialite/", "/mentions-legales/"):
            reponse = client.get(adresse, follow=True)
            self.assertEqual(reponse.status_code, 200, adresse)
            for reste in restes_latins(reponse.content.decode("utf-8")):
                if reste not in AUTORISES and not CODE_D_ECOLE.fullmatch(reste):
                    manques.setdefault(reste, adresse)
        self.assertEqual(manques, {}, self.rapport(manques))

    def test_pages_d_un_parent_d_un_eleve_et_d_un_enseignant(self):
        affectation = Affectation.objects.filter(classe=self.c6a).first()
        pages = {self.parent_ar: [reverse("comptes:portail_parent"), reverse("finances:suivi_paiements"), reverse("communication:liste_conversations")]}
        if affectation:
            pages[affectation.enseignant] = [reverse("pedagogie:mes_classes"), reverse("pedagogie:saisir_note", args=[affectation.pk])]
        for compte, adresses in pages.items():
            self.verifier(compte, adresses)

    def test_le_dossier_et_le_bulletin_d_un_eleve(self):
        Inscription.objects.get_or_create(eleve=self.e1, classe=self.c6a, defaults={"statut": Inscription.Statut.EN_COURS})
        self.verifier(self.fondateur, [
            reverse("scolarite:dossier_eleve", args=[self.e1.matricule]), reverse("pedagogie:bulletin_eleve", args=[self.e1.matricule]),
            reverse("pedagogie:historique_absences", args=[self.e1.matricule]),
        ])
