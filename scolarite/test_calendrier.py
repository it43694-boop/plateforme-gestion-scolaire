"""Calendrier scolaire : lecture par tous les comptes de l'école, dates réservées au personnel, gestion par le secrétariat et la direction."""
import datetime

from django.core.exceptions import ValidationError
from django.urls import reverse

from comptes.arabisation import invalider
from comptes.models import JournalAudit
from comptes.outils_test_arabe import client_en
from comptes.traduction import restes_latins
from scolarite.models import EvenementCalendrier, TypeEvenement, evenements_visibles_pour, prochains_evenements
from statistiques.test_education import EducationBase

D = datetime.date
AUJOURDHUI = D.today()


def jours(n):
    return AUJOURDHUI + datetime.timedelta(days=n)


class CalendrierBase(EducationBase):
    def evenement(self, titre="Réunion des parents", debut=None, fin=None, ecole=None, **extra):
        return EvenementCalendrier.objects.create(
            etablissement=ecole or self.ecole, titre=titre, date_debut=debut or jours(3), date_fin=fin, **extra,
        )

    def setUp(self):
        self.url = reverse("scolarite:calendrier")


class ModeleEtVisibiliteTests(CalendrierBase):
    def test_une_periode_et_une_journee(self):
        un_jour = self.evenement(debut=D(2026, 12, 25))
        periode = self.evenement(titre="Vacances de Noël", debut=D(2026, 12, 20), fin=D(2027, 1, 3))
        self.assertEqual((un_jour.fin, un_jour.est_une_periode), (D(2026, 12, 25), False))
        self.assertEqual((periode.fin, periode.est_une_periode), (D(2027, 1, 3), True))

    def test_les_dates_incoherentes_sont_refusees(self):
        with self.assertRaises(ValidationError):
            EvenementCalendrier(etablissement=self.ecole, titre="x", date_debut=D(2026, 12, 20), date_fin=D(2026, 12, 19)).full_clean()
        with self.assertRaises(ValidationError):
            EvenementCalendrier(etablissement=self.ecole, titre="x", date_debut=D(2026, 1, 1), date_fin=D(2027, 6, 1)).full_clean()

    def test_les_parents_et_les_eleves_ne_voient_pas_les_dates_du_personnel(self):
        public = self.evenement("Fête de l'école")
        prive = self.evenement("Conseil de classe", reserve_au_personnel=True)
        for compte, attendu in ((self.fondateur, {public, prive}), (self.t1, {public, prive}), (self.parent, {public}), (self.e1, {public})):
            with self.subTest(compte=compte.email):
                self.assertEqual(set(evenements_visibles_pour(compte)), attendu)

    def test_chaque_ecole_a_son_calendrier(self):
        self.evenement("Chez A")
        self.evenement("Chez B", ecole=self.ecole_b)
        self.assertEqual([e.titre for e in evenements_visibles_pour(self.fondateur)], ["Chez A"])
        self.assertEqual([e.titre for e in evenements_visibles_pour(self.fondateur_b)], ["Chez B"])

    def test_les_prochaines_dates_sont_celles_en_cours_ou_a_venir_dans_l_ordre(self):
        self.evenement("Passé", debut=jours(-10))
        self.evenement("Passé (période finie)", debut=jours(-10), fin=jours(-2))
        en_cours = self.evenement("En cours", debut=jours(-2), fin=jours(2))
        demain = self.evenement("Demain", debut=jours(1))
        lointain = self.evenement("Dans un mois", debut=jours(30))
        self.assertEqual(prochains_evenements(self.fondateur), [en_cours, demain, lointain])
        self.assertEqual(prochains_evenements(self.fondateur, nombre=2), [en_cours, demain])

    def test_aujourd_hui_est_encore_a_venir(self):
        aujourdhui = self.evenement("Aujourd'hui", debut=AUJOURDHUI)
        self.assertEqual(prochains_evenements(self.fondateur), [aujourdhui])


class PageCalendrierTests(CalendrierBase):
    def test_tout_compte_de_l_ecole_lit_le_calendrier(self):
        self.evenement("Fête de l'école", debut=D(2026, 10, 20))
        for compte in (self.fondateur, self.secretaire, self.comptable, self.t1, self.parent, self.e1, self.censeur):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                reponse = self.client.get(self.url)
                self.assertEqual(reponse.status_code, 200)
                self.assertContains(reponse, "Fête de l&#x27;école")

    def test_un_visiteur_est_renvoye_a_la_connexion(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_la_page_ne_montre_pas_les_dates_du_personnel_aux_parents(self):
        self.evenement("Conseil de classe confidentiel", debut=D(2026, 11, 5), reserve_au_personnel=True)
        self.client.force_login(self.parent)
        self.assertNotContains(self.client.get(self.url), "confidentiel")
        self.client.force_login(self.t1)
        self.assertContains(self.client.get(self.url), "confidentiel")

    def test_les_evenements_sont_ranges_par_mois_et_par_annee_scolaire(self):
        self.evenement("Rentrée", debut=D(2026, 10, 1), type_evenement=TypeEvenement.RENTREE)
        self.evenement("Examen de fin d'année", debut=D(2027, 6, 10), type_evenement=TypeEvenement.EXAMEN)
        self.evenement("Une date de l'année passée", debut=D(2025, 12, 1))
        self.client.force_login(self.fondateur)
        contexte = self.client.get(self.url).context
        self.assertEqual(contexte["annee"], self.annee)
        self.assertEqual([m.month for m, _ in contexte["mois"]], [10, 6])
        self.assertEqual(contexte["total"], 2)
        precedente = self.client.get(self.url, {"annee": self.precedente.pk}).context
        self.assertEqual([e.titre for _, groupe in precedente["mois"] for e in groupe], ["Une date de l'année passée"])

    def test_une_periode_a_cheval_sur_deux_annees_apparait_dans_les_deux(self):
        self.evenement("Vacances d'été", debut=D(2026, 7, 15), fin=D(2026, 10, 5))  # finit après le début de 2026-2027
        self.client.force_login(self.fondateur)
        self.assertEqual(self.client.get(self.url).context["total"], 1)
        self.assertEqual(self.client.get(self.url, {"annee": self.precedente.pk}).context["total"], 1)

    def test_le_filtre_par_type_et_un_filtre_invalide(self):
        self.evenement("Férié", debut=D(2026, 10, 10), type_evenement=TypeEvenement.FERIE)
        self.evenement("Examen", debut=D(2026, 10, 12), type_evenement=TypeEvenement.EXAMEN)
        self.client.force_login(self.fondateur)
        self.assertEqual(self.client.get(self.url, {"type": "ferie"}).context["total"], 1)
        self.assertEqual(self.client.get(self.url, {"type": "n'importe quoi", "annee": "abc"}).context["total"], 2)

    def test_le_calendrier_d_une_autre_ecole_n_apparait_pas(self):
        self.evenement("Secret de B", debut=D(2026, 10, 10), ecole=self.ecole_b)
        self.client.force_login(self.fondateur)
        self.assertNotContains(self.client.get(self.url), "Secret de B")

    def test_le_menu_propose_le_calendrier(self):
        self.client.force_login(self.parent)
        self.assertIn(self.url, self.client.get(reverse("comptes:portail_parent")).content.decode())
        self.client.force_login(self.comptable)
        self.assertIn(self.url, self.client.get(reverse("comptes:redirection_tableau_de_bord"), follow=True).content.decode())


class GestionTests(CalendrierBase):
    donnees = {"titre": "Journée portes ouvertes", "type_evenement": "reunion", "date_debut": "2026-11-14", "date_fin": "", "description": "Salle des fêtes"}

    def test_le_secretariat_et_la_direction_gerent_le_calendrier(self):
        for compte in (self.secretaire, self.fondateur, self.dir_1er):
            EvenementCalendrier.objects.all().delete()
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                reponse = self.client.post(reverse("scolarite:ajouter_evenement"), self.donnees)
                self.assertRedirects(reponse, self.url)
                evenement = EvenementCalendrier.objects.get()
                self.assertEqual((evenement.etablissement, evenement.cree_par, evenement.fin), (self.ecole, compte, D(2026, 11, 14)))

    def test_les_autres_roles_ne_peuvent_que_lire(self):
        evenement = self.evenement()
        for compte in (self.comptable, self.t1, self.parent, self.e1, self.censeur):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertEqual(self.client.get(reverse("scolarite:ajouter_evenement")).status_code, 403)
                self.assertEqual(self.client.post(reverse("scolarite:ajouter_evenement"), self.donnees).status_code, 403)
                self.assertEqual(self.client.get(reverse("scolarite:modifier_evenement", args=[evenement.pk])).status_code, 403)
                self.assertEqual(self.client.post(reverse("scolarite:supprimer_evenement", args=[evenement.pk])).status_code, 403)
        self.assertEqual(EvenementCalendrier.objects.count(), 1)

    def test_les_boutons_ne_sont_proposes_qu_a_ceux_qui_gerent(self):
        self.evenement()
        self.client.force_login(self.secretaire)
        self.assertContains(self.client.get(self.url), "Ajouter une date")
        self.client.force_login(self.parent)
        self.assertNotContains(self.client.get(self.url), "Ajouter une date")

    def test_modifier_et_supprimer(self):
        evenement = self.evenement("Avant")
        self.client.force_login(self.secretaire)
        reponse = self.client.post(
            reverse("scolarite:modifier_evenement", args=[evenement.pk]), {**self.donnees, "titre": "  Après   modifié  ", "reserve_au_personnel": "on"},
        )
        self.assertRedirects(reponse, self.url)
        evenement.refresh_from_db()
        self.assertEqual((evenement.titre, evenement.reserve_au_personnel), ("Après modifié", True))
        self.client.post(reverse("scolarite:supprimer_evenement", args=[evenement.pk]))
        self.assertFalse(EvenementCalendrier.objects.exists())
        actions = list(JournalAudit.objects.values_list("action", flat=True))
        for attendue in ("modification_evenement_calendrier", "suppression_evenement_calendrier"):
            self.assertIn(attendue, actions)

    def test_on_ne_touche_pas_au_calendrier_d_une_autre_ecole(self):
        chez_b = self.evenement("Chez B", ecole=self.ecole_b)
        self.client.force_login(self.fondateur)
        self.assertEqual(self.client.get(reverse("scolarite:modifier_evenement", args=[chez_b.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("scolarite:supprimer_evenement", args=[chez_b.pk])).status_code, 404)
        self.assertTrue(EvenementCalendrier.objects.filter(pk=chez_b.pk).exists())

    def test_la_suppression_se_fait_en_post_seulement(self):
        evenement = self.evenement()
        self.client.force_login(self.fondateur)
        self.assertEqual(self.client.get(reverse("scolarite:supprimer_evenement", args=[evenement.pk])).status_code, 405)

    def test_les_erreurs_sont_expliquees(self):
        self.client.force_login(self.fondateur)
        reponse = self.client.post(reverse("scolarite:ajouter_evenement"), {**self.donnees, "date_fin": "2026-11-01"})
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "ne peut pas précéder")
        reponse = self.client.post(reverse("scolarite:ajouter_evenement"), {**self.donnees, "titre": "", "date_debut": ""})
        self.assertContains(reponse, "obligatoire")
        self.assertEqual(EvenementCalendrier.objects.count(), 0)

    def test_un_type_inconnu_est_refuse(self):
        self.client.force_login(self.fondateur)
        reponse = self.client.post(reverse("scolarite:ajouter_evenement"), {**self.donnees, "type_evenement": "grande-fete"})
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(EvenementCalendrier.objects.count(), 0)


class TableauDeBordTests(CalendrierBase):
    def test_les_prochaines_dates_sont_sur_le_tableau_de_bord(self):
        self.evenement("Fête de l'école", debut=jours(4))
        self.evenement("Conseil confidentiel", debut=jours(5), reserve_au_personnel=True)
        self.client.force_login(self.fondateur)
        page = self.client.get(reverse("comptes:redirection_tableau_de_bord")).content.decode()
        self.assertIn("Prochaines dates", page)
        self.assertIn("Fête de l&#x27;école", page)
        self.assertIn("Conseil confidentiel", page)

    def test_le_portail_parent_montre_les_dates_publiques_seulement(self):
        self.evenement("Fête de l'école", debut=jours(4))
        self.evenement("Conseil confidentiel", debut=jours(5), reserve_au_personnel=True)
        self.client.force_login(self.parent)
        page = self.client.get(reverse("comptes:portail_parent")).content.decode()
        self.assertIn("Fête de l&#x27;école", page)
        self.assertNotIn("confidentiel", page)

    def test_sans_date_a_venir_aucune_carte(self):
        self.evenement("Passé", debut=jours(-30))
        self.client.force_login(self.fondateur)
        self.assertNotIn("Prochaines dates", self.client.get(reverse("comptes:redirection_tableau_de_bord")).content.decode())


class CalendrierEnArabeTests(CalendrierBase):
    def test_les_pages_sont_en_arabe_pur(self):
        self.evenement("اجتماع أولياء الأمور", debut=D(2026, 10, 20), type_evenement=TypeEvenement.REUNION, reserve_au_personnel=True)
        self.evenement("Vacances de Noël", debut=D(2026, 12, 20), fin=D(2027, 1, 3), type_evenement=TypeEvenement.VACANCES)
        invalider(self.ecole.pk)
        client = client_en(self.secretaire, "ar")
        for adresse in (self.url, reverse("scolarite:ajouter_evenement")):
            reponse = client.get(adresse)
            self.assertEqual(reponse.status_code, 200)
            with self.subTest(page=adresse):
                # « Vacances de Noël » est un titre saisi en français : il reste tel quel ; tout le reste de la page est en arabe
                self.assertEqual([t for t in restes_latins(reponse.content.decode()) if t not in {"Français", "Vacances de Noël"}], [])
        page = client_en(self.secretaire, "ar").get(self.url).content.decode()
        self.assertIn("أكتوبر", page)
        self.assertIn("العطلة", page)
