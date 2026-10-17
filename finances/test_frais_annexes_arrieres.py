"""
Frais annexes (tenue, examen, transport...) et arriérés des années passées.

Jeu de données (EducationBase) : 6A (2026-2027) a un échéancier de 30 000 (inscription 10 000 + 20 000 en un versement) ; la 5A de l'année
passée (2025-2026) en a un de 20 000. e1 était en 5A (redoublante), e2 aussi (admis) : leur année passée peut donc avoir un arriéré.
"""
import datetime

from django.core import mail
from django.test import override_settings
from django.urls import reverse

from comptes.arabisation import invalider
from comptes.models import JournalAudit, Utilisateur
from comptes.outils_test_arabe import client_en
from comptes.roles import Role
from comptes.traduction import restes_latins
from comptabilite.services import vecteur_attendu
from finances.annexes import (
    arrieres_des_eleves, limite_de_paiement, lignes_d_arrieres, inscriptions_passees, reste_a_payer, totaux_annexes,
)
from finances.models import FraisAnnexe, MouvementCaisse, Paiement, TypeTranche, enregistrer_paiement
from scolarite.models import (
    AideScolarite, EcheancierFrais, Inscription, Periodicite, calculer_scolarite_nette, calculer_total_du, total_frais_annexes,
)
from statistiques.test_education import EducationBase, creer_compte

D = datetime.date


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", EMAIL_ASYNC=False)
class AnnexesBase(EducationBase):
    def setUp(self):
        EcheancierFrais.objects.create(classe=self.c6a, montant_inscription=10000, periodicite=Periodicite.ANNUEL, montant_periode=20000, nombre_versements=1)
        EcheancierFrais.objects.create(classe=self.classe_5a, montant_inscription=10000, periodicite=Periodicite.ANNUEL, montant_periode=10000, nombre_versements=1)
        self.comptable = creer_compte(Role.COMPTABLE, "comptable@annexes.test", self.ecole)
        self.insc = Inscription.objects.get(eleve=self.e1, classe=self.c6a)
        self.insc_passee = Inscription.objects.get(eleve=self.e1, classe=self.classe_5a)
        self.insc_e2_passee = Inscription.objects.get(eleve=self.e2, classe=self.classe_5a)

    def frais(self, libelle="Tenue", montant=7500, classe=None, annee=None, ecole=None, **extra):
        return FraisAnnexe.objects.create(
            etablissement=ecole or self.ecole, annee_scolaire=annee or (classe.annee_scolaire if classe else self.annee), classe=classe,
            libelle=libelle, montant=montant, **extra,
        )

    def payer(self, eleve=None, tranche="versement", montant=1000, **champs):
        donnees = {"matricule_eleve": (eleve or self.e1).matricule, "tranche": tranche, "montant": montant, "mode_paiement": "especes"}
        donnees.update(champs)
        self.client.force_login(self.comptable)
        return self.client.post(reverse("finances:enregistrer_paiement"), donnees)


class CalculDuTests(AnnexesBase):
    def test_sans_frais_annexe_le_du_ne_change_pas(self):
        self.assertEqual(total_frais_annexes(self.insc), 0)
        self.assertEqual(calculer_total_du(self.insc), 30000)
        self.assertEqual(calculer_total_du(self.insc), calculer_scolarite_nette(self.insc))

    def test_le_du_ajoute_les_frais_de_la_classe_et_de_toute_l_ecole(self):
        self.frais("Tenue", 7500, classe=self.c6a)
        self.frais("Assurance", 2500)  # toute l'école
        self.frais("Tenue 6B", 9000, classe=self.c6b)  # une autre classe
        self.frais("Frais d'une autre année", 4000, annee=self.precedente)
        self.frais("Frais d'une autre école", 5000, ecole=self.ecole_b, annee=self.annee_b)
        self.assertEqual(total_frais_annexes(self.insc), 10000)
        self.assertEqual(calculer_total_du(self.insc), 40000)

    def test_les_aides_ne_reduisent_que_la_scolarite(self):
        self.frais("Tenue", 10000, classe=self.c6a)
        AideScolarite.objects.create(inscription=self.insc, type_aide="remise", pourcentage=50, motif="Fratrie", accordee_par=self.fondateur)
        self.assertEqual(calculer_scolarite_nette(self.insc), 15000)
        self.assertEqual(calculer_total_du(self.insc), 25000)  # 15 000 de scolarité + 10 000 de tenue, intacts

    def test_la_version_groupee_donne_les_memes_totaux_en_une_requete(self):
        self.frais("Tenue", 7500, classe=self.c6a)
        self.frais("Assurance", 2500)
        inscriptions = list(Inscription.objects.filter(classe__in=[self.c6a, self.c6b]).select_related("classe"))
        with self.assertNumQueries(1):
            total = totaux_annexes(inscriptions)
        for inscription in inscriptions:
            self.assertEqual(total(inscription), total_frais_annexes(inscription))
        self.assertEqual(total(inscriptions[0]) + total(next(i for i in inscriptions if i.classe == self.c6b)), 10000 + 2500)

    def test_un_frais_n_est_valide_que_s_il_est_coherent(self):
        from django.core.exceptions import ValidationError

        for erreur in (
            FraisAnnexe(etablissement=self.ecole, annee_scolaire=self.annee, libelle="x", montant=0),
            FraisAnnexe(etablissement=self.ecole, annee_scolaire=self.precedente, classe=self.c6a, libelle="x", montant=100),  # classe d'une autre année
            FraisAnnexe(etablissement=self.ecole, annee_scolaire=self.annee_b, libelle="x", montant=100),  # année d'une autre école
        ):
            with self.assertRaises(ValidationError):
                erreur.full_clean()


class GestionDesFraisTests(AnnexesBase):
    donnees = {"annee_scolaire": None, "classe": "", "libelle": "  Tenue   scolaire ", "montant": 7500, "date_limite": "2026-12-15"}

    def url(self):
        return reverse("finances:frais_annexes")

    def donnees_valides(self, **extra):
        return {**self.donnees, "annee_scolaire": self.annee.pk, **extra}

    def test_le_comptable_et_la_direction_ajoutent_un_frais(self):
        for compte in (self.comptable, self.fondateur):
            FraisAnnexe.objects.all().delete()
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                reponse = self.client.post(self.url(), self.donnees_valides(classe=self.c6a.pk))
                self.assertRedirects(reponse, self.url())
                frais = FraisAnnexe.objects.get()
                self.assertEqual((frais.libelle, frais.montant, frais.classe, frais.etablissement, frais.cree_par), ("Tenue scolaire", 7500, self.c6a, self.ecole, compte))
                self.assertEqual(frais.date_limite, D(2026, 12, 15))

    def test_un_frais_pour_toute_l_ecole(self):
        self.client.force_login(self.comptable)
        self.client.post(self.url(), self.donnees_valides())
        self.assertIsNone(FraisAnnexe.objects.get().classe)

    def test_les_erreurs_sont_expliquees(self):
        self.client.force_login(self.comptable)
        for donnees, erreur in (
            (self.donnees_valides(montant=0), "supérieure ou égale à 1"),
            (self.donnees_valides(libelle=""), "obligatoire"),
            (self.donnees_valides(classe=self.classe_5a.pk), "appartient pas à l"),  # une classe de l'année passée, pour 2026-2027
            (self.donnees_valides(classe=self.classe_b.pk), "Sélectionnez un choix valide"),  # la classe d'une autre école
        ):
            with self.subTest(erreur=erreur):
                self.assertContains(self.client.post(self.url(), donnees), erreur)
        self.assertEqual(FraisAnnexe.objects.count(), 0)

    def test_seuls_les_roles_financiers_gerent_les_frais(self):
        frais = self.frais()
        for compte in (self.secretaire, self.t1, self.parent, self.e1, self.dir_1er):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertEqual(self.client.get(self.url()).status_code, 403)
                self.assertEqual(self.client.post(self.url(), self.donnees_valides()).status_code, 403)
                self.assertEqual(self.client.post(reverse("finances:supprimer_frais_annexe", args=[frais.pk])).status_code, 403)
        self.assertEqual(FraisAnnexe.objects.count(), 1)

    def test_la_page_donne_les_chiffres_de_chaque_frais(self):
        frais = self.frais("Tenue", 7500, classe=self.c6a)
        self.payer(tranche="annexe", montant=7500, frais_annexe=frais.pk)
        self.payer(eleve=self.e2, tranche="annexe", montant=3000, frais_annexe=frais.pk)
        self.client.force_login(self.comptable)
        ligne = self.client.get(self.url()).context["liste"][0]
        self.assertEqual((ligne["concernes"], ligne["total_attendu"], ligne["total_paye"], ligne["payeurs"]), (3, 22500, 10500, 2))
        self.assertFalse(ligne["supprimable"])

    def test_supprimer_un_frais_sans_paiement(self):
        frais = self.frais()
        self.client.force_login(self.comptable)
        self.assertEqual(self.client.get(reverse("finances:supprimer_frais_annexe", args=[frais.pk])).status_code, 405)
        self.client.post(reverse("finances:supprimer_frais_annexe", args=[frais.pk]))
        self.assertFalse(FraisAnnexe.objects.exists())
        self.assertTrue(JournalAudit.objects.filter(action="suppression_frais_annexe").exists())

    def test_un_frais_deja_paye_ne_se_supprime_plus(self):
        frais = self.frais("Tenue", 7500, classe=self.c6a)
        self.payer(tranche="annexe", montant=1000, frais_annexe=frais.pk)
        reponse = self.client.post(reverse("finances:supprimer_frais_annexe", args=[frais.pk]), follow=True)
        self.assertContains(reponse, "ne peut plus être supprimé")
        self.assertTrue(FraisAnnexe.objects.filter(pk=frais.pk).exists())

    def test_une_autre_ecole_ne_voit_ni_ne_supprime_mes_frais(self):
        frais = self.frais("Uniforme zqx")
        self.client.force_login(self.fondateur_b)
        self.assertNotContains(self.client.get(self.url()), "Uniforme zqx")
        self.assertEqual(self.client.post(reverse("finances:supprimer_frais_annexe", args=[frais.pk])).status_code, 404)

    def test_le_menu_propose_les_frais_et_les_arrieres_aux_roles_financiers(self):
        for compte, attendu in ((self.comptable, True), (self.fondateur, True), (self.parent, False), (self.secretaire, False)):
            self.client.force_login(compte)
            page = self.client.get(reverse("comptes:redirection_tableau_de_bord"), follow=True).content.decode()
            with self.subTest(compte=compte.email):
                self.assertEqual(self.url() in page, attendu)
                self.assertEqual(reverse("finances:arrieres") in page, attendu)


class PaiementDeFraisAnnexesTests(AnnexesBase):
    def setUp(self):
        super().setUp()
        self.tenue = self.frais("Tenue", 7500, classe=self.c6a)

    def test_un_paiement_de_frais_annexe(self):
        reponse = self.payer(tranche="annexe", montant=5000, frais_annexe=self.tenue.pk)
        self.assertRedirects(reponse, reverse("finances:liste_paiements"))
        paiement = Paiement.objects.get()
        self.assertEqual((paiement.tranche, paiement.frais_annexe, paiement.montant, paiement.inscription), ("annexe", self.tenue, 5000, self.insc))
        self.assertEqual(paiement.mouvement_caisse.description, f"Frais annexe - Tenue - {self.e1.nom_complet}")

    def test_la_comptabilite_range_un_frais_annexe_en_autres_services_vendus(self):
        self.payer(tranche="annexe", montant=5000, frais_annexe=self.tenue.pk)
        self.payer(tranche="versement", montant=1000)
        self.payer(tranche="inscription", montant=1000)
        attendus = {m.paiement.tranche: vecteur_attendu(m) for m in MouvementCaisse.objects.select_related("paiement")}
        self.assertEqual(attendus["annexe"], {"571": 5000, "70608": -5000})
        self.assertEqual(attendus["versement"], {"571": 1000, "70602": -1000})
        self.assertEqual(attendus["inscription"], {"571": 1000, "70601": -1000})

    def test_le_frais_est_obligatoire_et_doit_concerner_l_eleve(self):
        for champs, erreur in (
            ({"tranche": "annexe"}, "Choisissez le frais annexe"),
            ({"tranche": "annexe", "frais_annexe": self.frais("Tenue 6B", 9000, classe=self.c6b).pk}, "ne concerne pas cet élève"),
            ({"tranche": "annexe", "frais_annexe": self.frais("Ancien", 4000, annee=self.precedente).pk}, "ne concerne pas cet élève"),
            ({"tranche": "versement", "frais_annexe": self.tenue.pk}, "se règle avec la tranche"),
        ):
            with self.subTest(erreur=erreur):
                self.assertContains(self.payer(**champs), erreur)
        self.assertEqual(Paiement.objects.count(), 0)

    def test_un_frais_ne_se_regle_pas_deux_fois_au_dela_de_son_montant(self):
        self.assertRedirects(self.payer(tranche="annexe", montant=5000, frais_annexe=self.tenue.pk), reverse("finances:liste_paiements"))
        reponse = self.payer(tranche="annexe", montant=3000, frais_annexe=self.tenue.pk)  # il ne reste que 2 500
        self.assertContains(reponse, "dépasse le reste dû (2500 FCFA)")
        self.assertRedirects(self.payer(tranche="annexe", montant=2500, frais_annexe=self.tenue.pk), reverse("finances:liste_paiements"))
        self.assertContains(self.payer(tranche="annexe", montant=1, frais_annexe=self.tenue.pk), "dépasse le reste dû (0 FCFA)")

    def test_chaque_eleve_regle_son_propre_frais(self):
        self.payer(tranche="annexe", montant=7500, frais_annexe=self.tenue.pk)
        self.assertRedirects(self.payer(eleve=self.e2, tranche="annexe", montant=7500, frais_annexe=self.tenue.pk), reverse("finances:liste_paiements"))

    def test_un_paiement_supprime_libere_le_reste(self):
        self.payer(tranche="annexe", montant=7500, frais_annexe=self.tenue.pk)
        Paiement.objects.update(est_supprime=True)
        self.assertEqual(limite_de_paiement(self.insc, TypeTranche.ANNEXE, self.tenue), 7500)

    def test_le_solde_tient_compte_du_frais_et_de_son_paiement(self):
        self.assertEqual(reste_a_payer(self.insc), 37500)
        self.payer(tranche="annexe", montant=7500, frais_annexe=self.tenue.pk)
        self.payer(tranche="inscription", montant=10000)
        self.assertEqual(reste_a_payer(self.insc), 20000)
        self.client.force_login(self.comptable)
        ligne = next(l for l in self.client.get(reverse("finances:suivi_paiements")).context["lignes"] if l["inscription"] == self.insc)
        self.assertEqual((ligne["total_du"], ligne["total_paye"], ligne["solde"], ligne["statut"]), (37500, 17500, 20000, "partiel"))

    def test_le_dossier_et_le_portail_parent_comptent_le_frais(self):
        self.client.force_login(self.fondateur)
        self.assertEqual(self.client.get(reverse("scolarite:dossier_eleve", args=[self.e1.matricule])).context["solde_annee_active"], 37500)
        self.client.force_login(self.parent)
        dossier = next(d for d in self.client.get(reverse("comptes:portail_parent")).context["dossiers"] if d["eleve"] == self.e1)
        self.assertEqual(dossier["solde"], 37500)

    def test_le_courriel_du_parent_donne_le_reste_a_payer_avec_les_frais(self):
        self.payer(tranche="annexe", montant=7500, frais_annexe=self.tenue.pk)
        self.assertIn("Reste à payer : 30000 FCFA.", mail.outbox[-1].body)

    def test_le_recu_et_la_liste_nomment_le_frais(self):
        self.payer(tranche="annexe", montant=7500, frais_annexe=self.tenue.pk)
        self.assertContains(self.client.get(reverse("finances:liste_paiements")), "Tenue")
        recu = self.client.get(reverse("finances:exporter_recu_paiement_pdf", args=[Paiement.objects.get().pk]))
        self.assertEqual(recu.status_code, 200)

    def test_les_statistiques_ont_une_ligne_pour_les_frais_annexes(self):
        self.payer(tranche="annexe", montant=7500, frais_annexe=self.tenue.pk)
        reponse = self.client.get(reverse("statistiques:statistiques_finances"), {"annee": self.annee.pk})
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual({l["libelle"]: l["total"] for l in reponse.context["par_tranche"]}["Frais annexe"], 7500)


class GardeFouDuMontantTests(AnnexesBase):
    def test_on_ne_peut_pas_depasser_la_scolarite(self):
        self.assertContains(self.payer(montant=30001), "dépasse le reste dû (30000 FCFA)")
        self.assertEqual(Paiement.objects.count(), 0)
        self.assertRedirects(self.payer(montant=30000), reverse("finances:liste_paiements"))  # exactement le reste : permis

    def test_le_reste_baisse_a_chaque_paiement(self):
        self.payer(montant=12000)
        self.assertContains(self.payer(montant=18001), "dépasse le reste dû (18000 FCFA)")

    def test_une_remise_baisse_aussi_le_plafond(self):
        AideScolarite.objects.create(inscription=self.insc, type_aide="remise", pourcentage=50, motif="Fratrie", accordee_par=self.fondateur)
        self.assertContains(self.payer(montant=15001), "dépasse le reste dû (15000 FCFA)")

    def test_sans_echeancier_aucun_plafond(self):
        EcheancierFrais.objects.filter(classe=self.c6a).delete()
        self.assertRedirects(self.payer(montant=999999), reverse("finances:liste_paiements"))

    def test_un_frais_annexe_paye_ne_reduit_pas_le_plafond_de_la_scolarite(self):
        tenue = self.frais("Tenue", 7500, classe=self.c6a)
        self.payer(tranche="annexe", montant=7500, frais_annexe=tenue.pk)
        self.assertEqual(limite_de_paiement(self.insc, TypeTranche.VERSEMENT), 30000)

    def test_l_enregistrement_direct_reste_possible_sans_garde_fou(self):
        """Seul le formulaire plafonne : le code métier (importations, tests, scripts) garde sa souplesse d'avant."""
        paiement = enregistrer_paiement(
            eleve=self.e1, inscription=self.insc, tranche="versement", montant=99999, mode_paiement="especes", enregistre_par=self.comptable,
        )
        self.assertEqual(paiement.montant, 99999)


class ArrieresTests(AnnexesBase):
    def test_une_annee_passee_impayee_est_un_arriere(self):
        lignes = lignes_d_arrieres(inscriptions_passees(self.fondateur))
        parLigne = {l["inscription"].eleve_id: l for l in lignes}
        self.assertEqual({k: (v["total_du"], v["total_paye"], v["solde"]) for k, v in parLigne.items()}, {
            self.e1.pk: (20000, 0, 20000), self.e2.pk: (20000, 0, 20000),
        })

    def test_l_annee_en_cours_n_est_jamais_un_arriere(self):
        ids = {l["inscription"].pk for l in lignes_d_arrieres(inscriptions_passees(self.fondateur))}
        self.assertNotIn(self.insc.pk, ids)

    def test_ils_sont_calcules_avec_la_classe_de_l_epoque(self):
        EcheancierFrais.objects.filter(classe=self.c6a).update(montant_periode=99000)  # la classe actuelle change : l'arriéré non
        self.assertEqual(arrieres_des_eleves([self.e1], self.fondateur), {self.e1.pk: 20000})
        self.frais("Tenue de l'an dernier", 4000, classe=self.classe_5a)  # un frais annexe de cette année-là s'y ajoute
        self.assertEqual(arrieres_des_eleves([self.e1], self.fondateur), {self.e1.pk: 24000})

    def test_une_remise_de_l_epoque_est_respectee(self):
        AideScolarite.objects.create(inscription=self.insc_passee, type_aide="remise", pourcentage=50, motif="Fratrie", accordee_par=self.fondateur)
        self.assertEqual(arrieres_des_eleves([self.e1], self.fondateur), {self.e1.pk: 10000})

    def test_regler_un_arriere_depuis_le_formulaire(self):
        self.assertRedirects(
            self.payer(montant=20000, inscription_visee=self.insc_passee.pk), reverse("finances:liste_paiements"),
        )
        paiement = Paiement.objects.get()
        self.assertEqual(paiement.inscription, self.insc_passee)  # le paiement va sur l'année passée, pas sur l'année en cours
        self.assertEqual(arrieres_des_eleves([self.e1], self.fondateur), {})
        self.assertEqual(reste_a_payer(self.insc), 30000)  # l'année en cours n'a rien reçu

    def test_un_paiement_partiel_laisse_le_reste(self):
        self.payer(montant=5000, inscription_visee=self.insc_passee.pk)
        self.assertEqual(arrieres_des_eleves([self.e1], self.fondateur), {self.e1.pk: 15000})

    def test_on_ne_depasse_pas_le_reste_de_l_arriere(self):
        self.assertContains(self.payer(montant=20001, inscription_visee=self.insc_passee.pk), "dépasse le reste dû (20000 FCFA)")

    def test_l_inscription_d_un_autre_eleve_est_refusee(self):
        reponse = self.payer(eleve=self.e1, montant=1000, inscription_visee=self.insc_e2_passee.pk)
        self.assertContains(reponse, "appartient pas à cet élève")
        self.assertEqual(Paiement.objects.count(), 0)

    def test_un_eleve_sans_inscription_en_cours_peut_regler_son_arriere(self):
        Inscription.objects.filter(pk=self.insc.pk).update(statut=Inscription.Statut.ABANDON)
        self.assertRedirects(self.payer(montant=1000, inscription_visee=self.insc_passee.pk), reverse("finances:liste_paiements"))
        self.assertContains(self.payer(montant=1000), "pas d&#x27;inscription en cours")  # sans arriéré visé, il en faut une

    def test_la_page_des_arrieres(self):
        self.client.force_login(self.comptable)
        reponse = self.client.get(reverse("finances:arrieres"))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual((len(reponse.context["lignes"]), reponse.context["total"]), (2, 40000))
        self.assertContains(reponse, f"?eleve={self.e1.matricule}&inscription={self.insc_passee.pk}")

    def test_les_filtres_de_la_page(self):
        self.client.force_login(self.comptable)
        url = reverse("finances:arrieres")
        self.assertEqual(len(self.client.get(url, {"annee": self.precedente.pk}).context["lignes"]), 2)
        self.assertEqual(len(self.client.get(url, {"annee": self.annee.pk}).context["lignes"]), 0)
        self.assertEqual(len(self.client.get(url, {"q": self.e2.matricule}).context["lignes"]), 1)
        self.assertEqual(len(self.client.get(url, {"annee": "abc"}).context["lignes"]), 2)  # un filtre invalide est ignoré

    def test_la_page_est_reservee_aux_roles_financiers_et_a_l_ecole(self):
        url = reverse("finances:arrieres")
        for compte in (self.secretaire, self.t1, self.parent, self.e1):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.fondateur_b)
        self.assertEqual(len(self.client.get(url).context["lignes"]), 0)  # l'autre école ne voit aucun de mes arriérés

    def test_le_lien_regler_remplit_le_formulaire(self):
        self.client.force_login(self.comptable)
        url = reverse("finances:enregistrer_paiement")
        page = self.client.get(url, {"eleve": self.e1.matricule, "inscription": self.insc_passee.pk})
        self.assertContains(page, "Règlement d'un arriéré")
        self.assertContains(page, f'value="{self.insc_passee.pk}"')
        self.assertContains(page, self.e1.matricule)

    def test_un_lien_regler_invalide_est_ignore(self):
        self.client.force_login(self.comptable)
        url = reverse("finances:enregistrer_paiement")
        for parametres in (
            {"eleve": self.e1.matricule, "inscription": self.insc_e2_passee.pk},  # l'inscription d'un autre élève
            {"eleve": self.e5.matricule, "inscription": "abc"},
            {"eleve": "N-IMPORTE-QUI", "inscription": "1"},
        ):
            with self.subTest(parametres=parametres):
                page = self.client.get(url, parametres)
                self.assertEqual(page.status_code, 200)
                self.assertNotContains(page, "Règlement d'un arriéré")

    def test_le_suivi_et_le_portail_montrent_les_arrieres(self):
        self.client.force_login(self.comptable)
        ligne = next(l for l in self.client.get(reverse("finances:suivi_paiements")).context["lignes"] if l["inscription"] == self.insc)
        self.assertEqual(ligne["arrieres"], 20000)
        self.client.force_login(self.parent)
        dossier = next(d for d in self.client.get(reverse("comptes:portail_parent")).context["dossiers"] if d["eleve"] == self.e1)
        self.assertEqual(dossier["arrieres"], 20000)
        self.assertContains(self.client.get(reverse("comptes:portail_parent")), "Arriérés des années passées")

    def test_l_enregistrement_est_journalise(self):
        self.payer(montant=1000, inscription_visee=self.insc_passee.pk)
        self.assertTrue(JournalAudit.objects.get(action="enregistrement_paiement").details["arriere"])

    def test_les_requetes_ne_croissent_pas_avec_le_nombre_d_eleves(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as avant:
            lignes_d_arrieres(inscriptions_passees(self.fondateur))
        # le même calcul avec plus d'inscriptions passées
        for numero in range(6):
            eleve = creer_compte(Role.ELEVE, f"ancien{numero}@annexes.test", self.ecole)
            Inscription.objects.create(eleve=eleve, classe=self.classe_5a, statut=Inscription.Statut.ADMIS)
        with CaptureQueriesContext(connection) as apres:
            lignes = lignes_d_arrieres(inscriptions_passees(self.fondateur))
        self.assertEqual(len(lignes), 8)
        self.assertLessEqual(len(apres.captured_queries), len(avant.captured_queries) + 1)


class AnnexesEnArabeTests(AnnexesBase):
    def test_les_pages_sont_en_arabe_pur(self):
        Utilisateur.objects.filter(pk=self.e1.pk).update(prenom="Aminata", nom="Traoré", prenom_ar="أميناتا", nom_ar="تراوري")
        self.e1.refresh_from_db()
        invalider(self.ecole.pk)
        tenue = self.frais("زي مدرسي", 7500, classe=self.c6a)
        client = client_en(self.comptable, "ar")
        pages = [
            reverse("finances:frais_annexes"), reverse("finances:arrieres"), reverse("finances:enregistrer_paiement"),
            reverse("finances:suivi_paiements"), reverse("finances:liste_paiements"),
            reverse("finances:enregistrer_paiement") + f"?eleve={self.e1.matricule}&inscription={self.insc_passee.pk}",
        ]
        for adresse in pages:
            reponse = client.get(adresse)
            self.assertEqual(reponse.status_code, 200, adresse)
            with self.subTest(page=adresse):
                self.assertEqual([t for t in restes_latins(reponse.content.decode()) if t != "Français"], [])
        refus = client.post(reverse("finances:enregistrer_paiement"), {
            "matricule_eleve": self.e1.matricule, "tranche": "annexe", "montant": 99999, "mode_paiement": "especes", "frais_annexe": tenue.pk,
        })
        self.assertEqual([t for t in restes_latins(refus.content.decode()) if t != "Français"], [])
