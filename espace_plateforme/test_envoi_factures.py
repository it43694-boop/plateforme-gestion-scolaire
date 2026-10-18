"""
Envoi des factures d'abonnement par email (PDF joint) et rappels automatiques des factures en retard.

Données fictives : écoles « Alpha » et « Beta », adresses en .test ; le courrier part dans la boîte factice de Django
(`mail.outbox`), jamais sur un vrai serveur.
"""
import datetime
import smtplib
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.contrib.messages import get_messages
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from comptes.entretien import CLE_CACHE_ENTRETIEN, entretien_si_du
from comptes.models import JournalAudit
from comptes.roles import Role, StatutCompte
from espace_developpeur.forms import ParametresEtablissementForm
from espace_plateforme.tests import creer_utilisateur_actif
from etablissement.abonnements import emettre_facture, enregistrer_reglement
from etablissement.envoi_factures import (
    ENVOIS_MAXIMAUX_PAR_PASSAGE, JOURS_ENTRE_DEUX_RAPPELS, NOMBRE_MAXIMAL_DE_RAPPELS, destinataires_de_facturation,
    envoyer_facture, relancer_factures_en_retard,
)
from etablissement.models import Etablissement, FactureAbonnement, PlanEtablissement

JOUR = datetime.timedelta(days=1)
STATUT = FactureAbonnement.Statut


def aujourdhui():
    return timezone.localdate()


def textes_des_messages(reponse):
    """Les messages affichés à l'utilisateur après une action (avant tout échappement HTML)."""
    return [str(message) for message in get_messages(reponse.wsgi_request)]


@override_settings(
    EDITEUR_NOM="Yelenova Test SARL", EDITEUR_EMAIL="contact@yelenova-test.test", NOM_COMMERCIAL="Yelenova Test",
    ABONNEMENT_INSTRUCTIONS_PAIEMENT="Orange Money : 70 00 00 00", DEFAULT_FROM_EMAIL="facturation@yelenova-test.test",
)
class FacturesParEmailBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alpha = Etablissement.objects.create(nom="École Alpha", plan=PlanEtablissement.TOUS_CYCLES)
        cls.beta = Etablissement.objects.create(nom="École Beta", plan=PlanEtablissement.PREMIER_CYCLE)
        cls.proprietaire = creer_utilisateur_actif("owner-envoi@example.test", Role.DEVELOPPEUR, is_superuser=True)
        cls.dev_alpha = creer_utilisateur_actif("dev-alpha@alpha.test", Role.DEVELOPPEUR, cls.alpha)
        cls.fondateur_alpha = creer_utilisateur_actif("fondateur@alpha.test", Role.FONDATEUR, cls.alpha)
        cls.fondateur_beta = creer_utilisateur_actif("fondateur@beta.test", Role.FONDATEUR, cls.beta)

    def facturer(self, ecole=None, debut=None, fin=None, montant=120000, **extra):
        debut = debut or datetime.date(aujourdhui().year, 1, 1)
        fin = fin or datetime.date(aujourdhui().year, 12, 31)
        return emettre_facture(
            etablissement=ecole or self.alpha, periode_debut=debut, periode_fin=fin, montant=montant,
            cree_par=self.proprietaire, **extra,
        )

    def facture_en_retard(self, ecole=None, jours=3, envoyee=True, **extra):
        """Facture dont l'échéance est passée depuis `jours` jours, déjà envoyée par email (sauf `envoyee=False`)."""
        facture = self.facturer(
            ecole, date_emission=aujourdhui() - (jours + 15) * JOUR, date_echeance=aujourdhui() - jours * JOUR, **extra,
        )
        if envoyee:
            facture.envoyee_le = timezone.now() - (jours + 1) * JOUR
            facture.save(update_fields=["envoyee_le"])
        return facture


class DestinatairesTests(FacturesParEmailBase):
    def test_l_adresse_de_facturation_passe_avant_tout(self):
        self.alpha.email_facturation = "  Comptabilite@Alpha.test "
        self.alpha.save()
        self.assertEqual(destinataires_de_facturation(self.alpha), ["comptabilite@alpha.test"])

    def test_sinon_les_comptes_de_direction_de_l_ecole(self):
        administrateur = creer_utilisateur_actif("admin-general@alpha.test", Role.ADMINISTRATEUR_GENERAL, self.alpha)
        self.assertEqual(destinataires_de_facturation(self.alpha), sorted([self.fondateur_alpha.email, administrateur.email]))

    def test_sinon_le_developpeur_de_l_ecole(self):
        self.fondateur_alpha.delete()
        self.assertEqual(destinataires_de_facturation(self.alpha), [self.dev_alpha.email])

    def test_jamais_un_compte_inactif_ni_d_une_autre_ecole(self):
        Etablissement.objects.filter(pk=self.alpha.pk).update(email_facturation="")
        self.fondateur_alpha.statut = StatutCompte.SUSPENDU
        self.fondateur_alpha.save()
        # le fondateur est suspendu : on retombe sur le développeur d'Alpha, jamais sur le fondateur de Beta
        self.assertEqual(destinataires_de_facturation(self.alpha), [self.dev_alpha.email])
        self.dev_alpha.is_active = False
        self.dev_alpha.save()
        self.assertEqual(destinataires_de_facturation(self.alpha), [])

    def test_le_champ_se_regle_dans_les_parametres_de_l_ecole(self):
        self.assertIn("email_facturation", ParametresEtablissementForm(instance=self.alpha).fields)
        champ = ParametresEtablissementForm(instance=self.alpha).fields["email_facturation"]
        self.assertFalse(champ.required)
        envoi = {
            "nom": "École Alpha", "devise": "", "code_devise": "FCFA", "pas_montant": 5000, "coefficient_conduite": 1,
            "email_facturation": "pas une adresse", "taux_inps_salarie": "3.6", "taux_inps_employeur": "20",
            "taux_amo_salarie": "3.06", "taux_amo_employeur": "3.5",
        }
        formulaire = ParametresEtablissementForm(envoi, instance=self.alpha)
        self.assertFalse(formulaire.is_valid())
        self.assertIn("email_facturation", formulaire.errors)
        formulaire = ParametresEtablissementForm({**envoi, "email_facturation": "compta@alpha.test"}, instance=self.alpha)
        self.assertTrue(formulaire.is_valid(), formulaire.errors)
        self.assertEqual(formulaire.save().email_facturation, "compta@alpha.test")


class EnvoiDUneFactureTests(FacturesParEmailBase):
    def test_le_message_porte_le_pdf_et_les_informations_utiles(self):
        facture = self.facturer(date_echeance=datetime.date(2030, 3, 15))
        resultat = envoyer_facture(facture, acteur=self.proprietaire)
        self.assertTrue(resultat.envoyee)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        destinataires = set(message.to) | set(message.bcc)
        self.assertIn(self.fondateur_alpha.email, destinataires)
        self.assertEqual(message.from_email, "facturation@yelenova-test.test")
        self.assertEqual(message.reply_to, ["contact@yelenova-test.test"])
        self.assertIn(facture.numero, message.subject)
        self.assertIn("120 000 FCFA", message.subject)
        self.assertIn("15/03/2030", message.subject)
        for texte in (facture.numero, "École Alpha", "120 000 FCFA", "15/03/2030", "Orange Money : 70 00 00 00", "Yelenova Test SARL"):
            self.assertIn(texte, message.body)
        self.assertEqual(len(message.attachments), 1)
        nom, contenu, type_mime = message.attachments[0]
        self.assertEqual((nom, type_mime), (f"facture_{facture.numero}.pdf", "application/pdf"))
        self.assertTrue(contenu.startswith(b"%PDF"))

    def test_la_facture_garde_la_date_d_envoi_et_le_journal_ne_garde_que_des_nombres(self):
        facture = self.facturer()
        envoyer_facture(facture, acteur=self.proprietaire)
        facture.refresh_from_db()
        self.assertIsNotNone(facture.envoyee_le)
        self.assertEqual(facture.nombre_rappels, 0)
        entree = JournalAudit.objects.get(action="envoi_facture_abonnement")
        self.assertEqual(entree.cible, facture.numero)
        self.assertEqual(entree.details, {"etablissement": "École Alpha", "destinataires": 1})
        self.assertNotIn("@", f"{entree.cible} {entree.details}")

    def test_aucun_message_ne_nomme_une_autre_ecole(self):
        self.facturer(self.beta, datetime.date(2031, 1, 1), datetime.date(2031, 12, 31))
        facture = self.facturer(self.alpha)
        envoyer_facture(facture)
        message = mail.outbox[0]
        self.assertNotIn("Beta", message.subject + message.body)
        self.assertNotIn(self.fondateur_beta.email, set(message.to) | set(message.bcc))

    def test_plusieurs_destinataires_sont_en_copie_cachee(self):
        creer_utilisateur_actif("admin-general@alpha.test", Role.ADMINISTRATEUR_GENERAL, self.alpha)
        envoyer_facture(self.facturer())
        message = mail.outbox[0]
        self.assertEqual(len(message.bcc), 2)
        self.assertNotIn("alpha.test", " ".join(message.to))

    def test_seule_une_facture_emise_part(self):
        payee = self.facturer(self.alpha, datetime.date(2030, 1, 1), datetime.date(2030, 12, 31))
        enregistrer_reglement(facture=payee, date_paiement=aujourdhui(), mode_reglement="especes")
        annulee = self.facturer(self.beta, datetime.date(2031, 1, 1), datetime.date(2031, 12, 31))
        annulee.statut = STATUT.ANNULEE
        annulee.save()
        for facture in (payee, annulee):
            with self.subTest(statut=facture.statut):
                resultat = envoyer_facture(facture)
                self.assertEqual((resultat.envoyee, resultat.raison), (False, "statut"))
        self.assertEqual(mail.outbox, [])

    def test_sans_adresse_rien_ne_part_et_la_facture_n_est_pas_marquee_envoyee(self):
        self.fondateur_alpha.delete()
        self.dev_alpha.delete()
        facture = self.facturer()
        resultat = envoyer_facture(facture)
        self.assertEqual((resultat.envoyee, resultat.raison), (False, "aucune_adresse"))
        facture.refresh_from_db()
        self.assertIsNone(facture.envoyee_le)
        self.assertEqual(mail.outbox, [])

    def test_un_echec_du_serveur_d_email_ne_leve_rien_et_ne_marque_rien(self):
        facture = self.facturer()
        with mock.patch("django.core.mail.EmailMessage.send", side_effect=smtplib.SMTPException("refus")):
            resultat = envoyer_facture(facture)
        self.assertEqual((resultat.envoyee, resultat.raison), (False, "echec"))
        facture.refresh_from_db()
        self.assertIsNone(facture.envoyee_le)
        self.assertFalse(JournalAudit.objects.filter(action="envoi_facture_abonnement").exists())

    def test_un_pdf_impossible_a_creer_n_envoie_rien(self):
        with mock.patch("etablissement.envoi_factures.pdf_de_la_facture", return_value=None):
            resultat = envoyer_facture(self.facturer())
        self.assertEqual((resultat.envoyee, resultat.raison), (False, "pdf"))
        self.assertEqual(mail.outbox, [])


class EmissionEtBoutonTests(FacturesParEmailBase):
    def setUp(self):
        self.client.force_login(self.proprietaire)

    def donnees(self, **extra):
        return {
            "etablissement": self.alpha.id, "periode_debut": "2030-01-01", "periode_fin": "2030-12-31", "montant": 150000,
            "date_emission": aujourdhui().isoformat(), "date_echeance": "", "libelle": "", **extra,
        }

    def test_la_case_est_cochee_par_defaut(self):
        page = self.client.get(reverse("espace_plateforme:emettre_facture"))
        self.assertContains(page, 'name="envoyer_par_email"')
        self.assertContains(page, "form-check-input")
        champ = page.context["formulaire"]["envoyer_par_email"]
        self.assertTrue(champ.initial)
        self.assertEqual(champ.label, "Envoyer la facture par email à l'école")
        # Un champ date du navigateur n'affiche une valeur que au format AAAA-MM-JJ.
        self.assertContains(page, f'name="date_emission" value="{aujourdhui():%Y-%m-%d}"')

    def test_emettre_en_cochant_la_case_envoie_la_facture(self):
        reponse = self.client.post(reverse("espace_plateforme:emettre_facture"), self.donnees(envoyer_par_email="on"))
        facture = FactureAbonnement.objects.get()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIsNotNone(facture.envoyee_le)
        textes = textes_des_messages(reponse)
        self.assertIn(f"Facture {facture.numero} émise pour « École Alpha ».", textes)
        self.assertIn(f"Facture envoyée par email à {self.fondateur_alpha.email}.", textes)

    def test_emettre_sans_cocher_n_envoie_rien(self):
        self.client.post(reverse("espace_plateforme:emettre_facture"), self.donnees())
        self.assertEqual(FactureAbonnement.objects.count(), 1)
        self.assertEqual(mail.outbox, [])
        self.assertIsNone(FactureAbonnement.objects.get().envoyee_le)

    def test_la_facture_est_emise_meme_si_l_email_echoue(self):
        with mock.patch("django.core.mail.EmailMessage.send", side_effect=TimeoutError("trop long")):
            reponse = self.client.post(reverse("espace_plateforme:emettre_facture"), self.donnees(envoyer_par_email="on"))
        self.assertEqual(FactureAbonnement.objects.count(), 1)
        self.assertIsNone(FactureAbonnement.objects.get().envoyee_le)
        self.assertTrue(any("L'email n'a pas pu partir" in texte for texte in textes_des_messages(reponse)))

    def test_la_facture_est_emise_meme_sans_aucune_adresse(self):
        self.fondateur_alpha.delete()
        self.dev_alpha.delete()
        reponse = self.client.post(reverse("espace_plateforme:emettre_facture"), self.donnees(envoyer_par_email="on"))
        self.assertEqual(FactureAbonnement.objects.count(), 1)
        self.assertTrue(any("Aucun email n'est connu pour cette école" in texte for texte in textes_des_messages(reponse)))

    def test_le_bouton_envoyer_de_la_liste(self):
        facture = self.facturer()
        page = self.client.get(reverse("espace_plateforme:liste_factures"))
        self.assertContains(page, "Envoyer par email")
        self.client.post(reverse("espace_plateforme:envoyer_facture", args=[facture.id]))
        self.assertEqual(len(mail.outbox), 1)
        page = self.client.get(reverse("espace_plateforme:liste_factures"))
        self.assertContains(page, "Envoyée par email le")
        self.assertContains(page, "Renvoyer par email")

    def test_un_double_clic_n_envoie_qu_un_email_mais_un_renvoi_plus_tard_est_possible(self):
        facture = self.facturer()
        adresse = reverse("espace_plateforme:envoyer_facture", args=[facture.id])
        self.client.post(adresse)
        self.client.post(adresse)
        self.assertEqual(len(mail.outbox), 1)
        FactureAbonnement.objects.filter(pk=facture.pk).update(envoyee_le=timezone.now() - 2 * JOUR)
        self.client.post(adresse)
        self.assertEqual(len(mail.outbox), 2)

    def test_l_envoi_ne_se_fait_jamais_par_un_simple_lien(self):
        facture = self.facturer()
        self.assertEqual(self.client.get(reverse("espace_plateforme:envoyer_facture", args=[facture.id])).status_code, 405)
        self.assertEqual(mail.outbox, [])

    def test_facture_inexistante(self):
        self.assertEqual(self.client.post(reverse("espace_plateforme:envoyer_facture", args=[999999])).status_code, 404)

    def test_reserve_au_proprietaire_de_la_plateforme(self):
        facture = self.facturer()
        adresse = reverse("espace_plateforme:envoyer_facture", args=[facture.id])
        for compte in (self.dev_alpha, self.fondateur_alpha, None):
            self.client.logout()
            if compte:
                self.client.force_login(compte)
            with self.subTest(compte=getattr(compte, "role", "anonyme")):
                self.assertEqual(self.client.post(adresse).status_code, 302)  # renvoyé vers la connexion
        self.assertEqual(mail.outbox, [])

    def test_le_pdf_de_la_page_est_le_meme_que_celui_du_message(self):
        facture = self.facturer()
        envoyer_facture(facture)
        telecharge = self.client.get(reverse("espace_plateforme:facture_pdf", args=[facture.id]))
        self.assertEqual(telecharge.status_code, 200)
        self.assertTrue(telecharge.content.startswith(b"%PDF"))
        self.assertTrue(mail.outbox[0].attachments[0][1].startswith(b"%PDF"))


class RappelsTests(FacturesParEmailBase):
    def test_pas_de_rappel_avant_l_echeance_ni_le_jour_meme(self):
        self.facturer(date_echeance=aujourdhui() + JOUR)
        a_payer_aujourdhui = self.facturer(self.beta, date_echeance=aujourdhui())
        FactureAbonnement.objects.update(envoyee_le=timezone.now())
        self.assertEqual(relancer_factures_en_retard()["rappels"], 0)
        self.assertEqual(mail.outbox, [])
        self.assertEqual(a_payer_aujourdhui.nombre_rappels, 0)

    def test_premier_rappel_des_le_lendemain_de_l_echeance(self):
        facture = self.facture_en_retard(jours=1)
        self.assertEqual(relancer_factures_en_retard()["rappels"], 1)
        message = mail.outbox[0]
        self.assertIn("Rappel", message.subject)
        self.assertIn(facture.numero, message.subject)
        self.assertIn("1 jour de retard", message.body)
        self.assertEqual(message.attachments[0][0], f"facture_{facture.numero}.pdf")
        facture.refresh_from_db()
        self.assertEqual((facture.nombre_rappels, facture.dernier_rappel_le), (1, aujourdhui()))
        self.assertEqual(JournalAudit.objects.filter(action="rappel_facture_abonnement").count(), 1)

    def test_un_seul_rappel_par_jour_puis_un_par_semaine_trois_au_plus(self):
        facture = self.facture_en_retard(jours=2)
        depart = aujourdhui()
        jours_de_rappel = []
        for decalage in range(0, 60):
            jour = depart + decalage * JOUR
            avant = len(mail.outbox)
            relancer_factures_en_retard(aujourdhui=jour)
            relancer_factures_en_retard(aujourdhui=jour)  # un deuxième passage le même jour ne renvoie rien
            if len(mail.outbox) > avant:
                self.assertEqual(len(mail.outbox), avant + 1)
                jours_de_rappel.append(decalage)
        self.assertEqual(jours_de_rappel, [0, JOURS_ENTRE_DEUX_RAPPELS, 2 * JOURS_ENTRE_DEUX_RAPPELS])
        facture.refresh_from_db()
        self.assertEqual(facture.nombre_rappels, NOMBRE_MAXIMAL_DE_RAPPELS)

    def test_une_facture_payee_ou_annulee_n_est_jamais_relancee(self):
        payee = self.facture_en_retard(self.alpha)
        enregistrer_reglement(facture=payee, date_paiement=aujourdhui(), mode_reglement="mobile_money")
        annulee = self.facture_en_retard(self.beta)
        annulee.statut = STATUT.ANNULEE
        annulee.motif_annulation = "Erreur"
        annulee.save()
        self.assertEqual(relancer_factures_en_retard()["rappels"], 0)
        self.assertEqual(mail.outbox, [])

    def test_seules_les_factures_envoyees_par_email_sont_relancees(self):
        self.facture_en_retard(envoyee=False)
        self.assertEqual(relancer_factures_en_retard()["rappels"], 0)
        self.assertEqual(mail.outbox, [])

    def test_le_paiement_arrete_les_rappels(self):
        facture = self.facture_en_retard()
        relancer_factures_en_retard()
        enregistrer_reglement(facture=facture, date_paiement=aujourdhui(), mode_reglement="virement")
        relancer_factures_en_retard(aujourdhui=aujourdhui() + 30 * JOUR)
        self.assertEqual(len(mail.outbox), 1)

    def test_un_echec_est_reessaye_demain_sans_compter_le_rappel(self):
        facture = self.facture_en_retard()
        with mock.patch("django.core.mail.EmailMessage.send", side_effect=smtplib.SMTPException("refus")):
            bilan = relancer_factures_en_retard()
        self.assertEqual(bilan, {"rappels": 0, "sans_adresse": 0, "echecs": 1})
        facture.refresh_from_db()
        self.assertEqual((facture.nombre_rappels, facture.dernier_rappel_le), (0, None))
        self.assertEqual(relancer_factures_en_retard(aujourdhui=aujourdhui() + JOUR)["rappels"], 1)

    def test_un_echec_arrete_le_passage_sans_insister_sur_les_autres_factures(self):
        self.facture_en_retard(self.alpha)
        self.facture_en_retard(self.beta)
        with mock.patch("django.core.mail.EmailMessage.send", side_effect=TimeoutError("trop long")) as envoi:
            relancer_factures_en_retard()
        self.assertEqual(envoi.call_count, 1)

    def test_une_ecole_sans_adresse_n_empeche_pas_les_autres(self):
        gamma = Etablissement.objects.create(nom="École Gamma", plan=PlanEtablissement.PREMIER_CYCLE)
        self.facture_en_retard(gamma)
        self.facture_en_retard(self.alpha)
        self.assertEqual(relancer_factures_en_retard(), {"rappels": 1, "sans_adresse": 1, "echecs": 0})

    def test_le_nombre_de_rappels_par_passage_est_borne(self):
        for numero in range(ENVOIS_MAXIMAUX_PAR_PASSAGE + 3):
            ecole = Etablissement.objects.create(nom=f"École {numero}", email_facturation=f"compta{numero}@ecole.test")
            self.facture_en_retard(ecole)
        self.assertEqual(relancer_factures_en_retard()["rappels"], ENVOIS_MAXIMAUX_PAR_PASSAGE)
        # Le passage suivant (un autre jour de l'entretien) envoie le reste : les dix premières viennent d'être relancées.
        self.assertEqual(relancer_factures_en_retard()["rappels"], 3)

    def test_la_simulation_compte_sans_envoyer(self):
        facture = self.facture_en_retard()
        self.assertEqual(relancer_factures_en_retard(simulation=True)["rappels"], 1)
        self.assertEqual(mail.outbox, [])
        facture.refresh_from_db()
        self.assertEqual(facture.nombre_rappels, 0)

    def test_les_rappels_partent_avec_l_entretien_quotidien_une_fois_par_jour(self):
        cache.delete(CLE_CACHE_ENTRETIEN)
        self.facture_en_retard()
        entretien_si_du()
        self.assertEqual(len(mail.outbox), 1)
        entretien_si_du()  # déjà fait aujourd'hui
        self.assertEqual(len(mail.outbox), 1)

    def test_une_panne_des_rappels_ne_gene_pas_l_entretien(self):
        cache.delete(CLE_CACHE_ENTRETIEN)
        with mock.patch("etablissement.envoi_factures.relancer_factures_en_retard", side_effect=RuntimeError("panne")):
            bilan = entretien_si_du()
        self.assertIsInstance(bilan, dict)  # les purges ont eu lieu et rendent leur bilan comme avant
        self.assertIn("sessions", bilan)

    def test_la_commande_entretien_envoie_ou_simule(self):
        facture = self.facture_en_retard()
        sortie = StringIO()
        call_command("entretien", "--simulation", stdout=sortie)
        self.assertIn("à envoyer : 1", sortie.getvalue())
        self.assertEqual(mail.outbox, [])
        sortie = StringIO()
        call_command("entretien", stdout=sortie)
        self.assertIn("envoyés : 1", sortie.getvalue())
        self.assertEqual(len(mail.outbox), 1)
        facture.refresh_from_db()
        self.assertEqual(facture.nombre_rappels, 1)

    def test_le_journal_des_rappels_ne_contient_aucune_adresse(self):
        self.facture_en_retard()
        relancer_factures_en_retard()
        entree = JournalAudit.objects.get(action="rappel_facture_abonnement")
        self.assertNotIn("@", f"{entree.cible} {entree.details}")
        self.assertIsNone(entree.acteur)
