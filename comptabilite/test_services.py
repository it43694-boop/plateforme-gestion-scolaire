"""
Comptabilité en partie double : écritures, comptabilisation automatique de la caisse, états, clôture, report.

Les montants attendus sont calculés à la main (voir les commentaires de chaque jeu de données) : un test qui échoue
signale un vrai écart comptable, pas un détail d'affichage.
"""
import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from comptabilite import etats, plan
from comptabilite.models import CompteComptable, Ecriture, Exercice, Journal, LigneEcriture
from comptabilite.services import (
    assurer_plan_comptable, cloturer_exercice, contrepasser, creer_compte, creer_ecriture, creer_exercice,
    ecarts_caisse, enregistrer_operation, exercice_suivant, reporter_a_nouveau, synchroniser_caisse, vecteur_attendu,
)
from comptes.models import Utilisateur
from comptes.roles import Role, StatutCompte
from etablissement.models import Etablissement
from finances.models import (
    MouvementCaisse, Salaire, TypeTranche, corriger_paiement, creer_bulletin_paie, enregistrer_paiement,
    marquer_salaire_paye, supprimer_paiement,
)
from scolarite.models import AnneeScolaire, Classe, Cycle, Inscription

ANNEE = timezone.localdate().year
Origine = Ecriture.Origine


def jour(mois, j, annee=ANNEE):
    return datetime.date(annee, mois, j)


def compte_utilisateur(email, role, ecole=None, **extra):
    utilisateur = Utilisateur(
        email=email, prenom="Test", nom=email.split("@")[0], role=role, etablissement=ecole,
        statut=StatutCompte.ACTIF, is_active=True, email_verifie=True, **extra,
    )
    utilisateur.set_unusable_password()
    utilisateur.save()
    return utilisateur


class ComptaBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ecole = Etablissement.objects.create(nom="École comptable A")
        cls.ecole_b = Etablissement.objects.create(nom="École comptable B")
        for ecole in (cls.ecole, cls.ecole_b):
            assurer_plan_comptable(ecole)
        cls.exercice = creer_exercice(etablissement=cls.ecole, libelle=f"Exercice {ANNEE}", date_debut=jour(1, 1), date_fin=jour(12, 31))
        cls.exercice_b = creer_exercice(etablissement=cls.ecole_b, libelle=f"Exercice {ANNEE}", date_debut=jour(1, 1), date_fin=jour(12, 31))
        cls.comptable = compte_utilisateur("comptable-c@compta.test", Role.COMPTABLE, cls.ecole)

    def ecrire(self, lignes, date=None, journal=Journal.OPERATIONS_DIVERSES, libelle="Écriture de test", etablissement=None, **extra):
        return creer_ecriture(
            etablissement=etablissement or self.ecole, journal=journal, date_ecriture=date or jour(3, 1), libelle=libelle,
            lignes=lignes, cree_par=self.comptable, **extra,
        )

    def soldes(self, exercice=None, **options):
        return {s.numero: (s.debit, s.credit) for s in etats.soldes_par_compte(self.ecole, exercice or self.exercice, **options)}


class PlanComptableTests(ComptaBase):
    def test_plan_de_base_cree_pour_chaque_ecole(self):
        total = len(plan.PLAN_DE_BASE)
        self.assertEqual(CompteComptable.objects.filter(etablissement=self.ecole).count(), total)
        self.assertEqual(CompteComptable.objects.filter(etablissement=self.ecole_b).count(), total)
        assurer_plan_comptable(self.ecole)  # idempotent
        self.assertEqual(CompteComptable.objects.filter(etablissement=self.ecole).count(), total)
        numeros = {c.numero for c in CompteComptable.objects.filter(etablissement=self.ecole)}
        for numero in (plan.CAISSE, plan.BANQUE, plan.MONNAIE_ELECTRONIQUE, plan.DROITS_INSCRIPTION, plan.FRAIS_SCOLARITE,
                       plan.REMUNERATIONS_PERSONNEL, plan.CHARGES_SOCIALES, plan.SECURITE_SOCIALE, plan.AUTRES_ORGANISMES_SOCIAUX,
                       plan.IMPOTS_SUR_SALAIRES, plan.RESULTAT_BENEFICE, plan.RESULTAT_PERTE):
            self.assertIn(numero, numeros)
        self.assertEqual(len(numeros), len(plan.PLAN_DE_BASE), "aucun numéro en double dans le plan de base")

    def test_le_plan_de_base_ne_comporte_que_des_classes_1_a_8(self):
        for numero, libelle in plan.PLAN_DE_BASE:
            self.assertTrue(numero.isdigit() and numero[0] in "12345678" and 3 <= len(numero) <= 5, numero)
            self.assertTrue(libelle.strip())

    def test_ajout_d_un_sous_compte(self):
        compte = creer_compte(etablissement=self.ecole, numero="52101", libelle="Banque BDM")
        self.assertFalse(compte.systeme)
        self.assertEqual(compte.classe, 5)
        self.assertFalse(CompteComptable.objects.filter(etablissement=self.ecole_b, numero="52101").exists())

    def test_sous_comptes_refuses(self):
        for numero, libelle, attendu in [
            ("9001", "Hors classe", "commence par 1 à 8"), ("5A1", "Lettres", "chiffres"), ("5", "Trop court", "2 à 10 chiffres"),
            ("571", "Doublon", "existe déjà"), ("52102", "  ", "intitulé"), ("12345678901", "Trop long", "2 à 10 chiffres"),
        ]:
            with self.subTest(numero=numero), self.assertRaisesMessage(ValidationError, attendu):
                creer_compte(etablissement=self.ecole, numero=numero, libelle=libelle)


class ExerciceTests(ComptaBase):
    def test_refus(self):
        for attendu, valeurs in [
            ("postérieure", dict(libelle="X", date_debut=jour(1, 1, ANNEE + 1), date_fin=jour(1, 1, ANNEE + 1))),
            ("chevauche", dict(libelle="Y", date_debut=jour(6, 1), date_fin=jour(6, 1, ANNEE + 1))),
            ("existe déjà", dict(libelle=f"Exercice {ANNEE}", date_debut=jour(1, 1, ANNEE + 1), date_fin=jour(12, 31, ANNEE + 1))),
            ("deux ans", dict(libelle="Z", date_debut=jour(1, 1, ANNEE + 1), date_fin=jour(1, 1, ANNEE + 4))),
            ("libellé", dict(libelle=" ", date_debut=jour(1, 1, ANNEE + 1), date_fin=jour(12, 31, ANNEE + 1))),
        ]:
            with self.subTest(attendu=attendu), self.assertRaisesMessage(ValidationError, attendu):
                creer_exercice(etablissement=self.ecole, **valeurs)

    def test_meme_libelle_possible_dans_une_autre_ecole(self):
        self.assertEqual(self.exercice.libelle, self.exercice_b.libelle)


class EcritureTests(ComptaBase):
    def test_ecriture_equilibree(self):
        ecriture = self.ecrire([("521", 100000, 0), ("101", 0, 100000)], libelle="Apport en capital")
        self.assertEqual(ecriture.numero, f"OD-{ANNEE}-000001")
        self.assertEqual((ecriture.total, ecriture.exercice, ecriture.origine), (100000, self.exercice, Origine.MANUELLE))
        self.assertEqual(self.soldes(), {"521": (100000, 0), "101": (0, 100000)})

    def test_numerotation_par_journal(self):
        premiere = self.ecrire([("521", 10, 0), ("101", 0, 10)])
        deuxieme = self.ecrire([("521", 10, 0), ("101", 0, 10)])
        caisse = self.ecrire([("571", 10, 0), ("101", 0, 10)], journal=Journal.CAISSE)
        self.assertEqual((premiere.numero[-6:], deuxieme.numero[-6:], caisse.numero), ("000001", "000002", f"CAI-{ANNEE}-000001"))

    def test_ecritures_refusees(self):
        for attendu, lignes, extra in [
            ("déséquilibrée", [("521", 100, 0), ("101", 0, 90)], {}),
            ("au moins deux lignes", [("521", 100, 0)], {}),
            ("n'existe pas", [("521", 100, 0), ("999999", 0, 100)], {}),
            ("pas les deux", [("521", 100, 100), ("101", 0, 0)], {}),
            ("montant", [("521", 100, 0), ("101", 0, 0), ("131", 0, 100)], {}),
            ("négatifs", [("521", -100, 0), ("101", 0, -100)], {}),
            ("libellé", [("521", 100, 0), ("101", 0, 100)], {"libelle": "  "}),
            ("Aucun exercice", [("521", 100, 0), ("101", 0, 100)], {"date": jour(1, 1, ANNEE + 5)}),
        ]:
            with self.subTest(attendu=attendu), self.assertRaisesMessage(ValidationError, attendu):
                self.ecrire(lignes, **extra)
        self.assertFalse(Ecriture.objects.exists())

    def test_un_compte_d_une_autre_ecole_est_refuse(self):
        compte_b = CompteComptable.objects.get(etablissement=self.ecole_b, numero="521")
        with self.assertRaisesMessage(ValidationError, "n'appartient pas"):
            self.ecrire([(compte_b, 100, 0), ("101", 0, 100)])

    def test_exercice_cloture_refuse(self):
        Exercice.objects.filter(pk=self.exercice.pk).update(cloture=True)
        with self.assertRaisesMessage(ValidationError, "clôturé"):
            self.ecrire([("521", 100, 0), ("101", 0, 100)])

    def test_contraintes_de_base_de_donnees(self):
        ecriture = self.ecrire([("521", 100, 0), ("101", 0, 100)])
        compte = CompteComptable.objects.get(etablissement=self.ecole, numero="521")
        for valeurs in (dict(debit=100, credit=100), dict(debit=0, credit=0), dict(debit=-5, credit=0)):
            with self.subTest(valeurs=valeurs), self.assertRaises(IntegrityError), transaction.atomic():
                LigneEcriture.objects.create(ecriture=ecriture, compte=compte, **valeurs)

    def test_balance_toujours_equilibree(self):
        self.ecrire([("521", 1000, 0), ("101", 0, 1000)])
        self.ecrire([("622", 300, 0), ("401", 0, 300)])
        _, totaux = etats.balance(self.ecole, self.exercice)
        self.assertEqual((totaux["debit"], totaux["credit"], totaux["equilibree"]), (1300, 1300, True))


class ContrepassationTests(ComptaBase):
    def test_contrepassation_annule_l_ecriture(self):
        ecriture = self.ecrire([("622", 80000, 0), ("401", 0, 80000)], libelle="Loyer")
        inverse = contrepasser(ecriture=ecriture, acteur=self.comptable, motif="Facture reçue deux fois")
        self.assertEqual(inverse.origine, Origine.CONTREPASSATION)
        self.assertEqual(inverse.contrepasse_de, ecriture)
        self.assertIn(ecriture.numero, inverse.libelle)
        self.assertEqual(self.soldes(), {"622": (80000, 80000), "401": (80000, 80000)})  # soldes nuls
        self.assertTrue(all(s.solde == 0 for s in etats.soldes_par_compte(self.ecole, self.exercice)))
        self.assertEqual(Ecriture.objects.count(), 2, "l'écriture d'origine est conservée")

    def test_une_ecriture_ne_se_contrepasse_qu_une_fois(self):
        ecriture = self.ecrire([("622", 100, 0), ("401", 0, 100)])
        contrepasser(ecriture=ecriture)
        ecriture = Ecriture.objects.get(pk=ecriture.pk)
        with self.assertRaisesMessage(ValidationError, "déjà été contre-passée"):
            contrepasser(ecriture=ecriture)

    def test_origines_non_contrepassables(self):
        for origine in (Origine.AUTOMATIQUE, Origine.CLOTURE, Origine.REPORT, Origine.CONTREPASSATION):
            ecriture = self.ecrire([("622", 100, 0), ("401", 0, 100)], origine=origine)
            with self.subTest(origine=origine), self.assertRaises(ValidationError):
                contrepasser(ecriture=ecriture)

    def test_contrepassation_impossible_dans_un_exercice_cloture(self):
        ecriture = self.ecrire([("622", 100, 0), ("401", 0, 100)])
        Exercice.objects.filter(pk=self.exercice.pk).update(cloture=True)
        with self.assertRaisesMessage(ValidationError, "clôturé"):
            contrepasser(ecriture=ecriture, date=jour(6, 1))


class OperationSimpleTests(ComptaBase):
    def test_depense_en_especes(self):
        ecriture = enregistrer_operation(
            etablissement=self.ecole, type_operation="depense", date_ecriture=jour(3, 10), montant=50000,
            compte="605", mode="especes", libelle="Facture d'électricité", piece="F-123", cree_par=self.comptable,
        )
        self.assertEqual((ecriture.journal, ecriture.piece), (Journal.CAISSE, "F-123"))
        self.assertEqual(self.soldes(), {"605": (50000, 0), "571": (0, 50000)})

    def test_recette_par_mobile_money_et_virement(self):
        mm = enregistrer_operation(etablissement=self.ecole, type_operation="recette", date_ecriture=jour(3, 10), montant=20000,
                                   compte="718", mode="mobile_money", libelle="Subvention")
        vir = enregistrer_operation(etablissement=self.ecole, type_operation="recette", date_ecriture=jour(3, 11), montant=30000,
                                    compte="758", mode="virement", libelle="Don")
        self.assertEqual((mm.journal, vir.journal), (Journal.BANQUE, Journal.BANQUE))
        self.assertEqual(self.soldes(), {"551": (20000, 0), "718": (0, 20000), "521": (30000, 0), "758": (0, 30000)})

    def test_refus(self):
        base = dict(etablissement=self.ecole, date_ecriture=jour(3, 10), montant=1000, mode="especes", libelle="x")
        for attendu, valeurs in [
            ("trésorerie", dict(type_operation="depense", compte="571")),
            ("produit", dict(type_operation="depense", compte="706")),
            ("charge", dict(type_operation="recette", compte="605")),
            ("strictement positif", dict(type_operation="depense", compte="605", montant=0)),
            ("Mode", dict(type_operation="depense", compte="605", mode="troc")),
            ("inconnu", dict(type_operation="depense", compte="999999")),
            ("Type", dict(type_operation="don", compte="605")),
        ]:
            with self.subTest(attendu=attendu), self.assertRaisesMessage(ValidationError, attendu):
                enregistrer_operation(**{**base, **valeurs})


class CaisseAutomatiqueTests(ComptaBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        annee = AnneeScolaire.objects.create(
            etablissement=cls.ecole, libelle=f"{ANNEE}-{ANNEE + 1}", date_debut=jour(10, 1), date_fin=jour(7, 31, ANNEE + 1), est_active=True,
        )
        cls.classe = Classe.objects.create(nom="6A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=annee)
        cls.eleve = compte_utilisateur("eleve-c@compta.test", Role.ELEVE, cls.ecole, matricule="202699001")
        cls.inscription = Inscription.objects.create(eleve=cls.eleve, classe=cls.classe)
        cls.prof = compte_utilisateur("prof-c@compta.test", Role.ENSEIGNANT, cls.ecole)
        cls.fondateur = compte_utilisateur("fond-c@compta.test", Role.FONDATEUR, cls.ecole)  # seule la direction annule un paiement

    def payer(self, montant=20000, mode="especes", tranche=TypeTranche.VERSEMENT):
        return enregistrer_paiement(
            eleve=self.eleve, inscription=self.inscription, tranche=tranche, montant=montant, mode_paiement=mode,
            enregistre_par=self.comptable,
        )

    def test_un_paiement_est_comptabilise_selon_son_mode_et_sa_tranche(self):
        self.payer(20000, "especes", TypeTranche.VERSEMENT)
        self.payer(10000, "mobile_money", TypeTranche.INSCRIPTION)
        self.payer(30000, "virement", TypeTranche.VERSEMENT)
        self.assertEqual(len(ecarts_caisse(self.ecole)), 3)
        resultat = synchroniser_caisse(self.ecole, acteur=self.comptable)
        self.assertEqual((resultat.creees, resultat.ignorees), (3, []))
        self.assertEqual(self.soldes(), {
            "571": (20000, 0), "551": (10000, 0), "521": (30000, 0), "70602": (0, 50000), "70601": (0, 10000),
        })
        journaux = sorted(Ecriture.objects.values_list("journal", flat=True))
        self.assertEqual(journaux, ["BQ", "BQ", "CAI"])
        self.assertEqual({e.origine for e in Ecriture.objects.all()}, {Origine.AUTOMATIQUE})

    def test_synchronisation_idempotente(self):
        self.payer()
        self.assertEqual(synchroniser_caisse(self.ecole).creees, 1)
        self.assertEqual(synchroniser_caisse(self.ecole).creees, 0)
        self.assertEqual(ecarts_caisse(self.ecole), [])
        self.assertEqual(Ecriture.objects.count(), 1)

    def test_correction_de_montant(self):
        paiement = self.payer(20000, "especes")
        synchroniser_caisse(self.ecole)
        corriger_paiement(paiement=paiement, montant=25000, acteur=self.comptable)
        resultat = synchroniser_caisse(self.ecole, aujourdhui=jour(5, 5))
        self.assertEqual(resultat.creees, 1)
        regularisation = Ecriture.objects.order_by("id").last()
        self.assertEqual((regularisation.journal, regularisation.date_ecriture), (Journal.OPERATIONS_DIVERSES, jour(5, 5)))
        self.assertIn("correction", regularisation.libelle)
        self.assertEqual(self.soldes(), {"571": (25000, 0), "70602": (0, 25000)})  # les écarts s'additionnent (5000 de plus)

    def test_correction_du_mode_de_paiement(self):
        paiement = self.payer(20000, "especes")
        synchroniser_caisse(self.ecole)
        corriger_paiement(paiement=paiement, mode_paiement="virement", acteur=self.comptable)
        synchroniser_caisse(self.ecole)
        s = self.soldes()
        self.assertEqual((s["571"][0] - s["571"][1], s["521"][0] - s["521"][1], s["70602"][1] - s["70602"][0]), (0, 20000, 20000))

    def test_annulation_d_un_paiement(self):
        paiement = self.payer(20000)
        synchroniser_caisse(self.ecole)
        supprimer_paiement(paiement=paiement, acteur=self.fondateur)
        self.assertEqual(len(ecarts_caisse(self.ecole)), 1)
        synchroniser_caisse(self.ecole)
        self.assertTrue(all(s.solde == 0 for s in etats.soldes_par_compte(self.ecole, self.exercice)))
        self.assertIn("annulation", Ecriture.objects.order_by("id").last().libelle)

    def test_un_paiement_annule_avant_toute_comptabilisation_ne_produit_rien(self):
        paiement = self.payer(20000)
        supprimer_paiement(paiement=paiement, acteur=self.fondateur)
        self.assertEqual(ecarts_caisse(self.ecole), [])
        self.assertEqual(synchroniser_caisse(self.ecole).creees, 0)

    def test_salaire_simple(self):
        salaire = Salaire.objects.create(employe=self.prof, periode=f"{ANNEE}-09", montant=50000, enregistre_par=self.comptable)
        marquer_salaire_paye(salaire=salaire, paye_par=self.comptable)
        synchroniser_caisse(self.ecole)
        self.assertEqual(self.soldes(), {"661": (50000, 0), "571": (0, 50000)})

    def test_bulletin_de_paie_detaille(self):
        """
        Brut 100 000, taux par défaut : INPS salarié 3,6 % = 3 600, INPS employeur 20 % = 20 000, AMO salarié 3,06 % = 3 060,
        AMO employeur 3,5 % = 3 500, ITS 2 000 -> net 100 000 - 3 600 - 3 060 - 2 000 = 91 340.
        Débits 100 000 + 23 500 = 123 500 ; crédits 91 340 + 23 600 + 6 560 + 2 000 = 123 500.
        """
        salaire = creer_bulletin_paie(employe=self.prof, periode=f"{ANNEE}-09", salaire_brut=100000, its=2000, enregistre_par=self.comptable)
        self.assertEqual(salaire.montant, 91340)
        marquer_salaire_paye(salaire=salaire, paye_par=self.comptable)
        mouvement = MouvementCaisse.objects.get(salaire=salaire)
        self.assertEqual(vecteur_attendu(mouvement), {
            "661": 100000, "664": 23500, "571": -91340, "431": -23600, "433": -6560, "447": -2000,
        })
        synchroniser_caisse(self.ecole)
        self.assertEqual(self.soldes(), {
            "661": (100000, 0), "664": (23500, 0), "571": (0, 91340), "431": (0, 23600), "433": (0, 6560), "447": (0, 2000),
        })
        _, totaux = etats.balance(self.ecole, self.exercice)
        self.assertTrue(totaux["equilibree"])

    def test_bulletin_incoherent_comptabilise_au_net(self):
        salaire = creer_bulletin_paie(employe=self.prof, periode=f"{ANNEE}-09", salaire_brut=100000, its=2000, enregistre_par=self.comptable)
        Salaire.objects.filter(pk=salaire.pk).update(cotisation_inps_salarie=1)  # brut - retenues != net
        marquer_salaire_paye(salaire=Salaire.objects.get(pk=salaire.pk), paye_par=self.comptable)
        mouvement = MouvementCaisse.objects.get(salaire=salaire)
        self.assertEqual(vecteur_attendu(mouvement), {"661": 91340, "571": -91340})

    def test_aucun_exercice_les_mouvements_sont_signales(self):
        Exercice.objects.filter(pk=self.exercice.pk).update(date_debut=jour(1, 1, ANNEE - 3), date_fin=jour(12, 31, ANNEE - 3))
        paiement = self.payer()
        resultat = synchroniser_caisse(self.ecole)
        self.assertEqual(resultat.creees, 0)
        self.assertEqual(len(resultat.ignorees), 1)
        self.assertIn(paiement.mouvement_caisse.reference, resultat.ignorees[0])  # référence de la ligne de caisse
        self.assertIn("aucun exercice", resultat.ignorees[0])
        # une fois l'exercice créé, le mouvement est comptabilisé
        Exercice.objects.filter(pk=self.exercice.pk).update(date_debut=jour(1, 1), date_fin=jour(12, 31))
        self.assertEqual(synchroniser_caisse(self.ecole).creees, 1)

    def test_exercice_cloture_les_mouvements_sont_signales(self):
        self.payer()
        Exercice.objects.filter(pk=self.exercice.pk).update(cloture=True)
        resultat = synchroniser_caisse(self.ecole)
        self.assertEqual((resultat.creees, len(resultat.ignorees)), (0, 1))
        self.assertIn("clôturé", resultat.ignorees[0])

    def test_une_ecole_ne_comptabilise_pas_les_mouvements_d_une_autre(self):
        self.payer()
        self.assertEqual(synchroniser_caisse(self.ecole_b).creees, 0)
        self.assertEqual(ecarts_caisse(self.ecole_b), [])
        self.assertFalse(Ecriture.objects.filter(etablissement=self.ecole_b).exists())

    def test_les_ecritures_automatiques_ne_se_contrepassent_pas_a_la_main(self):
        self.payer()
        synchroniser_caisse(self.ecole)
        with self.assertRaisesMessage(ValidationError, "annulez ou corrigez le paiement"):
            contrepasser(ecriture=Ecriture.objects.get())


class EtatsTests(ComptaBase):
    """
    Jeu de données (exercice de l'année) :
      E1 apport en capital         521 D 1 000 000 / 101 C 1 000 000
      E2 achat de mobilier         244 D   400 000 / 521 C   400 000
      E3 recette scolarité espèces 571 D   300 000 / 70602 C 300 000   (5 mars)
      E4 électricité en espèces    605 D    50 000 / 571 C    50 000   (10 mars)
      E5 salaires en espèces       661 D   120 000 / 571 C   120 000   (31 mars)
      E6 loyer à payer             622 D    80 000 / 401 C    80 000
    Soldes : 521 D 600 000 ; 571 D 130 000 ; 244 D 400 000 ; 101 C 1 000 000 ; 401 C 80 000 ; produits 300 000 ; charges 250 000.
    Résultat : 300 000 - 250 000 = bénéfice de 50 000. Actif = Passif = 1 130 000.
    """

    def setUp(self):
        self.ecrire([("521", 1000000, 0), ("101", 0, 1000000)], date=jour(1, 5), libelle="Apport en capital")
        self.ecrire([("244", 400000, 0), ("521", 0, 400000)], date=jour(2, 1), libelle="Achat de mobilier")
        enregistrer_operation(etablissement=self.ecole, type_operation="recette", date_ecriture=jour(3, 5), montant=300000,
                              compte="70602", mode="especes", libelle="Scolarité", cree_par=self.comptable)
        enregistrer_operation(etablissement=self.ecole, type_operation="depense", date_ecriture=jour(3, 10), montant=50000,
                              compte="605", mode="especes", libelle="Électricité", cree_par=self.comptable)
        enregistrer_operation(etablissement=self.ecole, type_operation="depense", date_ecriture=jour(3, 31), montant=120000,
                              compte="661", mode="especes", libelle="Salaires", cree_par=self.comptable)
        self.ecrire([("622", 80000, 0), ("401", 0, 80000)], date=jour(4, 1), libelle="Loyer à payer")

    def test_balance(self):
        lignes, totaux = etats.balance(self.ecole, self.exercice)
        self.assertEqual({s.numero: s.solde for s in lignes}, {
            "101": -1000000, "244": 400000, "401": -80000, "521": 600000, "571": 130000, "605": 50000, "622": 80000,
            "661": 120000, "70602": -300000,
        })
        self.assertEqual((totaux["debit"], totaux["credit"]), (1950000, 1950000))
        self.assertEqual((totaux["solde_debiteur"], totaux["solde_crediteur"]), (1380000, 1380000))
        self.assertTrue(totaux["equilibree"])

    def test_balance_a_une_date(self):
        lignes, _ = etats.balance(self.ecole, self.exercice, jusqu_au=jour(3, 10))
        self.assertEqual({s.numero: s.solde for s in lignes}["571"], 250000)  # 300 000 - 50 000, avant les salaires

    def test_grand_livre_d_un_compte(self):
        caisse = CompteComptable.objects.get(etablissement=self.ecole, numero="571")
        lignes, debit, credit = etats.grand_livre_compte(self.ecole, self.exercice, caisse)
        self.assertEqual([(l.date, l.debit, l.credit, l.solde) for l in lignes], [
            (jour(3, 5), 300000, 0, 300000), (jour(3, 10), 0, 50000, 250000), (jour(3, 31), 0, 120000, 130000),
        ])
        self.assertEqual((debit, credit), (300000, 170000))
        du_10, _, _ = etats.grand_livre_compte(self.ecole, self.exercice, caisse, du=jour(3, 10))
        self.assertEqual(len(du_10), 2)

    def test_compte_de_resultat(self):
        resultat = etats.compte_de_resultat(self.ecole, self.exercice)
        self.assertEqual((resultat["total_produits"], resultat["total_charges"], resultat["resultat"]), (300000, 250000, 50000))
        self.assertEqual({g["code"]: g["total"] for g in resultat["produits"]}, {"70": 300000})
        self.assertEqual({g["code"]: g["total"] for g in resultat["charges"]}, {"60": 50000, "62": 80000, "66": 120000})
        self.assertEqual(dict(resultat["soldes"])["Résultat d'exploitation"], 50000)
        self.assertEqual(dict(resultat["soldes"])["Résultat financier"], 0)
        self.assertEqual(dict(resultat["soldes"])["Résultat des activités ordinaires"], 50000)

    def test_bilan(self):
        bilan = etats.bilan(self.ecole, self.exercice)
        self.assertEqual(bilan["sous_totaux_actif"], {"immobilisations": 400000, "stocks": 0, "creances": 0, "tresorerie": 730000})
        self.assertEqual(bilan["sous_totaux_passif"], {"capitaux": 1000000, "dettes_financieres": 0, "dettes": 80000, "tresorerie": 0})
        self.assertEqual((bilan["resultat"], bilan["total_actif"], bilan["total_passif"]), (50000, 1130000, 1130000))
        self.assertTrue(bilan["equilibre"])

    def test_bilan_equilibre_avec_amortissement_et_solde_crediteur_de_banque(self):
        self.ecrire([("681", 40000, 0), ("284", 0, 40000)], date=jour(6, 30), libelle="Amortissement du mobilier")
        self.ecrire([("631", 5000, 0), ("521", 0, 700000), ("401", 695000, 0)], date=jour(7, 1), libelle="Banque à découvert")
        bilan = etats.bilan(self.ecole, self.exercice)
        self.assertTrue(bilan["equilibre"], (bilan["total_actif"], bilan["total_passif"]))
        self.assertEqual(bilan["sous_totaux_actif"]["immobilisations"], 400000 - 40000)  # l'amortissement vient en déduction
        self.assertEqual(bilan["sous_totaux_passif"]["tresorerie"], 100000)  # 521 : 600 000 - 700 000 = -100 000 -> passif

    def test_tableau_de_bord(self):
        fiche = etats.tableau_de_bord(self.ecole, self.exercice)
        self.assertEqual((fiche["produits"], fiche["charges"], fiche["resultat"], fiche["tresorerie"], fiche["nombre_ecritures"]),
                         (300000, 250000, 50000, 730000, 6))

    def test_isolation_entre_ecoles(self):
        self.assertEqual(etats.soldes_par_compte(self.ecole_b, self.exercice_b), [])
        self.assertEqual(list(etats.journal(self.ecole_b, self.exercice_b)), [])
        # l'exercice d'une école ne montre jamais les écritures d'une autre, même en le demandant explicitement
        self.assertEqual(etats.soldes_par_compte(self.ecole_b, self.exercice), [])

    def test_journal_filtres(self):
        self.assertEqual(etats.journal(self.ecole, self.exercice).count(), 6)
        self.assertEqual(etats.journal(self.ecole, self.exercice, code_journal=Journal.CAISSE).count(), 3)
        self.assertEqual(etats.journal(self.ecole, self.exercice, du=jour(3, 6), au=jour(3, 31)).count(), 2)


class ClotureEtReportTests(ComptaBase):
    def setUp(self):
        self.ecrire([("521", 1000000, 0), ("101", 0, 1000000)], date=jour(1, 5))
        self.ecrire([("244", 400000, 0), ("521", 0, 400000)], date=jour(2, 1))
        enregistrer_operation(etablissement=self.ecole, type_operation="recette", date_ecriture=jour(3, 5), montant=300000,
                              compte="70602", mode="especes", libelle="Scolarité")
        enregistrer_operation(etablissement=self.ecole, type_operation="depense", date_ecriture=jour(3, 10), montant=50000,
                              compte="605", mode="especes", libelle="Électricité")
        enregistrer_operation(etablissement=self.ecole, type_operation="depense", date_ecriture=jour(3, 31), montant=120000,
                              compte="661", mode="especes", libelle="Salaires")
        self.ecrire([("622", 80000, 0), ("401", 0, 80000)], date=jour(4, 1))

    def test_cloture_avec_benefice(self):
        exercice = cloturer_exercice(exercice=self.exercice, acteur=self.comptable)
        self.assertTrue(exercice.cloture)
        self.assertEqual(exercice.cloture_par, self.comptable)
        cloture = Ecriture.objects.get(origine=Origine.CLOTURE)
        self.assertEqual(cloture.date_ecriture, jour(12, 31))
        lignes = {(l.compte.numero, l.debit, l.credit) for l in cloture.lignes.select_related("compte")}
        self.assertEqual(lignes, {
            ("70602", 300000, 0), ("605", 0, 50000), ("622", 0, 80000), ("661", 0, 120000), ("131", 0, 50000),
        })
        # avec la clôture, les comptes de gestion sont soldés et le résultat est au compte 131
        complet = {s.numero: s.solde for s in etats.soldes_par_compte(self.ecole, self.exercice, inclure_cloture=True)}
        for numero in ("70602", "605", "622", "661"):
            self.assertEqual(complet[numero], 0)
        self.assertEqual(complet["131"], -50000)

    def test_les_etats_restent_identiques_apres_cloture(self):
        avant = (etats.compte_de_resultat(self.ecole, self.exercice)["resultat"], etats.bilan(self.ecole, self.exercice)["total_actif"])
        cloturer_exercice(exercice=self.exercice)
        exercice = Exercice.objects.get(pk=self.exercice.pk)
        apres = (etats.compte_de_resultat(self.ecole, exercice)["resultat"], etats.bilan(self.ecole, exercice)["total_actif"])
        self.assertEqual(avant, apres)
        self.assertEqual(apres, (50000, 1130000))
        self.assertTrue(etats.bilan(self.ecole, exercice)["equilibre"])

    def test_cloture_avec_perte(self):
        enregistrer_operation(etablissement=self.ecole, type_operation="depense", date_ecriture=jour(5, 1), montant=100000,
                              compte="624", mode="especes", libelle="Réparations")  # charges 350 000 > produits 300 000
        cloturer_exercice(exercice=self.exercice)
        cloture = Ecriture.objects.get(origine=Origine.CLOTURE)
        lignes = {(l.compte.numero, l.debit, l.credit) for l in cloture.lignes.select_related("compte")}
        self.assertIn(("139", 50000, 0), lignes)
        self.assertNotIn("131", {numero for numero, _, _ in lignes})

    def test_cloture_sans_activite(self):
        vide = creer_exercice(etablissement=self.ecole, libelle="Vide", date_debut=jour(1, 1, ANNEE + 1), date_fin=jour(12, 31, ANNEE + 1))
        cloturer_exercice(exercice=vide)
        self.assertFalse(Ecriture.objects.filter(exercice=vide).exists())
        self.assertTrue(Exercice.objects.get(pk=vide.pk).cloture)

    def test_un_exercice_cloture_n_accepte_plus_rien_et_ne_se_cloture_pas_deux_fois(self):
        cloturer_exercice(exercice=self.exercice)
        with self.assertRaisesMessage(ValidationError, "clôturé"):
            self.ecrire([("521", 100, 0), ("101", 0, 100)], date=jour(6, 1))
        with self.assertRaisesMessage(ValidationError, "déjà clôturé"):
            cloturer_exercice(exercice=Exercice.objects.get(pk=self.exercice.pk))

    def test_cloture_refusee_tant_que_la_caisse_n_est_pas_comptabilisee(self):
        annee = AnneeScolaire.objects.create(
            etablissement=self.ecole, libelle=f"{ANNEE}-{ANNEE + 1}", date_debut=jour(10, 1), date_fin=jour(7, 31, ANNEE + 1), est_active=True,
        )
        classe = Classe.objects.create(nom="6A", cycle=Cycle.PREMIER_CYCLE, annee_scolaire=annee)
        eleve = compte_utilisateur("eleve-cl@compta.test", Role.ELEVE, self.ecole, matricule="202699002")
        inscription = Inscription.objects.create(eleve=eleve, classe=classe)
        enregistrer_paiement(eleve=eleve, inscription=inscription, tranche=TypeTranche.VERSEMENT, montant=20000,
                             mode_paiement="especes", enregistre_par=self.comptable)
        with self.assertRaisesMessage(ValidationError, "Mettez d'abord la comptabilité à jour"):
            cloturer_exercice(exercice=self.exercice)
        self.assertFalse(Exercice.objects.get(pk=self.exercice.pk).cloture)
        synchroniser_caisse(self.ecole)
        cloturer_exercice(exercice=Exercice.objects.get(pk=self.exercice.pk))

    def test_report_a_nouveau(self):
        suivant = creer_exercice(etablissement=self.ecole, libelle=f"Exercice {ANNEE + 1}", date_debut=jour(1, 1, ANNEE + 1), date_fin=jour(12, 31, ANNEE + 1))
        with self.assertRaisesMessage(ValidationError, "Clôturez d'abord"):
            reporter_a_nouveau(exercice=self.exercice)
        cloturer_exercice(exercice=self.exercice)
        report = reporter_a_nouveau(exercice=Exercice.objects.get(pk=self.exercice.pk), acteur=self.comptable)
        self.assertEqual((report.journal, report.origine, report.date_ecriture, report.exercice), (Journal.A_NOUVEAUX, Origine.REPORT, jour(1, 1, ANNEE + 1), suivant))
        lignes = {(l.compte.numero, l.debit, l.credit) for l in report.lignes.select_related("compte")}
        self.assertEqual(lignes, {
            ("244", 400000, 0), ("521", 600000, 0), ("571", 130000, 0), ("101", 0, 1000000), ("401", 0, 80000), ("131", 0, 50000),
        })
        # dans l'exercice suivant : bilan équilibré, résultat de l'exercice précédent dans les capitaux, résultat courant nul
        bilan = etats.bilan(self.ecole, suivant)
        self.assertTrue(bilan["equilibre"])
        self.assertEqual((bilan["total_actif"], bilan["resultat"], bilan["sous_totaux_passif"]["capitaux"]), (1130000, 0, 1050000))
        with self.assertRaisesMessage(ValidationError, "déjà été reportés"):
            reporter_a_nouveau(exercice=Exercice.objects.get(pk=self.exercice.pk))

    def test_report_sans_exercice_suivant(self):
        cloturer_exercice(exercice=self.exercice)
        self.assertIsNone(exercice_suivant(self.exercice))
        with self.assertRaisesMessage(ValidationError, "exercice suivant"):
            reporter_a_nouveau(exercice=Exercice.objects.get(pk=self.exercice.pk))

    def test_les_ecritures_de_cloture_et_de_report_ne_se_contrepassent_pas(self):
        creer_exercice(etablissement=self.ecole, libelle=f"Exercice {ANNEE + 1}", date_debut=jour(1, 1, ANNEE + 1), date_fin=jour(12, 31, ANNEE + 1))
        cloturer_exercice(exercice=self.exercice)
        reporter_a_nouveau(exercice=Exercice.objects.get(pk=self.exercice.pk))
        for ecriture in Ecriture.objects.filter(origine__in=(Origine.CLOTURE, Origine.REPORT)):
            with self.subTest(ecriture=ecriture.numero), self.assertRaises(ValidationError):
                contrepasser(ecriture=ecriture)
