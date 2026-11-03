"""
Ce que chacun voit du parcours d'un élève qui a changé de cycle.

e5 a fini sa 5ème année (1er cycle, l'an dernier, admise) puis est en 9ème année (2ème cycle, cette année). Chaque classe porte ses propres données,
marquées d'un jeton (une absence « ABS5AXQ », une note en « MAT5AXQ », un paiement « PAI5AXQ »...). Un directeur ou un enseignant qui a eu l'élève
dans SA classe ne lit rien de ce qui s'est passé ensuite dans une classe qu'il ne voit pas : ni les notes, ni les absences, ni la discipline, ni les
paiements, ni les documents ; il ne remet pas non plus le mot de passe de l'élève, ne clôture pas son inscription et ne le réintègre pas.
L'élève, ses parents et l'administration de toute l'école voient tout le parcours.

Les modules sont accordés à tous les profils (l'école règle sa matrice) : cela ne doit rien changer à ce que chacun voit.
"""
import datetime
import html
from types import SimpleNamespace
from unittest import mock

from django.test import Client
from django.urls import reverse

from cantine import services as services_cantine
from cantine.models import FormuleCantine, InscriptionCantine, ModeCantine, RepasCantine
from comptes.roles import Role
from finances.models import Paiement, TypeTranche, enregistrer_paiement
from pedagogie.models import Absence, MesureDiscipline, Trimestre, TypeMesureDiscipline, saisir_note
from permissions_matrix.models import PermissionMatrix
from permissions_matrix.modules import Module
from scolarite.models import Affectation, Inscription, ResultatExamen
from scolarite.test_dossier_complet import StockageTemporaire
from statistiques.test_education import creer_compte

JETONS = {  # par classe : ce que cette classe a écrit pour e5
    "5A": {"ABS": "ABS5AXQ", "DIS": "DIS5AXQ", "MAT": "MAT5AXQ", "PAI": "PAI5AXQ"},
    "9A": {"ABS": "ABS9AXQ", "DIS": "DIS9AXQ", "MAT": "MAT9AXQ", "PAI": "PAI9AXQ"},
}
MODULES = (
    Module.ELEVES, Module.CLASSES, Module.FINANCES, Module.CANTINE, Module.NOTES_BULLETINS, Module.ABSENCES, Module.ASSISTANT,
)


class ParcoursEntreDeuxCyclesTests(StockageTemporaire):
    def setUp(self):
        self.insc_5a = Inscription.objects.create(eleve=self.e5, classe=self.classe_5a, statut=Inscription.Statut.ADMIS)
        self.insc_9a = self.i["e5"]
        self.dir_2eme = creer_compte(Role.DIRECTEUR_2EME_CYCLE, "dir2@parcours.test", self.ecole)
        self.dir_lycee = creer_compte(Role.DIRECTEUR_LYCEE, "dirl@parcours.test", self.ecole)
        self.parent5 = creer_compte(Role.PARENT, "parent5@parcours.test", self.ecole, telephone="70999015")
        self.e5.parents_lies.add(self.parent5)
        # (nom, compte, classes de e5 que cette personne voit)
        self.profils = [
            ("fondateur", self.fondateur, {"5A", "9A"}),
            ("secrétaire", self.secretaire, {"5A", "9A"}),
            ("directeur du 1er cycle", self.dir_1er, {"5A"}),
            ("directeur du 2ème cycle", self.dir_2eme, {"9A"}),
            ("enseignant de l'an dernier (5A)", self.t_ancien, {"5A"}),
            ("enseignant de la 9A", self.t2, {"9A"}),
            ("parent de e5", self.parent5, {"5A", "9A"}),
            ("élève e5", self.e5, {"5A", "9A"}),
        ]
        for _, compte, _ in self.profils + [("", self.dir_lycee, set()), ("", self.t1, set())]:
            for module in MODULES:
                PermissionMatrix.objects.update_or_create(
                    etablissement=self.ecole, role=compte.role, module=module, defaults={"autorise": True},
                )

        # Chaque classe écrit ses propres données sur e5.
        Affectation.objects.filter(enseignant=self.t_ancien, classe=self.classe_5a).update(matiere=JETONS["5A"]["MAT"])
        Affectation.objects.filter(enseignant=self.t2, classe=self.c9a).update(matiere=JETONS["9A"]["MAT"])
        for enseignant, classe in ((self.t_ancien, self.classe_5a), (self.t2, self.c9a)):
            saisir_note(
                eleve=self.e5, affectation=Affectation.objects.get(enseignant=enseignant, classe=classe), trimestre=Trimestre.T1.value,
                enseignant=enseignant, note_classe=12, note_composition=14,
            )
        for classe, nom, jour in ((self.classe_5a, "5A", datetime.date(2026, 5, 12)), (self.c9a, "9A", datetime.date(2026, 10, 12))):
            Absence.objects.create(eleve=self.e5, classe=classe, date_absence=jour, justifiee=False, motif=JETONS[nom]["ABS"])
            MesureDiscipline.objects.create(
                eleve=self.e5, classe=classe, date_mesure=jour, type_mesure=TypeMesureDiscipline.AVERTISSEMENT, motif=JETONS[nom]["DIS"],
            )
        self.paiement = {}
        for inscription, nom, montant in ((self.insc_5a, "5A", 1000), (self.insc_9a, "9A", 2000)):
            paiement = enregistrer_paiement(
                eleve=self.e5, inscription=inscription, tranche=TypeTranche.VERSEMENT, montant=montant, mode_paiement="especes",
                enregistre_par=self.comptable,
            )
            Paiement.objects.filter(pk=paiement.pk).update(reference=JETONS[nom]["PAI"])
            self.paiement[nom] = Paiement.objects.get(pk=paiement.pk)
        ResultatExamen.objects.create(inscription=self.insc_5a, examen="entree_7e", resultat=ResultatExamen.Resultat.ADMIS)

    # ------------------------------------------------------------------------------------------------------------------
    def ouvrir(self, compte, adresse, donnees=None):
        """(réponse, texte de la page + HTML des PDF produits)."""
        client = Client(raise_request_exception=False)
        client.force_login(compte)
        pdf_vus = []

        def faux_pdf(contenu, *args, **kwargs):
            pdf_vus.append(contenu)
            return SimpleNamespace(err=0)

        with mock.patch("comptes.pdf.pisa.CreatePDF", side_effect=faux_pdf):
            reponse = client.post(adresse, donnees) if donnees is not None else client.get(adresse)
        corps = reponse.content.decode("utf-8", errors="replace") if reponse.status_code == 200 else ""
        return reponse, html.unescape(corps + " ".join(pdf_vus))

    def jetons_lus(self, texte, genre):
        return {nom for nom, jetons in JETONS.items() if jetons[genre] in texte}

    def adresse(self, nom, *args):
        return reverse(nom, args=args)

    # ------------------------------------------------------------------------------------------------------------------
    def test_le_dossier_ne_montre_que_le_parcours_des_classes_de_la_personne(self):
        id_classe = {"5A": self.classe_5a.pk, "9A": self.c9a.pk}
        for nom, compte, classes in self.profils:
            with self.subTest(profil=nom):
                reponse, texte = self.ouvrir(compte, self.adresse("scolarite:dossier_eleve", self.e5.matricule))
                self.assertEqual(reponse.status_code, 200)
                self.assertEqual({i.classe_id for i in reponse.context["inscriptions"]}, {id_classe[c] for c in classes})
                active = reponse.context["inscription_active"]
                self.assertEqual(active is not None, "9A" in classes)  # l'inscription en cours est celle de la 9A
                self.assertEqual(int(reponse.context["total_absences"]), len(classes))
                self.assertEqual(int(reponse.context["total_paye"]), (1000 if "5A" in classes else 0) + (2000 if "9A" in classes else 0))
                if "resultats_examens" in reponse.context:  # l'état civil et les examens : l'élève, ses parents, la direction et le secrétariat
                    self.assertEqual({r.inscription.classe_id for r in reponse.context["resultats_examens"]}, {id_classe[c] for c in classes})
                    self.assertEqual("Certificat d'entrée" in texte, "5A" in classes)
                    self.assertEqual("Diplôme d'études fondamentales" in texte, "9A" in classes)

    def test_les_pages_de_l_eleve_ne_montrent_que_les_donnees_des_classes_de_la_personne(self):
        pages = {
            "ABS": self.adresse("pedagogie:historique_absences", self.e5.matricule),
            "DIS": self.adresse("pedagogie:historique_discipline", self.e5.matricule),
            "MAT": self.adresse("pedagogie:bulletin_eleve", self.e5.matricule),
            "PAI": self.adresse("finances:liste_paiements"),
        }
        for nom, compte, classes in self.profils:
            for genre, adresse in pages.items():
                with self.subTest(profil=nom, page=genre):
                    reponse, texte = self.ouvrir(compte, adresse)
                    self.assertEqual(reponse.status_code, 200)
                    attendu = classes
                    if genre == "MAT":  # le bulletin est celui de l'inscription en cours (9A) ; sinon les notes des classes qu'on voit
                        attendu = {"9A"} if "9A" in classes else classes
                    self.assertEqual(self.jetons_lus(texte, genre), attendu)

    def test_le_bulletin_en_pdf_suit_la_meme_regle(self):
        adresse = self.adresse("pedagogie:exporter_bulletin_pdf", self.e5.matricule)
        for nom, compte, classes in self.profils:
            with self.subTest(profil=nom):
                reponse, texte = self.ouvrir(compte, adresse)
                self.assertEqual(reponse.status_code, 200)
                self.assertEqual(self.jetons_lus(texte, "MAT"), {"9A"} if "9A" in classes else classes)

    def test_un_bulletin_demande_par_son_numero_n_est_donne_qu_a_qui_voit_la_classe(self):
        demandes = {"5A": self.insc_5a.pk, "9A": self.insc_9a.pk}
        for nom, compte, classes in self.profils:
            for page in ("pedagogie:bulletin_eleve", "pedagogie:exporter_bulletin_pdf"):
                for classe, pk in demandes.items():
                    with self.subTest(profil=nom, page=page, classe=classe):
                        reponse, texte = self.ouvrir(compte, self.adresse(page, self.e5.matricule) + f"?inscription={pk}")
                        if classe in classes:
                            self.assertEqual(reponse.status_code, 200)
                            self.assertEqual(self.jetons_lus(texte, "MAT"), {classe})
                        else:
                            self.assertEqual(reponse.status_code, 404)
        reponse, _ = self.ouvrir(self.fondateur, self.adresse("pedagogie:bulletin_eleve", self.e5.matricule) + "?inscription=abc")
        self.assertEqual(reponse.status_code, 404)  # un numéro qui n'en est pas un ne désigne rien (et ne plante plus)

    def test_le_recu_d_un_paiement_est_introuvable_hors_de_ses_classes(self):
        for nom, compte, classes in self.profils:
            for classe, paiement in self.paiement.items():
                with self.subTest(profil=nom, classe=classe):
                    reponse, texte = self.ouvrir(compte, self.adresse("finances:exporter_recu_paiement_pdf", paiement.pk))
                    self.assertEqual(reponse.status_code, 200 if classe in classes else 404 if compte.role != Role.PARENT else 403)

    def test_l_assistant_ne_donne_que_ce_qui_s_est_passe_dans_les_classes_de_la_personne(self):
        adresse = reverse("assistant:poser_question") + f"?matricule={self.e5.matricule}"
        for nom, compte, classes in self.profils:
            if compte.role == Role.ELEVE:
                continue  # l'assistant n'est pas fait pour l'élève
            with self.subTest(profil=nom):
                reponse, texte = self.ouvrir(compte, adresse)
                self.assertEqual(reponse.status_code, 200)
                resultat = reponse.context["resultat"]
                self.assertEqual(self.jetons_lus(texte, "PAI") if "derniers_paiements" in resultat else set(), classes if compte.role != Role.PARENT else classes)
                self.assertEqual(int(resultat["total_absences"]), len(classes))
                self.assertEqual({n.affectation.matiere for n in resultat["dernieres_notes"]}, {JETONS[c]["MAT"] for c in classes})
                self.assertEqual(resultat["inscription"] is not None, "9A" in classes)

    def test_les_documents_sont_ceux_de_la_classe_de_la_personne(self):
        certificat = self.adresse("scolarite:document_officiel", self.e5.matricule, "certificat-scolarite")
        attestation = self.adresse("scolarite:generer_attestation_scolarite", self.e5.matricule)
        carte = self.adresse("scolarite:carte_eleve_pdf", self.e5.matricule)
        # Le directeur du 1er cycle n'édite que le certificat de la 5A (admise) : jamais l'attestation ni la carte de la 9A.
        reponse, texte = self.ouvrir(self.dir_1er, certificat)
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("2025-2026", texte)
        self.assertNotIn("2026-2027", texte)
        for adresse in (attestation, carte):
            reponse, _ = self.ouvrir(self.dir_1er, adresse)
            self.assertEqual(reponse.status_code, 302)  # « aucune inscription en cours pour cet élève »
        # Le directeur du 2ème cycle, lui, édite ceux de la 9A.
        reponse, texte = self.ouvrir(self.dir_2eme, certificat)
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("2026-2027", texte)
        self.assertNotIn("2025-2026", texte)
        for adresse in (attestation, carte):
            reponse, _ = self.ouvrir(self.dir_2eme, adresse)
            self.assertEqual(reponse.status_code, 200)

    def test_les_fichiers_portent_le_numero_du_cycle_et_non_le_matricule_d_origine(self):
        from scolarite.models import Cycle, NumeroCycle

        NumeroCycle.objects.create(eleve=self.e5, cycle=Cycle.DEUXIEME_CYCLE, numero="NEUF-9A-77")
        NumeroCycle.objects.create(eleve=self.e5, cycle=Cycle.PREMIER_CYCLE, numero="UN-5A-11")
        for compte, adresse, attendu in (
            (self.fondateur, self.adresse("pedagogie:exporter_bulletin_pdf", self.e5.matricule), "bulletin_NEUF-9A-77.pdf"),
            (self.fondateur, self.adresse("pedagogie:exporter_bulletin_pdf", self.e5.matricule) + f"?inscription={self.insc_5a.pk}", "bulletin_UN-5A-11.pdf"),
            (self.fondateur, self.adresse("scolarite:carte_eleve_pdf", self.e5.matricule), "carte_NEUF-9A-77.pdf"),
            (self.fondateur, self.adresse("scolarite:generer_attestation_scolarite", self.e5.matricule), "attestation_NEUF-9A-77.pdf"),
            (self.dir_1er, self.adresse("scolarite:document_officiel", self.e5.matricule, "certificat-scolarite"), "cert_UN-5A-11.pdf"),
        ):
            with self.subTest(adresse=adresse):
                reponse, _ = self.ouvrir(compte, adresse)
                self.assertEqual(reponse.status_code, 200)
                self.assertIn(attendu, reponse["Content-Disposition"])
                self.assertNotIn(self.e5.matricule, reponse["Content-Disposition"])

    def test_le_bulletin_mensuel_n_existe_que_pour_le_cycle_de_la_personne(self):
        adresse = self.adresse("pedagogie:mensuel_eleve", self.e5.matricule) + f"?inscription={self.insc_5a.pk}"
        self.assertEqual(self.ouvrir(self.dir_1er, adresse)[0].status_code, 200)  # la 5A est du 1er cycle
        self.assertEqual(self.ouvrir(self.t_ancien, adresse)[0].status_code, 200)
        self.assertEqual(self.ouvrir(self.dir_2eme, adresse)[0].status_code, 404)  # il ne voit pas cette classe
        self.assertEqual(self.ouvrir(self.t2, adresse)[0].status_code, 404)

    # ------------------------------------------------------------------------------------------------------------------
    def test_on_n_agit_pas_sur_un_eleve_qui_n_est_plus_dans_ses_classes(self):
        mot_de_passe = self.adresse("scolarite:mot_de_passe_provisoire", self.e5.matricule)
        cloture = self.adresse("scolarite:cloturer_inscription", self.e5.matricule)
        correction = self.adresse("scolarite:corriger_dossier_eleve", self.e5.matricule)
        avant = self.e5.__class__.objects.get(pk=self.e5.pk).password

        self.assertEqual(self.ouvrir(self.dir_1er, mot_de_passe, donnees={})[0].status_code, 403)
        self.assertEqual(self.e5.__class__.objects.get(pk=self.e5.pk).password, avant)  # rien n'a été remis
        self.assertEqual(self.ouvrir(self.dir_1er, cloture)[0].status_code, 404)  # l'inscription en cours est celle de la 9A
        self.assertEqual(self.ouvrir(self.dir_1er, cloture, donnees={"decision": "abandon", "motif": "x", "date_evenement": "2026-11-02"})[0].status_code, 404)
        self.assertEqual(Inscription.objects.get(pk=self.insc_9a.pk).statut, Inscription.Statut.EN_COURS)
        self.assertEqual(self.ouvrir(self.dir_1er, correction)[0].status_code, 403)

        self.assertEqual(self.ouvrir(self.dir_2eme, cloture)[0].status_code, 200)
        self.assertEqual(self.ouvrir(self.dir_2eme, correction)[0].status_code, 200)
        self.assertEqual(self.ouvrir(self.dir_2eme, mot_de_passe, donnees={})[0].status_code, 200)

    def test_la_reintegration_se_fait_dans_le_cycle_d_ou_l_eleve_est_parti(self):
        parti = creer_compte(Role.ELEVE, "parti@parcours.test", self.ecole)
        Inscription.objects.create(eleve=parti, classe=self.classe_5a, statut=Inscription.Statut.ADMIS)
        Inscription.objects.create(eleve=parti, classe=self.ctse, statut=Inscription.Statut.ABANDON)  # parti du lycée
        adresse = self.adresse("scolarite:reintegrer_eleve", parti.matricule)
        self.assertEqual(self.ouvrir(self.dir_1er, adresse)[0].status_code, 404)  # il l'a eu en 5A, mais il est parti du lycée
        self.assertEqual(self.ouvrir(self.dir_lycee, adresse)[0].status_code, 200)
        reponse, _ = self.ouvrir(self.dir_1er, self.adresse("scolarite:dossier_eleve", parti.matricule))
        self.assertFalse(reponse.context["peut_reintegrer"])
        reponse, _ = self.ouvrir(self.dir_lycee, self.adresse("scolarite:dossier_eleve", parti.matricule))
        self.assertTrue(reponse.context["peut_reintegrer"])

    # ------------------------------------------------------------------------------------------------------------------
    def inscrire_a_la_cantine(self, eleves):
        formule = FormuleCantine.objects.create(etablissement=self.ecole, libelle="Midi", mode=ModeCantine.MENSUEL, montant=5000)
        inscriptions = {}
        for eleve in eleves:
            inscription = InscriptionCantine(
                etablissement=self.ecole, eleve=eleve, annee_scolaire=self.annee, formule=formule,
                date_debut=datetime.date(2026, 10, 15), cree_par=self.fondateur,
            )
            inscription.full_clean()
            inscription.save()
            inscriptions[eleve.pk] = inscription
        return inscriptions

    def test_la_cantine_ne_montre_que_les_eleves_de_ses_classes(self):
        inscriptions = self.inscrire_a_la_cantine([self.e1, self.e5])  # e1 est en 6A (1er cycle), e5 en 9A (2ème cycle)
        paiement = services_cantine.enregistrer_paiement(inscription=inscriptions[self.e5.pk], montant=5000, mode_paiement="especes", acteur=self.fondateur)
        for nom, compte, attendus in (
            ("fondateur", self.fondateur, {self.e1.pk, self.e5.pk}), ("directeur du 1er cycle", self.dir_1er, {self.e1.pk}),
            ("directeur du 2ème cycle", self.dir_2eme, {self.e5.pk}), ("enseignant de la 6A", self.t1, {self.e1.pk}),
        ):
            with self.subTest(profil=nom):
                reponse, _ = self.ouvrir(compte, reverse("cantine:tableau"))
                self.assertEqual(reponse.status_code, 200)
                self.assertEqual({ligne.eleve_id for ligne in reponse.context["lignes"]}, attendus)
                for eleve in (self.e1, self.e5):
                    for adresse in (
                        reverse("cantine:fiche_inscription", args=[inscriptions[eleve.pk].pk]), reverse("cantine:paiement", args=[inscriptions[eleve.pk].pk]),
                    ):
                        self.assertEqual(self.ouvrir(compte, adresse)[0].status_code, 200 if eleve.pk in attendus else 404, (nom, adresse))
                self.assertEqual(
                    self.ouvrir(compte, reverse("cantine:recu_pdf", args=[paiement.pk]))[0].status_code, 200 if self.e5.pk in attendus else 404,
                )
        # Un parent ou un élève n'a que « mon suivi », même si l'école lui accorde le module.
        for compte in (self.parent5, self.e5):
            for adresse in (reverse("cantine:tableau"), reverse("cantine:fiche_inscription", args=[inscriptions[self.e5.pk].pk]), reverse("cantine:appel")):
                self.assertEqual(self.ouvrir(compte, adresse)[0].status_code, 403, (compte.role, adresse))
        self.assertEqual(self.ouvrir(self.parent5, reverse("cantine:mon_suivi"))[0].status_code, 200)

    def test_l_appel_de_la_cantine_ne_touche_que_les_eleves_de_ses_classes(self):
        inscriptions = self.inscrire_a_la_cantine([self.e1, self.e5])
        jour = datetime.date(2026, 11, 2)
        for inscription in inscriptions.values():
            RepasCantine.objects.create(inscription=inscription, date_repas=jour, saisi_par=self.fondateur)
        # Le directeur du 1er cycle décoche tout : seul le repas de e1 (6A) disparaît, celui de e5 (9A) reste.
        reponse, _ = self.ouvrir(self.dir_1er, reverse("cantine:appel"), donnees={"date": jour.isoformat()})
        self.assertEqual(reponse.status_code, 302)
        self.assertFalse(RepasCantine.objects.filter(inscription=inscriptions[self.e1.pk], date_repas=jour).exists())
        self.assertTrue(RepasCantine.objects.filter(inscription=inscriptions[self.e5.pk], date_repas=jour).exists())
        # Et il ne coche pas le repas d'un élève d'un autre cycle en envoyant son numéro.
        RepasCantine.objects.filter(inscription=inscriptions[self.e5.pk]).delete()
        self.ouvrir(self.dir_1er, reverse("cantine:appel"), donnees={"date": jour.isoformat(), "presents": [inscriptions[self.e5.pk].pk]})
        self.assertFalse(RepasCantine.objects.filter(inscription=inscriptions[self.e5.pk], date_repas=jour).exists())
