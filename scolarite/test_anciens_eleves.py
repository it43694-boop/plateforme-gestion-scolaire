"""Anciens élèves (transférés, partis) : la liste et la réintégration dans une classe."""
import datetime

from django.core.files.base import ContentFile
from django.urls import reverse

from comptes.arabisation import invalider
from comptes.models import JournalAudit, Utilisateur
from comptes.outils_test_arabe import client_en
from comptes.roles import Role
from comptes.traduction import restes_latins
from scolarite.anciens import derniere_sortie_par_eleve, est_ancien_eleve, reintegrer
from scolarite.models import Abandon, AnneeScolaire, Classe, Cycle, Inscription, TransfertEleve
from scolarite.test_dossier_complet import StockageTemporaire
from statistiques.test_education import EducationBase, creer_compte

D = datetime.date


class AnciensBase(StockageTemporaire):
    def setUp(self):
        self.secretaire = self.secretaire
        self.url = reverse("scolarite:anciens_eleves")

    def transferer(self, eleve, destination="Lycée Askia", date=D(2026, 11, 3), justificatif=False):
        inscription = Inscription.objects.get(eleve=eleve, statut=Inscription.Statut.EN_COURS)
        Inscription.objects.filter(pk=inscription.pk).update(statut=Inscription.Statut.TRANSFERE)
        transfert = TransfertEleve(
            inscription=inscription, destination_libelle=destination, date_transfert=date, motif="Déménagement", enregistre_par=self.secretaire,
        )
        if justificatif:
            transfert.justificatif.save("justificatif.pdf", ContentFile(b"%PDF-1.4 test"), save=False)
        transfert.save()
        return inscription, transfert

    def abandonner(self, eleve, date=D(2026, 12, 1)):
        inscription = Inscription.objects.get(eleve=eleve, statut=Inscription.Statut.EN_COURS)
        Inscription.objects.filter(pk=inscription.pk).update(statut=Inscription.Statut.ABANDON)
        Abandon.objects.create(inscription=inscription, date_abandon=date, motif="Raison privée", enregistre_par=self.secretaire)
        return inscription


class ListeDesAnciensTests(AnciensBase):
    def test_seuls_ceux_qui_ont_quitte_l_ecole_apparaissent(self):
        self.transferer(self.e5)
        self.abandonner(self.e4)
        lignes = derniere_sortie_par_eleve(self.fondateur)
        self.assertEqual({l["eleve"].pk for l in lignes}, {self.e4.pk, self.e5.pk})
        by = {l["eleve"].pk: l for l in lignes}
        self.assertEqual((by[self.e5.pk]["type"], by[self.e5.pk]["date"], by[self.e5.pk]["destination"]), ("Transféré / parti", D(2026, 11, 3), "Lycée Askia"))
        self.assertEqual((by[self.e4.pk]["type"], by[self.e4.pk]["date"]), ("Abandon", D(2026, 12, 1)))

    def test_un_ancien_redevenu_eleve_n_est_plus_un_ancien(self):
        inscription, _ = self.transferer(self.e5)
        self.assertTrue(est_ancien_eleve(self.e5))
        reintegrer(self.e5, inscription.classe)
        self.assertFalse(est_ancien_eleve(self.e5))
        self.assertEqual(derniere_sortie_par_eleve(self.fondateur), [])

    def test_un_eleve_en_cours_ou_admis_n_est_pas_un_ancien(self):
        self.assertFalse(est_ancien_eleve(self.e1))  # en cours (et redoublante l'an dernier)
        self.assertFalse(est_ancien_eleve(self.e2))
        self.assertEqual(derniere_sortie_par_eleve(self.fondateur), [])

    def test_une_ligne_par_eleve_avec_sa_derniere_sortie(self):
        self.transferer(self.e5)
        # il revient l'année suivante puis repart : seule la dernière sortie compte
        vieille = Inscription.objects.get(eleve=self.e5)
        Inscription.objects.filter(pk=vieille.pk).update(classe=self.classe_5a)
        nouvelle = Inscription.objects.create(eleve=self.e5, classe=self.c9a)
        Inscription.objects.filter(pk=nouvelle.pk).update(statut=Inscription.Statut.ABANDON)
        Abandon.objects.create(inscription=nouvelle, date_abandon=D(2027, 2, 1), motif="x", enregistre_par=self.secretaire)
        lignes = [l for l in derniere_sortie_par_eleve(self.fondateur) if l["eleve"] == self.e5]
        self.assertEqual((len(lignes), lignes[0]["type"]), (1, "Abandon"))

    def test_les_eleves_anonymises_n_apparaissent_pas(self):
        self.abandonner(self.e4)
        Utilisateur.objects.filter(pk=self.e4.pk).update(matricule="ANON-4")
        self.assertEqual(derniere_sortie_par_eleve(self.fondateur), [])

    def test_les_filtres(self):
        self.transferer(self.e5)
        self.abandonner(self.e4)
        self.client.force_login(self.fondateur)
        self.assertEqual(self.client.get(self.url).context["total"], 2)
        self.assertEqual(self.client.get(self.url, {"q": self.e4.matricule}).context["total"], 1)
        self.assertEqual(self.client.get(self.url, {"annee": self.annee.pk}).context["total"], 2)
        self.assertEqual(self.client.get(self.url, {"annee": self.precedente.pk}).context["total"], 0)
        self.assertEqual(self.client.get(self.url, {"annee": "abc", "q": "  "}).context["total"], 2)

    def test_un_directeur_de_cycle_ne_voit_que_son_cycle_et_une_autre_ecole_rien(self):
        self.transferer(self.e5)  # 9A : 2ème cycle
        self.abandonner(self.e4)  # 6B : 1er cycle
        self.client.force_login(self.dir_1er)
        self.assertEqual([l["eleve"].pk for l in self.client.get(self.url).context["lignes"]], [self.e4.pk])
        self.client.force_login(self.fondateur_b)
        self.assertEqual(self.client.get(self.url).context["total"], 0)

    def test_les_droits(self):
        for compte, code in ((self.secretaire, 200), (self.fondateur, 200), (self.dir_1er, 200), (self.t1, 403), (self.parent, 403), (self.e1, 403), (self.comptable, 403)):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertEqual(self.client.get(self.url).status_code, code)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_le_menu_propose_la_page_a_l_administration(self):
        for compte, attendu in ((self.secretaire, True), (self.fondateur, True), (self.t1, False), (self.parent, False)):
            self.client.force_login(compte)
            page = self.client.get(reverse("comptes:redirection_tableau_de_bord"), follow=True).content.decode()
            with self.subTest(compte=compte.email):
                self.assertEqual(self.url in page, attendu)


class ReintegrationTests(AnciensBase):
    def url_de(self, eleve):
        return reverse("scolarite:reintegrer_eleve", args=[eleve.matricule])

    def test_il_revient_dans_sa_classe_la_meme_annee_son_inscription_est_rouverte(self):
        inscription, _ = self.transferer(self.e5, justificatif=True)
        self.client.force_login(self.secretaire)
        reponse = self.client.post(self.url_de(self.e5), {"classe": self.c9a.pk})
        self.assertRedirects(reponse, reverse("scolarite:dossier_eleve", args=[self.e5.matricule]))
        inscription.refresh_from_db()
        self.assertEqual((inscription.statut, inscription.classe), (Inscription.Statut.EN_COURS, self.c9a))
        self.assertFalse(TransfertEleve.objects.filter(inscription=inscription).exists())
        self.assertEqual(Inscription.objects.filter(eleve=self.e5).count(), 1)  # la même inscription : ses notes, absences et paiements la suivent

    def test_il_revient_dans_une_autre_classe_de_la_meme_annee(self):
        inscription, _ = self.transferer(self.e4)  # 6B
        self.client.force_login(self.secretaire)
        self.client.post(self.url_de(self.e4), {"classe": self.c6a.pk})
        inscription.refresh_from_db()
        self.assertEqual((inscription.statut, inscription.classe), (Inscription.Statut.EN_COURS, self.c6a))

    def test_un_abandon_est_efface_aussi(self):
        inscription = self.abandonner(self.e4)
        reintegrer(self.e4, inscription.classe)
        self.assertFalse(Abandon.objects.filter(inscription=inscription).exists())

    def test_un_ancien_d_une_annee_passee_recoit_une_nouvelle_inscription(self):
        Inscription.objects.filter(eleve=self.e2, classe=self.classe_5a).update(statut=Inscription.Statut.ABANDON)  # e2 est parti en 2025-2026
        Inscription.objects.filter(eleve=self.e2, classe=self.c6a).delete()  # et n'a pas d'inscription cette année
        Abandon.objects.create(
            inscription=Inscription.objects.get(eleve=self.e2, classe=self.classe_5a), date_abandon=D(2026, 3, 1), motif="x", enregistre_par=self.secretaire,
        )
        self.assertTrue(est_ancien_eleve(self.e2))
        nouvelle = reintegrer(self.e2, self.c6a)
        self.assertEqual((nouvelle.classe, nouvelle.statut), (self.c6a, Inscription.Statut.EN_COURS))
        self.assertEqual(Inscription.objects.filter(eleve=self.e2).count(), 2)  # l'ancienne année reste dans son historique
        self.assertEqual(Inscription.objects.get(eleve=self.e2, classe=self.classe_5a).statut, Inscription.Statut.ABANDON)

    def test_les_refus(self):
        from django.core.exceptions import ValidationError

        with self.assertRaisesMessage(ValidationError, "déjà inscrit"):
            reintegrer(self.e1, self.c6a)
        with self.assertRaisesMessage(ValidationError, "Seul un élève"):
            reintegrer(self.t1, self.c6a)
        inscription, _ = self.transferer(self.e5)
        with self.assertRaisesMessage(ValidationError, "même établissement"):
            reintegrer(self.e5, self.classe_b)
        AnneeScolaire.objects.filter(pk=self.annee.pk).update(est_archivee=True)
        with self.assertRaisesMessage(ValidationError, "archivée"):
            reintegrer(self.e5, Classe.objects.get(pk=self.c9a.pk))

    def test_la_page_ne_propose_que_les_classes_ouvertes_de_l_ecole(self):
        self.transferer(self.e5)
        self.client.force_login(self.secretaire)
        classes = set(self.client.get(self.url_de(self.e5)).context["formulaire"].fields["classe"].queryset)
        self.assertIn(self.c9a, classes)
        self.assertNotIn(self.classe_b, classes)  # une autre école
        AnneeScolaire.objects.filter(pk=self.precedente.pk).update(est_archivee=True)
        classes = set(self.client.get(self.url_de(self.e5)).context["formulaire"].fields["classe"].queryset)
        self.assertNotIn(self.classe_5a, classes)  # une année archivée

    def test_une_classe_d_une_autre_ecole_est_refusee_par_le_formulaire(self):
        self.transferer(self.e5)
        self.client.force_login(self.secretaire)
        reponse = self.client.post(self.url_de(self.e5), {"classe": self.classe_b.pk})
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(est_ancien_eleve(self.e5))

    def test_un_eleve_qui_n_a_pas_quitte_l_ecole_n_est_pas_reintegrable(self):
        self.client.force_login(self.secretaire)
        reponse = self.client.get(self.url_de(self.e1), follow=True)
        self.assertContains(reponse, "rien à réintégrer")

    def test_les_droits_et_le_cloisonnement(self):
        self.transferer(self.e5)
        for compte in (self.t1, self.parent, self.e1, self.comptable):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertEqual(self.client.post(self.url_de(self.e5), {"classe": self.c9a.pk}).status_code, 403)
        self.client.force_login(self.fondateur_b)
        self.assertEqual(self.client.post(self.url_de(self.e5), {"classe": self.c9a.pk}).status_code, 404)
        self.client.force_login(self.dir_1er)  # 9A n'est pas de son cycle
        self.assertEqual(self.client.get(self.url_de(self.e5)).status_code, 403)
        self.assertTrue(est_ancien_eleve(self.e5))

    def test_la_reintegration_est_journalisee(self):
        self.transferer(self.e5)
        self.client.force_login(self.secretaire)
        self.client.post(self.url_de(self.e5), {"classe": self.c9a.pk})
        journal = JournalAudit.objects.get(action="reintegration_eleve")
        self.assertEqual((journal.cible, journal.details["sortie"]), (self.e5.matricule, "transfere"))

    def test_le_bouton_du_dossier(self):
        def bouton(eleve):
            page = self.client.get(reverse("scolarite:dossier_eleve", args=[eleve.matricule])).content.decode()
            return self.url_de(eleve) in page

        self.client.force_login(self.secretaire)
        self.transferer(self.e5)
        self.assertTrue(bouton(self.e5))
        self.assertFalse(bouton(self.e1))  # e1 est inscrite en cours
        self.client.force_login(self.fondateur)
        self.assertTrue(bouton(self.e5))

    def test_apres_reintegration_les_documents_et_cartes_refonctionnent(self):
        inscription, _ = self.transferer(self.e5)
        self.client.force_login(self.secretaire)
        self.assertEqual(self.client.get(reverse("scolarite:document_officiel", args=[self.e5.matricule, "attestation-frequentation"]), follow=True).status_code, 200)
        self.client.post(self.url_de(self.e5), {"classe": self.c9a.pk})
        reponse = self.client.get(reverse("scolarite:document_officiel", args=[self.e5.matricule, "attestation-frequentation"]))
        self.assertEqual(reponse["Content-Type"], "application/pdf")


class AnciensEnArabeTests(AnciensBase):
    def test_les_pages_sont_en_arabe_pur(self):
        self.transferer(self.e5, destination="Lycée Askia")
        Utilisateur.objects.filter(pk=self.e5.pk).update(prenom="Aminata", nom="Traoré", prenom_ar="أميناتا", nom_ar="تراوري")
        invalider(self.ecole.pk)
        client = client_en(self.secretaire, "ar")
        for adresse in (self.url, reverse("scolarite:reintegrer_eleve", args=[self.e5.matricule])):
            reponse = client.get(adresse)
            self.assertEqual(reponse.status_code, 200)
            with self.subTest(page=adresse):
                self.assertEqual([t for t in restes_latins(reponse.content.decode()) if t != "Français"], [])
