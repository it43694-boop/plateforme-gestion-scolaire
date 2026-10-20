"""Paiement Mobile Money déclaré par un parent : déclaration, doublons, droits, validation par la comptabilité (reçu, caisse, notification), refus avec motif, arabe pur."""
import datetime

from django.core import mail
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from comptes.arabisation import invalider
from comptes.models import JournalAudit, Notification
from comptes.outils_test_arabe import client_en, restes_hors_textes_saisis
from comptes.roles import Role
from finances.declarations import declarer, inscription_en_cours
from finances.models import MouvementCaisse, Paiement, PaiementDeclare, StatutDeclaration, normaliser_reference_transaction
from permissions_matrix.models import PermissionMatrix
from scolarite.test_dossier_complet import StockageTemporaire, image_octets
from statistiques.test_education import creer_compte


def aujourd_hui():
    return timezone.localdate()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", EMAIL_ASYNC=False)
class DeclarationBase(StockageTemporaire):
    def setUp(self):
        cache.clear()  # la limite de déclarations par heure se compte dans le cache
        self.addCleanup(cache.clear)
        self.parent.email = "parent-declare@example.com"
        self.parent.save(update_fields=["email"])
        self.adresse = reverse("finances:declarer_paiement")
        self.liste = reverse("finances:declarations")

    def donnees(self, **autres):
        base = {
            "eleve": self.e1.pk, "operateur": "orange_money", "montant": "5000", "reference_transaction": "MP261019AB12",
            "date_du_paiement": aujourd_hui().isoformat(), "telephone_payeur": "70999001",
        }
        base.update(autres)
        return base

    def declarer(self, compte=None, **autres):
        self.client.force_login(compte or self.parent)
        return self.client.post(self.adresse, self.donnees(**autres))

    def creer(self, **autres):
        valeurs = dict(parent=self.parent, eleve=self.e1, montant=5000, operateur="orange_money", reference="MP261019AB12", date_du_paiement=aujourd_hui())
        valeurs.update(autres)
        return declarer(**valeurs)

    def autre_parent(self):
        autre = creer_compte(Role.PARENT, "parent-e4@stat.test", self.ecole, telephone="70999002")
        self.e4.parents_lies.add(autre)
        return autre


class DeclarerUnPaiementTests(DeclarationBase):
    def test_la_page_du_parent(self):
        self.ecole.instructions_mobile_money = "Orange Money : 70 11 22 33 (Ecole Test)"
        self.ecole.save()
        self.client.force_login(self.parent)
        page = self.client.get(self.adresse)
        self.assertEqual(page.status_code, 200)
        for attendu in ("Déclarer un paiement Mobile Money", "Orange Money : 70 11 22 33", "Comment payer", self.e1.nom_complet, "Envoyer la déclaration", "Mes déclarations"):
            self.assertContains(page, attendu)
        self.assertNotContains(page, self.e4.nom_complet)  # pas l'enfant d'un autre parent

    def test_declarer_enregistre_la_declaration_sans_rien_mettre_en_caisse(self):
        reponse = self.declarer(reference_transaction="mp 26-1019.ab12")
        self.assertRedirects(reponse, self.adresse, fetch_redirect_response=False)
        declaration = PaiementDeclare.objects.get()
        self.assertEqual((declaration.eleve, declaration.declare_par, declaration.montant, declaration.statut), (self.e1, self.parent, 5000, StatutDeclaration.EN_ATTENTE))
        self.assertEqual(declaration.reference_transaction, "MP261019AB12")  # espaces, points et tirets retirés
        self.assertEqual(declaration.inscription, inscription_en_cours(self.e1))
        self.assertEqual(declaration.etablissement, self.ecole)
        self.assertFalse(Paiement.objects.exists())
        self.assertFalse(MouvementCaisse.objects.exists())
        journal = JournalAudit.objects.get(action="declaration_paiement", acteur=self.parent)
        self.assertEqual(journal.details["montant"], 5000)

    def test_la_comptabilite_est_prevenue(self):
        self.declarer()
        notification = Notification.objects.get(destinataire=self.comptable)
        self.assertEqual(notification.titre, "Paiement à valider")
        self.assertIn("5000", notification.message)
        self.assertIn("MP261019AB12", notification.message)
        self.assertEqual(notification.url, self.liste)
        self.assertFalse(Notification.objects.filter(destinataire=self.secretaire).exists())

    def test_sans_comptable_la_direction_est_prevenue(self):
        self.comptable.is_active = False
        self.comptable.save(update_fields=["is_active"])
        self.declarer()
        self.assertTrue(Notification.objects.filter(destinataire=self.fondateur, titre="Paiement à valider").exists())

    def test_un_numero_de_transaction_ne_se_declare_qu_une_fois(self):
        self.declarer()
        reponse = self.declarer(reference_transaction="mp261019 ab12")  # le même, écrit autrement
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Ce numéro de transaction a déjà été déclaré.")
        self.assertEqual(PaiementDeclare.objects.count(), 1)
        self.assertEqual(self.declarer(operateur="moov_money").status_code, 302)  # un autre opérateur : une autre transaction
        self.assertEqual(PaiementDeclare.objects.count(), 2)

    def test_une_declaration_refusee_peut_etre_refaite(self):
        premiere = self.creer()
        PaiementDeclare.objects.filter(pk=premiere.pk).update(statut=StatutDeclaration.REFUSE, motif_refus="Introuvable")
        self.assertEqual(self.declarer().status_code, 302)
        self.assertEqual(PaiementDeclare.objects.count(), 2)

    def test_la_contrainte_de_la_base_refuse_deux_declarations_valables_du_meme_numero(self):
        self.creer()
        with self.assertRaises((IntegrityError, ValidationError)), transaction.atomic():
            PaiementDeclare.objects.bulk_create([PaiementDeclare(
                etablissement=self.ecole, eleve=self.e1, inscription=inscription_en_cours(self.e1), declare_par=self.parent, montant=1, operateur="orange_money",
                reference_transaction="MP261019AB12", date_du_paiement=aujourd_hui(),
            )])

    def test_les_donnees_invalides_sont_refusees(self):
        self.client.force_login(self.parent)
        demain = (aujourd_hui() + datetime.timedelta(days=1)).isoformat()
        trop_ancienne = (aujourd_hui() - datetime.timedelta(days=400)).isoformat()
        for libelle, donnees in (
            ("montant nul", {"montant": "0"}), ("montant négatif", {"montant": "-5"}), ("montant énorme", {"montant": "100000001"}), ("montant en lettres", {"montant": "cinq"}),
            ("numéro trop court", {"reference_transaction": "AB1"}), ("numéro vide", {"reference_transaction": ""}), ("date future", {"date_du_paiement": demain}),
            ("date trop ancienne", {"date_du_paiement": trop_ancienne}), ("opérateur inconnu", {"operateur": "western_union"}), ("enfant inconnu", {"eleve": 99999999}),
        ):
            with self.subTest(libelle):
                self.assertEqual(self.client.post(self.adresse, self.donnees(**donnees)).status_code, 200)
        self.assertFalse(PaiementDeclare.objects.exists())

    def test_un_parent_ne_declare_que_pour_ses_propres_enfants(self):
        reponse = self.declarer(eleve=self.e4.pk)  # e4 n'est pas son enfant
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(PaiementDeclare.objects.exists())
        with self.assertRaises(PermissionDenied):
            self.creer(eleve=self.e4)
        autre = self.autre_parent()
        self.assertEqual(self.declarer(compte=autre, eleve=self.e1.pk).status_code, 200)  # ni l'enfant d'un autre parent
        self.assertEqual(self.declarer(compte=autre, eleve=self.e4.pk).status_code, 302)
        self.assertEqual(PaiementDeclare.objects.get().eleve, self.e4)

    def test_un_enfant_sans_inscription_en_cours_n_est_pas_propose(self):
        from scolarite.models import Inscription

        Inscription.objects.filter(eleve=self.e1).update(statut=Inscription.Statut.ABANDON)
        self.client.force_login(self.parent)
        page = self.client.get(self.adresse)
        self.assertContains(page, "Aucun de vos enfants n")
        self.assertEqual(self.declarer().status_code, 200)
        self.assertFalse(PaiementDeclare.objects.exists())

    def test_seul_un_parent_declare(self):
        for compte in (self.comptable, self.fondateur, self.secretaire, self.t1, self.e1):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertEqual(self.client.get(self.adresse).status_code, 403)
                self.assertEqual(self.client.post(self.adresse, self.donnees()).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.adresse).status_code, 302)
        self.assertFalse(PaiementDeclare.objects.exists())

    def test_vingt_declarations_par_heure_au_plus(self):
        for numero in range(20):
            self.assertEqual(self.declarer(reference_transaction=f"MP2610190000{numero:02d}").status_code, 302)
        reponse = self.declarer(reference_transaction="MP26101900099")
        self.assertContains(reponse, "Trop de déclarations en peu de temps")
        self.assertEqual(PaiementDeclare.objects.count(), 20)

    def test_la_capture_d_ecran_est_facultative_et_controlee(self):
        self.client.force_login(self.parent)
        png = SimpleUploadedFile("capture.png", image_octets((300, 200), format="PNG"), content_type="image/png")
        self.assertEqual(self.client.post(self.adresse, self.donnees(capture=png)).status_code, 302)
        self.assertTrue(PaiementDeclare.objects.get().capture)
        faux = SimpleUploadedFile("capture.png", b"ceci n'est pas une image", content_type="image/png")
        lourde = SimpleUploadedFile("lourde.png", image_octets((300, 200), format="PNG") + b"0" * (2 * 1024 * 1024 + 10), content_type="image/png")
        for fichier in (faux, lourde):
            self.assertEqual(self.client.post(self.adresse, self.donnees(reference_transaction="MP26101900777", capture=fichier)).status_code, 200)
        self.assertEqual(PaiementDeclare.objects.count(), 1)

    def test_le_parent_suit_l_etat_de_ses_declarations_et_pas_celles_des_autres(self):
        validee, refusee = self.creer(reference="VALIDE000001"), self.creer(reference="REFUSE000001")
        PaiementDeclare.objects.filter(pk=refusee.pk).update(statut=StatutDeclaration.REFUSE, motif_refus="Transaction introuvable")
        PaiementDeclare.objects.filter(pk=validee.pk).update(statut=StatutDeclaration.VALIDE)
        autre = self.autre_parent()
        declarer(parent=autre, eleve=self.e4, montant=100, operateur="moov_money", reference="AUTRE0000001", date_du_paiement=aujourd_hui())
        self.client.force_login(self.parent)
        page = self.client.get(self.adresse)
        for attendu in ("VALIDE000001", "REFUSE000001", "Transaction introuvable", "Refusé", "Validé"):
            self.assertContains(page, attendu)
        self.assertNotContains(page, "AUTRE0000001")

    def test_normaliser_la_reference(self):
        self.assertEqual(normaliser_reference_transaction(" mp-26.10 19 ab12 "), "MP261019AB12")
        self.assertEqual(normaliser_reference_transaction(None), "")


class LaComptabiliteTraiteTests(DeclarationBase):
    def valider(self, declaration, compte=None, **autres):
        self.client.force_login(compte or self.comptable)
        donnees = {"declaration": declaration.pk, "matricule_eleve": declaration.eleve.matricule, "tranche": "versement", "montant": str(declaration.montant), "mode_paiement": "mobile_money"}
        donnees.update(autres)
        return self.client.post(reverse("finances:enregistrer_paiement"), donnees)

    def test_la_liste_montre_ce_qui_est_a_valider(self):
        declaration = self.creer()
        self.client.force_login(self.comptable)
        page = self.client.get(self.liste)
        self.assertEqual(page.status_code, 200)
        for attendu in ("Paiements déclarés par les parents", "À valider (1)", self.e1.nom_complet, "MP261019AB12", "Orange Money", "Valider", "Refuser"):
            self.assertContains(page, attendu)
        self.assertContains(page, f"{reverse('finances:enregistrer_paiement')}?declaration={declaration.pk}")
        PaiementDeclare.objects.filter(pk=declaration.pk).update(statut=StatutDeclaration.VALIDE)
        self.assertNotContains(self.client.get(self.liste), "MP261019AB12")  # plus dans « à valider »
        self.assertContains(self.client.get(self.liste + "?statut=tous"), "MP261019AB12")

    def test_seuls_la_comptabilite_et_la_direction_voient_les_declarations(self):
        self.creer()
        for compte in (self.fondateur, self.comptable):
            self.client.force_login(compte)
            self.assertEqual(self.client.get(self.liste).status_code, 200, compte.role)
        PermissionMatrix.objects.update_or_create(etablissement=self.ecole, role=Role.ENSEIGNANT.value, module="finances", defaults={"autorise": True})
        for compte in (self.parent, self.t1, self.secretaire, self.e1, self.dir_1er):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertIn(self.client.get(self.liste).status_code, (302, 403))

    def test_valider_enregistre_le_paiement_la_caisse_et_previent_le_parent(self):
        declaration = self.creer()
        self.client.force_login(self.comptable)
        page = self.client.get(f"{reverse('finances:enregistrer_paiement')}?declaration={declaration.pk}")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Paiement déclaré par un parent")
        self.assertContains(page, "MP261019AB12")
        self.assertEqual(page.context["formulaire"].initial["montant"], 5000)
        self.assertEqual(page.context["formulaire"].initial["mode_paiement"], "mobile_money")
        mail.outbox.clear()
        reponse = self.valider(declaration)
        self.assertRedirects(reponse, self.liste, fetch_redirect_response=False)
        declaration.refresh_from_db()
        paiement = Paiement.objects.get()
        self.assertEqual((declaration.statut, declaration.paiement, declaration.traite_par), (StatutDeclaration.VALIDE, paiement, self.comptable))
        self.assertEqual((paiement.montant, paiement.mode_paiement, paiement.eleve, paiement.enregistre_par), (5000, "mobile_money", self.e1, self.comptable))
        self.assertEqual(MouvementCaisse.objects.get().paiement, paiement)
        notification = Notification.objects.get(destinataire=self.parent, titre="Paiement validé")
        self.assertIn(paiement.reference, notification.message)
        self.assertEqual(len(mail.outbox), 1)  # le reçu par courriel, comme pour un paiement ordinaire
        self.assertIn(paiement.reference, mail.outbox[0].subject)
        self.assertTrue(JournalAudit.objects.filter(action="validation_paiement_declare", acteur=self.comptable).exists())

    def test_la_direction_peut_valider_aussi(self):
        declaration = self.creer()
        self.assertEqual(self.valider(declaration, compte=self.fondateur).status_code, 302)
        self.assertEqual(PaiementDeclare.objects.get().statut, StatutDeclaration.VALIDE)

    def test_une_declaration_ne_donne_jamais_deux_paiements(self):
        declaration = self.creer()
        self.valider(declaration)
        reponse = self.valider(declaration)  # la page renvoyée par erreur
        self.assertRedirects(reponse, self.liste, fetch_redirect_response=False)
        self.assertEqual(Paiement.objects.count(), 1)
        self.assertEqual(MouvementCaisse.objects.count(), 1)

    def test_on_ne_valide_que_pour_l_eleve_de_la_declaration(self):
        declaration = self.creer()
        reponse = self.valider(declaration, matricule_eleve=self.e2.matricule)
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Cet élève n&#x27;est pas celui de la déclaration.")
        self.assertFalse(Paiement.objects.exists())
        self.assertEqual(PaiementDeclare.objects.get().statut, StatutDeclaration.EN_ATTENTE)

    def test_un_parent_ou_un_enseignant_ne_valide_rien(self):
        declaration = self.creer()
        for compte in (self.parent, self.t1, self.secretaire):
            reponse = self.valider(declaration, compte=compte)
            self.assertIn(reponse.status_code, (302, 403))
        self.assertFalse(Paiement.objects.exists())
        self.assertEqual(PaiementDeclare.objects.get().statut, StatutDeclaration.EN_ATTENTE)

    def test_refuser_demande_un_motif_et_previent_le_parent(self):
        declaration = self.creer()
        adresse = reverse("finances:refuser_declaration", args=[declaration.pk])
        self.client.force_login(self.comptable)
        self.assertEqual(self.client.get(adresse).status_code, 200)
        vide = self.client.post(adresse, {"motif": "   "})
        self.assertEqual(vide.status_code, 200)
        self.assertEqual(PaiementDeclare.objects.get().statut, StatutDeclaration.EN_ATTENTE)
        reponse = self.client.post(adresse, {"motif": "Transaction introuvable dans notre compte"})
        self.assertRedirects(reponse, self.liste, fetch_redirect_response=False)
        declaration.refresh_from_db()
        self.assertEqual((declaration.statut, declaration.motif_refus, declaration.traite_par), (StatutDeclaration.REFUSE, "Transaction introuvable dans notre compte", self.comptable))
        notification = Notification.objects.get(destinataire=self.parent, titre="Paiement non validé")
        self.assertIn("Transaction introuvable dans notre compte", notification.message)
        self.assertFalse(Paiement.objects.exists())
        self.assertTrue(JournalAudit.objects.filter(action="refus_paiement_declare", acteur=self.comptable).exists())

    def test_une_declaration_traitee_ne_se_refuse_plus(self):
        declaration = self.creer()
        self.valider(declaration)
        adresse = reverse("finances:refuser_declaration", args=[declaration.pk])
        self.client.force_login(self.comptable)
        self.assertRedirects(self.client.get(adresse), self.liste, fetch_redirect_response=False)
        self.client.post(adresse, {"motif": "Trop tard"})
        self.assertEqual(PaiementDeclare.objects.get().statut, StatutDeclaration.VALIDE)

    def test_une_autre_ecole_ne_voit_ni_ne_traite_rien(self):
        declaration = self.creer()
        self.client.force_login(self.fondateur_b)
        self.assertNotContains(self.client.get(self.liste), "MP261019AB12")
        self.assertEqual(self.client.get(reverse("finances:refuser_declaration", args=[declaration.pk])).status_code, 404)
        self.client.post(reverse("finances:refuser_declaration", args=[declaration.pk]), {"motif": "Intrus"})
        reponse = self.valider(declaration, compte=self.fondateur_b)
        self.assertRedirects(reponse, self.liste, fetch_redirect_response=False)
        self.assertFalse(Paiement.objects.exists())
        self.assertEqual(PaiementDeclare.objects.get().statut, StatutDeclaration.EN_ATTENTE)


class TableauDeBordEtMenuTests(DeclarationBase):
    def chiffres(self, compte):
        self.client.force_login(compte)
        page = self.client.get(reverse("comptes:redirection_tableau_de_bord"))
        return {ligne["label"]: ligne["valeur"] for ligne in page.context["indicateurs"]} if page.status_code == 200 else {}

    def test_le_tableau_de_bord_compte_ce_qui_attend_la_comptabilite(self):
        self.assertNotIn("Paiements à valider", self.chiffres(self.comptable))
        self.creer()
        self.creer(reference="MP261019CD34")
        self.assertEqual(self.chiffres(self.comptable)["Paiements à valider"], 2)
        self.assertEqual(self.chiffres(self.fondateur)["Paiements à valider"], 2)
        for compte in (self.t1, self.secretaire, self.e1):
            self.assertNotIn("Paiements à valider", self.chiffres(compte))

    def test_le_menu_propose_la_bonne_page_a_chacun(self):
        def liens(compte):
            self.client.force_login(compte)
            page = self.client.get(reverse("finances:suivi_paiements") if compte.role in (Role.PARENT, Role.COMPTABLE) else reverse("comptes:redirection_tableau_de_bord"))
            return {lien["url"] for section in page.context["sections_navigation"] for lien in section["liens"]}

        self.assertIn("finances:declarer_paiement", liens(self.parent))
        self.assertNotIn("finances:declarations", liens(self.parent))
        self.assertIn("finances:declarations", liens(self.comptable))
        self.assertNotIn("finances:declarer_paiement", liens(self.comptable))
        for compte in (self.t1, self.e1):
            self.assertFalse({"finances:declarations", "finances:declarer_paiement"} & liens(compte))


class InstructionsDeLEcoleTests(DeclarationBase):
    def test_le_developpeur_ecrit_comment_payer(self):
        developpeur = creer_compte(Role.DEVELOPPEUR, "dev-mm@stat.test", self.ecole)
        self.client.force_login(developpeur)
        page = self.client.get(reverse("espace_developpeur:parametres_etablissement"))
        self.assertContains(page, "Comment payer par Mobile Money")
        self.assertContains(page, "instructions_mobile_money")


class DeclarationsEnArabeTests(DeclarationBase):
    maxDiff = None

    def test_les_pages_sont_en_arabe_pur(self):
        # un vrai nom : « parent » (le nom du compte de test) serait remplacé par sa transcription partout, même dans les phrases de l'interface
        self.parent.nom, self.parent.prenom = "Coulibaly", "Aminata"
        self.parent.save(update_fields=["nom", "prenom"])
        cache.clear()
        invalider(self.ecole.pk)
        self.ecole.instructions_mobile_money = "Orange Money : 70 11 22 33"
        self.ecole.save()
        declaration = self.creer()
        saisis = {"Français", self.ecole.nom, self.e1.nom_complet, self.parent.nom_complet, "Orange Money : 70 11 22 33", "MP261019AB12"}
        pages = (
            (self.parent, reverse("finances:declarer_paiement")),
            (self.comptable, reverse("finances:declarations")),
            (self.comptable, reverse("finances:refuser_declaration", args=[declaration.pk])),
            (self.comptable, f"{reverse('finances:enregistrer_paiement')}?declaration={declaration.pk}"),
        )
        for compte, adresse in pages:
            with self.subTest(adresse=adresse):
                page = client_en(compte, "ar").get(adresse)
                self.assertEqual(page.status_code, 200)
                self.assertEqual(restes_hors_textes_saisis(page.content.decode(), saisis), [])
        erreurs = client_en(self.parent, "ar").post(self.adresse, self.donnees(montant="0", reference_transaction="AB"))
        self.assertEqual(restes_hors_textes_saisis(erreurs.content.decode(), saisis), [])
