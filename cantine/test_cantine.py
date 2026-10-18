"""
Cantine : le calcul de ce que chaque élève doit, l'inscription, l'appel du jour, les paiements (reçu, Caisse, comptabilité), les droits du gérant
de la cantine (rôle « Personnel » avec le module Cantine), le suivi des familles et le cloisonnement entre écoles.
"""
import datetime
from unittest import mock

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from cantine import services
from cantine.models import FormuleCantine, InscriptionCantine, ModeCantine, PaiementCantine, RepasCantine
from comptabilite.services import vecteur_attendu
from comptes.roles import Role
from finances.models import MouvementCaisse
from permissions_matrix.models import PermissionMatrix
from permissions_matrix.modules import Module
from scolarite.models import AnneeScolaire
from statistiques.test_education import EducationBase, creer_compte

D = datetime.date
AUJOURDHUI = timezone.localdate()


def client_de(compte):
    client = Client()
    if compte is not None:
        client.force_login(compte)
    return client


class CantineBase(EducationBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.gerant = creer_compte(Role.PERSONNEL, "gerant@cantine.test", cls.ecole)
        PermissionMatrix.objects.update_or_create(
            etablissement=cls.ecole, role=Role.PERSONNEL.value, module=Module.CANTINE.value, defaults={"autorise": True},
        )
        cls.gerant_b = creer_compte(Role.PERSONNEL, "gerant-b@cantine.test", cls.ecole_b)
        PermissionMatrix.objects.update_or_create(
            etablissement=cls.ecole_b, role=Role.PERSONNEL.value, module=Module.CANTINE.value, defaults={"autorise": True},
        )
        cls.mensuelle = FormuleCantine.objects.create(etablissement=cls.ecole, libelle="Formule du midi", mode=ModeCantine.MENSUEL, montant=5000)
        cls.au_repas = FormuleCantine.objects.create(etablissement=cls.ecole, libelle="Repas à l'unité", mode=ModeCantine.REPAS, montant=300)
        cls.formule_b = FormuleCantine.objects.create(etablissement=cls.ecole_b, libelle="Cantine B", mode=ModeCantine.MENSUEL, montant=4000)

    def inscrire(self, eleve=None, formule=None, debut=D(2026, 10, 15), fin=None, annee=None):
        inscription = InscriptionCantine(
            etablissement=self.ecole, eleve=eleve or self.e1, annee_scolaire=annee or self.annee, formule=formule or self.mensuelle,
            date_debut=debut, date_fin=fin, cree_par=self.gerant,
        )
        inscription.full_clean()
        inscription.save()
        return inscription


# ---------------------------------------------------------------------------------------------------------------------
# Ce que l'élève doit
# ---------------------------------------------------------------------------------------------------------------------

class CalculDuTests(CantineBase):
    def test_tout_mois_commence_est_du(self):
        self.assertEqual(services.mois_commences(D(2026, 10, 15), D(2026, 10, 15)), 1)
        self.assertEqual(services.mois_commences(D(2026, 10, 31), D(2026, 11, 1)), 2)
        self.assertEqual(services.mois_commences(D(2026, 10, 15), D(2027, 1, 2)), 4)
        self.assertEqual(services.mois_commences(D(2026, 12, 1), D(2026, 11, 1)), 0)

    def calcul(self, **options):
        base = dict(
            mode=ModeCantine.MENSUEL, tarif=5000, debut=D(2026, 10, 15), fin=None, fin_annee=D(2027, 7, 31), nombre_de_repas=0,
            aujourdhui=D(2026, 12, 5),
        )
        return services.calculer_du(**{**base, **options})

    def test_au_mois_jusqu_a_aujourd_hui(self):
        self.assertEqual(self.calcul(), 3 * 5000)  # octobre, novembre, décembre

    def test_au_mois_jusqu_a_la_fin_de_l_inscription(self):
        self.assertEqual(self.calcul(fin=D(2026, 11, 20)), 2 * 5000)

    def test_au_mois_jamais_au_dela_de_la_fin_de_l_annee(self):
        self.assertEqual(self.calcul(aujourdhui=D(2028, 3, 1)), 10 * 5000)  # octobre 2026 à juillet 2027

    def test_inscription_dans_le_futur_ne_doit_rien(self):
        self.assertEqual(self.calcul(debut=D(2027, 1, 10)), 0)

    def test_au_repas_chaque_repas_servi(self):
        self.assertEqual(self.calcul(mode=ModeCantine.REPAS, tarif=300, nombre_de_repas=12), 3600)

    def test_les_soldes_d_une_liste_se_calculent_sans_requete_par_ligne(self):
        for eleve in (self.e1, self.e2, self.e3, self.e4):
            self.inscrire(eleve=eleve)
        avec_un = len(self.capturer(lambda: services.avec_soldes(InscriptionCantine.objects.filter(eleve=self.e1), D(2026, 12, 5))))
        avec_quatre = len(self.capturer(lambda: services.avec_soldes(InscriptionCantine.objects.all(), D(2026, 12, 5))))
        self.assertEqual(avec_un, avec_quatre)

    def capturer(self, fonction):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as requetes:
            fonction()
        return requetes.captured_queries

    def test_solde_dû_payé_et_avance(self):
        inscription = self.inscrire(debut=D(2026, 10, 15))
        services.enregistrer_paiement(inscription=inscription, montant=20000, mode_paiement="especes", acteur=self.gerant)
        ligne = services.avec_soldes(InscriptionCantine.objects.filter(pk=inscription.pk), D(2026, 12, 5))[0]
        self.assertEqual((ligne.du, ligne.total_paye, ligne.solde, ligne.avance), (15000, 20000, -5000, 5000))
        services.enregistrer_paiement(inscription=inscription, montant=3000, mode_paiement="especes", acteur=self.gerant)
        ligne = services.avec_soldes(InscriptionCantine.objects.filter(pk=inscription.pk), D(2026, 12, 5))[0]
        self.assertEqual((ligne.solde, ligne.avance), (-8000, 8000))

    def test_un_paiement_annule_ne_compte_plus(self):
        inscription = self.inscrire(debut=D(2026, 10, 15))
        paiement = services.enregistrer_paiement(inscription=inscription, montant=15000, mode_paiement="especes", acteur=self.gerant)
        services.annuler_paiement(paiement=paiement, acteur=self.fondateur, motif="Erreur de saisie")
        ligne = services.avec_soldes(InscriptionCantine.objects.filter(pk=inscription.pk), D(2026, 12, 5))[0]
        self.assertEqual((ligne.total_paye, ligne.solde), (0, 15000))


# ---------------------------------------------------------------------------------------------------------------------
# Inscriptions et appel
# ---------------------------------------------------------------------------------------------------------------------

class InscriptionTests(CantineBase):
    def test_inscrire_un_eleve(self):
        inscription = services.inscrire(eleve=self.e1, formule=self.mensuelle, annee=self.annee, date_debut=D(2026, 10, 15), acteur=self.gerant)
        self.assertTrue(inscription.ouverte)
        self.assertEqual(inscription.etablissement, self.ecole)

    def test_une_seule_inscription_ouverte_par_annee(self):
        services.inscrire(eleve=self.e1, formule=self.mensuelle, annee=self.annee, date_debut=D(2026, 10, 15), acteur=self.gerant)
        with self.assertRaisesMessage(ValidationError, "déjà inscrit"):
            services.inscrire(eleve=self.e1, formule=self.au_repas, annee=self.annee, date_debut=D(2026, 11, 1), acteur=self.gerant)

    def test_la_base_elle_meme_refuse_deux_inscriptions_ouvertes(self):
        self.inscrire()
        with self.assertRaises(IntegrityError), transaction.atomic():
            InscriptionCantine.objects.create(
                etablissement=self.ecole, eleve=self.e1, annee_scolaire=self.annee, formule=self.mensuelle, date_debut=D(2026, 11, 1),
            )

    def test_terminer_puis_se_reinscrire(self):
        inscription = services.inscrire(eleve=self.e1, formule=self.mensuelle, annee=self.annee, date_debut=D(2026, 10, 15), acteur=self.gerant)
        services.terminer(inscription=inscription, date_fin=D(2026, 11, 30), acteur=self.gerant)
        inscription.refresh_from_db()
        self.assertEqual(inscription.date_fin, D(2026, 11, 30))
        with self.assertRaisesMessage(ValidationError, "déjà terminée"):
            services.terminer(inscription=inscription, date_fin=D(2026, 12, 1), acteur=self.gerant)
        nouvelle = services.inscrire(eleve=self.e1, formule=self.au_repas, annee=self.annee, date_debut=D(2027, 1, 10), acteur=self.gerant)
        self.assertEqual(InscriptionCantine.objects.filter(eleve=self.e1).count(), 2)
        self.assertTrue(nouvelle.ouverte)

    def test_la_fin_ne_peut_pas_preceder_le_debut(self):
        inscription = self.inscrire(debut=D(2026, 11, 10))
        with self.assertRaises(ValidationError):
            services.terminer(inscription=inscription, date_fin=D(2026, 11, 1), acteur=self.gerant)

    def test_l_eleve_la_formule_et_l_annee_doivent_etre_de_la_meme_ecole(self):
        eleve_b = creer_compte(Role.ELEVE, "eleve@cantine-b.test", self.ecole_b)
        for options in (
            {"eleve": eleve_b}, {"formule": self.formule_b}, {"annee": self.annee_b},
        ):
            with self.subTest(options=list(options)), self.assertRaises(ValidationError):
                self.inscrire(**options)

    def test_seul_un_eleve_peut_etre_inscrit(self):
        with self.assertRaises(ValidationError):
            self.inscrire(eleve=self.parent)


class AppelTests(CantineBase):
    def setUp(self):
        self.jour = AUJOURDHUI
        self.i1 = self.inscrire(eleve=self.e1, debut=self.jour - datetime.timedelta(days=5))
        self.i2 = self.inscrire(eleve=self.e2, debut=self.jour - datetime.timedelta(days=5), formule=self.au_repas)

    def appeler(self, presents, jour=None):
        return services.enregistrer_appel(etablissement=self.ecole, date=jour or self.jour, presents_ids=presents, acteur=self.gerant)

    def test_les_eleves_coches_ont_mange(self):
        self.assertEqual(self.appeler([self.i1.pk]), (1, 0))
        self.assertEqual(list(RepasCantine.objects.values_list("inscription_id", flat=True)), [self.i1.pk])

    def test_refaire_l_appel_corrige_le_precedent_sans_doublon(self):
        self.appeler([self.i1.pk, self.i2.pk])
        self.assertEqual(self.appeler([self.i1.pk, self.i2.pk]), (0, 0))
        self.assertEqual(RepasCantine.objects.count(), 2)
        self.assertEqual(self.appeler([self.i2.pk]), (0, 1))
        self.assertEqual(list(RepasCantine.objects.values_list("inscription_id", flat=True)), [self.i2.pk])

    def test_un_jour_futur_est_refuse(self):
        with self.assertRaisesMessage(ValidationError, "pas encore venu"):
            self.appeler([self.i1.pk], jour=self.jour + datetime.timedelta(days=1))

    def test_un_eleve_non_inscrit_ce_jour_est_ignore(self):
        avant = self.jour - datetime.timedelta(days=9)  # avant le début des inscriptions
        self.assertEqual(self.appeler([self.i1.pk], jour=avant), (0, 0))
        self.assertEqual(RepasCantine.objects.count(), 0)

    def test_apres_la_fin_de_l_inscription_plus_de_repas(self):
        services.terminer(inscription=self.i1, date_fin=self.jour - datetime.timedelta(days=2), acteur=self.gerant)
        self.assertEqual(self.appeler([self.i1.pk]), (0, 0))
        self.assertEqual(self.appeler([self.i1.pk], jour=self.jour - datetime.timedelta(days=3)), (1, 0))  # mais il a mangé avant la fin

    def test_un_numero_d_une_autre_ecole_est_ignore(self):
        eleve_b = creer_compte(Role.ELEVE, "eleve2@cantine-b.test", self.ecole_b)
        autre = InscriptionCantine.objects.create(
            etablissement=self.ecole_b, eleve=eleve_b, annee_scolaire=self.annee_b, formule=self.formule_b, date_debut=self.jour - datetime.timedelta(days=5),
        )
        self.assertEqual(self.appeler([autre.pk]), (0, 0))
        self.assertEqual(RepasCantine.objects.count(), 0)

    def test_une_annee_archivee_n_a_plus_d_appel(self):
        AnneeScolaire.objects.filter(pk=self.annee.pk).update(est_archivee=True)
        self.assertEqual(self.appeler([self.i1.pk]), (0, 0))

    def test_le_nombre_de_repas_fait_le_du_au_repas(self):
        for decalage in (1, 2, 3):
            self.appeler([self.i2.pk], jour=self.jour - datetime.timedelta(days=decalage))
        ligne = services.avec_soldes(InscriptionCantine.objects.filter(pk=self.i2.pk), self.jour)[0]
        self.assertEqual((ligne.nb_repas, ligne.du), (3, 900))


# ---------------------------------------------------------------------------------------------------------------------
# Paiements, Caisse, comptabilité
# ---------------------------------------------------------------------------------------------------------------------

class PaiementTests(CantineBase):
    def setUp(self):
        self.inscription = self.inscrire()

    def test_un_paiement_cree_son_recu_et_sa_ligne_de_caisse(self):
        paiement = services.enregistrer_paiement(inscription=self.inscription, montant=5000, mode_paiement="especes", acteur=self.gerant)
        self.assertRegex(paiement.reference, r"^CAN-\d{4}-\d{6}$")
        mouvement = paiement.mouvement_caisse
        self.assertEqual((mouvement.type_mouvement, mouvement.montant, mouvement.etablissement), (MouvementCaisse.TypeMouvement.ENTREE, 5000, self.ecole))
        self.assertEqual(mouvement.compte_contrepartie, "70608")
        self.assertIn("Cantine", mouvement.description)

    def test_les_numeros_de_recu_se_suivent_par_ecole(self):
        un = services.enregistrer_paiement(inscription=self.inscription, montant=1000, mode_paiement="especes", acteur=self.gerant)
        deux = services.enregistrer_paiement(inscription=self.inscription, montant=1000, mode_paiement="especes", acteur=self.gerant)
        self.assertEqual(int(deux.reference[-6:]), int(un.reference[-6:]) + 1)

    def test_un_montant_nul_ou_negatif_est_refuse(self):
        for montant in (0, -500):
            with self.subTest(montant=montant), self.assertRaises(ValidationError):
                services.enregistrer_paiement(inscription=self.inscription, montant=montant, mode_paiement="especes", acteur=self.gerant)
        self.assertEqual(PaiementCantine.objects.count(), 0)

    def test_tout_ou_rien_si_la_caisse_echoue(self):
        with mock.patch("cantine.services.MouvementCaisse.objects.create", side_effect=RuntimeError("panne")):
            with self.assertRaises(RuntimeError):
                services.enregistrer_paiement(inscription=self.inscription, montant=5000, mode_paiement="especes", acteur=self.gerant)
        self.assertEqual(PaiementCantine.objects.count(), 0)

    def test_annulation_reservee_a_la_direction(self):
        paiement = services.enregistrer_paiement(inscription=self.inscription, montant=5000, mode_paiement="especes", acteur=self.gerant)
        for acteur in (self.gerant, self.comptable, self.secretaire):
            with self.subTest(role=acteur.role), self.assertRaises(ValidationError):
                services.annuler_paiement(paiement=paiement, acteur=acteur, motif="Test")
        services.annuler_paiement(paiement=paiement, acteur=self.fondateur, motif="Erreur de saisie")
        paiement.refresh_from_db()
        self.assertTrue(paiement.annule)
        self.assertEqual(paiement.annule_par, self.fondateur)
        self.assertEqual(paiement.motif_annulation, "Erreur de saisie")
        self.assertTrue(paiement.mouvement_caisse.annule)  # la ligne de Caisse est conservée, marquée annulée
        with self.assertRaisesMessage(ValidationError, "déjà annulé"):
            services.annuler_paiement(paiement=paiement, acteur=self.fondateur, motif="Encore")

    def test_comptabilite_selon_le_mode_de_paiement(self):
        for mode, tresorerie in (("especes", "571"), ("mobile_money", "551"), ("virement", "521"), ("cheque", "521")):
            with self.subTest(mode=mode):
                paiement = services.enregistrer_paiement(inscription=self.inscription, montant=2500, mode_paiement=mode, acteur=self.gerant)
                self.assertEqual(vecteur_attendu(paiement.mouvement_caisse), {tresorerie: 2500, "70608": -2500})

    def test_un_paiement_annule_ne_produit_rien_en_comptabilite(self):
        paiement = services.enregistrer_paiement(inscription=self.inscription, montant=2500, mode_paiement="especes", acteur=self.gerant)
        services.annuler_paiement(paiement=paiement, acteur=self.fondateur, motif="Erreur")
        paiement.mouvement_caisse.refresh_from_db()
        self.assertEqual(vecteur_attendu(paiement.mouvement_caisse), {})

    def test_la_caisse_exige_exactement_une_origine(self):
        sans_origine = MouvementCaisse(type_mouvement="entree", montant=10, etablissement=self.ecole, description="x", reference="CAI-X-2")
        with self.assertRaises(ValidationError):
            sans_origine.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():  # la base elle-même le refuse, même sans passer par le modèle
            MouvementCaisse.objects.bulk_create([sans_origine])


# ---------------------------------------------------------------------------------------------------------------------
# Pages : droits
# ---------------------------------------------------------------------------------------------------------------------

class DroitsTests(CantineBase):
    def setUp(self):
        self.inscription = self.inscrire()
        self.paiement = services.enregistrer_paiement(inscription=self.inscription, montant=5000, mode_paiement="especes", acteur=self.gerant)

    def adresses_de_gestion(self):
        return [
            reverse("cantine:tableau"), reverse("cantine:inscrire_eleves"), reverse("cantine:appel"), reverse("cantine:formules"),
            reverse("cantine:fiche_inscription", args=[self.inscription.pk]), reverse("cantine:paiement", args=[self.inscription.pk]),
            reverse("cantine:recu_pdf", args=[self.paiement.pk]),
        ]

    def test_le_gerant_et_la_direction_gerent_la_cantine(self):
        for compte in (self.gerant, self.fondateur):
            client = client_de(compte)
            for adresse in self.adresses_de_gestion():
                with self.subTest(role=compte.role, adresse=adresse):
                    self.assertEqual(client.get(adresse).status_code, 200)

    def test_sans_le_module_cantine_tout_est_refuse(self):
        for compte in (self.secretaire, self.comptable, self.t1, self.parent, self.e1, self.censeur, self.dir_1er):
            client = client_de(compte)
            for adresse in self.adresses_de_gestion():
                with self.subTest(role=compte.role, adresse=adresse):
                    self.assertEqual(client.get(adresse).status_code, 403)

    def test_le_module_se_donne_a_un_autre_role_depuis_la_matrice(self):
        PermissionMatrix.objects.update_or_create(
            etablissement=self.ecole, role=Role.SECRETAIRE.value, module=Module.CANTINE.value, defaults={"autorise": True},
        )
        self.assertEqual(client_de(self.secretaire).get(reverse("cantine:tableau")).status_code, 200)

    def test_par_defaut_aucun_role_n_a_le_module_sauf_le_super_administrateur(self):
        for role in (Role.SECRETAIRE, Role.COMPTABLE, Role.ENSEIGNANT, Role.PARENT, Role.ELEVE, Role.CENSEUR, Role.SURVEILLANT_GENERAL):
            self.assertFalse(PermissionMatrix.a_acces(role.value, Module.CANTINE.value, etablissement=self.ecole), role.value)
        from permissions_matrix.matrice_par_defaut import MATRICE_PAR_DEFAUT

        self.assertEqual(MATRICE_PAR_DEFAUT[Role.PERSONNEL], set())
        self.assertIn(Module.CANTINE, MATRICE_PAR_DEFAUT[Role.SUPER_ADMINISTRATEUR])

    def test_un_visiteur_anonyme_est_renvoye_vers_la_connexion(self):
        client = client_de(None)
        for adresse in self.adresses_de_gestion() + [reverse("cantine:mon_suivi")]:
            with self.subTest(adresse=adresse):
                reponse = client.get(adresse)
                self.assertEqual(reponse.status_code, 302)
                self.assertIn("/connexion", reponse["Location"])

    def test_seule_la_direction_annule_un_paiement(self):
        adresse = reverse("cantine:annuler_paiement", args=[self.paiement.pk])
        self.assertEqual(client_de(self.gerant).post(adresse, {"motif": "Test"}).status_code, 403)
        self.paiement.refresh_from_db()
        self.assertFalse(self.paiement.annule)
        reponse = client_de(self.fondateur).post(adresse, {"motif": "Erreur de saisie"})
        self.assertEqual(reponse.status_code, 302)
        self.paiement.refresh_from_db()
        self.assertTrue(self.paiement.annule)

    def test_annuler_sans_motif_ne_fait_rien(self):
        client_de(self.fondateur).post(reverse("cantine:annuler_paiement", args=[self.paiement.pk]), {"motif": ""})
        self.paiement.refresh_from_db()
        self.assertFalse(self.paiement.annule)

    def test_les_actions_ne_se_font_que_par_envoi_de_formulaire(self):
        for nom, arguments in (
            ("cantine:annuler_paiement", [self.paiement.pk]), ("cantine:terminer_inscription", [self.inscription.pk]),
        ):
            self.assertEqual(client_de(self.fondateur).get(reverse(nom, args=arguments)).status_code, 405)


# ---------------------------------------------------------------------------------------------------------------------
# Pages : parcours du gérant
# ---------------------------------------------------------------------------------------------------------------------

class ParcoursDuGerantTests(CantineBase):
    def setUp(self):
        self.client = client_de(self.gerant)

    def test_creer_une_formule(self):
        reponse = self.client.post(reverse("cantine:formules"), {"libelle": "  Petit   déjeuner ", "mode": "mensuel", "montant": "3000"})
        self.assertEqual(reponse.status_code, 302)
        formule = FormuleCantine.objects.get(libelle="Petit déjeuner")
        self.assertEqual((formule.etablissement, formule.montant, formule.active), (self.ecole, 3000, True))

    def test_une_formule_au_tarif_nul_ou_en_double_est_refusee(self):
        for donnees, attendu in (
            ({"libelle": "X", "mode": "mensuel", "montant": "0"}, "supérieur"),
            ({"libelle": "formule DU midi", "mode": "mensuel", "montant": "100"}, "déjà ce nom"),
        ):
            with self.subTest(donnees=donnees):
                reponse = self.client.post(reverse("cantine:formules"), donnees)
                self.assertEqual(reponse.status_code, 200)
                self.assertContains(reponse, attendu)
        self.assertEqual(FormuleCantine.objects.filter(etablissement=self.ecole).count(), 2)

    def test_desactiver_une_formule_la_retire_des_nouvelles_inscriptions(self):
        self.client.post(reverse("cantine:basculer_formule", args=[self.au_repas.pk]))
        self.au_repas.refresh_from_db()
        self.assertFalse(self.au_repas.active)
        reponse = self.client.get(reverse("cantine:inscrire_eleves"), {"classe": self.c6a.pk})
        formules = [formule for formule in reponse.context["formulaire"].fields["formule"].queryset]
        self.assertEqual(formules, [self.mensuelle])

    def test_inscrire_une_classe_entiere(self):
        reponse = self.client.post(reverse("cantine:inscrire_eleves"), {
            "classe": self.c6a.pk, "formule": self.mensuelle.pk, "date_debut": "2026-10-15", "eleves": [self.e1.pk, self.e2.pk],
        })
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(InscriptionCantine.objects.filter(formule=self.mensuelle).count(), 2)

    def test_le_choix_au_mois_ou_au_repas_se_fait_a_l_inscription_de_chaque_eleve(self):
        page = self.client.get(reverse("cantine:inscrire_eleves"), {"classe": self.c6a.pk})
        contenu = page.content.decode().replace(chr(160), " ").replace(chr(8239), " ")  # espaces insécables des montants
        for attendu in ("Formule du midi", "Au mois", "unité", "Au repas", "5 000", "300"):
            self.assertIn(attendu, contenu)
        self.assertContains(page, 'type="radio"', count=2)  # une case à cocher par formule
        base = {"classe": self.c6a.pk, "date_debut": "2026-10-15"}
        self.client.post(reverse("cantine:inscrire_eleves"), {**base, "formule": self.mensuelle.pk, "eleves": [self.e1.pk]})
        self.client.post(reverse("cantine:inscrire_eleves"), {**base, "formule": self.au_repas.pk, "eleves": [self.e2.pk]})
        self.assertEqual(InscriptionCantine.objects.get(eleve=self.e1).formule, self.mensuelle)
        self.assertEqual(InscriptionCantine.objects.get(eleve=self.e2).formule, self.au_repas)

    def test_inscrire_sans_choisir_la_formule_est_refuse(self):
        reponse = self.client.post(reverse("cantine:inscrire_eleves"), {"classe": self.c6a.pk, "date_debut": "2026-10-15", "eleves": [self.e1.pk]})
        self.assertContains(reponse, "au mois ou au repas")
        self.assertEqual(InscriptionCantine.objects.count(), 0)

    def test_on_n_inscrit_que_des_eleves_de_la_classe_choisie(self):
        reponse = self.client.post(reverse("cantine:inscrire_eleves"), {
            "classe": self.c6a.pk, "formule": self.mensuelle.pk, "date_debut": "2026-10-15", "eleves": [self.e4.pk],  # e4 est en 6B
        })
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(InscriptionCantine.objects.count(), 0)

    def test_une_formule_d_une_autre_ecole_est_refusee(self):
        reponse = self.client.post(reverse("cantine:inscrire_eleves"), {
            "classe": self.c6a.pk, "formule": self.formule_b.pk, "date_debut": "2026-10-15", "eleves": [self.e1.pk],
        })
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(InscriptionCantine.objects.count(), 0)

    def test_inscrire_sans_cocher_personne_est_refuse(self):
        reponse = self.client.post(reverse("cantine:inscrire_eleves"), {
            "classe": self.c6a.pk, "formule": self.mensuelle.pk, "date_debut": "2026-10-15",
        })
        self.assertContains(reponse, "Cochez au moins un élève")

    def test_les_eleves_deja_inscrits_ne_sont_plus_proposes(self):
        self.inscrire(eleve=self.e1)
        reponse = self.client.get(reverse("cantine:inscrire_eleves"), {"classe": self.c6a.pk})
        proposes = list(reponse.context["formulaire"].fields["eleves"].queryset)
        self.assertNotIn(self.e1, proposes)
        self.assertIn(self.e2, proposes)
        self.assertEqual(reponse.context["deja_inscrits"], [self.e1])

    def test_sans_formule_on_est_renvoye_vers_la_creation_d_une_formule(self):
        FormuleCantine.objects.filter(etablissement=self.ecole).update(active=False)
        reponse = self.client.get(reverse("cantine:inscrire_eleves"))
        self.assertRedirects(reponse, reverse("cantine:formules"))

    def test_l_appel_du_jour_par_la_page(self):
        inscription = self.inscrire(debut=AUJOURDHUI - datetime.timedelta(days=3))
        reponse = self.client.post(reverse("cantine:appel"), {"date": AUJOURDHUI.isoformat(), "presents": [inscription.pk]})
        self.assertEqual(reponse.status_code, 302)
        self.assertTrue(RepasCantine.objects.filter(inscription=inscription, date_repas=AUJOURDHUI).exists())
        page = self.client.get(reverse("cantine:appel"), {"date": AUJOURDHUI.isoformat()})
        self.assertEqual(page.context["presents"], 1)
        self.assertTrue(page.context["inscrits"][0].a_mange)

    def test_un_jour_futur_ou_illisible_revient_a_aujourd_hui(self):
        futur = (AUJOURDHUI + datetime.timedelta(days=3)).isoformat()
        self.assertEqual(self.client.get(reverse("cantine:appel"), {"date": futur}).context["date"], AUJOURDHUI)
        self.assertEqual(self.client.get(reverse("cantine:appel"), {"date": "pas-une-date"}).context["date"], AUJOURDHUI)

    def test_encaisser_par_la_page_donne_un_recu(self):
        inscription = self.inscrire()
        reponse = self.client.post(reverse("cantine:paiement", args=[inscription.pk]), {"montant": "5000", "mode_paiement": "especes"})
        self.assertRedirects(reponse, reverse("cantine:fiche_inscription", args=[inscription.pk]))
        paiement = PaiementCantine.objects.get()
        self.assertEqual((paiement.montant, paiement.enregistre_par), (5000, self.gerant))
        pdf = self.client.get(reverse("cantine:recu_pdf", args=[paiement.pk]))
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        self.assertIn("recu", pdf["Content-Disposition"])

    def test_un_montant_invalide_n_enregistre_rien(self):
        inscription = self.inscrire()
        for montant in ("0", "-5", "abc", ""):
            with self.subTest(montant=montant):
                reponse = self.client.post(reverse("cantine:paiement", args=[inscription.pk]), {"montant": montant, "mode_paiement": "especes"})
                self.assertEqual(reponse.status_code, 200)
        self.assertEqual(PaiementCantine.objects.count(), 0)

    def test_mettre_fin_a_une_inscription(self):
        inscription = self.inscrire()
        reponse = self.client.post(reverse("cantine:terminer_inscription", args=[inscription.pk]), {"date_fin": "2026-12-20"})
        self.assertEqual(reponse.status_code, 302)
        inscription.refresh_from_db()
        self.assertEqual(inscription.date_fin, D(2026, 12, 20))

    def test_le_tableau_filtre_et_additionne(self):
        with mock.patch("cantine.services.timezone.localdate", return_value=D(2026, 12, 5)):
            a_jour = self.inscrire(eleve=self.e1)  # 3 mois dus = 15 000
            services.enregistrer_paiement(inscription=a_jour, montant=15000, mode_paiement="especes", acteur=self.gerant)
            en_retard = self.inscrire(eleve=self.e2, debut=D(2026, 11, 3))  # 2 mois dus = 10 000, rien payé
            finie = self.inscrire(eleve=self.e3, debut=D(2026, 10, 15), fin=D(2026, 10, 31))
            reponse = self.client.get(reverse("cantine:tableau"))
            self.assertEqual(reponse.context["inscrits"], 2)
            self.assertEqual({ligne.pk for ligne in reponse.context["lignes"]}, {a_jour.pk, en_retard.pk})  # par défaut : les inscriptions en cours
            self.assertEqual((reponse.context["total_du"], reponse.context["total_paye"], reponse.context["total_reste"]), (25000, 15000, 10000))
            impayes = self.client.get(reverse("cantine:tableau"), {"etat": "impayes"})
            self.assertEqual({ligne.pk for ligne in impayes.context["lignes"]}, {en_retard.pk, finie.pk})  # tous ceux qui ont un reste à payer
            terminees = self.client.get(reverse("cantine:tableau"), {"etat": "terminees"})
            self.assertEqual([ligne.pk for ligne in terminees.context["lignes"]], [finie.pk])
            recherche = self.client.get(reverse("cantine:tableau"), {"etat": "toutes", "q": self.e2.nom})
            self.assertEqual([ligne.pk for ligne in recherche.context["lignes"]], [en_retard.pk])

    def test_la_page_de_la_caisse_montre_le_paiement_de_cantine(self):
        inscription = self.inscrire()
        services.enregistrer_paiement(inscription=inscription, montant=5000, mode_paiement="especes", acteur=self.gerant)
        reponse = client_de(self.comptable).get(reverse("finances:registre_caisse"))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Cantine")
        self.assertEqual(reponse.context["solde"], 5000)

    def test_le_journal_de_caisse_separe_la_cantine_de_la_scolarite(self):
        inscription = self.inscrire()
        services.enregistrer_paiement(inscription=inscription, montant=5000, mode_paiement="especes", acteur=self.gerant)
        reponse = client_de(self.comptable).get(reverse("finances:journal_caisse_syscohada"))
        comptes = {ligne["compte"]: (ligne["debit"], ligne["credit"]) for ligne in reponse.context["balance"]}
        self.assertEqual(comptes["571"], (5000, 0))
        self.assertEqual(comptes["706"], (0, 0))  # rien de scolarité
        self.assertEqual(comptes["70608"], (0, 5000))


# ---------------------------------------------------------------------------------------------------------------------
# Les familles
# ---------------------------------------------------------------------------------------------------------------------

class SuiviDesFamillesTests(CantineBase):
    def setUp(self):
        self.i1 = self.inscrire(eleve=self.e1)
        self.i2 = self.inscrire(eleve=self.e2)
        self.autre_parent = creer_compte(Role.PARENT, "parent2@cantine.test", self.ecole)
        self.e2.parents_lies.add(self.autre_parent)

    def test_un_parent_ne_voit_que_ses_enfants(self):
        reponse = client_de(self.parent).get(reverse("cantine:mon_suivi"))
        self.assertEqual(reponse.status_code, 200)
        eleves = [eleve for eleve, _ in reponse.context["familles"]]
        self.assertEqual(eleves, [self.e1])
        self.assertContains(reponse, self.e1.nom)
        self.assertNotContains(reponse, self.e2.nom)

    def test_un_eleve_ne_voit_que_lui(self):
        reponse = client_de(self.e1).get(reverse("cantine:mon_suivi"))
        self.assertEqual([eleve for eleve, _ in reponse.context["familles"]], [self.e1])

    def test_le_personnel_n_a_pas_cette_page(self):
        for compte in (self.gerant, self.comptable, self.t1, self.secretaire):
            with self.subTest(role=compte.role):
                self.assertEqual(client_de(compte).get(reverse("cantine:mon_suivi")).status_code, 403)

    def test_le_solde_de_l_enfant_est_affiche(self):
        with mock.patch("cantine.services.timezone.localdate", return_value=D(2026, 12, 5)):
            services.enregistrer_paiement(inscription=self.i1, montant=5000, mode_paiement="especes", acteur=self.gerant)
            reponse = client_de(self.parent).get(reverse("cantine:mon_suivi"))
        ligne = reponse.context["familles"][0][1][0]
        self.assertEqual((ligne.du, ligne.total_paye, ligne.solde), (15000, 5000, 10000))

    def test_le_lien_du_menu_n_apparait_que_s_il_y_a_une_formule_active(self):
        def liens(compte):
            reponse = client_de(compte).get(reverse("comptes:liste_notifications"))
            return [lien["url"] for section in reponse.context["sections_navigation"] for lien in section["liens"]]

        self.assertIn("cantine:mon_suivi", liens(self.parent))
        FormuleCantine.objects.filter(etablissement=self.ecole).update(active=False)
        self.assertNotIn("cantine:mon_suivi", liens(self.parent))

    def test_le_menu_du_gerant_a_sa_section_et_pas_les_autres(self):
        def liens(compte):
            reponse = client_de(compte).get(reverse("comptes:liste_notifications"))
            return [lien["url"] for section in reponse.context["sections_navigation"] for lien in section["liens"]]

        self.assertTrue({"cantine:tableau", "cantine:appel", "cantine:inscrire_eleves", "cantine:formules"} <= set(liens(self.gerant)))
        for compte in (self.secretaire, self.comptable, self.t1):
            self.assertNotIn("cantine:tableau", liens(compte))
        self.assertNotIn("finances:tenues_vendre", liens(self.gerant))  # il ne vend pas de tenues


# ---------------------------------------------------------------------------------------------------------------------
# Cloisonnement
# ---------------------------------------------------------------------------------------------------------------------

class CloisonnementTests(CantineBase):
    def setUp(self):
        self.inscription = self.inscrire()
        self.paiement = services.enregistrer_paiement(inscription=self.inscription, montant=5000, mode_paiement="especes", acteur=self.gerant)

    def test_une_autre_ecole_ne_voit_ni_ne_touche_rien(self):
        for compte in (self.gerant_b, self.fondateur_b):
            client = client_de(compte)
            for nom, arguments in (
                ("cantine:fiche_inscription", [self.inscription.pk]), ("cantine:paiement", [self.inscription.pk]),
                ("cantine:recu_pdf", [self.paiement.pk]),
            ):
                with self.subTest(role=compte.role, page=nom):
                    self.assertEqual(client.get(reverse(nom, args=arguments)).status_code, 404)
            for nom, arguments, donnees in (
                ("cantine:terminer_inscription", [self.inscription.pk], {"date_fin": "2026-12-01"}),
                ("cantine:annuler_paiement", [self.paiement.pk], {"motif": "Piratage"}),
                ("cantine:basculer_formule", [self.mensuelle.pk], {}),
                ("cantine:paiement", [self.inscription.pk], {"montant": "100", "mode_paiement": "especes"}),
            ):
                with self.subTest(role=compte.role, action=nom):
                    refuse = {403, 404} if nom == "cantine:annuler_paiement" else {404}  # annuler : le gérant est refusé avant même de chercher
                    self.assertIn(client.post(reverse(nom, args=arguments), donnees).status_code, refuse)
        self.inscription.refresh_from_db()
        self.paiement.refresh_from_db()
        self.mensuelle.refresh_from_db()
        self.assertEqual((self.inscription.date_fin, self.paiement.annule, self.mensuelle.active), (None, False, True))
        self.assertEqual(PaiementCantine.objects.count(), 1)

    def test_les_listes_d_une_autre_ecole_sont_vides(self):
        reponse = client_de(self.gerant_b).get(reverse("cantine:tableau"))
        self.assertEqual(list(reponse.context["lignes"]), [])
        self.assertContains(client_de(self.gerant_b).get(reverse("cantine:formules")), "Cantine B")
        self.assertNotContains(client_de(self.gerant_b).get(reverse("cantine:formules")), "Formule du midi")

    def test_les_inscrits_d_une_autre_ecole_ne_sont_pas_dans_mon_appel(self):
        reponse = client_de(self.gerant_b).get(reverse("cantine:appel"))
        self.assertEqual(list(reponse.context["inscrits"]), [])

    def test_une_autre_ecole_ne_peut_pas_inscrire_mes_eleves(self):
        client = client_de(self.gerant_b)
        reponse = client.post(reverse("cantine:inscrire_eleves"), {
            "classe": self.c6a.pk, "formule": self.formule_b.pk, "date_debut": "2026-10-15", "eleves": [self.e2.pk],
        })
        self.assertEqual(InscriptionCantine.objects.filter(eleve=self.e2).count(), 0)
