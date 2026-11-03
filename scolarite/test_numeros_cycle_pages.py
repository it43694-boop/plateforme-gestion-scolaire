"""
Le numéro du cycle sur les autres pages (reçus, finances, cantine, tenues, anciens élèves, portail du parent) et l'import Excel des numéros.

Jeu de données de EducationBase (voir scolarite.test_numeros_cycle) : e5 est en 9A (2ème cycle) et avait une inscription l'an dernier en 5A
(1er cycle) ; son numéro du 2ème cycle est DEF-0001 et celui du 1er cycle PRIM-0009.
"""
import datetime
import io
import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from openpyxl import Workbook, load_workbook

from cantine.models import FormuleCantine, InscriptionCantine, ModeCantine
from cantine import services as services_cantine
from comptes.outils_test_arabe import CaptureHtmlDuPdf, client_en
from comptes.roles import Role
from finances import tenues
from finances.models import ArticleTenue, TypeTranche, enregistrer_paiement
from scolarite.models import Cycle, Inscription, NumeroCycle
from scolarite.numeros_cycle import numeros_des_eleves
from scolarite.test_numeros_cycle import NumerosBase


class PagesBase(NumerosBase):
    def setUp(self):
        super().setUp()
        NumeroCycle.objects.create(eleve=self.e5, cycle=Cycle.DEUXIEME_CYCLE, numero="DEF-0001")
        NumeroCycle.objects.create(eleve=self.e5, cycle=Cycle.PREMIER_CYCLE, numero="PRIM-0009")
        self.client.force_login(self.fondateur)

    def html_du_pdf(self, adresse):
        with CaptureHtmlDuPdf() as capture:
            reponse = self.client.get(adresse)
        self.assertEqual(reponse.status_code, 200)
        return capture.html


class NumerosDesElevesTests(PagesBase):
    def test_le_numero_de_la_classe_en_cours_d_abord(self):
        self.assertEqual(numeros_des_eleves([self.e5.pk, self.e6.pk, self.e1.pk]), {
            self.e5.pk: "DEF-0001", self.e6.pk: self.e6.matricule, self.e1.pk: self.e1.matricule,
        })

    def test_le_numero_du_cycle_de_l_annee_demandee(self):
        self.assertEqual(numeros_des_eleves([self.e5.pk], annee=self.precedente), {self.e5.pk: "PRIM-0009"})
        self.assertEqual(numeros_des_eleves([self.e5.pk], annee=self.annee), {self.e5.pk: "DEF-0001"})

    def test_un_eleve_sans_inscription_garde_son_matricule(self):
        seul = creer_eleve_sans_classe(self)
        self.assertEqual(numeros_des_eleves([seul.pk]), {seul.pk: seul.matricule})


def creer_eleve_sans_classe(test):
    from statistiques.test_education import creer_compte

    return creer_compte(Role.ELEVE, "sansclasse@stat.test", test.ecole)


class FinancesTests(PagesBase):
    def setUp(self):
        super().setUp()
        self.paiement = enregistrer_paiement(
            eleve=self.e5, inscription=self.i["e5"], tranche=TypeTranche.VERSEMENT, montant=15000, mode_paiement="especes",
            enregistre_par=self.comptable,
        )

    def test_la_liste_des_paiements_et_le_suivi(self):
        for adresse in (reverse("finances:liste_paiements"), reverse("finances:suivi_paiements")):
            with self.subTest(adresse=adresse):
                page = self.client.get(adresse)
                self.assertContains(page, "(DEF-0001)")
                self.assertNotContains(page, f"({self.e5.matricule})")

    def test_le_recu_de_paiement(self):
        html = self.html_du_pdf(reverse("finances:exporter_recu_paiement_pdf", args=[self.paiement.pk]))
        self.assertIn("(DEF-0001)", html)
        self.assertNotIn(self.e5.matricule, html)

    def test_la_recherche_d_un_eleve_pour_un_paiement(self):
        for terme in ("DEF-0001", self.e5.matricule, "Test eleve5"):
            with self.subTest(terme=terme):
                donnees = json.loads(self.client.get(reverse("finances:rechercher_eleve_json"), {"q": terme}).content)["resultats"]
                self.assertEqual([r["matricule"] for r in donnees], [self.e5.matricule])  # la valeur envoyée reste le matricule d'origine
                self.assertTrue(donnees[0]["nom_complet"].endswith("(DEF-0001)"))

    def test_la_page_de_paiement_prerempli(self):
        page = self.client.get(reverse("finances:enregistrer_paiement"), {"eleve": self.e5.matricule, "inscription": self.i["e5"].pk})
        self.assertContains(page, f"{self.e5.nom_complet} (DEF-0001)")
        ancienne = Inscription.objects.get(eleve=self.e5, classe=self.classe_5a)  # l'arriéré de l'an dernier se règle sous le numéro du 1er cycle
        page = self.client.get(reverse("finances:enregistrer_paiement"), {"eleve": self.e5.matricule, "inscription": ancienne.pk})
        self.assertContains(page, f"{self.e5.nom_complet} (PRIM-0009)")

    def test_les_arrieres_se_cherchent_par_le_numero_du_cycle_de_la_classe(self):
        for terme in ("PRIM-0009", "DEF-0001", self.e5.matricule):
            with self.subTest(terme=terme):
                self.assertEqual(self.client.get(reverse("finances:arrieres"), {"q": terme}).status_code, 200)


class TenuesTests(PagesBase):
    def setUp(self):
        super().setUp()
        article = ArticleTenue.objects.create(etablissement=self.ecole, libelle="Polo", taille="12", prix=4500)
        ArticleTenue.objects.filter(pk=article.pk).update(stock=10)
        self.vente = tenues.vendre(
            quantites={article.pk: 1}, etablissement=self.ecole, eleve=self.e5, acheteur="", mode_paiement="especes", acteur=self.comptable,
        )

    def test_la_liste_des_ventes_et_sa_recherche(self):
        page = self.client.get(reverse("finances:tenues_ventes"))
        self.assertContains(page, "(DEF-0001)")
        self.assertNotContains(page, f"({self.e5.matricule})")
        for terme in ("DEF-0001", self.e5.matricule):
            with self.subTest(terme=terme):
                self.assertContains(self.client.get(reverse("finances:tenues_ventes"), {"q": terme}), "(DEF-0001)")
        self.assertNotContains(self.client.get(reverse("finances:tenues_ventes"), {"q": "ZZZ-INCONNU"}), "(DEF-0001)")
        self.assertNotContains(self.client.get(reverse("finances:tenues_ventes"), {"q": "PRIM-0009"}), "(DEF-0001)")  # numéro d'un ancien cycle

    def test_le_recu_de_la_vente(self):
        html = self.html_du_pdf(reverse("finances:tenues_recu_pdf", args=[self.vente.pk]))
        self.assertIn("(DEF-0001)", html)
        self.assertNotIn(self.e5.matricule, html)


class CantineTests(PagesBase):
    def setUp(self):
        super().setUp()
        formule = FormuleCantine.objects.create(etablissement=self.ecole, libelle="Midi", mode=ModeCantine.MENSUEL, montant=5000)
        self.inscription = InscriptionCantine(
            etablissement=self.ecole, eleve=self.e5, annee_scolaire=self.annee, formule=formule,
            date_debut=datetime.date(2026, 10, 15), cree_par=self.fondateur,
        )
        self.inscription.full_clean()
        self.inscription.save()
        self.paiement = services_cantine.enregistrer_paiement(
            inscription=self.inscription, montant=5000, mode_paiement="especes", acteur=self.fondateur,
        )

    def test_l_appel_du_jour(self):
        page = self.client.get(reverse("cantine:appel"), {"date": "2026-11-02"})
        self.assertContains(page, "(DEF-0001)")
        self.assertNotContains(page, f"({self.e5.matricule})")

    def test_le_recu_de_cantine(self):
        html = self.html_du_pdf(reverse("cantine:recu_pdf", args=[self.paiement.pk]))
        self.assertIn("(DEF-0001)", html)
        self.assertNotIn(self.e5.matricule, html)

    def test_la_liste_se_cherche_par_le_numero_sans_changer_les_totaux(self):
        sans_recherche = self.client.get(reverse("cantine:tableau"))
        avec_recherche = self.client.get(reverse("cantine:tableau"), {"q": "DEF-0001"})
        self.assertContains(avec_recherche, self.e5.nom_complet)
        self.assertEqual(avec_recherche.context["total_paye"], sans_recherche.context["total_paye"])
        self.assertEqual(avec_recherche.context["nombre"], 1)
        self.assertEqual(self.client.get(reverse("cantine:tableau"), {"q": "PRIM-0009"}).context["nombre"], 0)  # numéro d'un ancien cycle

    def test_la_liste_des_eleves_a_inscrire(self):
        NumeroCycle.objects.create(eleve=self.e6, cycle=Cycle.DEUXIEME_CYCLE, numero="DEF-0002")
        page = self.client.get(reverse("cantine:inscrire_eleves"), {"classe": self.c9a.pk})
        self.assertContains(page, "(DEF-0002)")
        self.assertNotContains(page, f"({self.e6.matricule})")


class AnciensEtPortailTests(PagesBase):
    def test_les_anciens_eleves_montrent_et_cherchent_le_numero_du_cycle_quitte(self):
        NumeroCycle.objects.create(eleve=self.e6, cycle=Cycle.DEUXIEME_CYCLE, numero="DEF-0002")
        self.i["e6"].statut = Inscription.Statut.TRANSFERE
        self.i["e6"].save(update_fields=["statut"])
        page = self.client.get(reverse("scolarite:anciens_eleves"))
        self.assertContains(page, "(DEF-0002)")
        self.assertNotContains(page, f"({self.e6.matricule})")
        for terme in ("DEF-0002", self.e6.matricule):
            with self.subTest(terme=terme):
                self.assertContains(self.client.get(reverse("scolarite:anciens_eleves"), {"q": terme}), "(DEF-0002)")
        self.assertNotContains(self.client.get(reverse("scolarite:anciens_eleves"), {"q": "PRIM-0009"}), "(DEF-0002)")

    def test_le_portail_du_parent_montre_le_numero_du_cycle_de_son_enfant(self):
        self.e5.parents_lies.add(self.parent)
        self.client.force_login(self.parent)
        page = self.client.get(reverse("comptes:portail_parent"))
        self.assertContains(page, "Matricule : DEF-0001")
        self.assertNotContains(page, "PRIM-0009")  # son numéro d'un autre cycle ne s'affiche pas
        self.assertNotContains(page, f"Matricule : {self.e5.matricule}")


def classeur_en_octets(lignes) -> bytes:
    classeur = Workbook()
    for ligne in lignes:
        classeur.active.append(ligne)
    tampon = io.BytesIO()
    classeur.save(tampon)
    return tampon.getvalue()


class ImportDesNumerosTests(NumerosBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.secretaire)

    def importer(self, lignes, nom="numeros.xlsx", classe=None, client=None):
        fichier = SimpleUploadedFile(nom, classeur_en_octets(lignes) if not isinstance(lignes, bytes) else lignes)
        return (client or self.client).post(self.url(classe), {"action": "importer", "fichier": fichier})

    def test_le_modele_contient_les_eleves_de_la_classe_et_leurs_matricules(self):
        NumeroCycle.objects.create(eleve=self.e5, cycle=Cycle.DEUXIEME_CYCLE, numero="DEF-0001")
        reponse = self.client.get(reverse("scolarite:modele_numeros_cycle", args=[self.c9a.pk]))
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("spreadsheetml", reponse["Content-Type"])
        feuille = load_workbook(io.BytesIO(reponse.content)).active
        lignes = [[cellule.value for cellule in rangee] for rangee in feuille.iter_rows()]
        self.assertIn(["Matricule d'origine", "Prénom", "Nom", "Numéro du cycle"], lignes)
        donnees = {ligne[0]: ligne[3] for ligne in lignes if ligne[0] in (self.e5.matricule, self.e6.matricule)}
        self.assertEqual(donnees, {self.e5.matricule: "DEF-0001", self.e6.matricule: None})
        self.assertNotIn(self.e1.matricule, {ligne[0] for ligne in lignes})  # e1 est en 6A

    def test_le_modele_rempli_pose_les_numeros_dans_les_champs_sans_rien_enregistrer(self):
        modele = self.client.get(reverse("scolarite:modele_numeros_cycle", args=[self.c9a.pk])).content
        classeur = load_workbook(io.BytesIO(modele))
        feuille = classeur.active
        for rangee in feuille.iter_rows():
            if rangee[0].value == self.e5.matricule:
                rangee[3].value = "DEF-0001"
            elif rangee[0].value == self.e6.matricule:
                rangee[3].value = "007"
        tampon = io.BytesIO()
        classeur.save(tampon)
        page = self.importer(tampon.getvalue())
        self.assertContains(page, "Fichier lu : 2 numéro(s)")
        self.assertContains(page, 'value="DEF-0001"')
        self.assertContains(page, 'value="007"')
        self.assertFalse(NumeroCycle.objects.exists())  # rien n'est enregistré avant « Enregistrer les numéros »
        self.poster({self.e5: "DEF-0001", self.e6: "007"})  # la personne vérifie puis enregistre
        self.assertEqual((self.numero(self.e5), self.numero(self.e6)), ("DEF-0001", "007"))

    def test_un_eleve_se_reconnait_par_son_nom_sans_matricule(self):
        page = self.importer([["Prénom", "Nom", "Numéro du cycle"], [self.e5.prenom, self.e5.nom.upper(), "DEF-0001"]])
        self.assertContains(page, 'value="DEF-0001"')

    def test_une_ligne_sans_numero_est_ignoree_et_n_efface_rien(self):
        NumeroCycle.objects.create(eleve=self.e5, cycle=Cycle.DEUXIEME_CYCLE, numero="DEF-0001")
        page = self.importer([
            ["Matricule d'origine", "Numéro du cycle"], [self.e5.matricule, ""], [self.e6.matricule, "DEF-0002"],
        ])
        self.assertContains(page, "Fichier lu : 1 numéro(s)")
        self.assertContains(page, 'value="DEF-0001"')  # e5 garde son numéro dans le champ
        self.assertContains(page, 'value="DEF-0002"')

    def test_un_fichier_sans_aucun_numero(self):
        page = self.importer([["Matricule d'origine", "Numéro du cycle"], [self.e5.matricule, ""]])
        self.assertContains(page, "Aucun numéro à lire")

    def test_un_eleve_introuvable_ou_hors_classe_arrete_la_lecture(self):
        page = self.importer([
            ["Matricule d'origine", "Numéro du cycle"], [self.e5.matricule, "DEF-0001"], [self.e1.matricule, "X-1"], ["INCONNU", "X-2"],
        ])
        self.assertContains(page, "Ligne 3 : élève introuvable dans cette classe")
        self.assertContains(page, "Ligne 4 : élève introuvable dans cette classe")
        self.assertNotContains(page, 'value="DEF-0001"')  # tout ou rien : aucun numéro n'est placé
        self.assertContains(page, "Le fichier n&#x27;a pas été lu en entier")

    def test_un_meme_eleve_deux_fois(self):
        page = self.importer([
            ["Matricule d'origine", "Numéro du cycle"], [self.e5.matricule, "A-1"], [self.e5.matricule, "A-2"],
        ])
        self.assertContains(page, "Ligne 3 : même élève que la ligne 2")

    def test_les_refus_de_la_saisie_valent_aussi_pour_le_fichier(self):
        NumeroCycle.objects.create(eleve=self.e6, cycle=Cycle.DEUXIEME_CYCLE, numero="A-1")
        page = self.importer([["Matricule d'origine", "Numéro du cycle"], [self.e5.matricule, "a-1"]])
        self.assertContains(page, "déjà celui d&#x27;un autre élève")
        self.assertContains(page, "is-invalid")

    def test_les_chiffres_arabes_donnent_le_meme_numero(self):
        self.importer([["Matricule d'origine", "Numéro du cycle"], [self.e5.matricule, "٢٠٢٦-٧"]])
        self.poster({self.e5: "٢٠٢٦-٧"})
        self.assertEqual(self.numero(self.e5), "2026-7")

    def test_un_fichier_inutilisable(self):
        for contenu, nom, attendu in (
            (b"pas un classeur", "numeros.xlsx", "n&#x27;est pas un classeur Excel"),
            (b"a;b", "numeros.csv", "doit être un classeur Excel"),
            (classeur_en_octets([["Matricule d'origine", "Prénom"], [self.e5.matricule, "Awa"]]), "numeros.xlsx", "Colonne « Numéro du cycle » introuvable"),
            (classeur_en_octets([["Prénom", "Numéro du cycle"], ["Awa", "A-1"]]), "numeros.xlsx", "Colonne « Matricule d&#x27;origine » introuvable"),
        ):
            with self.subTest(nom=nom, attendu=attendu):
                self.assertContains(self.importer(contenu, nom=nom), attendu)
        self.assertFalse(NumeroCycle.objects.exists())

    def test_sans_fichier(self):
        reponse = self.client.post(self.url(), {"action": "importer"})
        self.assertContains(reponse, "Choisissez d&#x27;abord le fichier Excel")

    def test_les_droits_sont_ceux_de_la_saisie(self):
        for compte in (self.comptable, self.censeur, self.t2, self.parent, self.e5):
            self.accorder_les_modules(compte)
            client = self.client_de(compte)
            with self.subTest(role=compte.role):
                self.assertEqual(client.get(reverse("scolarite:modele_numeros_cycle", args=[self.c9a.pk])).status_code, 403)
                self.assertEqual(self.importer([["Matricule d'origine", "Numéro du cycle"], [self.e5.matricule, "X-1"]], client=client).status_code, 403)
        self.client.force_login(self.dir_1er)
        self.assertEqual(self.client.get(reverse("scolarite:modele_numeros_cycle", args=[self.c9a.pk])).status_code, 404)
        self.assertEqual(self.importer([["Matricule d'origine", "Numéro du cycle"], [self.e5.matricule, "X-1"]]).status_code, 404)
        self.client.force_login(self.fondateur_b)
        self.assertEqual(self.client.get(reverse("scolarite:modele_numeros_cycle", args=[self.c9a.pk])).status_code, 404)

    def client_de(self, compte):
        from django.test import Client

        client = Client()
        client.force_login(compte)
        return client

    def test_la_page_et_le_modele_sont_en_arabe_pur(self):
        from comptes.outils_test_arabe import restes_hors_textes_saisis

        client = client_en(self.secretaire, "ar")
        saisis = {self.e5.matricule, self.e6.matricule, "9A", self.ecole.nom, "2026-2027", "Français"}
        page = client.get(self.url())
        self.assertEqual(restes_hors_textes_saisis(page.content.decode(), saisis), [])
        lu = self.importer([["Matricule d'origine", "Numéro du cycle"], ["INCONNU", "X-1"]], client=client)
        self.assertEqual(restes_hors_textes_saisis(lu.content.decode(), saisis | {"INCONNU"}), [])
        modele = client.get(reverse("scolarite:modele_numeros_cycle", args=[self.c9a.pk]))
        feuille = load_workbook(io.BytesIO(modele.content)).active
        textes = [cellule.value for rangee in feuille.iter_rows() for cellule in rangee if isinstance(cellule.value, str)]
        self.assertIn("رقم التسجيل الأصلي", textes)
        self.assertIn("رقم التسجيل في المرحلة", textes)
        # le fichier en arabe se relit : ses titres arabes sont reconnus, l'élève se retrouve par son matricule d'origine
        rempli = load_workbook(io.BytesIO(modele.content))
        for rangee in rempli.active.iter_rows():
            if any(cellule.value in (self.e5.matricule, self.e5.matricule.translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))) for cellule in rangee):
                rangee[3].value = "DEF-0001"
        tampon = io.BytesIO()
        rempli.save(tampon)
        relu = self.importer(tampon.getvalue(), client=client)
        self.assertContains(relu, "DEF-0001")


class SaisieParLeNumeroTests(PagesBase):
    """Un enseignant qui note ou marque absent un élève peut taper le numéro du cycle de la classe, celui des listes qu'il a sous les yeux."""

    def formulaire(self, saisie):
        from pedagogie.forms import SaisirNoteForm
        from pedagogie.models import Trimestre
        from scolarite.models import Affectation

        affectation = Affectation.objects.get(enseignant=self.t2, classe=self.c9a)
        return SaisirNoteForm({"matricule_eleve": saisie, "trimestre": Trimestre.T1.value, "note_classe": "12"}, affectation=affectation)

    def test_le_numero_du_cycle_de_la_classe_designe_l_eleve(self):
        formulaire = self.formulaire("DEF-0001")
        self.assertTrue(formulaire.is_valid(), formulaire.errors)
        self.assertEqual(formulaire.cleaned_data["matricule_eleve"], self.e5.matricule)  # c'est toujours le matricule d'origine qui est gardé

    def test_le_matricule_d_origine_et_le_nom_marchent_toujours(self):
        for saisie in (self.e5.matricule, "Test eleve5"):
            with self.subTest(saisie=saisie):
                formulaire = self.formulaire(saisie)
                self.assertTrue(formulaire.is_valid(), formulaire.errors)
                self.assertEqual(formulaire.cleaned_data["matricule_eleve"], self.e5.matricule)

    def test_le_numero_d_un_autre_cycle_ne_designe_personne(self):
        formulaire = self.formulaire("PRIM-0009")  # numéro du 1er cycle : la classe est du 2ème
        self.assertFalse(formulaire.is_valid())
        self.assertIn("matricule_eleve", formulaire.errors)

    def test_les_propositions_pour_les_homonymes_montrent_le_numero_du_cycle(self):
        from scolarite.recherche import options_de_saisie

        class Eleve:
            def __init__(self, prenom, matricule, numero):
                self.nom, self.prenom, self.matricule, self.numero_cycle = "Keita", prenom, matricule, numero

        propositions = options_de_saisie([Eleve("Awa", "2026111", "DEF-0001"), Eleve("Awa", "2026222", "DEF-0002")])
        self.assertEqual(propositions, ["Keita Awa (DEF-0001)", "Keita Awa (DEF-0002)"])


class PhotosParNumeroTests(PagesBase):
    def test_une_photo_peut_porter_le_numero_du_cycle_de_la_classe(self):
        from scolarite.test_dossier_complet import archive_zip, image_octets

        self.client.force_login(self.secretaire)
        photo = image_octets()
        reponse = self.client.post(reverse("scolarite:importer_photos_classe", args=[self.c9a.pk]), {
            "archive": SimpleUploadedFile("photos.zip", archive_zip({"DEF-0001.jpg": photo, f"{self.e6.matricule}.jpg": photo}), content_type="application/zip"),
        })
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual({eleve.pk for eleve, _ in reponse.context["bilan"].importees}, {self.e5.pk, self.e6.pk})
        self.assertEqual(reponse.context["bilan"].ignorees, [])

    def test_le_numero_d_un_autre_cycle_ne_designe_personne(self):
        from scolarite.test_dossier_complet import archive_zip, image_octets

        self.client.force_login(self.secretaire)
        reponse = self.client.post(reverse("scolarite:importer_photos_classe", args=[self.c9a.pk]), {
            "archive": SimpleUploadedFile("photos.zip", archive_zip({"PRIM-0009.jpg": image_octets()}), content_type="application/zip"),
        })
        self.assertEqual(reponse.context["bilan"].importees, [])
        self.assertEqual(len(reponse.context["bilan"].ignorees), 1)


class ExportsDeLaClasseTests(PagesBase):
    """Les exports Excel des notes et des absences portent le numéro du cycle de la classe, pas le matricule d'origine (identifiant de connexion)."""

    def cellules(self, reponse):
        classeur = load_workbook(io.BytesIO(reponse.content))
        return {str(cellule.value) for feuille in classeur.worksheets for rangee in feuille.iter_rows() for cellule in rangee if cellule.value is not None}

    def test_le_releve_de_notes(self):
        from pedagogie.models import Trimestre, saisir_note
        from scolarite.models import Affectation

        affectation = Affectation.objects.get(enseignant=self.t2, classe=self.c9a)
        saisir_note(eleve=self.e5, affectation=affectation, trimestre=Trimestre.T1, note_classe=14, enseignant=self.t2)
        reponse = self.client.get(reverse("pedagogie:exporter_releve_notes_xlsx", args=[self.c9a.pk]))
        cellules = self.cellules(reponse)
        self.assertIn("DEF-0001", cellules)
        self.assertNotIn(self.e5.matricule, cellules)

    def test_les_absences(self):
        reponse = self.client.get(reverse("pedagogie:exporter_absences_xlsx", args=[self.c9a.pk]))
        cellules = self.cellules(reponse)
        self.assertIn("DEF-0001", cellules)
        self.assertIn(self.e6.matricule, cellules)  # sans numéro propre : le matricule reprend sa place
        self.assertNotIn(self.e5.matricule, cellules)
