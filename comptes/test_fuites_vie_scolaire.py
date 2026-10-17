"""
Cloisonnement des pages ajoutées à la vie scolaire (photos, cartes, documents officiels, discipline, calendrier, cahier de textes, programmes,
clôtures, frais annexes, anciens élèves, pré-inscription, noms en arabe) : ni une autre école, ni un visiteur anonyme, ni un compte de la même
école sans lien avec l'élève ou la classe ne voit ni ne modifie rien.

Chaque donnée de l'école A porte un mot-témoin (MOT-TEMOIN-...) : s'il apparaît dans la page d'un compte qui n'y a pas droit, c'est une fuite.
"""
import datetime

from django.test import Client
from django.urls import reverse

from comptes.roles import Role
from finances.models import FraisAnnexe, Paiement
from pedagogie.models import ChapitreProgramme, MesureDiscipline, PeriodeCloturee, SeanceCahier, TypeMesureDiscipline
from scolarite.models import Affectation, EvenementCalendrier, Inscription
from statistiques.test_education import EducationBase, creer_compte
from tests_niveau.models import Candidat, CampagnePreinscription, StatutDemande

D = datetime.date
TEMOINS = (
    "MOT-TEMOIN-DISCIPLINE", "MOT-TEMOIN-CAHIER", "MOT-TEMOIN-DEVOIR", "MOT-TEMOIN-CHAPITRE", "MOT-TEMOIN-FRAIS", "MOT-TEMOIN-CALENDRIER",
    "MOT-TEMOIN-CAMPAGNE", "MOT-TEMOIN-CANDIDAT", "MOT-TEMOIN-PERE", "MOT-TEMOIN-ADRESSE", "MOT-TEMOIN-URGENCE",
)
MODELES_SURVEILLES = (MesureDiscipline, SeanceCahier, ChapitreProgramme, FraisAnnexe, EvenementCalendrier, CampagnePreinscription, Candidat, PeriodeCloturee, Inscription, Paiement)
REFUSES = {403, 404, 405}


def client_de(compte):
    client = Client()
    if compte is not None:
        client.force_login(compte)
    return client


class CloisonnementDesPagesDeLaVieScolaireTests(EducationBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.mesure = MesureDiscipline.objects.create(
            eleve=cls.e1, classe=cls.c6a, date_mesure=D(2026, 10, 5), type_mesure=TypeMesureDiscipline.BLAME, motif="MOT-TEMOIN-DISCIPLINE",
            enregistre_par=cls.fondateur,
        )
        cls.affectation = Affectation.objects.get(enseignant=cls.t1, classe=cls.c6a)
        cls.seance = SeanceCahier.objects.create(
            affectation=cls.affectation, date_seance=D(2026, 10, 6), contenu="MOT-TEMOIN-CAHIER", travail_a_faire="MOT-TEMOIN-DEVOIR",
            date_remise=D(2027, 1, 6), cree_par=cls.t1,
        )
        cls.chapitre = ChapitreProgramme.objects.create(affectation=cls.affectation, titre="MOT-TEMOIN-CHAPITRE", pourcentage=30)
        cls.frais = FraisAnnexe.objects.create(
            etablissement=cls.ecole, annee_scolaire=cls.annee, libelle="MOT-TEMOIN-FRAIS", montant=7000, cree_par=cls.fondateur,
        )
        cls.evenement = EvenementCalendrier.objects.create(
            etablissement=cls.ecole, titre="MOT-TEMOIN-CALENDRIER", date_debut=D(2026, 11, 2), cree_par=cls.fondateur,
        )
        cls.campagne = CampagnePreinscription.objects.create(
            etablissement=cls.ecole, titre="MOT-TEMOIN-CAMPAGNE", annee_scolaire=cls.annee, cree_par=cls.fondateur,
        )
        cls.candidat = Candidat.objects.create(
            prenom="MOT-TEMOIN-CANDIDAT", nom="Famille", date_naissance=D(2015, 1, 1), telephone_contact="70123456", classe_visee=cls.c6a,
            campagne=cls.campagne, statut_demande=StatutDemande.RECUE, email_contact="famille@fuites.test",
        )
        cls.e1.nom_pere, cls.e1.adresse, cls.e1.contact_urgence_nom = "MOT-TEMOIN-PERE", "MOT-TEMOIN-ADRESSE", "MOT-TEMOIN-URGENCE"
        cls.e1.save()

        # École B
        cls.secretaire_b = creer_compte(Role.SECRETAIRE, "secretaire@fuites-b.test", cls.ecole_b)
        cls.parent_b = creer_compte(Role.PARENT, "parent@fuites-b.test", cls.ecole_b)
        cls.eleve_b = creer_compte(Role.ELEVE, "eleve@fuites-b.test", cls.ecole_b)
        cls.enseignant_b = creer_compte(Role.ENSEIGNANT, "enseignant@fuites-b.test", cls.ecole_b)
        Inscription.objects.create(eleve=cls.eleve_b, classe=cls.classe_b)
        cls.eleve_b.parents_lies.add(cls.parent_b)

        # École A : des comptes sans lien avec l'élève e1 ni avec sa classe (6A)
        cls.parent_autre = creer_compte(Role.PARENT, "parent-autre@fuites.test", cls.ecole)
        cls.e4.parents_lies.add(cls.parent_autre)

    # -- les adresses qui portent un objet de l'école A ------------------------------------------------------------------

    def adresses_de_l_ecole_a(self):
        matricule, classe, annee = self.e1.matricule, self.c6a.pk, self.annee.pk
        return [
            reverse("scolarite:photo_eleve", args=[matricule]),
            reverse("scolarite:envoyer_photo_eleve", args=[matricule]),
            reverse("scolarite:supprimer_photo_eleve", args=[matricule]),
            reverse("scolarite:importer_photos_classe", args=[classe]),
            reverse("scolarite:cartes_classe_pdf", args=[classe]),
            reverse("scolarite:carte_eleve_pdf", args=[matricule]),
            reverse("scolarite:reintegrer_eleve", args=[matricule]),
            reverse("scolarite:modifier_evenement", args=[self.evenement.pk]),
            reverse("scolarite:supprimer_evenement", args=[self.evenement.pk]),
            *[reverse("scolarite:document_officiel", args=[matricule, code]) for code in ("certificat-scolarite", "attestation-frequentation", "certificat-radiation")],
            reverse("scolarite:exporter_liste_classe_csv", args=[classe]),
            reverse("scolarite:exporter_liste_classe_pdf", args=[classe]),
            reverse("scolarite:exporter_liste_classe_xlsx", args=[classe]),
            reverse("pedagogie:registre_discipline", args=[classe]),
            reverse("pedagogie:historique_discipline", args=[matricule]),
            reverse("pedagogie:supprimer_mesure_discipline", args=[self.mesure.pk]),
            reverse("pedagogie:cahier_affectation", args=[self.affectation.pk]),
            reverse("pedagogie:cahier_classe", args=[classe]),
            reverse("pedagogie:modifier_seance", args=[self.seance.pk]),
            reverse("pedagogie:supprimer_seance", args=[self.seance.pk]),
            reverse("pedagogie:programme_affectation", args=[self.affectation.pk]),
            reverse("pedagogie:modifier_chapitre", args=[self.chapitre.pk]),
            reverse("pedagogie:supprimer_chapitre", args=[self.chapitre.pk]),
            reverse("pedagogie:exporter_bulletins_classe_pdf", args=[classe]),
            reverse("pedagogie:cloturer_periode", args=[annee, "trimestre_1"]),
            reverse("pedagogie:rouvrir_periode", args=[annee, "trimestre_1"]),
            reverse("finances:supprimer_frais_annexe", args=[self.frais.pk]),
            reverse("tests_niveau:basculer_campagne", args=[self.campagne.pk]),
            reverse("tests_niveau:convoquer_candidat", args=[self.candidat.pk]),
            reverse("tests_niveau:refuser_demande", args=[self.candidat.pk]),
            reverse("tests_niveau:decider_candidat", args=[self.candidat.pk, "admis"]),
        ]

    # -- les pages sans objet dans l'adresse (leur contenu dépend du compte qui les ouvre) --------------------------------

    PAGES_DU_COMPTE = (
        "scolarite:calendrier", "scolarite:anciens_eleves", "scolarite:liste_eleves", "scolarite:liste_classes", "pedagogie:devoirs",
        "pedagogie:avancement_programmes", "pedagogie:clotures_notes", "finances:frais_annexes", "finances:arrieres", "tests_niveau:campagnes",
        "tests_niveau:liste_candidats", "comptes:noms_en_arabe", "comptes:redirection_tableau_de_bord", "comptes:liste_notifications",
    )

    def etat_de_la_base(self):
        return [list(modele.objects.order_by("pk").values()) for modele in MODELES_SURVEILLES]

    # -- une autre école et les visiteurs anonymes ------------------------------------------------------------------------

    def comptes_de_l_ecole_b(self):
        return [self.fondateur_b, self.secretaire_b, self.parent_b, self.eleve_b, self.enseignant_b]

    def test_une_autre_ecole_n_atteint_aucun_objet_de_l_ecole_a(self):
        for compte in self.comptes_de_l_ecole_b():
            client = client_de(compte)
            for adresse in self.adresses_de_l_ecole_a():
                for methode in ("get", "post"):
                    with self.subTest(compte=compte.role, adresse=adresse, methode=methode):
                        statut = getattr(client, methode)(adresse).status_code
                        self.assertIn(statut, REFUSES, f"{methode.upper()} {adresse} répond {statut} à un compte de l'école B")

    def test_une_autre_ecole_ne_change_rien_dans_la_base(self):
        avant = self.etat_de_la_base()
        for compte in self.comptes_de_l_ecole_b():
            client = client_de(compte)
            for adresse in self.adresses_de_l_ecole_a():
                client.post(adresse, {})
        self.assertEqual(self.etat_de_la_base(), avant)

    def test_les_pages_d_une_autre_ecole_ne_montrent_rien_de_l_ecole_a(self):
        for compte in self.comptes_de_l_ecole_b():
            client = client_de(compte)
            for nom in self.PAGES_DU_COMPTE:
                with self.subTest(compte=compte.role, page=nom):
                    reponse = client.get(reverse(nom))
                    if reponse.status_code == 200:
                        page = reponse.content.decode("utf-8", errors="replace")
                        for temoin in TEMOINS + (self.e1.matricule, "famille@fuites.test"):
                            self.assertNotIn(temoin, page)

    def test_un_visiteur_anonyme_est_renvoye_vers_la_connexion_partout(self):
        client = client_de(None)
        pages = [reverse(nom) for nom in self.PAGES_DU_COMPTE]
        for adresse in self.adresses_de_l_ecole_a() + pages:
            for methode in ("get", "post"):
                with self.subTest(adresse=adresse, methode=methode):
                    reponse = getattr(client, methode)(adresse)
                    self.assertEqual(reponse.status_code, 302)
                    self.assertIn("/connexion", reponse["Location"])

    # -- la même école, sans lien avec l'élève ou la classe -----------------------------------------------------------------

    def test_un_compte_sans_lien_avec_l_eleve_ou_la_classe_n_y_acces_pas(self):
        # Le parent d'un autre enfant, un élève d'une autre classe et un enseignant sans cours en 6A.
        for compte in (self.parent_autre, self.e4, self.t2):
            client = client_de(compte)
            for adresse in self.adresses_de_l_ecole_a():
                with self.subTest(compte=compte.email, adresse=adresse):
                    self.assertIn(client.get(adresse).status_code, REFUSES)

    def test_un_compte_sans_droit_sur_l_etat_civil_ne_voit_pas_le_dossier_complet(self):
        # Les enseignants, le comptable et le censeur voient parfois l'élève, jamais sa filiation, son adresse ni son contact d'urgence.
        for compte in (self.t1, self.comptable, self.censeur):
            client = client_de(compte)
            for adresse in (
                reverse("scolarite:dossier_eleve", args=[self.e1.matricule]), reverse("scolarite:liste_eleves"),
                reverse("pedagogie:historique_discipline", args=[self.e1.matricule]),
            ):
                reponse = client.get(adresse)
                if reponse.status_code == 200:
                    page = reponse.content.decode("utf-8", errors="replace")
                    for temoin in ("MOT-TEMOIN-PERE", "MOT-TEMOIN-ADRESSE", "MOT-TEMOIN-URGENCE"):
                        with self.subTest(compte=compte.role, adresse=adresse, temoin=temoin):
                            self.assertNotIn(temoin, page)

    def test_le_calendrier_reserve_au_personnel_reste_cache_aux_familles(self):
        EvenementCalendrier.objects.create(
            etablissement=self.ecole, titre="REUNION-DU-PERSONNEL", date_debut=D(2026, 11, 3), reserve_au_personnel=True, cree_par=self.fondateur,
        )
        for compte in (self.parent, self.e1):
            page = client_de(compte).get(reverse("scolarite:calendrier")).content.decode("utf-8")
            self.assertIn("MOT-TEMOIN-CALENDRIER", page)  # la date ouverte à tous s'affiche bien
            self.assertNotIn("REUNION-DU-PERSONNEL", page)
        page = client_de(self.fondateur).get(reverse("scolarite:calendrier")).content.decode("utf-8")
        self.assertIn("REUNION-DU-PERSONNEL", page)  # et le personnel voit les deux
