"""Conseils de classe : droits, cloisonnement, calculs, enregistrement, validation, documents PDF et passage de classe."""
from decimal import Decimal

from django.test import override_settings
from django.urls import reverse

from comptes.models import JournalAudit
from comptes.roles import Role
from pedagogie.conseils import distinction_suggeree, passage_suggere
from pedagogie.models import ConseilDeClasse, DecisionConseil, Trimestre, saisir_note
from scolarite.models import Affectation, Inscription
from statistiques.test_education import EducationBase, creer_compte

T1, T2, T3 = Trimestre.T1.value, Trimestre.T2.value, Trimestre.T3.value


class ConseilBase(EducationBase):
    """6A : e1 (moyenne 18), e2 (12), e3 (8) au 1er trimestre ; e1 et e2 ont aussi des notes au 3ème."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.affectation = Affectation.objects.get(enseignant=cls.t1, classe=cls.c6a)
        for eleve, classe, composition in ((cls.e1, 18, 36), (cls.e2, 12, 24), (cls.e3, 8, 16)):
            saisir_note(eleve=eleve, affectation=cls.affectation, trimestre=T1, enseignant=cls.t1, note_classe=classe, note_composition=composition)
        saisir_note(eleve=cls.e1, affectation=cls.affectation, trimestre=T3, enseignant=cls.t1, note_classe=14, note_composition=28)
        saisir_note(eleve=cls.e2, affectation=cls.affectation, trimestre=T3, enseignant=cls.t1, note_classe=6, note_composition=12)
        cls.surveillant = creer_compte(Role.SURVEILLANT_GENERAL, "surveillant@conseil.test", cls.ecole)
        cls.resp_peda = creer_compte(Role.RESPONSABLE_PEDAGOGIQUE, "resp@conseil.test", cls.ecole)
        cls.fondateur_b = creer_compte(Role.FONDATEUR, "fondateur@conseil-b.test", cls.ecole_b)

    def adresse(self, trimestre=T1, classe=None):
        return reverse("pedagogie:conseil", args=[(classe or self.c6a).pk, trimestre])

    def envoyer(self, donnees, trimestre=T1, classe=None, suivre=True):
        return self.client.post(self.adresse(trimestre, classe), donnees, follow=suivre)

    def lignes(self, reponse):
        return {ligne["eleve"].pk: ligne for ligne in reponse.context["lignes"]}


class DroitsEtCloisonnementTests(ConseilBase):
    def test_la_direction_voit_la_liste_et_le_conseil(self):
        for compte in (self.fondateur, self.resp_peda, self.dir_1er):
            with self.subTest(role=compte.role):
                self.client.force_login(compte)
                self.assertEqual(self.client.get(reverse("pedagogie:conseils")).status_code, 200)
                self.assertEqual(self.client.get(self.adresse()).status_code, 200)

    def test_les_autres_roles_n_y_ont_pas_acces(self):
        for compte in (self.comptable, self.secretaire, self.surveillant, self.t1, self.parent, self.e1):
            with self.subTest(role=compte.role):
                self.client.force_login(compte)
                self.assertEqual(self.client.get(reverse("pedagogie:conseils")).status_code, 403)
                self.assertIn(self.client.get(self.adresse()).status_code, (403, 404))
                self.assertIn(self.client.get(reverse("pedagogie:conseil_proces_verbal_pdf", args=[self.c6a.pk, T1])).status_code, (403, 404))
                self.assertEqual(self.client.post(self.adresse(), {"action": "enregistrer"}).status_code, 403)
        self.assertFalse(ConseilDeClasse.objects.exists())

    def test_un_conseil_d_une_autre_ecole_reste_introuvable(self):
        self.client.force_login(self.fondateur)
        self.assertEqual(self.client.get(self.adresse(classe=self.classe_b)).status_code, 404)
        self.assertEqual(self.client.post(self.adresse(classe=self.classe_b), {"action": "enregistrer"}).status_code, 404)
        self.client.force_login(self.fondateur_b)
        self.assertEqual(self.client.get(self.adresse()).status_code, 404)  # la classe de l'école A
        self.assertFalse(ConseilDeClasse.objects.exists())

    def test_un_directeur_de_cycle_ne_voit_que_les_classes_de_son_cycle(self):
        self.client.force_login(self.dir_1er)
        self.assertEqual(self.client.get(self.adresse()).status_code, 200)  # 6A : 1er cycle
        self.assertEqual(self.client.get(self.adresse(classe=self.c9a)).status_code, 404)  # 9A : 2ème cycle
        liste = self.client.get(reverse("pedagogie:conseils"))
        noms = [ligne["classe"].nom for ligne in liste.context["lignes"]]
        self.assertIn("6A", noms)
        self.assertNotIn("9A", noms)

    def test_le_trimestre_inconnu_est_introuvable(self):
        self.client.force_login(self.fondateur)
        self.assertEqual(self.client.get(self.adresse("trimestre_9")).status_code, 404)

    def test_le_menu_propose_les_conseils_a_la_direction_seulement(self):
        self.client.force_login(self.fondateur)
        self.assertContains(self.client.get(reverse("comptes:redirection_tableau_de_bord"), follow=True), "Conseils de classe")
        for compte in (self.t1, self.parent, self.comptable):
            self.client.force_login(compte)
            self.assertNotContains(self.client.get(reverse("comptes:redirection_tableau_de_bord"), follow=True), "Conseils de classe")


class TableauDuConseilTests(ConseilBase):
    def setUp(self):
        self.client.force_login(self.fondateur)

    def test_les_moyennes_et_les_rangs_sont_ceux_du_bulletin(self):
        lignes = self.lignes(self.client.get(self.adresse()))
        self.assertEqual(lignes[self.e1.pk]["moyenne"], Decimal("18.00"))
        self.assertEqual(lignes[self.e2.pk]["moyenne"], Decimal("12.00"))
        self.assertEqual(lignes[self.e3.pk]["moyenne"], Decimal("8.00"))
        self.assertEqual([lignes[e.pk]["rang"] for e in (self.e1, self.e2, self.e3)], [1, 2, 3])
        bulletin = self.client.get(reverse("pedagogie:bulletin_eleve", args=[self.e2.matricule]))
        self.assertEqual(bulletin.context["bulletins_trimestre"][0]["rang"], 2)
        self.assertEqual(bulletin.context["bulletins_trimestre"][0]["moyenne"], Decimal("12.00"))

    def test_le_tableau_suit_l_ordre_du_classement(self):
        reponse = self.client.get(self.adresse())
        self.assertEqual([ligne["eleve"].pk for ligne in reponse.context["lignes"]][:3], [self.e1.pk, self.e2.pk, self.e3.pk])

    def test_les_reperes_de_la_classe(self):
        reperes = self.client.get(self.adresse()).context["reperes"]
        self.assertEqual(reperes["effectif"], 3)
        self.assertEqual(reperes["plus_forte"], Decimal("18.00"))
        self.assertEqual(reperes["plus_faible"], Decimal("8.00"))
        self.assertEqual(reperes["moyenne_de_la_classe"], Decimal("12.67"))
        self.assertFalse(reperes["au_troisieme_trimestre"])

    def test_les_distinctions_suggerees_suivent_les_seuils(self):
        lignes = self.lignes(self.client.get(self.adresse()))
        self.assertEqual(lignes[self.e1.pk]["distinction_suggeree"], "felicitations")
        self.assertEqual(lignes[self.e2.pk]["distinction_suggeree"], "tableau_d_honneur")  # 12 : le seuil est atteint
        self.assertEqual(lignes[self.e3.pk]["distinction_suggeree"], "")

    def test_les_seuils_et_les_cas_limites_de_la_suggestion(self):
        conseil = ConseilDeClasse(classe=self.c6a, trimestre=T1)
        self.assertEqual(distinction_suggeree(Decimal("15.99"), conseil), "encouragements")
        self.assertEqual(distinction_suggeree(Decimal("16"), conseil), "felicitations")
        self.assertEqual(distinction_suggeree(Decimal("11.99"), conseil), "")
        self.assertEqual(distinction_suggeree(None, conseil), "")
        conseil.trimestre = T3
        self.assertEqual(passage_suggere(Decimal("10"), conseil), "admis")
        self.assertEqual(passage_suggere(Decimal("9.99"), conseil), "redouble")
        self.assertEqual(passage_suggere(None, conseil), "")
        conseil.trimestre = T1
        self.assertEqual(passage_suggere(Decimal("15"), conseil), "")  # pas de décision de passage avant le 3ème trimestre

    def test_les_absences_non_justifiees_et_les_avertissements_sont_comptes(self):
        from pedagogie.models import Absence, MesureDiscipline

        import datetime

        passe = datetime.date.today() - datetime.timedelta(days=3)
        Absence.objects.create(eleve=self.e3, classe=self.c6a, date_absence=passe, justifiee=False)
        Absence.objects.create(eleve=self.e3, classe=self.c6a, date_absence=passe - datetime.timedelta(days=1), justifiee=True)
        MesureDiscipline.objects.create(eleve=self.e3, classe=self.c6a, date_mesure=passe, type_mesure="blame", motif="Bagarre")
        MesureDiscipline.objects.create(eleve=self.e3, classe=self.c6a, date_mesure=passe, type_mesure="retard")
        ligne = self.lignes(self.client.get(self.adresse()))[self.e3.pk]
        self.assertEqual((ligne["absences"], ligne["absences_non_justifiees"], ligne["mesures"]), (2, 1, 1))

    def test_un_eleve_qui_n_a_pas_de_note_n_a_ni_moyenne_ni_rang_et_passe_apres_les_classes(self):
        sans_note = creer_compte(Role.ELEVE, "sans-note@conseil.test", self.ecole)
        Inscription.objects.create(eleve=sans_note, classe=self.c6a)
        reponse = self.client.get(self.adresse())
        derniere = reponse.context["lignes"][-1]
        self.assertEqual(derniere["eleve"].pk, sans_note.pk)
        self.assertIsNone(derniere["moyenne"])
        self.assertIsNone(derniere["rang"])
        self.assertEqual(derniere["distinction_suggeree"], "")

    def test_l_avertissement_sur_les_notes_non_cloturees_disparait_une_fois_le_trimestre_cloture(self):
        self.assertContains(self.client.get(self.adresse()), "ne sont pas encore clôturées")
        from pedagogie.clotures import cloturer

        cloturer(self.annee, T1, self.fondateur)
        self.assertNotContains(self.client.get(self.adresse()), "ne sont pas encore clôturées")

    def test_aucune_ecriture_en_base_quand_on_ouvre_la_page(self):
        self.client.get(self.adresse())
        self.client.get(reverse("pedagogie:conseils"))
        self.assertFalse(ConseilDeClasse.objects.exists())


class EnregistrementTests(ConseilBase):
    def setUp(self):
        self.client.force_login(self.fondateur)

    def donnees(self, **en_plus):
        base = {
            "action": "enregistrer", "date_conseil": "2026-12-20", "seuil_tableau_d_honneur": "12", "seuil_encouragements": "14",
            "seuil_felicitations": "16", "observations": "Bon trimestre dans l'ensemble.",
            f"distinction_{self.e1.pk}": "felicitations", f"sanction_{self.e1.pk}": "", f"observation_{self.e1.pk}": "Très sérieuse.",
            f"distinction_{self.e2.pk}": "", f"sanction_{self.e2.pk}": "avertissement_travail", f"observation_{self.e2.pk}": "",
            f"distinction_{self.e3.pk}": "", f"sanction_{self.e3.pk}": "", f"observation_{self.e3.pk}": "",
        }
        base.update(en_plus)
        return base

    def test_enregistrer_cree_le_conseil_et_garde_seulement_les_lignes_remplies(self):
        reponse = self.envoyer(self.donnees())
        self.assertContains(reponse, "Le conseil est enregistré.")
        conseil = ConseilDeClasse.objects.get(classe=self.c6a, trimestre=T1)
        self.assertEqual(str(conseil.date_conseil), "2026-12-20")
        self.assertEqual(conseil.observations, "Bon trimestre dans l'ensemble.")
        decisions = {d.eleve_id: d for d in conseil.decisions.all()}
        self.assertEqual(set(decisions), {self.e1.pk, self.e2.pk})  # e3 n'a rien : pas de ligne
        self.assertEqual(decisions[self.e1.pk].distinction, "felicitations")
        self.assertEqual(decisions[self.e1.pk].observation, "Très sérieuse.")
        self.assertEqual(decisions[self.e2.pk].sanction, "avertissement_travail")
        self.assertTrue(JournalAudit.objects.filter(action="conseil_enregistre", acteur=self.fondateur).exists())

    def test_enregistrer_deux_fois_met_a_jour_le_meme_conseil(self):
        self.envoyer(self.donnees())
        self.envoyer(self.donnees(**{f"distinction_{self.e1.pk}": "encouragements", f"sanction_{self.e2.pk}": ""}))
        self.assertEqual(ConseilDeClasse.objects.filter(classe=self.c6a, trimestre=T1).count(), 1)
        conseil = ConseilDeClasse.objects.get(classe=self.c6a, trimestre=T1)
        self.assertEqual(conseil.decisions.get(eleve=self.e1).distinction, "encouragements")
        self.assertFalse(conseil.decisions.filter(eleve=self.e2).exists())  # sa ligne est devenue vide : retirée

    def test_chaque_trimestre_a_son_conseil(self):
        self.envoyer(self.donnees(), trimestre=T1)
        self.envoyer(self.donnees(), trimestre=T2)
        self.assertEqual(ConseilDeClasse.objects.filter(classe=self.c6a).count(), 2)

    def test_les_seuils_du_dernier_conseil_sont_proposes_au_suivant(self):
        self.envoyer(self.donnees(seuil_tableau_d_honneur="11", seuil_encouragements="13", seuil_felicitations="15"))
        reponse = self.client.get(self.adresse(T2, classe=self.c6b))
        conseil = reponse.context["conseil"]
        self.assertEqual((conseil.seuil_tableau_d_honneur, conseil.seuil_encouragements, conseil.seuil_felicitations), (Decimal("11"), Decimal("13"), Decimal("15")))

    def test_la_virgule_decimale_est_acceptee(self):
        self.envoyer(self.donnees(seuil_tableau_d_honneur="11,5"))
        self.assertEqual(ConseilDeClasse.objects.get(classe=self.c6a).seuil_tableau_d_honneur, Decimal("11.50"))

    def test_des_seuils_dans_le_desordre_sont_refuses_et_la_saisie_est_conservee(self):
        reponse = self.envoyer(self.donnees(seuil_tableau_d_honneur="17"))
        self.assertContains(reponse, "du plus bas")
        self.assertFalse(ConseilDeClasse.objects.exists())
        self.assertEqual(self.lignes(reponse)[self.e1.pk]["distinction"], "felicitations")  # ce qui était tapé est resté dans le tableau

    def test_un_seuil_hors_de_zero_a_vingt_ou_un_texte_sont_refuses(self):
        for valeur in ("25", "-1", "abc"):
            with self.subTest(valeur=valeur):
                self.envoyer(self.donnees(seuil_felicitations=valeur))
                self.assertFalse(ConseilDeClasse.objects.exists())

    def test_une_date_invalide_est_refusee(self):
        self.envoyer(self.donnees(date_conseil="31/02/2026"))
        self.assertFalse(ConseilDeClasse.objects.exists())

    def test_une_distinction_ou_une_sanction_inconnue_est_refusee_sans_rien_enregistrer(self):
        self.envoyer(self.donnees(**{f"distinction_{self.e1.pk}": "grand_prix"}))
        self.assertFalse(DecisionConseil.objects.exists())
        self.envoyer(self.donnees(**{f"sanction_{self.e1.pk}": "pendaison"}))
        self.assertFalse(DecisionConseil.objects.exists())

    def test_une_observation_trop_longue_est_refusee(self):
        self.envoyer(self.donnees(**{f"observation_{self.e1.pk}": "x" * 256}))
        self.assertFalse(DecisionConseil.objects.exists())
        self.envoyer(self.donnees(observations="x" * 1001))
        self.assertFalse(DecisionConseil.objects.exists())

    def test_un_eleve_d_une_autre_classe_ou_d_une_autre_ecole_n_est_jamais_atteint(self):
        e_autre_ecole = creer_compte(Role.ELEVE, "autre@conseil-b.test", self.ecole_b)
        self.envoyer(self.donnees(**{f"distinction_{self.e4.pk}": "felicitations", f"distinction_{e_autre_ecole.pk}": "felicitations"}))
        self.assertEqual(set(DecisionConseil.objects.values_list("eleve_id", flat=True)), {self.e1.pk, self.e2.pk})

    def test_la_decision_de_passage_n_existe_qu_au_troisieme_trimestre(self):
        self.envoyer(self.donnees(**{f"passage_{self.e1.pk}": "admis"}))
        self.assertFalse(ConseilDeClasse.objects.exists())
        self.envoyer(self.donnees(**{f"passage_{self.e1.pk}": "admis"}), trimestre=T3)
        self.assertEqual(DecisionConseil.objects.get(eleve=self.e1).decision_passage, "admis")

    def test_une_decision_de_passage_inconnue_est_refusee(self):
        self.envoyer(self.donnees(**{f"passage_{self.e1.pk}": "exclu"}), trimestre=T3)
        self.assertFalse(DecisionConseil.objects.exists())

    def test_appliquer_les_suggestions_remplace_les_distinctions_et_garde_les_sanctions(self):
        self.envoyer(self.donnees())
        self.envoyer({"action": "suggestions", "seuil_tableau_d_honneur": "12", "seuil_encouragements": "14", "seuil_felicitations": "16",
                      f"sanction_{self.e2.pk}": "avertissement_travail"})
        decisions = {d.eleve_id: d for d in DecisionConseil.objects.all()}
        self.assertEqual(decisions[self.e1.pk].distinction, "felicitations")
        self.assertEqual(decisions[self.e2.pk].distinction, "tableau_d_honneur")
        self.assertEqual(decisions[self.e2.pk].sanction, "avertissement_travail")
        self.assertNotIn(self.e3.pk, decisions)

    def test_les_suggestions_du_troisieme_trimestre_proposent_le_passage_selon_la_moyenne_de_l_annee(self):
        self.envoyer({"action": "suggestions", "seuil_passage": "10"}, trimestre=T3)
        decisions = {d.eleve_id: d.decision_passage for d in DecisionConseil.objects.all()}
        # e1 : (18 + 14) / 2 notes ; e2 : 12 et 6 -> 9 : sous le seuil ; e3 : 8 -> sous le seuil
        self.assertEqual(decisions[self.e1.pk], "admis")
        self.assertEqual(decisions[self.e2.pk], "redouble")
        self.assertEqual(decisions[self.e3.pk], "redouble")

    def test_une_action_inconnue_est_refusee(self):
        reponse = self.client.post(self.adresse(), {"action": "tout_effacer"})
        self.assertEqual(reponse.status_code, 404)


class ValidationTests(ConseilBase):
    def setUp(self):
        self.client.force_login(self.fondateur)
        self.envoyer({"action": "enregistrer", f"distinction_{self.e1.pk}": "felicitations"})

    def test_valider_verrouille_le_conseil(self):
        reponse = self.envoyer({"action": "valider", f"distinction_{self.e1.pk}": "encouragements"})
        self.assertContains(reponse, "Le conseil est validé")
        conseil = ConseilDeClasse.objects.get(classe=self.c6a)
        self.assertTrue(conseil.valide)
        self.assertEqual(conseil.valide_par, self.fondateur)
        self.assertEqual(conseil.decisions.get(eleve=self.e1).distinction, "encouragements")  # la saisie envoyée avec « valider » est gardée
        self.assertTrue(JournalAudit.objects.filter(action="conseil_valide").exists())
        refus = self.envoyer({"action": "enregistrer", f"distinction_{self.e1.pk}": "tableau_d_honneur"})
        self.assertContains(refus, "est validé")
        self.assertEqual(conseil.decisions.get(eleve=self.e1).distinction, "encouragements")
        refus = self.envoyer({"action": "suggestions"})
        self.assertEqual(conseil.decisions.get(eleve=self.e1).distinction, "encouragements")

    def test_la_page_d_un_conseil_valide_est_en_lecture_seule(self):
        self.envoyer({"action": "valider"})
        page = self.client.get(self.adresse()).content.decode()
        self.assertIn("ne peut plus être modifié", page)
        self.assertNotIn('value="valider"', page)
        self.assertIn("disabled", page)

    def test_seule_la_direction_generale_rouvre_un_conseil(self):
        self.envoyer({"action": "valider"})
        self.client.force_login(self.dir_1er)
        self.assertEqual(self.client.post(self.adresse(), {"action": "rouvrir"}).status_code, 403)
        self.assertTrue(ConseilDeClasse.objects.get(classe=self.c6a).valide)
        self.client.force_login(self.fondateur)
        self.assertContains(self.envoyer({"action": "rouvrir"}), "rouvert")
        self.assertFalse(ConseilDeClasse.objects.get(classe=self.c6a).valide)
        self.assertTrue(JournalAudit.objects.filter(action="conseil_rouvert").exists())
        self.assertContains(self.envoyer({"action": "enregistrer", f"distinction_{self.e1.pk}": "encouragements"}), "Le conseil est enregistré.")

    def test_rouvrir_un_conseil_qui_n_est_pas_valide_ou_qui_n_existe_pas_ne_fait_rien(self):
        self.assertContains(self.envoyer({"action": "rouvrir"}), "pas validé")
        self.assertEqual(self.client.post(self.adresse(T2), {"action": "rouvrir"}).status_code, 404)

    def test_on_ne_valide_pas_deux_fois(self):
        self.envoyer({"action": "valider"})
        reponse = self.envoyer({"action": "valider"})
        self.assertContains(reponse, "est validé")


class DocumentsTests(ConseilBase):
    def setUp(self):
        self.client.force_login(self.fondateur)

    def adresse_pdf(self, nom, trimestre=T1, classe=None):
        return reverse(nom, args=[(classe or self.c6a).pk, trimestre])

    def test_rien_a_imprimer_tant_que_le_conseil_n_est_pas_enregistre(self):
        for nom in ("pedagogie:conseil_proces_verbal_pdf", "pedagogie:conseil_tableau_d_honneur_pdf"):
            with self.subTest(document=nom):
                reponse = self.client.get(self.adresse_pdf(nom), follow=True)
                self.assertContains(reponse, "Enregistrez d")
                self.assertEqual(reponse.redirect_chain[-1][0], self.adresse())

    def test_les_deux_pdf_se_fabriquent(self):
        self.envoyer({"action": "suggestions"})
        for nom in ("pedagogie:conseil_proces_verbal_pdf", "pedagogie:conseil_tableau_d_honneur_pdf"):
            with self.subTest(document=nom):
                reponse = self.client.get(self.adresse_pdf(nom))
                self.assertEqual(reponse.status_code, 200)
                self.assertEqual(reponse["Content-Type"], "application/pdf")
                self.assertTrue(reponse.content.startswith(b"%PDF"))
                self.assertIn(".pdf", reponse["Content-Disposition"])
        self.assertTrue(JournalAudit.objects.filter(action="export_proces_verbal_conseil").exists())
        self.assertTrue(JournalAudit.objects.filter(action="export_tableau_d_honneur").exists())

    def test_le_contenu_du_procès_verbal_et_du_tableau_d_honneur(self):
        from comptes.outils_test_arabe import CaptureHtmlDuPdf

        self.envoyer({"action": "suggestions", "date_conseil": "2026-12-20", "observations": "Conseil serein."})
        with CaptureHtmlDuPdf() as capture:
            self.client.get(self.adresse_pdf("pedagogie:conseil_proces_verbal_pdf"))
            self.client.get(self.adresse_pdf("pedagogie:conseil_tableau_d_honneur_pdf"))
        html = capture.html
        self.assertIn(self.e1.nom_complet, html)
        self.assertIn("Félicitations", html)
        self.assertIn("Tableau d'honneur", html)
        self.assertIn("projet, non validé", html)
        self.assertIn("Conseil serein.", html)
        self.assertIn("20/12/2026", html)
        self.assertNotIn(self.e4.nom_complet, html)  # un élève d'une autre classe n'y est jamais

    def test_le_document_d_un_conseil_valide_n_est_plus_un_projet(self):
        from comptes.outils_test_arabe import CaptureHtmlDuPdf

        self.envoyer({"action": "valider"})
        with CaptureHtmlDuPdf() as capture:
            self.client.get(self.adresse_pdf("pedagogie:conseil_proces_verbal_pdf"))
        self.assertNotIn("projet, non validé", capture.html)

    def test_le_tableau_d_honneur_range_du_niveau_le_plus_haut_au_plus_bas(self):
        from comptes.outils_test_arabe import CaptureHtmlDuPdf

        self.envoyer({"action": "suggestions"})
        with CaptureHtmlDuPdf() as capture:
            self.client.get(self.adresse_pdf("pedagogie:conseil_tableau_d_honneur_pdf"))
        html = capture.html
        self.assertLess(html.index("Félicitations"), html.index("Tableau d&#x27;honneur</h2>"))

    def test_un_tableau_d_honneur_sans_distingue_le_dit(self):
        from comptes.outils_test_arabe import CaptureHtmlDuPdf

        self.envoyer({"action": "enregistrer", "observations": "Rien à signaler."})
        with CaptureHtmlDuPdf() as capture:
            self.client.get(self.adresse_pdf("pedagogie:conseil_tableau_d_honneur_pdf"))
        self.assertIn("Aucun élève n'a reçu de distinction", capture.html)

    def test_les_documents_d_une_autre_ecole_sont_introuvables(self):
        self.envoyer({"action": "suggestions"})
        self.client.force_login(self.fondateur_b)
        for nom in ("pedagogie:conseil_proces_verbal_pdf", "pedagogie:conseil_tableau_d_honneur_pdf"):
            self.assertEqual(self.client.get(self.adresse_pdf(nom)).status_code, 404)

    def test_les_roles_sans_droit_n_obtiennent_aucun_document(self):
        self.envoyer({"action": "suggestions"})
        for compte in (self.t1, self.parent, self.comptable):
            self.client.force_login(compte)
            for nom in ("pedagogie:conseil_proces_verbal_pdf", "pedagogie:conseil_tableau_d_honneur_pdf"):
                self.assertIn(self.client.get(self.adresse_pdf(nom)).status_code, (403, 404))


class PassageDeClasseTests(ConseilBase):
    def setUp(self):
        self.client.force_login(self.fondateur)

    def adresse_passage(self):
        return reverse("scolarite:passage_de_classe", args=[self.c6a.pk]) + f"?annee_destination={self.precedente.pk}"

    def test_sans_conseil_valide_tout_le_monde_est_admis_par_defaut(self):
        page = self.client.get(self.adresse_passage())
        self.assertFalse(page.context["decisions_du_conseil"])
        self.assertNotContains(page, "Les décisions du conseil de classe")
        self.assertNotContains(page, 'value="redouble" selected')

    def test_un_conseil_non_valide_ne_prerempli_pas_le_passage(self):
        self.envoyer({"action": "suggestions"}, trimestre=T3)
        self.assertFalse(self.client.get(self.adresse_passage()).context["decisions_du_conseil"])

    def test_un_conseil_valide_du_troisieme_trimestre_prerempli_le_passage(self):
        self.envoyer({"action": "suggestions"}, trimestre=T3)
        self.envoyer({"action": "valider"}, trimestre=T3)
        page = self.client.get(self.adresse_passage())
        self.assertTrue(page.context["decisions_du_conseil"])
        self.assertContains(page, "Les décisions du conseil de classe du 3ème trimestre")
        par_eleve = {i.eleve_id: i.decision_du_conseil for i in page.context["eleves_en_cours"]}
        self.assertEqual(par_eleve[self.e1.pk], "admis")
        self.assertEqual(par_eleve[self.e2.pk], "redouble")
        self.assertContains(page, 'value="redouble" selected')

    def test_un_conseil_valide_d_un_autre_trimestre_ne_prerempli_pas_le_passage(self):
        self.envoyer({"action": "suggestions"}, trimestre=T1)
        self.envoyer({"action": "valider"}, trimestre=T1)
        self.assertFalse(self.client.get(self.adresse_passage()).context["decisions_du_conseil"])

    def test_le_prerempli_reste_une_proposition_que_la_direction_peut_changer(self):
        import datetime

        from scolarite.models import AnneeScolaire, Classe, Cycle

        self.envoyer({"action": "suggestions"}, trimestre=T3)
        self.envoyer({"action": "valider"}, trimestre=T3)
        futur = AnneeScolaire.objects.create(etablissement=self.ecole, libelle="2027-2028", date_debut=datetime.date(2027, 10, 1), date_fin=datetime.date(2028, 7, 31))
        admis = Classe.objects.create(nom="7A", cycle=Cycle.DEUXIEME_CYCLE, niveau="annee_7", annee_scolaire=futur)
        redoublants = Classe.objects.create(nom="6A", cycle=Cycle.PREMIER_CYCLE, niveau="annee_6", annee_scolaire=futur)
        donnees = {"annee_destination": futur.pk, "classe_admis": admis.pk, "classe_redouble": redoublants.pk}
        choix = {self.e1.pk: "redouble", self.e2.pk: "admis", self.e3.pk: "admis"}  # le conseil proposait : e1 admis, e2 et e3 redoublent
        for inscription in Inscription.objects.filter(classe=self.c6a, statut=Inscription.Statut.EN_COURS):
            donnees[f"decision_{inscription.pk}"] = choix[inscription.eleve_id]
        self.client.post(reverse("scolarite:passage_de_classe", args=[self.c6a.pk]), donnees)
        statuts = {i.eleve_id: i.statut for i in Inscription.objects.filter(classe=self.c6a)}
        self.assertEqual(statuts[self.e1.pk], Inscription.Statut.REDOUBLE)
        self.assertEqual(statuts[self.e2.pk], Inscription.Statut.ADMIS)
        self.assertEqual(statuts[self.e3.pk], Inscription.Statut.ADMIS)


class ChampAbsentTests(ConseilBase):
    def test_un_champ_absent_de_l_envoi_ne_supprime_rien(self):
        self.client.force_login(self.fondateur)
        self.envoyer({
            "action": "enregistrer", "date_conseil": "2026-12-20", "observations": "À garder.", f"distinction_{self.e1.pk}": "felicitations",
            f"sanction_{self.e2.pk}": "blame_conduite", f"observation_{self.e2.pk}": "Bavardages.",
        })
        self.envoyer({"action": "enregistrer"})  # aucun champ envoyé
        conseil = ConseilDeClasse.objects.get(classe=self.c6a)
        self.assertEqual(str(conseil.date_conseil), "2026-12-20")
        self.assertEqual(conseil.observations, "À garder.")
        self.assertEqual(conseil.decisions.get(eleve=self.e1).distinction, "felicitations")
        self.assertEqual(conseil.decisions.get(eleve=self.e2).sanction, "blame_conduite")
        self.assertEqual(conseil.decisions.get(eleve=self.e2).observation, "Bavardages.")

    def test_un_champ_envoye_vide_efface_bien_la_valeur(self):
        self.client.force_login(self.fondateur)
        self.envoyer({"action": "enregistrer", "date_conseil": "2026-12-20", f"distinction_{self.e1.pk}": "felicitations"})
        self.envoyer({"action": "enregistrer", "date_conseil": "", f"distinction_{self.e1.pk}": ""})
        conseil = ConseilDeClasse.objects.get(classe=self.c6a)
        self.assertIsNone(conseil.date_conseil)
        self.assertFalse(conseil.decisions.exists())


class BoutonsTests(ConseilBase):
    """La page envoie le NOM du bouton cliqué (pas sa valeur : la page arabe traduit les valeurs de boutons)."""

    def setUp(self):
        self.client.force_login(self.fondateur)

    def test_le_nom_du_bouton_suffit_pour_choisir_l_action(self):
        self.envoyer({"suggestions": "", "date_conseil": "2026-12-20"})
        self.assertEqual(DecisionConseil.objects.get(eleve=self.e1).distinction, "felicitations")
        self.envoyer({"valider": ""})
        self.assertTrue(ConseilDeClasse.objects.get(classe=self.c6a).valide)

    def test_sans_nom_de_bouton_connu_on_enregistre_sans_jamais_valider(self):
        self.envoyer({f"distinction_{self.e1.pk}": "encouragements"})  # Entrée dans un champ de texte
        conseil = ConseilDeClasse.objects.get(classe=self.c6a)
        self.assertFalse(conseil.valide)
        self.assertEqual(conseil.decisions.get(eleve=self.e1).distinction, "encouragements")

    def test_les_boutons_de_la_page_n_ont_pas_de_valeur_traduisible(self):
        page = self.client.get(self.adresse()).content.decode()
        for nom in ("enregistrer", "suggestions"):
            self.assertIn(f'name="{nom}"', page)
        self.assertNotRegex(page, r'<button[^>]*name="(?:enregistrer|suggestions|valider)"[^>]*value=')

    def test_la_page_arabe_envoie_les_memes_noms_de_boutons(self):
        from comptes.outils_test_arabe import client_en

        arabe = client_en(self.fondateur, "ar")
        page = arabe.get(self.adresse()).content.decode()
        self.assertIn('name="enregistrer"', page)
        self.assertIn('name="suggestions"', page)
        arabe.post(self.adresse(), {"suggestions": ""})  # le même envoi que fait la page arabe
        self.assertEqual(DecisionConseil.objects.get(eleve=self.e1).distinction, "felicitations")
        arabe.post(self.adresse(), {"valider": ""})
        self.assertTrue(ConseilDeClasse.objects.get(classe=self.c6a).valide)


class BulletinTests(ConseilBase):
    """Ce que le conseil a décidé arrive sur le bulletin de l'élève, seulement quand le conseil est validé, et seulement pour lui."""

    def setUp(self):
        self.client.force_login(self.fondateur)
        self.envoyer({
            "enregistrer": "", f"distinction_{self.e1.pk}": "felicitations", f"sanction_{self.e2.pk}": "blame_travail",
            f"observation_{self.e2.pk}": "Doit travailler davantage.",
        })

    def bulletin(self, compte, eleve):
        self.client.force_login(compte)
        return self.client.get(reverse("pedagogie:bulletin_eleve", args=[eleve.matricule]))

    def test_un_conseil_non_valide_n_apparait_pas_sur_le_bulletin(self):
        reponse = self.bulletin(self.fondateur, self.e1)
        self.assertIsNone(reponse.context["bulletins_trimestre"][0]["conseil"])
        self.assertNotContains(reponse, "Distinction du conseil de classe")

    def test_un_conseil_valide_apparait_sur_le_bulletin_de_l_eleve_concerne(self):
        self.envoyer({"valider": ""})
        reponse = self.bulletin(self.fondateur, self.e1)
        conseil = reponse.context["bulletins_trimestre"][0]["conseil"]
        self.assertEqual(conseil["distinction"], "Félicitations")
        self.assertContains(reponse, "Distinction du conseil de classe")
        reponse = self.bulletin(self.fondateur, self.e2)
        self.assertEqual(reponse.context["bulletins_trimestre"][0]["conseil"]["sanction"], "Blâme (travail)")
        self.assertContains(reponse, "Doit travailler davantage.")

    def test_un_eleve_sans_decision_n_a_rien_de_plus_sur_son_bulletin(self):
        self.envoyer({"valider": ""})
        reponse = self.bulletin(self.fondateur, self.e3)
        self.assertIsNone(reponse.context["bulletins_trimestre"][0]["conseil"])
        self.assertNotContains(reponse, "du conseil de classe")

    def test_chacun_ne_voit_que_les_decisions_de_son_propre_bulletin(self):
        self.envoyer({"valider": ""})
        reponse = self.bulletin(self.e1, self.e1)  # l'élève lui-même
        self.assertContains(reponse, "Félicitations")
        self.assertNotContains(reponse, "Doit travailler davantage.")
        reponse = self.bulletin(self.parent, self.e1)  # son parent
        self.assertContains(reponse, "Distinction du conseil de classe")
        self.assertEqual(self.bulletin(self.e1, self.e2).status_code, 403)  # un autre élève : refusé
        self.assertEqual(self.bulletin(self.parent, self.e2).status_code, 403)  # le parent d'un autre élève : refusé

    def test_la_decision_de_passage_est_sur_le_bulletin_du_troisieme_trimestre(self):
        self.envoyer({"suggestions": ""}, trimestre=T3)
        self.envoyer({"valider": ""}, trimestre=T3)
        blocs = self.bulletin(self.fondateur, self.e1).context["bulletins_trimestre"]
        trimestre_3 = [b for b in blocs if b["trimestre"] == "3ème trimestre"][0]
        self.assertEqual(trimestre_3["conseil"]["passage"], "Admis")

    def test_le_conseil_d_une_autre_classe_ne_passe_jamais_sur_ce_bulletin(self):
        e_autre = creer_compte(Role.ELEVE, "autre-classe@conseil.test", self.ecole)
        Inscription.objects.create(eleve=e_autre, classe=self.c6b)
        saisir_note(eleve=e_autre, affectation=Affectation.objects.get(enseignant=self.t2, classe=self.c6b), trimestre=T1, enseignant=self.t2, note_classe=15, note_composition=30)
        self.envoyer({"enregistrer": "", f"distinction_{e_autre.pk}": "felicitations"}, classe=self.c6b)
        self.envoyer({"valider": ""}, classe=self.c6b)
        # Le conseil de la 6B est validé, celui de la 6A (classe de e1) ne l'est pas : e1 n'a rien sur son bulletin.
        self.assertIsNone(self.bulletin(self.fondateur, self.e1).context["bulletins_trimestre"][0]["conseil"])
        self.assertEqual(self.bulletin(self.fondateur, e_autre).context["bulletins_trimestre"][0]["conseil"]["distinction"], "Félicitations")

    def test_le_bulletin_pdf_porte_la_decision_du_conseil_valide(self):
        from comptes.outils_test_arabe import CaptureHtmlDuPdf

        self.envoyer({"valider": ""})
        with CaptureHtmlDuPdf() as capture:
            reponse = self.client.get(reverse("pedagogie:exporter_bulletin_pdf", args=[self.e1.matricule]))
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("Distinction du conseil de classe", capture.html)
        self.assertIn("Félicitations", capture.html)
