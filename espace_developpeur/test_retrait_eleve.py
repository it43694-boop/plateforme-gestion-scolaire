"""
Retirer un élève : suppression définitive (aucun historique) ou anonymisation (historique à conserver).

Jeu de données de EducationBase (statistiques.test_education) : école A (e1..e9), école B vide. e1 a pour parent `parent`
(70999001). On y ajoute un développeur dans chaque école.
"""
import datetime
import tempfile

from django.core.files.base import ContentFile
from django.test import override_settings
from django.urls import reverse

from cantine import services as cantine
from cantine.models import FormuleCantine, InscriptionCantine
from comptabilite.services import assurer_plan_comptable, creer_exercice, synchroniser_caisse
from comptabilite.models import Ecriture
from communication.models import Message
from comptes.models import JournalAudit, Notification, Utilisateur, generer_matricule
from comptes.roles import Role, StatutCompte
from espace_developpeur.retrait_eleve import mode_de_retrait, historique_eleve
from finances import tenues
from finances.models import ArticleTenue, MouvementCaisse, TypeTranche, enregistrer_paiement
from pedagogie.models import Absence
from scolarite.models import Inscription, ParentEnAttente, TransfertEleve
from statistiques.fiche import construire_fiche
from statistiques.test_education import EducationBase, creer_compte


def url(eleve):
    return reverse("espace_developpeur:retirer_eleve", args=[eleve.matricule])


def retirer(client, eleve, confirmation=None):
    return client.post(url(eleve), {"confirmation": eleve.matricule if confirmation is None else confirmation})


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class RetraitBase(EducationBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.dev = creer_compte(Role.DEVELOPPEUR, "dev@retrait.test", cls.ecole)
        cls.dev_b = creer_compte(Role.DEVELOPPEUR, "dev-b@retrait.test", cls.ecole_b)
        cls.formule_cantine = FormuleCantine.objects.create(etablissement=cls.ecole, libelle="Cantine", mode="mensuel", montant=5000)
        cls.article = ArticleTenue.objects.create(etablissement=cls.ecole, libelle="Polo", taille="M", prix=4000)
        ArticleTenue.objects.filter(pk=cls.article.pk).update(stock=50)

    def doublon(self):
        """Un élève inscrit par erreur : une inscription, un parent sans compte, rien d'autre."""
        doublon = creer_compte(Role.ELEVE, f"doublon{Utilisateur.objects.count()}@retrait.test", self.ecole, sexe="F")
        Inscription.objects.create(eleve=doublon, classe=self.c6a)
        ParentEnAttente.objects.create(eleve=doublon, email="attente@retrait.test", telephone="70555009")
        return doublon

    def connecte(self, compte=None):
        self.client.force_login(compte or self.dev)


class AccesRetraitTests(RetraitBase):
    def test_seul_le_developpeur_ouvre_la_page(self):
        self.connecte()
        self.assertEqual(self.client.get(url(self.e1)).status_code, 200)
        for compte in (self.fondateur, self.secretaire, self.dir_1er, self.comptable, self.t1, self.parent, self.e1):
            self.client.force_login(compte)
            with self.subTest(role=compte.role):
                self.assertEqual(self.client.get(url(self.e1)).status_code, 403)
                self.assertEqual(retirer(self.client, self.e1).status_code, 403)
        self.assertTrue(Utilisateur.objects.filter(pk=self.e1.pk, is_active=True).exists())

    def test_un_developpeur_ne_touche_pas_un_eleve_d_une_autre_ecole(self):
        self.connecte(self.dev_b)
        self.assertEqual(self.client.get(url(self.e1)).status_code, 404)
        self.assertEqual(retirer(self.client, self.e1).status_code, 404)
        self.assertTrue(Utilisateur.objects.filter(pk=self.e1.pk, is_active=True).exists())

    def test_visiteur_anonyme_redirige(self):
        self.client.logout()
        self.assertEqual(self.client.get(url(self.e1)).status_code, 302)

    def test_le_bouton_n_est_propose_qu_au_developpeur(self):
        dossier = reverse("scolarite:dossier_eleve", args=[self.e1.matricule])
        self.connecte()
        self.assertContains(self.client.get(dossier), url(self.e1))
        for compte in (self.fondateur, self.secretaire, self.parent):
            self.client.force_login(compte)
            self.assertNotContains(self.client.get(dossier), url(self.e1))

    def test_un_compte_qui_n_est_pas_un_eleve_est_introuvable(self):
        self.connecte()
        reponse = self.client.get(reverse("espace_developpeur:retirer_eleve", args=["inconnu"]))
        self.assertEqual(reponse.status_code, 404)


class ModeDeRetraitTests(RetraitBase):
    def test_sans_historique_c_est_une_suppression(self):
        doublon = self.doublon()
        self.assertEqual(mode_de_retrait(doublon, historique_eleve(doublon)), "suppression")
        self.connecte()
        self.assertContains(self.client.get(url(doublon)), "Suppression définitive")

    def test_chaque_element_d_historique_force_l_anonymisation(self):
        cas = {
            "absence": lambda e, i: Absence.objects.create(eleve=e, classe=self.c6a, date_absence=datetime.date(2026, 11, 3)),
            "message": lambda e, i: (e.parents_lies.add(self.parent), Message.objects.create(
                etablissement=self.ecole, eleve=e, expediteur=self.parent, destinataire=self.t1, contenu="Bonjour")),
            "paiement": lambda e, i: enregistrer_paiement(
                eleve=e, inscription=i, tranche=TypeTranche.VERSEMENT, montant=1000, mode_paiement="especes",
                enregistre_par=self.comptable),
            "cantine": lambda e, i: InscriptionCantine.objects.create(
                etablissement=self.ecole, eleve=e, annee_scolaire=self.annee, formule=self.formule_cantine, date_debut=datetime.date(2026, 10, 15)),
            "achat de tenues": lambda e, i: tenues.vendre(
                etablissement=self.ecole, quantites={self.article.pk: 1}, eleve=e, acheteur="", mode_paiement="especes", acteur=self.comptable),
        }
        for nom, creer in cas.items():
            with self.subTest(historique=nom):
                doublon = self.doublon()
                creer(doublon, doublon.inscriptions.first())
                self.assertEqual(mode_de_retrait(doublon, historique_eleve(doublon)), "anonymisation")

    def test_on_ne_peut_pas_forcer_la_suppression_d_un_eleve_qui_a_un_historique(self):
        """Le mode est décidé par le serveur : un POST ne peut pas demander « supprimer »."""
        self.connecte()
        reponse = self.client.post(url(self.e1), {"confirmation": self.e1.matricule, "mode": "suppression", "action": "supprimer"})
        self.assertRedirects(reponse, reverse("scolarite:liste_eleves"))
        self.assertTrue(Utilisateur.objects.filter(pk=self.e1.pk).exists())
        self.assertTrue(Utilisateur.objects.get(pk=self.e1.pk).matricule.startswith("ANON-"))


class SuppressionTests(RetraitBase):
    def test_le_matricule_mal_retape_ne_supprime_rien(self):
        doublon = self.doublon()
        self.connecte()
        for faux in ("", "123", doublon.matricule + "0", doublon.matricule.lower() + " x"):
            reponse = retirer(self.client, doublon, confirmation=faux)
            self.assertEqual(reponse.status_code, 200)
        self.assertTrue(Utilisateur.objects.filter(pk=doublon.pk).exists())
        self.assertFalse(JournalAudit.objects.filter(action="suppression_eleve").exists())

    def test_suppression_complete_du_doublon(self):
        doublon = self.doublon()
        matricule, nom, pk = doublon.matricule, doublon.nom, doublon.pk
        self.connecte()
        reponse = retirer(self.client, doublon)
        self.assertRedirects(reponse, reverse("scolarite:liste_eleves"))
        self.assertFalse(Utilisateur.objects.filter(pk=pk).exists())
        self.assertFalse(Inscription.objects.filter(eleve_id=pk).exists())
        self.assertFalse(ParentEnAttente.objects.filter(eleve_id=pk).exists())
        self.assertTrue(Utilisateur.objects.filter(pk=self.parent.pk).exists())  # les autres comptes ne sont pas touchés

    def test_le_journal_ne_garde_ni_le_nom_ni_le_matricule(self):
        doublon = self.doublon()
        matricule, nom, pk = doublon.matricule, doublon.nom, doublon.pk
        self.connecte()
        retirer(self.client, doublon)
        entree = JournalAudit.objects.get(action="suppression_eleve")
        self.assertEqual(entree.cible, f"eleve-{pk}")
        self.assertEqual(entree.acteur, self.dev)
        texte = f"{entree.cible} {entree.details}"
        self.assertNotIn(matricule, texte)
        self.assertNotIn(nom, texte)
        self.assertNotIn("70555009", texte)


class AnonymisationTests(RetraitBase):
    def setUp(self):
        # e2 : sexe M, né le 10/03/2013, handicap moteur, parents = p (compte) + une famille sans compte
        self.e2.telephone = "70999777"
        self.e2.lieu_naissance, self.e2.numero_acte_naissance = "Kayes", "ACTE-42"
        self.e2.profession = "x"
        self.e2.save()
        self.parent_lie = creer_compte(Role.PARENT, "lie-e2@retrait.test", self.ecole, telephone="70999888")
        self.e2.parents_lies.add(self.parent_lie)
        ParentEnAttente.objects.create(eleve=self.e2, email="attente@retrait.test", nom="Dupont", telephone="70555009")
        self.inscription = self.i["e2"]
        Absence.objects.create(
            eleve=self.e2, classe=self.c6a, date_absence=datetime.date(2026, 11, 3), motif="Palu, voir le médecin",
        )
        self.paiement = enregistrer_paiement(
            eleve=self.e2, inscription=self.inscription, tranche=TypeTranche.VERSEMENT, montant=15000,
            mode_paiement="especes", enregistre_par=self.comptable,
        )
        Message.objects.create(
            etablissement=self.ecole, eleve=self.e2, expediteur=self.parent_lie, destinataire=self.t1, contenu="Il est malade",
        )
        self.nom_complet, self.matricule = self.e2.nom_complet, self.e2.matricule
        Notification.objects.create(
            destinataire=self.parent_lie, titre="Absence", message=f"{self.nom_complet} est absent(e)", url="/pedagogie/",
        )
        self.notification_etrangere = Notification.objects.create(
            destinataire=self.parent_lie, titre="Réunion", message="Réunion des parents", url="/communication/",
        )
        self.connecte()

    def anonymiser(self):
        reponse = retirer(self.client, self.e2)
        self.assertRedirects(reponse, reverse("scolarite:liste_eleves"))
        self.e2.refresh_from_db()

    def test_la_page_annonce_l_anonymisation_et_l_historique(self):
        reponse = self.client.get(url(self.e2))
        self.assertContains(reponse, "Anonymisation")
        self.assertContains(reponse, "1 paiement(s)")
        self.assertContains(reponse, "1 absence(s)")
        self.assertContains(reponse, "message(s)")

    def test_la_personne_est_effacee(self):
        self.anonymiser()
        e = self.e2
        self.assertEqual(e.prenom, "Élève")
        self.assertEqual(e.nom, f"Anonymisé {e.pk}")
        self.assertEqual(e.matricule, f"ANON-{e.pk}")
        self.assertEqual(e.email, f"anonyme-{e.pk}@eleves.local")
        self.assertIsNone(e.telephone)
        self.assertEqual((e.lieu_naissance, e.numero_acte_naissance, e.profession), ("", "", ""))
        self.assertEqual(e.statut, StatutCompte.DESACTIVE)
        self.assertFalse(e.is_active)
        self.assertFalse(e.has_usable_password())
        for texte in (self.nom_complet, self.matricule, "70999777", "Kayes", "ACTE-42"):
            self.assertNotIn(texte, f"{e.nom_complet} {e.email} {e.lieu_naissance} {e.numero_acte_naissance} {e.matricule} {e.telephone}")

    def test_la_famille_est_detachee_mais_les_comptes_parents_restent(self):
        self.anonymiser()
        self.assertFalse(self.e2.parents_lies.exists())
        self.assertFalse(ParentEnAttente.objects.filter(eleve=self.e2).exists())
        self.assertTrue(Utilisateur.objects.filter(pk=self.parent_lie.pk, is_active=True).exists())

    def test_messages_et_notifications_qui_le_concernent_sont_effaces(self):
        self.anonymiser()
        self.assertFalse(Message.objects.filter(eleve=self.e2).exists())
        self.assertFalse(Notification.objects.filter(message__contains=self.nom_complet).exists())
        self.assertTrue(Notification.objects.filter(pk=self.notification_etrangere.pk).exists())

    def test_les_chiffres_restent(self):
        avant = construire_fiche(self.fondateur, self.annee)
        self.anonymiser()
        e = self.e2
        self.assertEqual(e.sexe, "M")
        self.assertEqual(e.handicap, "moteur")
        self.assertEqual(e.date_naissance, datetime.date(2013, 3, 1))  # jour effacé, année et mois gardés
        self.assertTrue(Inscription.objects.filter(eleve=e).exists())
        self.assertEqual(Absence.objects.get(eleve=e).motif, "")  # l'absence reste, son motif (santé) non
        self.assertEqual(Absence.objects.filter(eleve=e).count(), 1)
        self.paiement.refresh_from_db()
        self.assertEqual(self.paiement.montant, 15000)
        apres = construire_fiche(self.fondateur, self.annee)
        self.assertEqual(avant["totaux"], apres["totaux"])
        self.assertEqual(avant["effectifs"], apres["effectifs"])

    def test_le_justificatif_de_transfert_est_supprime_du_disque(self):
        inscription = self.i["e3"]
        transfert = TransfertEleve(
            inscription=inscription, destination_libelle="École lointaine", date_transfert=datetime.date(2026, 12, 1),
            motif="Déménagement de la famille", enregistre_par=self.secretaire,
        )
        transfert.justificatif.save("justificatif.pdf", ContentFile(b"%PDF-1.4 contenu"), save=False)
        transfert.save()
        chemin = transfert.justificatif.path
        self.assertTrue(transfert.justificatif.storage.exists(transfert.justificatif.name))
        retirer(self.client, self.e3)
        transfert.refresh_from_db()
        self.assertEqual(transfert.motif, "Anonymisé")
        self.assertFalse(transfert.justificatif)
        import os
        self.assertFalse(os.path.exists(chemin))

    def test_le_journal_note_des_compteurs_sans_donnee_personnelle(self):
        self.anonymiser()
        entree = JournalAudit.objects.get(action="anonymisation_eleve")
        self.assertEqual(entree.cible, f"eleve-{self.e2.pk}")
        self.assertEqual(entree.details["parents_en_attente"], 1)
        self.assertEqual(entree.details["parents_delies"], 1)
        self.assertEqual(entree.details["historique_conserve"]["paiements"], 1)
        texte = f"{entree.cible} {entree.details}"
        for secret in (self.nom_complet, self.matricule, "70555009", "70999777", "Dupont", "Kayes"):
            self.assertNotIn(secret, texte)

    def test_un_eleve_deja_anonymise_n_est_pas_retraite(self):
        self.anonymiser()
        nouveau_matricule = self.e2.matricule
        reponse = self.client.get(url(self.e2))
        self.assertContains(reponse, "déjà anonymisé")
        reponse = self.client.post(url(self.e2), {"confirmation": nouveau_matricule})
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(JournalAudit.objects.filter(action="anonymisation_eleve").count(), 1)

    def test_l_eleve_anonymise_ne_peut_plus_se_connecter(self):
        self.anonymiser()
        self.client.logout()
        self.assertFalse(self.client.login(username=self.e2.email, password="n'importe"))
        reponse = self.client.get(reverse("scolarite:dossier_eleve", args=[self.e2.matricule]))
        self.assertEqual(reponse.status_code, 302)
class NomEffaceDeLaCaisseEtDeLaComptabiliteTests(RetraitBase):
    """La Caisse et la comptabilité se conservent, mais le nom de l'élève disparaît de leurs libellés."""

    def test_le_nom_n_est_plus_dans_les_libelles_apres_anonymisation(self):
        assurer_plan_comptable(self.ecole)
        creer_exercice(etablissement=self.ecole, libelle="Exercice test", date_debut=datetime.date(datetime.date.today().year, 1, 1),
                       date_fin=datetime.date(datetime.date.today().year, 12, 31))
        inscription = cantine.inscrire(eleve=self.e1, formule=self.formule_cantine, annee=self.annee, date_debut=datetime.date(2026, 10, 15), acteur=self.dev)
        enregistrer_paiement(eleve=self.e1, inscription=self.i["e1"], tranche=TypeTranche.VERSEMENT, montant=1000, mode_paiement="especes", enregistre_par=self.comptable)
        cantine.enregistrer_paiement(inscription=inscription, montant=2000, mode_paiement="especes", acteur=self.dev)
        tenues.vendre(etablissement=self.ecole, quantites={self.article.pk: 1}, eleve=self.e1, acheteur="", mode_paiement="especes", acteur=self.comptable)
        autre = enregistrer_paiement(eleve=self.e2, inscription=self.i["e2"], tranche=TypeTranche.VERSEMENT, montant=500, mode_paiement="especes", enregistre_par=self.comptable)
        synchroniser_caisse(self.ecole, acteur=self.comptable)
        nom = self.e1.nom_complet
        self.assertEqual(sum(nom in m.description for m in MouvementCaisse.objects.all()), 3)
        self.assertEqual(sum(nom in e.libelle for e in Ecriture.objects.all()), 3)

        self.connecte()
        retirer(self.client, self.e1)

        self.assertEqual(sum(nom in m.description for m in MouvementCaisse.objects.all()), 0)
        self.assertEqual(sum(nom in e.libelle for e in Ecriture.objects.all()), 0)
        self.assertEqual(MouvementCaisse.objects.filter(description__contains="Élève anonymisé").count(), 3)
        self.assertEqual(sum(m.montant for m in MouvementCaisse.objects.filter(annule=False)), 1000 + 2000 + 4000 + 500)  # les chiffres restent
        autre.refresh_from_db()
        self.assertIn(self.e2.nom_complet, autre.mouvement_caisse.description)  # un autre élève n'est pas touché
