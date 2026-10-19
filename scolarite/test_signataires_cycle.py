"""Signature et cachet des cartes d'élève, cycle par cycle : le signataire de chaque cycle, le repli sur celui de l'école, la page de saisie du développeur."""
import base64
import io
import re
from unittest import mock

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.urls import reverse
from PIL import Image
from pypdf import PdfReader

from comptes.arabisation import invalider
from comptes.models import JournalAudit
from comptes.outils_test_arabe import CaptureHtmlDuPdf, client_en, restes_hors_textes_saisis
from comptes.roles import Role
from etablissement.models import SignataireCycle
from scolarite.cartes import ajouter_les_signataires, cachet_en_donnees, signataires_par_cycle
from scolarite.models import Cycle, cycles_autorises_pour
from scolarite.test_dossier_complet import StockageTemporaire, image_octets
from statistiques.test_education import creer_compte

PREMIER, DEUXIEME, LYCEE = Cycle.PREMIER_CYCLE.value, Cycle.DEUXIEME_CYCLE.value, Cycle.LYCEE.value


def png(couleur):
    """Une petite image PNG (la couleur la distingue des autres)."""
    return image_octets((200, 80), format="PNG", couleur=couleur)


def donnees(contenu):
    """L'adresse « data: » que la carte imprime pour cette image."""
    return "data:image/png;base64," + base64.b64encode(contenu).decode("ascii")


def couleur_du_cachet(adresse):
    """La couleur au centre du cachet imprimé (une image unie : sa couleur dit de quel fichier il vient), et le fait qu'il soit carré."""
    image = Image.open(io.BytesIO(base64.b64decode(adresse.split(",", 1)[1]))).convert("RGBA")
    assert image.width == image.height, image.size
    return image.getpixel((image.width // 2, image.height // 2))[:3]


def cachets_du_html(html):
    """Les couleurs des cachets imprimés dans le HTML d'une carte."""
    return [couleur_du_cachet(adresse) for adresse in re.findall(r'<img src="(data:image/png;base64,[^"]+)" class="cachet">', html)]


def televerser(nom, couleur):
    return SimpleUploadedFile(nom, png(couleur), content_type="image/png")


ROUGE, VERT, BLEU, GRIS = (200, 30, 30), (30, 160, 60), (30, 60, 200), (120, 120, 120)


class SignatairesParCycleTests(StockageTemporaire):
    def ecole_avec(self, **champs):
        for nom, valeur in champs.items():
            setattr(self.ecole, nom, valeur)
        self.ecole.save()

    def cycle(self, cycle, **champs):
        signataire = SignataireCycle(etablissement=self.ecole, cycle=cycle, **{k: v for k, v in champs.items() if k not in ("signature", "cachet")})
        signataire.save()
        for nom in ("signature", "cachet"):
            if champs.get(nom):
                getattr(signataire, nom).save(f"{nom}.png", ContentFile(champs[nom]), save=True)
        return signataire

    def test_un_cycle_sans_signataire_propre_reprend_celui_de_l_ecole(self):
        self.ecole_avec(nom_signataire="Directeur Général", fonction_signataire="Le Directeur Général")
        self.ecole.signature.save("s.png", ContentFile(png(ROUGE)), save=True)
        self.ecole.cachet.save("c.png", ContentFile(png(VERT)), save=True)
        resultat = signataires_par_cycle(self.ecole, [PREMIER])[PREMIER]
        self.assertEqual((resultat["nom"], resultat["fonction"]), ("Directeur Général", "Le Directeur Général"))
        self.assertEqual(resultat["signature"], donnees(png(ROUGE)))
        self.assertEqual(couleur_du_cachet(resultat["cachet"]), VERT)

    def test_chaque_cycle_a_son_signataire(self):
        self.cycle(PREMIER, nom_signataire="Directeur du premier cycle", fonction_signataire="Le Directeur du 1er cycle", signature=png(ROUGE), cachet=png(VERT))
        self.cycle(DEUXIEME, nom_signataire="Directrice du second cycle", fonction_signataire="La Directrice du 2ème cycle", signature=png(BLEU), cachet=png(GRIS))
        resultat = signataires_par_cycle(self.ecole, [PREMIER, DEUXIEME, LYCEE])
        self.assertEqual(resultat[PREMIER]["nom"], "Directeur du premier cycle")
        self.assertEqual(resultat[PREMIER]["signature"], donnees(png(ROUGE)))
        self.assertEqual(couleur_du_cachet(resultat[PREMIER]["cachet"]), VERT)
        self.assertEqual(resultat[DEUXIEME]["nom"], "Directrice du second cycle")
        self.assertEqual(resultat[DEUXIEME]["signature"], donnees(png(BLEU)))
        self.assertEqual(couleur_du_cachet(resultat[DEUXIEME]["cachet"]), GRIS)
        self.assertIsNone(resultat[LYCEE])  # ni le cycle ni l'école n'ont rien saisi

    def test_la_signature_de_l_ecole_n_accompagne_jamais_le_nom_d_un_autre_directeur(self):
        self.ecole_avec(nom_signataire="Directeur Général")
        self.ecole.signature.save("s.png", ContentFile(png(ROUGE)), save=True)
        self.cycle(PREMIER, nom_signataire="Directrice du premier cycle")  # son nom, mais pas de signature
        resultat = signataires_par_cycle(self.ecole, [PREMIER])[PREMIER]
        self.assertEqual(resultat["nom"], "Directrice du premier cycle")
        self.assertEqual(resultat["signature"], "")  # pas celle de l'école : elle est d'une autre personne

    def test_le_cachet_du_cycle_sinon_celui_de_l_ecole(self):
        self.ecole.cachet.save("c.png", ContentFile(png(VERT)), save=True)
        self.cycle(PREMIER, nom_signataire="Directrice", cachet=png(BLEU))
        self.cycle(DEUXIEME, nom_signataire="Directeur")  # sans cachet à lui
        resultat = signataires_par_cycle(self.ecole, [PREMIER, DEUXIEME])
        self.assertEqual(couleur_du_cachet(resultat[PREMIER]["cachet"]), BLEU)
        self.assertEqual(couleur_du_cachet(resultat[DEUXIEME]["cachet"]), VERT)

    def test_un_cycle_qui_n_a_que_son_cachet_garde_le_signataire_de_l_ecole(self):
        self.ecole_avec(nom_signataire="Directeur Général")
        self.cycle(PREMIER, cachet=png(BLEU))
        resultat = signataires_par_cycle(self.ecole, [PREMIER])[PREMIER]
        self.assertEqual(resultat["nom"], "Directeur Général")
        self.assertEqual(couleur_du_cachet(resultat["cachet"]), BLEU)

    def test_le_signataire_d_une_autre_ecole_n_est_jamais_utilise(self):
        SignataireCycle.objects.create(etablissement=self.ecole_b, cycle=PREMIER, nom_signataire="Directeur de l'autre école")
        self.assertIsNone(signataires_par_cycle(self.ecole, [PREMIER])[PREMIER])

    def test_une_image_n_est_lue_qu_une_fois_meme_si_plusieurs_cycles_s_en_servent(self):
        self.ecole.cachet.save("c.png", ContentFile(png(VERT)), save=True)
        with mock.patch("scolarite.cartes.cachet_en_donnees", wraps=cachet_en_donnees) as lecture:
            signataires_par_cycle(self.ecole, [PREMIER, DEUXIEME, LYCEE])
        self.assertEqual(lecture.call_count, 1)

    def test_un_cachet_de_toute_forme_est_recadre_dans_un_carre_sans_deformation(self):
        self.ecole.cachet.save("c.png", ContentFile(png(VERT)), save=True)  # 200 x 80
        adresse = cachet_en_donnees(self.ecole.cachet)
        image = Image.open(io.BytesIO(base64.b64decode(adresse.split(",", 1)[1])))
        self.assertEqual(image.size, (200, 200))
        self.assertEqual(image.convert("RGBA").getpixel((100, 100))[:3], VERT)
        self.assertEqual(image.convert("RGBA").getpixel((100, 5))[3], 0)  # la marge ajoutée est transparente

    def test_un_cachet_illisible_ou_absent_ne_fait_pas_echouer_la_carte(self):
        self.assertEqual(cachet_en_donnees(self.ecole.cachet), "")
        self.ecole.cachet.save("c.png", ContentFile(b"ceci n'est pas une image"), save=True)
        self.assertEqual(cachet_en_donnees(self.ecole.cachet), "")
        self.assertIsNone(signataires_par_cycle(self.ecole, [PREMIER])[PREMIER])

    def test_un_seul_signataire_par_cycle_et_par_ecole(self):
        SignataireCycle.objects.create(etablissement=self.ecole, cycle=PREMIER, nom_signataire="A")
        with self.assertRaises(IntegrityError), transaction.atomic():
            SignataireCycle.objects.create(etablissement=self.ecole, cycle=PREMIER, nom_signataire="B")

    def test_un_cycle_inconnu_est_refuse(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            SignataireCycle(etablissement=self.ecole, cycle="universite", nom_signataire="A").full_clean()

    def test_les_cartes_recoivent_le_signataire_du_cycle_de_leur_classe(self):
        from scolarite.cartes import construire_cartes
        from scolarite.models import Inscription

        self.cycle(PREMIER, nom_signataire="Directeur du premier cycle")
        self.cycle(DEUXIEME, nom_signataire="Directrice du second cycle")
        inscriptions = list(Inscription.objects.filter(eleve__in=[self.e1, self.e5]).select_related("eleve", "classe__annee_scolaire"))
        cartes = construire_cartes(inscriptions, lambda code: f"http://testserver/verifier/?code={code}")
        ajouter_les_signataires(cartes, self.ecole)
        par_eleve = {carte["eleve"].pk: carte["signataire"]["nom"] for carte in cartes}
        self.assertEqual(par_eleve[self.e1.pk], "Directeur du premier cycle")
        self.assertEqual(par_eleve[self.e5.pk], "Directrice du second cycle")


class CartesDeChaqueCycleTests(StockageTemporaire):
    def setUp(self):
        self.client.force_login(self.secretaire)
        self.url_6a = reverse("scolarite:cartes_classe_pdf", args=[self.c6a.pk])
        self.url_9a = reverse("scolarite:cartes_classe_pdf", args=[self.c9a.pk])
        premier = SignataireCycle.objects.create(etablissement=self.ecole, cycle=PREMIER, nom_signataire="Madame Premier", fonction_signataire="La Directrice du premier cycle")
        premier.signature.save("s.png", ContentFile(png(ROUGE)), save=True)
        premier.cachet.save("c.png", ContentFile(png(VERT)), save=True)
        deuxieme = SignataireCycle.objects.create(etablissement=self.ecole, cycle=DEUXIEME, nom_signataire="Monsieur Second", fonction_signataire="Le Directeur du 2ème cycle")
        deuxieme.signature.save("s.png", ContentFile(png(BLEU)), save=True)

    def html_de(self, adresse, client=None):
        with CaptureHtmlDuPdf() as capture:
            reponse = (client or self.client).get(adresse)
        self.assertEqual(reponse.status_code, 200)
        return capture.html

    def test_chaque_cycle_imprime_son_signataire_sa_signature_et_son_cachet(self):
        html = self.html_de(self.url_6a)
        self.assertIn("Madame Premier", html)
        self.assertIn("La Directrice du premier cycle", html)
        self.assertIn(donnees(png(ROUGE)), html)
        self.assertEqual(cachets_du_html(html), [VERT] * 3)  # une fois par carte (trois élèves en 6A)
        for autre in ("Monsieur Second", donnees(png(BLEU))):
            self.assertNotIn(autre, html)

        html = self.html_de(self.url_9a)
        self.assertIn("Monsieur Second", html)
        self.assertIn(donnees(png(BLEU)), html)
        self.assertNotIn('class="cachet"', html)  # ce cycle n'a pas de cachet, et l'école non plus
        for autre in ("Madame Premier", donnees(png(ROUGE))):
            self.assertNotIn(autre, html)

    def test_un_cycle_sans_signataire_garde_celui_de_l_ecole_et_son_cachet(self):
        self.ecole.nom_signataire = "Directeur Général"
        self.ecole.save()
        self.ecole.cachet.save("c.png", ContentFile(png(GRIS)), save=True)
        html = self.html_de(reverse("scolarite:cartes_classe_pdf", args=[self.ctse.pk]))  # le lycée n'a rien de propre
        self.assertIn("Directeur Général", html)
        self.assertEqual(set(cachets_du_html(html)), {GRIS})
        self.assertNotIn("Madame Premier", html)

    def test_le_cachet_de_l_ecole_est_imprime_sur_la_carte(self):
        SignataireCycle.objects.all().delete()
        self.assertNotIn('class="cachet"', self.html_de(self.url_6a))
        self.ecole.cachet.save("c.png", ContentFile(png(GRIS)), save=True)
        self.assertIn('class="cachet"', self.html_de(self.url_6a))

    def test_la_carte_reste_sur_la_page_prevue_avec_la_signature_et_le_cachet(self):
        reponse = self.client.get(self.url_6a)
        self.assertEqual(len(PdfReader(io.BytesIO(reponse.content)).pages), 1)

    def test_le_signataire_n_est_imprime_que_s_il_y_a_quelque_chose_a_imprimer(self):
        SignataireCycle.objects.all().delete()
        self.assertNotIn('class="signataire"', self.html_de(self.url_6a))

    def test_la_carte_en_arabe_est_en_arabe_pur_avec_un_signataire_de_cycle(self):
        invalider(self.ecole.pk)
        client = client_en(self.secretaire, "ar")
        with CaptureHtmlDuPdf() as capture:
            reponse = client.get(self.url_6a)
        self.assertEqual(reponse.status_code, 200)
        codes = set(__import__("scolarite.models", fromlist=["x"]).VerificationDocument.objects.values_list("code", flat=True))
        saisis = codes | {"testserver/verifier", "Madame Premier", "La Directrice du premier cycle"}
        self.assertEqual(restes_hors_textes_saisis(capture.html, saisis), [])
        self.assertEqual(len(PdfReader(io.BytesIO(reponse.content)).pages), 1)


class PageDesSignatairesTests(StockageTemporaire):
    maxDiff = None

    def setUp(self):
        self.developpeur = creer_compte(Role.DEVELOPPEUR, "dev-signataires@cartes.test", self.ecole)
        self.client.force_login(self.developpeur)
        self.adresse = reverse("espace_developpeur:signataires_cycle")

    def donnees(self, cycle, nom="", fonction="", **fichiers):
        envoi = {f"{cycle}-nom_signataire": nom, f"{cycle}-fonction_signataire": fonction}
        envoi.update({f"{cycle}-{champ}": fichier for champ, fichier in fichiers.items()})
        return envoi

    def test_la_page_propose_les_cycles_de_la_formule(self):
        page = self.client.get(self.adresse)
        self.assertEqual(page.status_code, 200)
        for attendu in ("Signatures et cachets par cycle", "1er cycle", "2ème cycle", "Nom du signataire", "Fonction du signataire", "Signature", "Cachet", "Enregistrer"):
            self.assertContains(page, attendu)
        autorises = cycles_autorises_pour(self.ecole)
        self.assertEqual({cycle for cycle, _, _ in page.context["formulaires"]}, {c for c, _ in Cycle.choices if c in autorises})

    def test_un_cycle_hors_formule_qui_a_deja_un_signataire_reste_visible(self):
        from etablissement.models import PlanEtablissement

        self.ecole.plan = PlanEtablissement.PREMIER_CYCLE
        self.ecole.save()
        self.assertNotIn(LYCEE, {c for c, _, _ in self.client.get(self.adresse).context["formulaires"]})
        SignataireCycle.objects.create(etablissement=self.ecole, cycle=LYCEE, nom_signataire="Proviseur")
        self.assertIn(LYCEE, {c for c, _, _ in self.client.get(self.adresse).context["formulaires"]})

    def test_enregistrer_le_signataire_la_signature_et_le_cachet_d_un_cycle(self):
        envoi = self.donnees(PREMIER, "  Madame   Premier ", "La Directrice", signature=televerser("sig.png", ROUGE), cachet=televerser("cachet.png", VERT))
        reponse = self.client.post(self.adresse, envoi)
        self.assertRedirects(reponse, self.adresse, fetch_redirect_response=False)
        signataire = SignataireCycle.objects.get(etablissement=self.ecole, cycle=PREMIER)
        self.assertEqual((signataire.nom_signataire, signataire.fonction_signataire), ("Madame Premier", "La Directrice"))  # espaces nettoyés
        self.assertTrue(signataire.signature and signataire.cachet)
        self.assertEqual(SignataireCycle.objects.count(), 1)  # les cycles laissés vides ne créent rien
        journal = JournalAudit.objects.get(action="signataires_cycle", acteur=self.developpeur)
        self.assertEqual(journal.details, {"cycles": [PREMIER]})

    def test_la_page_reprend_ce_qui_est_enregistre(self):
        SignataireCycle.objects.create(etablissement=self.ecole, cycle=PREMIER, nom_signataire="Madame Premier", fonction_signataire="La Directrice")
        page = self.client.get(self.adresse)
        self.assertContains(page, 'value="Madame Premier"')
        self.assertContains(page, 'value="La Directrice"')

    def test_modifier_puis_effacer_la_signature(self):
        self.client.post(self.adresse, self.donnees(PREMIER, "Madame Premier", signature=televerser("sig.png", ROUGE)))
        self.assertTrue(SignataireCycle.objects.get(cycle=PREMIER).signature)
        envoi = self.donnees(PREMIER, "Madame Première")
        self.client.post(self.adresse, envoi)  # sans nouveau fichier : la signature reste
        signataire = SignataireCycle.objects.get(cycle=PREMIER)
        self.assertEqual(signataire.nom_signataire, "Madame Première")
        self.assertTrue(signataire.signature)
        envoi[f"{PREMIER}-signature-clear"] = "on"
        self.client.post(self.adresse, envoi)
        self.assertFalse(SignataireCycle.objects.get(cycle=PREMIER).signature)

    def test_un_cycle_dont_tout_est_vide_est_retire(self):
        SignataireCycle.objects.create(etablissement=self.ecole, cycle=PREMIER, nom_signataire="Madame Premier")
        self.client.post(self.adresse, self.donnees(PREMIER))
        self.assertFalse(SignataireCycle.objects.filter(etablissement=self.ecole).exists())
        self.assertEqual(JournalAudit.objects.get(action="signataires_cycle").details, {"cycles": [PREMIER]})

    def test_un_envoi_sans_changement_ne_change_rien(self):
        SignataireCycle.objects.create(etablissement=self.ecole, cycle=PREMIER, nom_signataire="Madame Premier")
        reponse = self.client.post(self.adresse, self.donnees(PREMIER, "Madame Premier"), follow=True)
        self.assertContains(reponse, "Aucune modification.")
        self.assertFalse(JournalAudit.objects.filter(action="signataires_cycle").exists())

    def test_un_fichier_qui_n_est_pas_une_image_est_refuse_et_rien_n_est_enregistre(self):
        faux = SimpleUploadedFile("sig.png", b"ceci n'est pas une image", content_type="image/png")
        reponse = self.client.post(self.adresse, {**self.donnees(PREMIER, "Madame Premier", signature=faux), **self.donnees(DEUXIEME, "Monsieur Second")})
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(SignataireCycle.objects.exists())  # tout ou rien : le deuxième cycle n'est pas enregistré non plus

    def test_une_image_trop_lourde_est_refusee(self):
        lourde = SimpleUploadedFile("sig.png", png(ROUGE) + b"0" * (2 * 1024 * 1024 + 10), content_type="image/png")
        reponse = self.client.post(self.adresse, self.donnees(PREMIER, "Madame Premier", signature=lourde))
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(SignataireCycle.objects.exists())

    def test_les_signataires_d_une_autre_ecole_ne_sont_ni_vus_ni_touches(self):
        SignataireCycle.objects.create(etablissement=self.ecole_b, cycle=PREMIER, nom_signataire="Directeur de l'autre école")
        self.assertNotContains(self.client.get(self.adresse), "Directeur de l'autre école")
        self.client.post(self.adresse, self.donnees(PREMIER, "Madame Premier"))
        self.client.post(self.adresse, self.donnees(PREMIER))  # vider l'école A ne vide pas l'école B
        self.assertEqual(SignataireCycle.objects.get(etablissement=self.ecole_b).nom_signataire, "Directeur de l'autre école")

    def test_seul_le_developpeur_de_l_ecole_y_acces(self):
        for compte in (self.fondateur, self.secretaire, self.comptable, self.parent):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertIn(self.client.get(self.adresse).status_code, (302, 403))
                self.assertIn(self.client.post(self.adresse, self.donnees(PREMIER, "Intrus")).status_code, (302, 403))
        self.client.logout()
        self.assertEqual(self.client.get(self.adresse).status_code, 302)
        self.assertFalse(SignataireCycle.objects.exists())

    def test_le_lien_est_sur_la_page_identite_de_l_etablissement(self):
        page = self.client.get(reverse("espace_developpeur:parametres_etablissement"))
        self.assertContains(page, self.adresse)
        self.assertContains(page, "Signatures et cachets par cycle")

    def test_la_page_en_arabe_est_en_arabe_pur(self):
        cache.clear()
        invalider(self.ecole.pk)
        SignataireCycle.objects.create(etablissement=self.ecole, cycle=PREMIER, nom_signataire="Madame Premier", fonction_signataire="La Directrice")
        client = client_en(self.developpeur, "ar")
        saisis = {"Français", self.ecole.nom, "Madame Premier", "La Directrice"}
        page = client.get(self.adresse)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(restes_hors_textes_saisis(page.content.decode(), saisis), [])
        faux = SimpleUploadedFile("sig.png", b"pas une image", content_type="image/png")
        erreurs = client.post(self.adresse, self.donnees(PREMIER, "Madame Premier", signature=faux))
        self.assertEqual(restes_hors_textes_saisis(erreurs.content.decode(), saisis), [])
