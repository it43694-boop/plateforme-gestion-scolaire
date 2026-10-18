"""
Messages aux familles : liens WhatsApp et SMS prêts à envoyer (aucun envoi par le serveur).

Jeu de données de EducationBase (statistiques.test_education) : école A, classes 6A (e1 F, e2 M, e3 F), 6B (e4 M),
9A (e5 F, e6 M), TSE (e7, e8), CAP-E (e9) ; école B vide. On y ajoute des familles :
- p (« parent », 70999001) : parent de e1
- p2 (+22370999002) : parent de e1 et de e2
- p3 : parent de e4, SANS numéro
- p4 (123456789, 9 chiffres : ni local ni international) : parent de e5
- e3 n'a pas de parent mais son propre numéro 70999003 ; e6 n'a ni parent ni numéro
"""
import datetime
import re
from urllib.parse import quote

from django.test import TestCase
from django.urls import reverse

from comptes.models import JournalAudit, Utilisateur
from comptes.roles import Role
from finances.models import TypeTranche, enregistrer_paiement
from pedagogie.models import Absence
from scolarite.models import EcheancierFrais, Inscription
from statistiques.test_education import EducationBase, creer_compte

URL = "communication:messages_a_envoyer"
ECOLE_A = "École statistiques A"


class DiffusionBase(EducationBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.p2 = creer_compte(Role.PARENT, "p2@diff.test", cls.ecole, telephone="+22370999002")
        cls.p3 = creer_compte(Role.PARENT, "p3@diff.test", cls.ecole)
        cls.p4 = creer_compte(Role.PARENT, "p4@diff.test", cls.ecole, telephone="123456789")
        cls.e1.parents_lies.add(cls.p2)
        cls.e2.parents_lies.add(cls.p2)
        cls.e4.parents_lies.add(cls.p3)
        cls.e5.parents_lies.add(cls.p4)
        Utilisateur.objects.filter(pk=cls.e3.pk).update(telephone="70999003")

    def ouvrir(self, compte, **parametres):
        self.client.force_login(compte)
        return self.client.get(reverse(URL), parametres)

    def lignes(self, reponse):
        return reponse.context["resultat"]["lignes"]


class AccesTests(DiffusionBase):
    def test_types_proposes_selon_le_role(self):
        reponse = self.ouvrir(self.fondateur)
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual([code for code, _ in reponse.context["types"]], ["annonce", "convocation", "absence", "paiement"])
        reponse = self.ouvrir(self.comptable)  # la comptabilité ne relance que la scolarité
        self.assertEqual([code for code, _ in reponse.context["types"]], ["paiement"])
        types_dir = [code for code, _ in self.ouvrir(self.dir_1er).context["types"]]
        self.assertIn("annonce", types_dir)

    def test_roles_sans_droit_refuses(self):
        for compte in (self.t1, self.parent, self.p2, self.e1):
            self.client.force_login(compte)
            with self.subTest(role=compte.role):
                self.assertEqual(self.client.get(reverse(URL)).status_code, 403)
                self.assertEqual(self.client.get(reverse(URL), {"type": "annonce", "classe": "toutes"}).status_code, 403)

    def test_visiteur_anonyme_redirige(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse(URL)).status_code, 302)

    def test_le_proprietaire_sans_etablissement_n_y_accede_pas(self):
        proprietaire = creer_compte(Role.DEVELOPPEUR, "owner@diff.test", None, is_superuser=True)
        self.client.force_login(proprietaire)
        self.assertIn(self.client.get(reverse(URL)).status_code, (302, 403))

    def test_un_type_non_autorise_est_refuse_et_un_type_inconnu_est_introuvable(self):
        self.client.force_login(self.comptable)
        self.assertEqual(self.client.get(reverse(URL), {"type": "annonce", "classe": "toutes"}).status_code, 403)
        self.assertEqual(self.client.get(reverse(URL), {"type": "pirate", "classe": "toutes"}).status_code, 404)

    def test_menu_et_bouton_pour_les_roles_autorises_seulement(self):
        self.client.force_login(self.fondateur)
        page = self.client.get(reverse("communication:liste_annonces"))
        self.assertContains(page, reverse(URL), count=2)  # menu + bouton de la page
        self.client.force_login(self.comptable)
        self.assertContains(self.client.get(reverse("finances:suivi_paiements")), reverse(URL))
        for compte in (self.t1, self.parent):
            self.client.force_login(compte)
            self.assertNotContains(self.client.get(reverse("communication:liste_annonces")), reverse(URL))


class AnnonceTests(DiffusionBase):
    def test_une_ligne_par_numero_avec_les_liens(self):
        reponse = self.ouvrir(self.fondateur, type="annonce", classe=self.c6a.pk)
        self.assertEqual(reponse.status_code, 200)
        lignes = self.lignes(reponse)
        # p2 (parent de e1 et e2, une seule ligne), puis parent (e1), puis e3 qui a son propre numéro
        self.assertEqual([ligne["telephone"] for ligne in lignes], ["+22370999002", "70999001", "70999003"])
        self.assertEqual(lignes[0]["eleves"], [self.e1.nom_complet, self.e2.nom_complet])
        message = f"Bonjour, {ECOLE_A} vous informe : (à compléter)."
        self.assertEqual(lignes[0]["whatsapp"], f"https://wa.me/22370999002?text={quote(message)}")
        self.assertEqual(lignes[0]["sms"], f"sms:+22370999002?&body={quote(message, safe='')}")
        self.assertEqual(lignes[1]["whatsapp"], f"https://wa.me/22370999001?text={quote(message)}")  # numéro local complété
        self.assertTrue(lignes[2]["famille"].endswith("(élève)"))
        self.assertTrue(all(not ligne["a_verifier"] for ligne in lignes))

    def test_numero_douteux_et_famille_sans_numero(self):
        reponse = self.ouvrir(self.fondateur, type="annonce", classe=self.c9a.pk)
        lignes = self.lignes(reponse)
        self.assertEqual([(ligne["telephone"], ligne["a_verifier"]) for ligne in lignes], [("123456789", True)])
        self.assertEqual(reponse.context["resultat"]["sans_numero"], [f"{self.e6.nom_complet} (9A)"])
        self.assertContains(reponse, "à vérifier")
        self.assertContains(reponse, "Sans numéro utilisable")

    def test_le_message_d_une_annonce_ne_contient_aucun_nom_d_eleve(self):
        texte = "Réunion pour {eleve} ({prenom}) de la {classe} à {ecole}, le {date}."
        reponse = self.ouvrir(self.fondateur, type="annonce", classe=self.c6a.pk, texte=texte, date="2026-11-10")
        message = self.lignes(reponse)[0]["message"]
        self.assertEqual(message, f"Réunion pour votre enfant (votre enfant) de la 6A à {ECOLE_A}, le 10/11/2026.")
        for eleve in (self.e1, self.e2, self.e3):
            self.assertNotIn(eleve.prenom + " " + eleve.nom, message)

    def test_message_a_copier_dans_un_groupe_seulement_pour_une_classe_et_une_annonce(self):
        reponse = self.ouvrir(self.fondateur, type="annonce", classe=self.c6a.pk, texte="Fête de l'école {eleve} {classe}")
        self.assertEqual(reponse.context["message_groupe"], "Fête de l'école votre enfant 6A")
        self.assertContains(reponse, "Copier le message")
        reponse = self.ouvrir(self.fondateur, type="annonce", classe="toutes")
        self.assertEqual(reponse.context["message_groupe"], "")  # plusieurs classes : pas de groupe unique
        self.assertNotContains(reponse, "Copier le message")
        for type_, date in (("convocation", "2026-11-10"), ("absence", ""), ("paiement", "")):
            reponse = self.ouvrir(self.fondateur, type=type_, classe=self.c6a.pk, date=date)
            with self.subTest(type=type_):
                self.assertIsNotNone(reponse.context["resultat"])
                self.assertEqual(reponse.context["message_groupe"], "")
                self.assertNotContains(reponse, "Copier le message")


class MessagesIndividuelsTests(DiffusionBase):
    def test_convocation_une_ligne_par_parent_et_par_eleve(self):
        reponse = self.ouvrir(self.fondateur, type="convocation", classe=self.c6a.pk, date="2026-11-10")
        lignes = self.lignes(reponse)
        self.assertEqual(
            [(ligne["telephone"], ligne["eleves"]) for ligne in lignes],
            [("+22370999002", [self.e1.nom_complet]), ("70999001", [self.e1.nom_complet]),
             ("+22370999002", [self.e2.nom_complet]), ("70999003", [self.e3.nom_complet])],
        )
        self.assertEqual(
            lignes[0]["message"],
            f"Bonjour, {ECOLE_A} vous prie de passer à l'école au sujet de {self.e1.nom_complet} (6A) le 10/11/2026.",
        )

    def test_la_date_est_exigee_quand_le_message_en_contient_une(self):
        reponse = self.ouvrir(self.fondateur, type="convocation", classe=self.c6a.pk)
        self.assertContains(reponse, "Choisissez une date")
        self.assertIsNone(reponse.context["resultat"])

    def test_absences_du_jour_par_defaut(self):
        aujourdhui = datetime.date.today()
        Absence.objects.create(eleve=self.e2, classe=self.c6a, date_absence=aujourdhui)
        Absence.objects.create(eleve=self.e4, classe=self.c6b, date_absence=aujourdhui - datetime.timedelta(days=1))
        Absence.objects.create(eleve=self.e6, classe=self.c9a, date_absence=aujourdhui)  # e6 : aucun numéro
        reponse = self.ouvrir(self.fondateur, type="absence", classe="toutes")
        lignes = self.lignes(reponse)
        self.assertEqual([(ligne["telephone"], ligne["eleves"]) for ligne in lignes], [("+22370999002", [self.e2.nom_complet])])
        self.assertIn(aujourdhui.strftime("%d/%m/%Y"), lignes[0]["message"])
        self.assertEqual(reponse.context["resultat"]["sans_numero"], [f"{self.e6.nom_complet} (9A)"])
        # une autre date : l'absence de la veille (e4 : p3 n'a pas de numéro)
        reponse = self.ouvrir(self.fondateur, type="absence", classe="toutes", date=(aujourdhui - datetime.timedelta(days=1)).isoformat())
        self.assertEqual(self.lignes(reponse), [])
        self.assertEqual(reponse.context["resultat"]["sans_numero"], [f"{self.e4.nom_complet} (6B)"])

    def test_une_absence_ne_peut_pas_etre_dans_le_futur(self):
        demain = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        reponse = self.ouvrir(self.fondateur, type="absence", classe="toutes", date=demain)
        self.assertContains(reponse, "ne peut pas être dans le futur")
        self.assertIsNone(reponse.context["resultat"])

    def test_relance_de_scolarite_seulement_pour_les_soldes_non_regles(self):
        EcheancierFrais.objects.create(classe=self.c6a, montant_inscription=10000, montant_periode=5000, nombre_versements=3)
        for eleve, montant in ((self.e1, 25000), (self.e2, 5000)):
            enregistrer_paiement(
                eleve=eleve, inscription=self.i[f"e{eleve.nom[-1]}"], tranche=TypeTranche.VERSEMENT, montant=montant,
                mode_paiement="especes", enregistre_par=self.comptable,
            )
        reponse = self.ouvrir(self.comptable, type="paiement", classe="toutes")
        lignes = self.lignes(reponse)
        # e1 a tout payé : absent ; e2 doit 20 000 (parent p2) ; e3 doit 25 000 (son propre numéro)
        self.assertEqual([(ligne["telephone"], ligne["eleves"]) for ligne in lignes],
                         [("+22370999002", [self.e2.nom_complet]), ("70999003", [self.e3.nom_complet])])
        self.assertEqual(
            lignes[0]["message"],
            f"Bonjour, rappel de {ECOLE_A} : le solde de scolarité de {self.e2.nom_complet} (6A) est de 20 000 FCFA. "
            "Merci de régulariser.",
        )
        self.assertIn("25 000 FCFA", lignes[1]["message"])

    def test_les_classes_sans_echeancier_n_apparaissent_pas_dans_les_relances(self):
        self.assertEqual(self.lignes(self.ouvrir(self.comptable, type="paiement", classe="toutes")), [])


class CloisonnementTests(DiffusionBase):
    def test_le_directeur_de_cycle_ne_voit_que_son_cycle(self):
        reponse = self.ouvrir(self.dir_1er, type="annonce", classe="toutes")
        self.assertEqual({classe.nom for classe in reponse.context["classes"]}, {"6A", "6B"})
        telephones = {ligne["telephone"] for ligne in self.lignes(reponse)}
        self.assertEqual(telephones, {"+22370999002", "70999001", "70999003"})
        self.assertNotIn("123456789", telephones)  # famille de e5 (2ème cycle)
        self.assertEqual(self.client.get(reverse(URL), {"type": "annonce", "classe": self.c9a.pk}).status_code, 404)

    def test_une_classe_d_une_autre_ecole_ou_d_une_annee_passee_est_introuvable(self):
        self.client.force_login(self.fondateur)
        for classe in (self.classe_b, self.classe_5a):
            with self.subTest(classe=classe.pk):
                self.assertEqual(self.client.get(reverse(URL), {"type": "annonce", "classe": classe.pk}).status_code, 404)
        self.assertEqual(self.client.get(reverse(URL), {"type": "annonce", "classe": "999999"}).status_code, 404)

    def test_l_autre_ecole_ne_voit_aucune_famille_de_l_ecole_a(self):
        reponse = self.ouvrir(self.fondateur_b, type="annonce", classe="toutes")
        self.assertEqual({classe.nom for classe in reponse.context["classes"]}, {"6A"})  # sa propre classe 6A, vide
        self.assertEqual(self.lignes(reponse), [])
        self.assertNotContains(reponse, "70999001")
        self.assertEqual(self.client.get(reverse(URL), {"type": "annonce", "classe": self.c6a.pk}).status_code, 404)

    def test_parametres_invalides(self):
        self.client.force_login(self.fondateur)
        for parametres in ({"type": "annonce", "classe": "abc"}, {"type": "annonce", "classe": "toutes", "date": "2026-13-45"}):
            with self.subTest(parametres=parametres):
                self.assertEqual(self.client.get(reverse(URL), parametres).status_code, 404)


class SecuriteDuTexteTests(DiffusionBase):
    def test_un_texte_malicieux_n_est_jamais_interprete(self):
        texte = "{eleve.__class__} {0} {x} {% load %} {{ 7*7 }}"
        reponse = self.ouvrir(self.fondateur, type="annonce", classe=self.c6a.pk, texte=texte)
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(self.lignes(reponse)[0]["message"], texte)  # recopié tel quel, rien n'est évalué
        # Le jeton CSRF et le « nonce » de sécurité sont tirés au hasard à chaque affichage et contiennent « 49 » environ une fois sur vingt : on les retire.
        page = re.sub(r'nonce="[^"]*"|name="csrfmiddlewaretoken" value="[^"]*"', "", reponse.content.decode())
        self.assertNotIn("49", page)

    def test_un_message_trop_long_est_refuse(self):
        reponse = self.ouvrir(self.fondateur, type="annonce", classe=self.c6a.pk, texte="x" * 501)
        self.assertContains(reponse, "trop long")
        self.assertIsNone(reponse.context["resultat"])

    def test_classe_obligatoire(self):
        reponse = self.ouvrir(self.fondateur, type="annonce")
        self.assertContains(reponse, "Choisissez une classe")
        self.assertIsNone(reponse.context["resultat"])

    def test_la_page_ne_contient_aucun_style_en_ligne(self):
        page = self.ouvrir(self.fondateur, type="annonce", classe=self.c6a.pk)
        self.assertNotContains(page, ' style="')


class JournalEtPaginationTests(DiffusionBase):
    def test_la_preparation_est_notee_sans_numero_ni_nom(self):
        self.ouvrir(self.fondateur, type="convocation", classe=self.c6a.pk, date="2026-11-10")
        entree = JournalAudit.objects.get(action="preparation_messages_familles")
        self.assertEqual(entree.cible, "convocation")
        self.assertEqual(entree.details, {"classe": self.c6a.pk, "lignes": 4, "sans_numero": 0})
        texte = f"{entree.cible} {entree.details}"
        self.assertNotIn("7099", texte)
        self.assertNotIn(self.e1.nom, texte)

    def test_une_page_suivante_n_est_pas_notee_une_deuxieme_fois(self):
        self.ouvrir(self.fondateur, type="annonce", classe="toutes")
        self.ouvrir(self.fondateur, type="annonce", classe="toutes", page=2)
        self.assertEqual(JournalAudit.objects.filter(action="preparation_messages_familles").count(), 1)

    def test_pagination_conserve_les_criteres(self):
        from communication import views_diffusion
        ancien = views_diffusion.LIGNES_PAR_PAGE
        views_diffusion.LIGNES_PAR_PAGE = 2
        try:
            reponse = self.ouvrir(self.fondateur, type="annonce", classe=self.c6a.pk, texte="Bonjour")
        finally:
            views_diffusion.LIGNES_PAR_PAGE = ancien
        self.assertEqual(len(reponse.context["lignes"]), 2)
        self.assertContains(reponse, "Page 1 sur 2")
        self.assertContains(reponse, "&page=2")
        self.assertContains(reponse, "type=annonce")


class EnArabeTests(DiffusionBase):
    """Une page arabe propose un message en arabe, écrit avec des marqueurs arabes, avec les noms de l'école et de l'élève en arabe."""

    def en_arabe(self, **parametres):
        self.client.force_login(self.fondateur)
        self.client.cookies["nexora_langue"] = "ar"
        return self.client.get(reverse(URL), parametres)

    def test_le_message_propose_est_en_arabe(self):
        reponse = self.en_arabe(type="convocation", classe=self.c6a.pk, date="2026-10-20")
        self.assertIn("السلام عليكم", reponse.context["texte"])
        self.assertIn("{التلميذ}", reponse.context["texte"])

    def test_les_marqueurs_arabes_sont_remplaces_par_les_noms_en_arabe(self):
        Utilisateur.objects.filter(pk=self.e1.pk).update(prenom_ar="سلمى", nom_ar="كيتا")
        from comptes.arabisation import invalider
        invalider(self.ecole.pk)
        reponse = self.en_arabe(type="convocation", classe=self.c6a.pk, date="2026-10-20")
        messages = [ligne["message"] for ligne in self.lignes(reponse)]
        self.assertTrue(any("سلمى كيتا" in message for message in messages), messages)
        self.assertTrue(all("{" not in message for message in messages), messages)
        self.assertTrue(all("٢٠/١٠/٢٠٢٦" in message for message in messages), messages)  # date et chiffres en arabe

    def test_le_message_de_groupe_dit_votre_enfant_en_arabe(self):
        reponse = self.en_arabe(type="annonce", classe=self.c6a.pk)
        self.assertNotIn("votre enfant", reponse.context["message_groupe"])
        self.assertIn("السلام عليكم", reponse.context["message_groupe"])

    def test_en_francais_rien_ne_change(self):
        self.client.force_login(self.fondateur)
        reponse = self.client.get(reverse(URL), {"type": "annonce", "classe": self.c6a.pk})
        self.assertIn("Bonjour", reponse.context["texte"])

    def test_la_date_est_exigee_pour_le_marqueur_arabe_aussi(self):
        self.client.force_login(self.fondateur)
        self.client.cookies["nexora_langue"] = "ar"
        reponse = self.client.get(reverse(URL), {"type": "annonce", "classe": self.c6a.pk, "texte": "موعدنا يوم {التاريخ}"})
        self.assertIn("Choisissez une date", reponse.context["erreur"])
