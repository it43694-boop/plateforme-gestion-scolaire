"""
Retrouver un élève par son NOM, sans retenir son matricule : saisie des notes et des absences, assistant, paiements, recherche
générale. Sans tenir compte des accents ni de l'ordre des mots.

Jeu de données de EducationBase (statistiques.test_education) : école A (classe 6A : e1, e2, e3 ; 6B : e4 ; enseignant t1 en 6A,
t2 en 6B ; parent lié à e1), école B vide. On donne de vrais noms aux élèves :
e1 MAIGA Aïssata, e2 KEITA Awa, e3 KEITA Awa (homonyme de e2, même classe), e4 DIARRA Mamadou (6B).
"""
from django.test import SimpleTestCase
from django.urls import reverse

from comptes.models import Utilisateur
from comptes.roles import Role
from pedagogie.forms import MESSAGE_ELEVE_INTROUVABLE_DANS_LA_CLASSE, MESSAGE_PLUSIEURS_ELEVES
from pedagogie.models import Absence, Note, Trimestre
from scolarite.models import Affectation, Inscription, eleve_visible_pour, eleves_visibles_pour
from scolarite.recherche import INTROUVABLE, PLUSIEURS, filtrer, normaliser, options_de_saisie, trouver_eleve
from statistiques.test_education import EducationBase, creer_compte


class Personne:
    def __init__(self, nom, prenom, matricule="", email=""):
        self.nom, self.prenom, self.matricule, self.email = nom, prenom, matricule, email


CLASSE = [
    Personne("MAIGA", "Aïssata", "2026001"), Personne("KEITA", "Awa", "2026002"),
    Personne("KEITA", "Awa", "2026003"), Personne("DIARRA", "Mamadou", "2026004"),
]


class RechercheUnitaireTests(SimpleTestCase):
    def test_normaliser(self):
        self.assertEqual(normaliser("  Aïssata   MAIGA "), "aissata maiga")
        self.assertEqual(normaliser("ÉLÈVE Çà"), "eleve ca")
        self.assertEqual((normaliser(None), normaliser("")), ("", ""))

    def test_filtrer_sans_accents_ni_ordre(self):
        for terme in ("aissata", "AÏSSATA", "maiga aissata", "Aïssata MAIGA", "ssat", "202600"):
            with self.subTest(terme=terme):
                self.assertIn("2026001", [p.matricule for p in filtrer(CLASSE, terme, "nom", "prenom", "matricule")])

    def test_filtrer_tous_les_mots_doivent_correspondre(self):
        self.assertEqual([p.matricule for p in filtrer(CLASSE, "keita mamadou", "nom", "prenom")], [])
        self.assertEqual(len(filtrer(CLASSE, "keita", "nom", "prenom")), 2)

    def test_filtrer_terme_vide_et_limite(self):
        self.assertEqual(filtrer(CLASSE, "", "nom"), [])
        self.assertEqual(filtrer(CLASSE, "   ", "nom"), [])
        self.assertEqual(len(filtrer(CLASSE, "a", "nom", "prenom", limite=2)), 2)

    def test_filtrer_a_travers_une_relation(self):
        class Inscription:
            def __init__(self, eleve):
                self.eleve = eleve

        trouvees = filtrer([Inscription(p) for p in CLASSE], "diarra", "eleve.nom", "eleve.prenom")
        self.assertEqual([i.eleve.matricule for i in trouvees], ["2026004"])

    def test_trouver_eleve(self):
        attendu = {
            "2026001": "2026001", "Aïssata MAIGA": "2026001", "maiga aissata": "2026001", "MAIGA Aïssata (2026001)": "2026001",
            "KEITA Awa (2026003)": "2026003", "KEITA Awa - 2026002": "2026002", "  Mamadou   Diarra ": "2026004",
        }
        for saisie, matricule in attendu.items():
            with self.subTest(saisie=saisie):
                eleve, probleme = trouver_eleve(saisie, CLASSE)
                self.assertEqual((eleve.matricule, probleme), (matricule, None))

    def test_trouver_eleve_problemes(self):
        self.assertEqual(trouver_eleve("Awa KEITA", CLASSE), (None, PLUSIEURS))
        for saisie in ("Awa", "keit", "inconnu", "", "   ", None, "MAIGA Aïssata (9999999)"):
            with self.subTest(saisie=saisie):
                self.assertEqual(trouver_eleve(saisie, CLASSE), (None, INTROUVABLE))

    def test_une_saisie_a_moitie_tapee_ne_designe_personne(self):
        """Jamais un bout de nom : on ne note pas le mauvais élève parce qu'un seul commence par « Mam »."""
        self.assertEqual(trouver_eleve("Mam", CLASSE), (None, INTROUVABLE))
        self.assertEqual(trouver_eleve("Diarra", CLASSE), (None, INTROUVABLE))

    def test_options_de_saisie(self):
        self.assertEqual(
            options_de_saisie(CLASSE),
            ["DIARRA Mamadou", "KEITA Awa (2026002)", "KEITA Awa (2026003)", "MAIGA Aïssata"],  # matricule seulement pour les homonymes
        )


class BaseNoms(EducationBase):
    def setUp(self):
        for eleve, (nom, prenom) in {
            self.e1: ("MAIGA", "Aïssata"), self.e2: ("KEITA", "Awa"), self.e3: ("KEITA", "Awa"), self.e4: ("DIARRA", "Mamadou"),
        }.items():
            Utilisateur.objects.filter(pk=eleve.pk).update(nom=nom, prenom=prenom)
            eleve.refresh_from_db()
        self.eleve_autre_ecole = creer_compte(Role.ELEVE, "bamba@noms.test", self.ecole_b)
        Utilisateur.objects.filter(pk=self.eleve_autre_ecole.pk).update(nom="BAMBA", prenom="Fanta")
        Inscription.objects.create(eleve=self.eleve_autre_ecole, classe=self.classe_b)  # visible du seul fondateur de l'école B
        self.affectation = Affectation.objects.get(enseignant=self.t1, classe=self.c6a)


class VisibiliteTests(BaseNoms):
    def test_la_requete_donne_exactement_la_regle_de_eleve_visible_pour(self):
        eleves = [self.e1, self.e2, self.e3, self.e4, self.e5, self.e9, self.eleve_autre_ecole]
        comptes = [
            self.fondateur, self.dir_1er, self.secretaire, self.comptable, self.censeur, self.t1, self.t2, self.t3,
            self.parent, self.e1, self.e2, self.fondateur_b,
        ]
        for compte in comptes:
            attendu = {e.pk for e in eleves if eleve_visible_pour(compte, e)}
            obtenu = {e.pk for e in eleves_visibles_pour(compte) if e.pk in {x.pk for x in eleves}}
            with self.subTest(role=compte.role, compte=compte.email):
                self.assertEqual(obtenu, attendu)

    def test_jamais_un_eleve_d_une_autre_ecole(self):
        for compte in (self.fondateur, self.dir_1er, self.secretaire, self.t1):
            self.assertNotIn(self.eleve_autre_ecole.pk, {e.pk for e in eleves_visibles_pour(compte)})
        self.assertEqual({e.pk for e in eleves_visibles_pour(self.fondateur_b)}, {self.eleve_autre_ecole.pk})


class SaisieDesNotesParNomTests(BaseNoms):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.t1)

    def poster(self, saisie, **extra):
        return self.client.post(
            reverse("pedagogie:saisir_note", args=[self.affectation.pk]),
            {"matricule_eleve": saisie, "trimestre": Trimestre.T1.value, "note_classe": "12", **extra},
        )

    def test_le_nom_suffit_meme_sans_accent_ni_ordre(self):
        for saisie in ("aissata maiga", "MAIGA Aïssata", "Aïssata  MAIGA"):
            with self.subTest(saisie=saisie):
                Note.objects.all().delete()
                self.assertEqual(self.poster(saisie).status_code, 302)
                self.assertEqual(list(Note.objects.values_list("eleve_id", flat=True)), [self.e1.pk])

    def test_le_matricule_marche_toujours(self):
        self.assertEqual(self.poster(self.e1.matricule).status_code, 302)
        self.assertTrue(Note.objects.filter(eleve=self.e1).exists())

    def test_le_choix_de_la_liste_avec_matricule_marche(self):
        self.assertEqual(self.poster(f"KEITA Awa ({self.e3.matricule})").status_code, 302)
        self.assertTrue(Note.objects.filter(eleve=self.e3).exists())
        self.assertFalse(Note.objects.filter(eleve=self.e2).exists())

    def test_deux_homonymes_il_faut_choisir(self):
        reponse = self.poster("Awa KEITA")
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.context["formulaire"].errors["matricule_eleve"], [MESSAGE_PLUSIEURS_ELEVES])
        self.assertFalse(Note.objects.exists())

    def test_une_saisie_incomplete_n_enregistre_rien(self):
        reponse = self.poster("Aïss")
        self.assertEqual(reponse.context["formulaire"].errors["matricule_eleve"], [MESSAGE_ELEVE_INTROUVABLE_DANS_LA_CLASSE])
        self.assertFalse(Note.objects.exists())

    def test_un_autre_eleve_ne_se_distingue_pas_d_un_inconnu(self):
        """Élève d'une autre classe, d'une autre école, ou qui n'existe pas : même réponse."""
        erreurs = {
            saisie: self.poster(saisie).context["formulaire"].errors["matricule_eleve"]
            for saisie in ("Mamadou DIARRA", self.e4.matricule, "Fanta BAMBA", self.eleve_autre_ecole.matricule, "Personne Inconnu")
        }
        self.assertEqual({tuple(v) for v in erreurs.values()}, {(MESSAGE_ELEVE_INTROUVABLE_DANS_LA_CLASSE,)}, erreurs)
        self.assertFalse(Note.objects.exists())

    def test_la_liste_de_la_page_ne_contient_que_la_classe(self):
        page = self.client.get(reverse("pedagogie:saisir_note", args=[self.affectation.pk]))
        self.assertContains(page, '<datalist id="eleves-de-la-classe">')
        self.assertContains(page, '<option value="MAIGA Aïssata">')
        self.assertContains(page, f'<option value="KEITA Awa ({self.e2.matricule})">')  # homonymes : le matricule les distingue
        self.assertContains(page, f'<option value="KEITA Awa ({self.e3.matricule})">')
        for absent in ("DIARRA", "BAMBA", self.e4.matricule, self.eleve_autre_ecole.matricule):
            self.assertNotContains(page, absent)

    def test_le_matricule_d_un_eleve_sans_homonyme_n_est_pas_affiche(self):
        page = self.client.get(reverse("pedagogie:saisir_note", args=[self.affectation.pk]))
        self.assertNotContains(page, self.e1.matricule)

    def test_le_champ_demande_un_nom_ou_un_matricule(self):
        page = self.client.get(reverse("pedagogie:saisir_note", args=[self.affectation.pk]))
        self.assertContains(page, 'placeholder="Nom ou matricule"')
        self.assertContains(page, 'list="eleves-de-la-classe"')

    def test_la_saisie_hors_ligne_par_nom_est_rejouable(self):
        """Le script envoie le champ tel quel (JSON) : le nom doit donner la même note qu'avec le matricule."""
        reponse = self.client.post(
            reverse("pedagogie:saisir_note", args=[self.affectation.pk]),
            {"matricule_eleve": "maiga aissata", "trimestre": Trimestre.T1.value, "note_classe": "15"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        donnees = reponse.json()
        self.assertTrue(donnees["ok"])
        self.assertEqual(donnees["eleve"], self.e1.nom_complet)


class SaisieDesAbsencesParNomTests(BaseNoms):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.t1)

    def poster(self, saisie):
        return self.client.post(
            reverse("pedagogie:saisir_absence", args=[self.c6a.pk]), {"matricule_eleve": saisie, "date_absence": "2026-11-03"},
        )

    def test_par_nom_par_matricule_et_par_choix_de_la_liste(self):
        for saisie in ("aissata maiga", self.e1.matricule, "MAIGA Aïssata"):
            with self.subTest(saisie=saisie):
                Absence.objects.all().delete()
                self.assertEqual(self.poster(saisie).status_code, 302)
                self.assertEqual(list(Absence.objects.values_list("eleve_id", flat=True)), [self.e1.pk])

    def test_homonymes_et_inconnus(self):
        self.assertEqual(self.poster("Awa KEITA").context["formulaire"].errors["matricule_eleve"], [MESSAGE_PLUSIEURS_ELEVES])
        for saisie in ("Mamadou DIARRA", "Fanta BAMBA", "nobody"):
            self.assertEqual(
                self.poster(saisie).context["formulaire"].errors["matricule_eleve"], [MESSAGE_ELEVE_INTROUVABLE_DANS_LA_CLASSE],
            )
        self.assertFalse(Absence.objects.exists())

    def test_la_liste_de_la_page_ne_contient_que_la_classe(self):
        page = self.client.get(reverse("pedagogie:saisir_absence", args=[self.c6a.pk]))
        self.assertContains(page, '<option value="MAIGA Aïssata">')
        self.assertNotContains(page, "DIARRA")
        self.assertNotContains(page, "BAMBA")


class AssistantParNomTests(BaseNoms):
    URL = "assistant:rechercher_eleve_json"

    def chercher(self, compte, terme):
        self.client.force_login(compte)
        return self.client.get(reverse(self.URL), {"q": terme})

    def noms(self, reponse):
        return [r["nom_complet"] for r in reponse.json()["resultats"]]

    def test_recherche_sans_accent_ni_ordre(self):
        for terme in ("aissata", "maiga aissata", "MAIGA", "ïssa"):
            with self.subTest(terme=terme):
                self.assertEqual(self.noms(self.chercher(self.fondateur, terme)), [f"{self.e1.nom_complet} ({self.e1.matricule})"])

    def test_au_moins_deux_caracteres(self):
        self.assertEqual(self.chercher(self.fondateur, "a").json()["resultats"], [])

    def test_un_enseignant_ne_trouve_que_les_eleves_de_ses_classes(self):
        self.assertEqual(len(self.noms(self.chercher(self.t1, "keita"))), 2)  # 6A : e2 et e3
        self.assertEqual(self.noms(self.chercher(self.t1, "diarra")), [])      # e4 est en 6B, classe de t2
        self.assertEqual(len(self.noms(self.chercher(self.t2, "diarra"))), 1)

    def test_un_directeur_de_cycle_ne_trouve_que_son_cycle(self):
        self.assertEqual(len(self.noms(self.chercher(self.dir_1er, "diarra"))), 1)     # e4 : 6B, 1er cycle
        Utilisateur.objects.filter(pk=self.e5.pk).update(nom="SIDIBE", prenom="Oumar")  # e5 : 9A, 2ème cycle
        self.assertEqual(self.noms(self.chercher(self.dir_1er, "sidibe")), [])

    def test_jamais_un_eleve_d_une_autre_ecole(self):
        self.assertEqual(self.noms(self.chercher(self.fondateur, "bamba")), [])
        self.assertEqual(self.noms(self.chercher(self.fondateur_b, "keita")), [])
        self.assertEqual(len(self.noms(self.chercher(self.fondateur_b, "bamba"))), 1)

    def test_les_roles_sans_l_assistant_sont_refuses(self):
        for compte in (self.parent, self.e1):
            self.assertEqual(self.chercher(compte, "maiga").status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse(self.URL), {"q": "maiga"}).status_code, 302)

    def page(self, compte, saisie):
        self.client.force_login(compte)
        return self.client.get(reverse("assistant:poser_question"), {"matricule": saisie})

    def test_le_nom_tape_ouvre_le_dossier(self):
        for saisie in ("Aïssata MAIGA", "maiga aissata", f"{self.e1.nom_complet} ({self.e1.matricule})", self.e1.matricule):
            with self.subTest(saisie=saisie):
                reponse = self.page(self.fondateur, saisie)
                self.assertIsNone(reponse.context["erreur"])
                self.assertEqual(reponse.context["resultat"]["eleve"], self.e1)

    def test_homonymes(self):
        reponse = self.page(self.fondateur, "Awa KEITA")
        self.assertIn("Plusieurs élèves portent ce nom", reponse.context["erreur"])
        self.assertIsNone(reponse.context["resultat"])
        reponse = self.page(self.fondateur, f"KEITA Awa ({self.e3.matricule})")
        self.assertEqual(reponse.context["resultat"]["eleve"], self.e3)

    def test_messages_inchanges_pour_un_matricule_inconnu_ou_hors_de_portee(self):
        self.assertEqual(self.page(self.fondateur, "00000000").context["erreur"], "Aucun élève trouvé avec ce matricule.")
        self.assertEqual(self.page(self.fondateur, "Fanta BAMBA").context["erreur"], "Aucun élève trouvé avec ce matricule.")
        self.assertEqual(
            self.page(self.fondateur, self.eleve_autre_ecole.matricule).context["erreur"], "Aucun élève trouvé avec ce matricule.",
        )
        # Un enseignant qui tape l'élève d'une autre classe de SON école : même message qu'avant.
        self.assertEqual(
            self.page(self.t1, self.e4.matricule).context["erreur"], "Vous n'avez pas accès aux informations de cet élève.",
        )
        self.assertEqual(self.page(self.t1, "Mamadou DIARRA").context["erreur"], "Aucun élève trouvé avec ce matricule.")

    def test_la_page_propose_la_recherche(self):
        page = self.page(self.fondateur, "")
        self.assertContains(page, 'data-recherche-url="' + reverse(self.URL) + '"')
        self.assertContains(page, "Tapez un nom, un prénom ou un matricule")


class PaiementsEtRechercheGeneraleTests(BaseNoms):
    def test_la_recherche_des_paiements_ignore_les_accents(self):
        self.client.force_login(self.comptable)
        reponse = self.client.get(reverse("finances:rechercher_eleve_json"), {"q": "aissata maiga"})
        self.assertEqual([r["matricule"] for r in reponse.json()["resultats"]], [self.e1.matricule])

    def test_la_recherche_du_personnel_ignore_les_accents(self):
        Utilisateur.objects.filter(pk=self.t1.pk).update(prenom="Élodie", nom="DEMBÉLÉ")
        self.client.force_login(self.comptable)
        reponse = self.client.get(reverse("finances:rechercher_employe_json"), {"q": "elodie dembele"})
        self.assertEqual([r["email"] for r in reponse.json()["resultats"]], [self.t1.email])

    def test_la_barre_de_recherche_ignore_les_accents_et_l_ordre(self):
        self.client.force_login(self.fondateur)
        for terme in ("aissata maiga", "Maiga", "AÏSSATA"):
            with self.subTest(terme=terme):
                reponse = self.client.get(reverse("scolarite:recherche_globale"), {"q": terme})
                self.assertEqual([i.eleve for i in reponse.context["resultats"]], [self.e1])

    def test_la_barre_de_recherche_reste_cloisonnee(self):
        self.client.force_login(self.parent)  # parent de e1 seulement
        trouves = self.client.get(reverse("scolarite:recherche_globale"), {"q": "keita"}).context["resultats"]
        self.assertEqual(list(trouves), [])
        trouves = self.client.get(reverse("scolarite:recherche_globale"), {"q": "maiga"}).context["resultats"]
        self.assertEqual([i.eleve for i in trouves], [self.e1])
        self.client.force_login(self.fondateur_b)
        self.assertEqual(list(self.client.get(reverse("scolarite:recherche_globale"), {"q": "maiga"}).context["resultats"]), [])
