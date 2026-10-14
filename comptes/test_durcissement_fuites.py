"""
Audit de fuites (octobre 2026) : un test par défaut trouvé, pour qu'il ne revienne pas.

1. CSV : un libellé qui commence par = + - @ n'est jamais interprété comme une formule par le tableur.
2. Synthèse des alertes (IA) : jamais partagée entre deux utilisateurs qui n'ont pas les mêmes alertes.
3. Saisie de notes et d'absences : un matricule d'une autre classe ou d'une autre école ne se distingue pas d'un matricule inexistant.
4. Connexion : un compte verrouillé ne se distingue pas d'un identifiant qui n'existe pas.
5. Journaux de l'hébergeur : jamais de nom, d'email, de matricule ni de numéro de téléphone.
6. Lien d'image des PDF : jamais en dehors du dossier des médias ou des fichiers statiques.
7. En-tête de sécurité : un formulaire ne peut envoyer ses données que vers ce site.

Jeu de données de EducationBase (statistiques.test_education) : école A (classe 6A : e1, e2, e3 ; 6B : e4 ; enseignant t1 en 6A,
t2 en 6B), école B vide.
"""
import hashlib
import json
import os
import tempfile
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from comptes.audit import enregistrer_action
from comptes.models import JournalAudit
from comptes.roles import Role
from finances.models import MouvementCaisse, TypeTranche, enregistrer_paiement
from pedagogie.models import Trimestre
from scolarite.models import Affectation
from statistiques.test_education import EducationBase, creer_compte


class CsvSansFormuleTests(EducationBase):
    def test_journal_de_caisse(self):
        enregistrer_paiement(
            eleve=self.e1, inscription=self.i["e1"], tranche=TypeTranche.VERSEMENT, montant=1000, mode_paiement="especes",
            enregistre_par=self.comptable,
        )
        MouvementCaisse.objects.update(description='=HYPERLINK("http://exemple.test")', reference="+REF-1")
        self.client.force_login(self.comptable)
        contenu = self.client.get(reverse("finances:journal_caisse_syscohada_csv")).content.decode("utf-8-sig")
        self.assertIn("'=HYPERLINK", contenu)
        self.assertIn("'+REF-1", contenu)
        self.assertNotIn('"=HYPERLINK', contenu)
        self.assertNotIn(";+REF-1", contenu)

    def test_effectifs_par_classe(self):
        self.c6a.nom = "=1+1"
        self.c6a.save(update_fields=["nom"])
        self.client.force_login(self.fondateur)
        contenu = self.client.get(reverse("statistiques:exporter_effectifs_csv"), {"annee": self.annee.pk}).content.decode("utf-8-sig")
        self.assertIn("'=1+1", contenu)
        self.assertNotIn("\n=1+1", contenu)

    def test_le_neutralisateur_est_partage(self):
        from comptes.excel import cellule_csv
        from statistiques.fiche import cellule_csv as ancien_nom

        self.assertIs(cellule_csv, ancien_nom)
        for texte, attendu in (("=CMD()", "'=CMD()"), ("+1", "'+1"), ("-1", "'-1"), ("@x", "'@x"), ("\tx", "'\tx"), ("\rx", "'\rx")):
            self.assertEqual(cellule_csv(texte), attendu)
        self.assertEqual((cellule_csv("École"), cellule_csv(None), cellule_csv(12.5), cellule_csv("")), ("École", "", 12.5, ""))


class SyntheseDesAlertesTests(TestCase):
    """La phrase de synthèse (IA) ne se partage qu'entre des alertes strictement identiques."""

    def setUp(self):
        cache.clear()
        self.utilisateur = mock.Mock(etablissement_id=1, role="enseignant")

    def synthese(self, alertes, reponse):
        from comptes.views import _synthese_alertes_en_cache

        with mock.patch("assistant.services.ia_disponible", return_value=True), mock.patch(
            "assistant.services.resumer_alertes_avec_ia", return_value=reponse,
        ) as appel:
            return _synthese_alertes_en_cache(self.utilisateur, alertes), appel

    def test_deux_enseignants_aux_alertes_differentes_ne_partagent_pas_la_phrase(self):
        alertes_a = [{"titre": "5 élève(s) en risque de redoublement", "description": "Moyenne sous 10/20."}]
        alertes_b = [{"titre": "1 élève(s) en risque de redoublement", "description": "Moyenne sous 10/20."}]
        phrase_a, _ = self.synthese(alertes_a, "Cinq élèves sont en difficulté.")
        phrase_b, appel_b = self.synthese(alertes_b, "Un élève est en difficulté.")  # même rôle, même école
        self.assertEqual((phrase_a, phrase_b), ("Cinq élèves sont en difficulté.", "Un élève est en difficulté."))
        appel_b.assert_called_once()

    def test_des_alertes_identiques_ne_rappellent_pas_l_ia(self):
        alertes = [{"titre": "2 élève(s) avec des frais impayés", "description": "Solde dû."}]
        self.synthese(alertes, "Deux familles ont un impayé.")
        phrase, appel = self.synthese(alertes, "AUTRE PHRASE")
        self.assertEqual(phrase, "Deux familles ont un impayé.")
        appel.assert_not_called()

    def test_la_cle_ne_contient_ni_role_ni_etablissement(self):
        alertes = [{"titre": "t", "description": "d"}]
        self.synthese(alertes, "ok")
        contenu = json.dumps([["t", "d"]], ensure_ascii=False)
        attendu = "synthese_alertes_" + hashlib.sha256(contenu.encode("utf-8")).hexdigest()
        self.assertEqual(cache.get(attendu), "ok")


class MatriculeIntrouvableTests(EducationBase):
    """Même réponse pour : matricule inexistant, élève d'une autre classe, élève d'une autre école."""

    def setUp(self):
        self.affectation = Affectation.objects.get(enseignant=self.t1, classe=self.c6a)
        self.eleve_autre_ecole = creer_compte(Role.ELEVE, "eleve-b@durcissement.test", self.ecole_b)
        self.client.force_login(self.t1)

    def erreurs(self, reponse):
        return reponse.context["formulaire"].errors.get("matricule_eleve")

    def poster_note(self, matricule):
        return self.client.post(
            reverse("pedagogie:saisir_note", args=[self.affectation.pk]),
            {"matricule_eleve": matricule, "trimestre": Trimestre.T1.value, "note_classe": "12"},
        )

    def poster_absence(self, matricule):
        return self.client.post(
            reverse("pedagogie:saisir_absence", args=[self.c6a.pk]),
            {"matricule_eleve": matricule, "date_absence": "2026-11-03"},
        )

    def test_notes(self):
        reponses = {
            "inexistant": self.poster_note("00000000"),
            "autre classe": self.poster_note(self.e4.matricule),  # e4 est en 6B
            "autre école": self.poster_note(self.eleve_autre_ecole.matricule),
        }
        messages = {nom: self.erreurs(reponse) for nom, reponse in reponses.items()}
        self.assertTrue(all(messages.values()), messages)
        self.assertEqual(len({tuple(m) for m in messages.values()}), 1, messages)

    def test_absences(self):
        messages = {
            "inexistant": self.erreurs(self.poster_absence("00000000")),
            "autre classe": self.erreurs(self.poster_absence(self.e4.matricule)),
            "autre école": self.erreurs(self.poster_absence(self.eleve_autre_ecole.matricule)),
        }
        self.assertTrue(all(messages.values()), messages)
        self.assertEqual(len({tuple(m) for m in messages.values()}), 1, messages)

    def test_le_message_ne_dit_pas_que_l_eleve_existe_ailleurs(self):
        for erreur in (self.erreurs(self.poster_note(self.e4.matricule)), self.erreurs(self.poster_absence(self.e4.matricule))):
            texte = " ".join(erreur).lower()
            self.assertNotIn("n'est pas inscrit", texte)
            self.assertNotIn("existe", texte)

    def test_un_eleve_de_la_classe_reste_accepte(self):
        reponse = self.poster_absence(self.e1.matricule)
        self.assertEqual(reponse.status_code, 302)  # enregistré, retour à la page de saisie
        reponse = self.poster_note(self.e1.matricule)
        self.assertEqual(reponse.status_code, 302)


@override_settings(NB_TENTATIVES_CONNEXION_AVANT_VERROUILLAGE=3)
class ConnexionSansIndiceTests(TestCase):
    def setUp(self):
        cache.clear()
        from etablissement.models import Etablissement

        self.ecole = Etablissement.objects.create(nom="École de connexion")
        self.compte = creer_compte(Role.SECRETAIRE, "secretaire@connexion.test", self.ecole)
        self.compte.set_password("Bon-Mot-De-Passe-2026!")
        self.compte.save()

    def tenter(self, identifiant, mot_de_passe):
        cache.clear()  # la limite par adresse IP n'est pas ce que ce test vérifie
        return self.client.post(reverse("comptes:connexion"), {"email": identifiant, "mot_de_passe": mot_de_passe})

    def message(self, reponse):
        return [str(m) for m in reponse.context["messages"]]

    def test_un_compte_verrouille_repond_comme_un_identifiant_inconnu(self):
        inconnu = self.message(self.tenter("personne@connexion.test", "faux"))
        for _ in range(3):
            self.tenter(self.compte.email, "faux")
        self.compte.refresh_from_db()
        self.assertTrue(self.compte.verrouille())
        verrouille = self.message(self.tenter(self.compte.email, "faux"))
        self.assertEqual(verrouille, inconnu)

    def test_le_verrouillage_tient_meme_avec_le_bon_mot_de_passe(self):
        for _ in range(3):
            self.tenter(self.compte.email, "faux")
        reponse = self.tenter(self.compte.email, "Bon-Mot-De-Passe-2026!")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.message(reponse), self.message(self.tenter("personne@connexion.test", "faux")))

    def test_le_message_dit_quand_meme_a_la_personne_legitime_quoi_faire(self):
        texte = " ".join(self.message(self.tenter("personne@connexion.test", "faux")))
        self.assertIn("incorrect", texte)
        self.assertIn("verrouillé", texte)
        self.assertIn("Réessayez", texte)


class JournauxSansDonneesPersonnellesTests(EducationBase):
    def test_la_ligne_de_journal_de_l_hebergeur_ne_porte_que_des_numeros(self):
        with self.assertLogs("audit", level="INFO") as journal:
            enregistrer_action(
                acteur=self.secretaire, action="essai_audit", cible=f"{self.e1.nom_complet} ({self.e1.matricule})",
                details={"email": "parent@famille.test", "telephone": "70999001", "montant": 15000},
            )
        ligne = "\n".join(journal.output)
        self.assertIn("essai_audit", ligne)
        self.assertIn(f"acteur={self.secretaire.pk}", ligne)
        for interdit in (self.secretaire.nom, self.secretaire.email, self.e1.nom, self.e1.matricule, "parent@famille.test", "70999001", "15000"):
            self.assertNotIn(interdit, ligne)

    def test_le_journal_en_base_garde_tout_le_detail(self):
        enregistrer_action(acteur=self.secretaire, action="essai_audit", cible="cible précise", details={"k": "v"})
        entree = JournalAudit.objects.get(action="essai_audit")
        self.assertEqual((entree.cible, entree.details, entree.acteur), ("cible précise", {"k": "v"}, self.secretaire))

    def test_un_visiteur_anonyme_ne_casse_rien(self):
        with self.assertLogs("audit", level="INFO") as journal:
            enregistrer_action(acteur=None, action="essai_anonyme", cible="x")
        self.assertIn("acteur=None", journal.output[0])


class LienDImagePdfTests(SimpleTestCase):
    def test_un_lien_ne_sort_jamais_du_dossier_des_medias(self):
        from django.conf import settings

        from pedagogie.views import _lien_pdf

        with tempfile.TemporaryDirectory() as dossier, override_settings(MEDIA_ROOT=dossier):
            with open(os.path.join(dossier, "logo.png"), "wb") as fichier:
                fichier.write(b"x")
            dedans = _lien_pdf(settings.MEDIA_URL + "logo.png", None)
            self.assertEqual(os.path.realpath(dedans), os.path.realpath(os.path.join(dossier, "logo.png")))
            for piege in ("../secret.txt", "../../etc/passwd", "sous/../../secret.txt", "..\\secret.txt"):
                resultat = _lien_pdf(settings.MEDIA_URL + piege, None)
                with self.subTest(piege=piege):
                    # Rendu tel quel (introuvable, jamais lu) ou, quand le système ne voit pas là une sortie du dossier (sous Linux,
                    # « ..\secret.txt » n'est qu'un nom de fichier), un chemin qui reste DANS le dossier des médias.
                    rendu_tel_quel = resultat == settings.MEDIA_URL + piege
                    reste_dedans = os.path.realpath(resultat).startswith(os.path.realpath(dossier) + os.sep)
                    self.assertTrue(rendu_tel_quel or reste_dedans, resultat)

    def test_un_lien_statique_sort_pas_non_plus(self):
        from django.conf import settings

        from pedagogie.views import _lien_pdf

        resultat = _lien_pdf(settings.STATIC_URL + "../../manage.py", None)
        self.assertEqual(resultat, settings.STATIC_URL + "../../manage.py")


class EnTeteDeSecuriteTests(TestCase):
    def test_form_action_limite_aux_formulaires_de_ce_site(self):
        entete = self.client.get(reverse("comptes:connexion"))["Content-Security-Policy"]
        self.assertIn("form-action 'self'", entete)
        self.assertIn("frame-ancestors 'none'", entete)
        self.assertIn("script-src 'self' 'nonce-", entete)
