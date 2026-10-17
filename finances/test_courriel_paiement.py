"""Courriel envoyé aux parents quand un paiement est enregistré : reçu, montant, reste à payer, langue du parent, jamais bloquant."""
from unittest import mock

from django.core import mail
from django.test import override_settings
from django.urls import reverse

from comptes.arabisation import invalider
from comptes.models import Utilisateur
from comptes.roles import Role, StatutCompte
from finances.models import Paiement
from scolarite.models import EcheancierFrais, Periodicite
from statistiques.test_education import EducationBase, creer_compte


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", EMAIL_ASYNC=False)
class CourrielDePaiementTests(EducationBase):
    def setUp(self):
        EcheancierFrais.objects.create(
            classe=self.c6a, montant_inscription=10000, periodicite=Periodicite.ANNUEL, montant_periode=20000, nombre_versements=1,
        )
        self.comptable = creer_compte(Role.COMPTABLE, "comptable@courriel-paiement.test", self.ecole)
        self.parent = creer_compte(Role.PARENT, "parent@courriel-paiement.test", self.ecole, telephone="70120001")
        self.e1.parents_lies.clear()  # le jeu de données de base en lie déjà un : ici seuls ceux du test comptent
        self.e1.parents_lies.add(self.parent)
        self.client.force_login(self.comptable)

    def payer(self, montant=10000, tranche="inscription"):
        return self.client.post(reverse("finances:enregistrer_paiement"), {
            "matricule_eleve": self.e1.matricule, "tranche": tranche, "montant": montant, "mode_paiement": "especes",
        })

    def test_le_parent_recoit_le_recu_et_le_reste_a_payer(self):
        reponse = self.payer()
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(Paiement.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, [self.parent.email])
        reference = Paiement.objects.get().reference
        self.assertIn(reference, message.subject)
        self.assertIn("10000 FCFA", message.body)
        self.assertIn(f"Reçu n° {reference}.", message.body)
        self.assertIn("Reste à payer : 20000 FCFA.", message.body)

    def test_la_scolarite_entierement_reglee_est_annoncee(self):
        self.payer(10000, "inscription")
        mail.outbox.clear()
        self.payer(20000, "versement")
        self.assertIn("La scolarité est entièrement réglée.", mail.outbox[0].body)
        self.assertNotIn("Reste à payer", mail.outbox[0].body)

    def test_un_parent_arabe_recoit_le_courriel_en_arabe(self):
        Utilisateur.objects.filter(pk=self.parent.pk).update(langue="ar")
        Utilisateur.objects.filter(pk=self.e1.pk).update(prenom="Awa", nom="Traore", prenom_ar="عوا", nom_ar="تراوري")
        invalider(self.ecole.pk)
        self.payer()
        message = mail.outbox[0]
        self.assertIn("تم تسجيل الدفع", message.subject)
        self.assertIn("تم تسجيل دفعة بمبلغ", message.body)
        self.assertIn("عوا تراوري", message.body)
        self.assertIn("المتبقي للدفع", message.body)
        self.assertNotIn("Reste", message.body)
        self.assertNotIn("Reçu", message.body)

    def test_sans_parent_aucun_courriel_mais_le_paiement_est_enregistre(self):
        self.e1.parents_lies.clear()
        self.payer()
        self.assertEqual(Paiement.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_un_parent_inactif_n_est_pas_prevenu(self):
        Utilisateur.objects.filter(pk=self.parent.pk).update(is_active=False)
        self.payer()
        self.assertEqual(len(mail.outbox), 0)

    def test_un_compte_parent_suspendu_ou_pas_encore_valide_n_est_pas_prevenu(self):
        for statut in (StatutCompte.SUSPENDU, StatutCompte.DESACTIVE, StatutCompte.EN_ATTENTE_VALIDATION, StatutCompte.EN_ATTENTE_VERIFICATION_EMAIL):
            with self.subTest(statut=statut):
                Utilisateur.objects.filter(pk=self.parent.pk).update(statut=statut)
                self.payer(montant=1000)
                self.assertEqual(len(mail.outbox), 0)

    def test_un_envoi_qui_echoue_ne_bloque_jamais_le_paiement(self):
        with mock.patch("finances.courriels.envoyer_email", side_effect=RuntimeError("serveur de courriel en panne")):
            reponse = self.payer()
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(Paiement.objects.count(), 1)

    def test_deux_parents_deux_courriels(self):
        second = creer_compte(Role.PARENT, "parent2@courriel-paiement.test", self.ecole, telephone="70120002")
        self.e1.parents_lies.add(second)
        self.payer()
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), sorted([self.parent.email, second.email]))
