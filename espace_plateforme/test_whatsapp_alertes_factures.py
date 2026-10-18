"""
Factures d'abonnement non payées : bouton WhatsApp (lien pré-rempli, rien n'est envoyé par le serveur) et alertes du propriétaire
(factures en retard, factures à payer).

Données fictives : écoles « Alpha », « Beta » et « Gamma », numéros de téléphone inventés.
"""
import datetime
from urllib.parse import parse_qs, unquote, urlparse

from django.core import mail
from django.test import override_settings
from django.urls import reverse

from comptes.roles import Role
from espace_developpeur.forms import ParametresEtablissementForm
from espace_plateforme.test_envoi_factures import FacturesParEmailBase, aujourdhui
from espace_plateforme.tests import creer_utilisateur_actif
from etablissement.abonnements import alertes_factures, enregistrer_reglement
from etablissement.envoi_factures import ajouter_les_liens_whatsapp, message_whatsapp, telephones_de_facturation
from etablissement.models import Etablissement, FactureAbonnement, PlanEtablissement

JOUR = datetime.timedelta(days=1)
STATUT = FactureAbonnement.Statut


def decouper(lien):
    """(numéro, texte du message) d'un lien wa.me."""
    adresse = urlparse(lien)
    return adresse.path.strip("/"), parse_qs(adresse.query)["text"][0]


class TelephonesTests(FacturesParEmailBase):
    def test_le_numero_de_l_ecole_passe_avant_tout(self):
        self.alpha.telephone_facturation = " +223 70 00 00 01 "
        self.alpha.save()
        creer_utilisateur_actif("autre@alpha.test", Role.ADMINISTRATEUR_GENERAL, self.alpha, telephone="+223 70 00 00 02")
        self.assertEqual(telephones_de_facturation([self.alpha]), {self.alpha.pk: "+223 70 00 00 01"})

    def test_sinon_un_compte_de_direction_puis_le_developpeur(self):
        self.dev_alpha.telephone = "+223 70 00 00 03"
        self.dev_alpha.save()
        self.assertEqual(telephones_de_facturation([self.alpha]), {self.alpha.pk: "+223 70 00 00 03"})  # le développeur, faute de mieux
        self.fondateur_alpha.telephone = "+223 70 00 00 04"
        self.fondateur_alpha.save()
        self.assertEqual(telephones_de_facturation([self.alpha]), {self.alpha.pk: "+223 70 00 00 04"})  # la direction passe avant

    def test_jamais_le_numero_d_une_autre_ecole_ni_d_un_compte_sans_rapport(self):
        self.fondateur_beta.telephone = "+223 70 00 00 05"
        self.fondateur_beta.save()
        enseignant = creer_utilisateur_actif("prof@alpha.test", Role.ENSEIGNANT, self.alpha, telephone="+223 70 00 00 06")
        self.assertEqual(telephones_de_facturation([self.alpha]), {})
        self.assertEqual(telephones_de_facturation([self.beta]), {self.beta.pk: "+223 70 00 00 05"})
        self.assertNotIn(enseignant.telephone, telephones_de_facturation([self.alpha, self.beta]).values())

    def test_un_compte_suspendu_est_ignore(self):
        self.fondateur_alpha.telephone = "+223 70 00 00 07"
        self.fondateur_alpha.is_active = False
        self.fondateur_alpha.save()
        self.assertEqual(telephones_de_facturation([self.alpha]), {})

    def test_une_requete_pour_toutes_les_ecoles(self):
        with self.assertNumQueries(1):
            telephones_de_facturation([self.alpha, self.beta])
        self.alpha.telephone_facturation = "+223 70 00 00 08"
        self.beta.telephone_facturation = "+223 70 00 00 09"
        with self.assertNumQueries(0):
            telephones_de_facturation([self.alpha, self.beta])

    def test_le_champ_se_regle_dans_les_parametres_de_l_ecole(self):
        envoi = {
            "nom": "École Alpha", "devise": "", "code_devise": "FCFA", "pas_montant": 5000, "coefficient_conduite": 1,
            "taux_inps_salarie": "3.6", "taux_inps_employeur": "20", "taux_amo_salarie": "3.06", "taux_amo_employeur": "3.5",
        }
        for valeur, valide in (("", True), ("  70 00 00 01 ", True), ("+223 70 00 00 01", True), ("abc", False), ("123", False)):
            with self.subTest(valeur=valeur):
                formulaire = ParametresEtablissementForm({**envoi, "telephone_facturation": valeur}, instance=self.alpha)
                self.assertEqual(formulaire.is_valid(), valide, formulaire.errors)
                if valide:
                    self.assertEqual(formulaire.cleaned_data["telephone_facturation"], valeur.strip())
                else:
                    self.assertIn("telephone_facturation", formulaire.errors)


@override_settings(INDICATIF_TELEPHONIQUE="223", LONGUEUR_NUMERO_LOCAL=8)
class LienWhatsappTests(FacturesParEmailBase):
    def setUp(self):
        Etablissement.objects.filter(pk=self.alpha.pk).update(telephone_facturation="+223 70 00 00 01")
        self.alpha.refresh_from_db()

    def test_le_message_d_une_facture_dans_les_delais(self):
        facture = self.facturer(date_echeance=datetime.date(2030, 3, 15))
        numero, texte = decouper(ajouter_les_liens_whatsapp([facture])[0].lien_whatsapp)
        self.assertEqual(numero, "22370000001")
        for attendu in (facture.numero, "École Alpha", "120 000 FCFA", "15/03/2030", "Orange Money : 70 00 00 00", "Yelenova Test"):
            self.assertIn(attendu, texte)
        self.assertNotIn("rappel", texte.lower())

    def test_le_message_d_une_facture_en_retard_est_un_rappel(self):
        facture = self.facture_en_retard(jours=12)
        _, texte = decouper(ajouter_les_liens_whatsapp([facture])[0].lien_whatsapp)
        self.assertIn("rappel", texte.lower())
        self.assertIn("12 jours de retard", texte)

    def test_un_jour_de_retard_au_singulier(self):
        self.assertIn("1 jour de retard", message_whatsapp(self.facture_en_retard(jours=1)))

    def test_le_message_ne_nomme_jamais_une_autre_ecole(self):
        self.facturer(self.beta, datetime.date(2031, 1, 1), datetime.date(2031, 12, 31))
        facture = self.facturer(self.alpha)
        _, texte = decouper(ajouter_les_liens_whatsapp([facture])[0].lien_whatsapp)
        self.assertNotIn("Beta", texte)

    def test_pas_de_lien_pour_une_facture_payee_ou_annulee(self):
        payee = self.facturer(self.alpha, datetime.date(2030, 1, 1), datetime.date(2030, 12, 31))
        enregistrer_reglement(facture=payee, date_paiement=aujourdhui(), mode_reglement="especes")
        annulee = self.facturer(self.alpha, datetime.date(2031, 1, 1), datetime.date(2031, 12, 31))
        annulee.statut = STATUT.ANNULEE
        annulee.save()
        payee.refresh_from_db()  # enregistrer_reglement travaille sur sa propre copie de la facture
        for facture in ajouter_les_liens_whatsapp([payee, annulee]):
            self.assertEqual(facture.lien_whatsapp, "")

    def test_une_ecole_sans_numero_n_a_pas_de_lien(self):
        facture = self.facturer(self.beta)
        self.assertEqual(ajouter_les_liens_whatsapp([facture])[0].lien_whatsapp, "")

    def test_un_numero_inutilisable_n_a_pas_de_lien(self):
        Etablissement.objects.filter(pk=self.alpha.pk).update(telephone_facturation="12")
        facture = FactureAbonnement.objects.select_related("etablissement").get(pk=self.facturer(self.alpha).pk)
        self.assertEqual(ajouter_les_liens_whatsapp([facture])[0].lien_whatsapp, "")

    def test_une_page_de_factures_ne_fait_pas_une_requete_par_ligne(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.client.force_login(self.proprietaire)
        adresse = reverse("espace_plateforme:liste_factures")

        def requetes():
            with CaptureQueriesContext(connection) as contexte:
                self.client.get(adresse)
            return len(contexte)

        for numero in range(3):
            self.facturer(Etablissement.objects.create(nom=f"École {numero}", telephone_facturation=f"+223 70 00 10 {numero:02d}"))
        self.client.get(adresse)  # amorce ce qui se met en cache
        avant = requetes()
        for numero in range(3, 9):
            self.facturer(Etablissement.objects.create(nom=f"École {numero}", telephone_facturation=f"+223 70 00 10 {numero:02d}"))
        self.assertEqual(requetes(), avant)


@override_settings(INDICATIF_TELEPHONIQUE="223", LONGUEUR_NUMERO_LOCAL=8)
class BoutonWhatsappDeLaListeTests(FacturesParEmailBase):
    def setUp(self):
        Etablissement.objects.filter(pk=self.alpha.pk).update(telephone_facturation="+223 70 00 00 01")
        self.client.force_login(self.proprietaire)

    def test_le_bouton_ouvre_whatsapp_sur_le_numero_de_l_ecole(self):
        facture = self.facturer(self.alpha)
        page = self.client.get(reverse("espace_plateforme:liste_factures"))
        self.assertContains(page, ">WhatsApp</a>")
        self.assertContains(page, "https://wa.me/22370000001?text=")
        self.assertContains(page, 'rel="noopener"')
        self.assertEqual(page.context["factures"][0].numero, facture.numero)

    def test_aucun_envoi_par_le_serveur(self):
        self.facturer(self.alpha)
        self.client.get(reverse("espace_plateforme:liste_factures"))
        self.assertEqual(mail.outbox, [])

    def test_une_ecole_sans_numero_propose_d_en_ajouter_un(self):
        facture = self.facturer(self.beta)
        page = self.client.get(reverse("espace_plateforme:liste_factures"))
        self.assertNotContains(page, ">WhatsApp</a>")
        self.assertContains(page, "+ N° WhatsApp")
        self.assertContains(page, reverse("espace_plateforme:modifier_etablissement", args=[facture.etablissement_id]))

    def test_pas_de_bouton_sur_une_facture_payee(self):
        facture = self.facturer(self.alpha)
        enregistrer_reglement(facture=facture, date_paiement=aujourdhui(), mode_reglement="mobile_money")
        page = self.client.get(reverse("espace_plateforme:liste_factures"))
        self.assertNotContains(page, ">WhatsApp</a>")
        self.assertNotContains(page, "+ N° WhatsApp")

    def test_le_champ_figure_sur_la_page_de_modification_de_l_ecole(self):
        page = self.client.get(reverse("espace_plateforme:modifier_etablissement", args=[self.alpha.id]))
        self.assertContains(page, 'name="telephone_facturation"')
        self.assertContains(page, 'name="email_facturation"')

    def test_reserve_au_proprietaire(self):
        self.facturer(self.alpha)
        for compte in (self.dev_alpha, self.fondateur_alpha):
            self.client.force_login(compte)
            reponse = self.client.get(reverse("espace_plateforme:liste_factures"))
            self.assertEqual(reponse.status_code, 302)
            self.assertNotIn(b"wa.me", reponse.content)


class AlertesDesFacturesTests(FacturesParEmailBase):
    def test_aucune_alerte_sans_facture_a_encaisser(self):
        self.assertEqual(alertes_factures(), [])
        payee = self.facturer(self.alpha, datetime.date(2030, 1, 1), datetime.date(2030, 12, 31))
        enregistrer_reglement(facture=payee, date_paiement=aujourdhui(), mode_reglement="virement")
        annulee = self.facturer(self.beta)
        annulee.statut = STATUT.ANNULEE
        annulee.save()
        self.assertEqual(alertes_factures(), [])

    def test_les_factures_en_retard_donnent_une_alerte_rouge_en_premier(self):
        retard = self.facture_en_retard(self.alpha, jours=9, montant=100000)
        a_payer = self.facturer(self.beta, montant=40000, date_echeance=aujourdhui() + 5 * JOUR)
        alertes = alertes_factures()
        self.assertEqual([a["statut"] for a in alertes], ["en_retard", "a_payer"])
        rouge, orange = alertes
        self.assertEqual(rouge["gravite"], "danger")
        self.assertEqual(rouge["titre"], "1 facture d'abonnement en retard de paiement")
        self.assertEqual(rouge["description"], "100 000 FCFA à encaisser ; la plus ancienne a 9 jours de retard.")
        self.assertEqual([f.pk for f in rouge["factures"]], [retard.pk])
        self.assertEqual(orange["gravite"], "attention")
        self.assertEqual(orange["titre"], "1 facture d'abonnement à payer")
        self.assertEqual(orange["description"], f"40 000 FCFA à encaisser ; prochaine échéance le {aujourdhui() + 5 * JOUR:%d/%m/%Y}.")
        self.assertEqual([f.pk for f in orange["factures"]], [a_payer.pk])

    def test_pluriels_totaux_et_la_plus_ancienne(self):
        self.facture_en_retard(self.alpha, jours=1, montant=100000)
        self.facture_en_retard(self.beta, jours=30, montant=50000)
        alerte = alertes_factures()[0]
        self.assertEqual(alerte["titre"], "2 factures d'abonnement en retard de paiement")
        self.assertEqual(alerte["description"], "150 000 FCFA à encaisser ; la plus ancienne a 30 jours de retard.")
        self.assertEqual([f.etablissement.nom for f in alerte["factures"]], ["École Beta", "École Alpha"])  # la plus en retard d'abord

    def test_le_jour_de_l_echeance_ce_n_est_pas_encore_un_retard(self):
        self.facturer(self.alpha, date_echeance=aujourdhui())
        self.assertEqual([a["statut"] for a in alertes_factures()], ["a_payer"])

    def test_le_titre_et_la_description_ne_nomment_aucune_ecole(self):
        self.facture_en_retard(self.alpha)
        self.facturer(self.beta)
        for alerte in alertes_factures():
            self.assertNotIn("Alpha", alerte["titre"] + alerte["description"])
            self.assertNotIn("Beta", alerte["titre"] + alerte["description"])


class AlertesAffichageTests(FacturesParEmailBase):
    PAGES = ("liste_etablissements", "abonnements", "liste_factures")

    def setUp(self):
        self.client.force_login(self.proprietaire)

    def test_les_trois_pages_du_proprietaire_montrent_les_alertes(self):
        self.facture_en_retard(self.alpha, jours=4)
        self.facturer(self.beta, date_echeance=aujourdhui() + 3 * JOUR)
        for nom in self.PAGES:
            with self.subTest(page=nom):
                page = self.client.get(reverse(f"espace_plateforme:{nom}"))
                self.assertContains(page, "en retard de paiement")
                self.assertContains(page, "facture d&#x27;abonnement à payer")
                self.assertContains(page, f'{reverse("espace_plateforme:liste_factures")}?statut=en_retard')
                self.assertContains(page, f'{reverse("espace_plateforme:liste_factures")}?statut=a_payer')
                self.assertContains(page, "alert-danger")

    def test_rien_quand_tout_est_paye(self):
        for nom in self.PAGES:
            with self.subTest(page=nom):
                page = self.client.get(reverse(f"espace_plateforme:{nom}"))
                self.assertNotContains(page, "en retard de paiement")
                self.assertNotContains(page, "facture d&#x27;abonnement à payer")

    def test_le_proprietaire_est_renvoye_vers_la_liste_des_etablissements_ou_l_alerte_se_voit(self):
        self.facture_en_retard(self.alpha)
        reponse = self.client.get(reverse("comptes:redirection_tableau_de_bord"))
        self.assertRedirects(reponse, reverse("espace_plateforme:liste_etablissements"), fetch_redirect_response=False)
        self.assertContains(self.client.get(reponse["Location"]), "en retard de paiement")

    def test_le_filtre_a_payer_ne_montre_que_les_factures_dans_les_delais(self):
        retard = self.facture_en_retard(self.alpha)
        dans_les_delais = self.facturer(self.beta, date_echeance=aujourdhui() + 5 * JOUR)
        page = self.client.get(reverse("espace_plateforme:liste_factures"), {"statut": "a_payer"})
        self.assertEqual([f.pk for f in page.context["factures"]], [dans_les_delais.pk])
        page = self.client.get(reverse("espace_plateforme:liste_factures"), {"statut": "en_retard"})
        self.assertEqual([f.pk for f in page.context["factures"]], [retard.pk])

    def test_un_compte_d_ecole_ne_voit_jamais_ces_alertes(self):
        self.facture_en_retard(self.alpha)
        self.client.force_login(self.fondateur_alpha)
        for adresse in (reverse("comptes:redirection_tableau_de_bord"), reverse("espace_plateforme:liste_etablissements")):
            reponse = self.client.get(adresse, follow=True)
            self.assertNotContains(reponse, "en retard de paiement")
