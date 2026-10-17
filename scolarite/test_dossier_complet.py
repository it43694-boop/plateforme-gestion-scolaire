"""
Dossier élève complet : père, mère, adresse, personne à prévenir, école d'origine, photo (envoi, import ZIP, affichage protégé, anonymisation).

Une photo d'enfant est une donnée sensible : ces tests vérifient surtout qui la voit, ce qui est réellement enregistré (image refaite, sans
métadonnées) et ce qui est effacé à l'anonymisation.
"""
import io
import shutil
import tempfile
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from comptes.arabisation import invalider
from comptes.models import JournalAudit, Utilisateur
from comptes.outils_test_arabe import client_en
from comptes.roles import Role
from comptes.traduction import restes_latins
from espace_developpeur.retrait_eleve import anonymiser_eleve
from scolarite.photos import COTE_MAXIMAL, importer_archive, preparer_photo
from scolarite.test_correction_dossier import donnees_formulaire
from statistiques.test_education import EducationBase, creer_compte


def image_octets(taille=(1200, 800), format="JPEG", couleur=(200, 30, 30), **options):
    image = Image.new("RGB", taille, couleur)
    sortie = io.BytesIO()
    image.save(sortie, format=format, **options)
    return sortie.getvalue()


def fichier_image(nom="photo.jpg", **options):
    return SimpleUploadedFile(nom, image_octets(**options), content_type="image/jpeg")


def archive_zip(fichiers):
    """Un ZIP {nom: octets}."""
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as archive:
        for nom, contenu in fichiers.items():
            archive.writestr(nom, contenu)
    return tampon.getvalue()


class StockageTemporaire(EducationBase):
    """Les fichiers de ces tests s'écrivent dans un dossier jetable, jamais dans media/."""

    @classmethod
    def setUpClass(cls):
        cls._dossier = tempfile.mkdtemp(prefix="photos-test-")
        cls._reglage = override_settings(MEDIA_ROOT=cls._dossier)
        cls._reglage.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._reglage.disable()
        shutil.rmtree(cls._dossier, ignore_errors=True)


class PreparerPhotoTests(StockageTemporaire):
    def ouvrir(self, contenu):
        return Image.open(io.BytesIO(contenu.read()))

    def test_une_grande_photo_est_reduite_et_devient_un_jpeg(self):
        resultat = preparer_photo(image_octets((3000, 2000)))
        image = self.ouvrir(resultat)
        self.assertEqual(image.format, "JPEG")
        self.assertEqual(max(image.size), COTE_MAXIMAL)
        self.assertEqual(image.size, (480, 320))  # les proportions sont gardées

    def test_une_petite_photo_n_est_pas_agrandie(self):
        image = self.ouvrir(preparer_photo(image_octets((200, 100))))
        self.assertEqual(image.size, (200, 100))

    def test_l_orientation_de_l_appareil_est_corrigee(self):
        brut = Image.new("RGB", (400, 200), (10, 120, 10))
        exif = Image.Exif()
        exif[0x0112] = 6  # l'appareil dit : tourner de 90 degrés
        tampon = io.BytesIO()
        brut.save(tampon, format="JPEG", exif=exif)
        image = self.ouvrir(preparer_photo(tampon.getvalue()))
        self.assertEqual(image.size, (200, 400))

    def test_les_metadonnees_d_origine_disparaissent(self):
        exif = Image.Exif()
        exif[0x010F] = "Marque secrète"
        exif[0x0112] = 1
        tampon = io.BytesIO()
        Image.new("RGB", (300, 300), (1, 2, 3)).save(tampon, format="JPEG", exif=exif)
        resultat = preparer_photo(tampon.getvalue()).read()
        self.assertNotIn(b"Marque", resultat)
        self.assertNotIn(b"Exif", resultat)

    def test_une_transparence_devient_du_blanc(self):
        tampon = io.BytesIO()
        Image.new("RGBA", (50, 50), (255, 0, 0, 0)).save(tampon, format="PNG")
        image = self.ouvrir(preparer_photo(tampon.getvalue()))
        self.assertEqual(image.mode, "RGB")
        r, g, b = image.getpixel((25, 25))
        self.assertTrue(r > 240 and g > 240 and b > 240)

    def test_un_faux_fichier_est_refuse_quelle_que_soit_son_extension(self):
        from django.core.exceptions import ValidationError

        for contenu in (b"ceci n'est pas une image", b"<html><script>alert(1)</script></html>", b"%PDF-1.4 faux", b"", b"GIF89a\x01\x00\x01\x00"):
            with self.subTest(contenu=contenu[:12]), self.assertRaises(ValidationError):
                preparer_photo(contenu)

    def test_un_format_non_accepte_est_refuse(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            preparer_photo(image_octets((20, 20), format="BMP"))

    def test_une_image_gigantesque_dans_un_petit_fichier_est_refusee(self):
        from django.core.exceptions import ValidationError

        tampon = io.BytesIO()
        Image.new("L", (7000, 7000), 255).save(tampon, format="PNG")  # 49 millions de pixels, quelques ko
        self.assertLess(len(tampon.getvalue()), 1_000_000)
        with self.assertRaises(ValidationError):
            preparer_photo(tampon.getvalue())

    def test_un_fichier_trop_lourd_est_refuse(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            preparer_photo(b"0" * (10 * 1024 * 1024 + 1))


class DossierEtPhotoTests(StockageTemporaire):
    def setUp(self):
        self.client.force_login(self.secretaire)
        self.url_photo = reverse("scolarite:photo_eleve", args=[self.e1.matricule])
        self.url_envoi = reverse("scolarite:envoyer_photo_eleve", args=[self.e1.matricule])
        self.url_suppression = reverse("scolarite:supprimer_photo_eleve", args=[self.e1.matricule])
        self.url_dossier = reverse("scolarite:dossier_eleve", args=[self.e1.matricule])

    def envoyer(self, eleve=None, **fichier):
        return self.client.post(
            reverse("scolarite:envoyer_photo_eleve", args=[(eleve or self.e1).matricule]), {"photo": fichier.get("fichier") or fichier_image()},
        )

    # --- envoi, affichage, suppression
    def test_le_secretariat_ajoute_une_photo_qui_s_affiche(self):
        self.assertEqual(self.envoyer().status_code, 302)
        self.e1.refresh_from_db()
        self.assertTrue(self.e1.photo)
        reponse = self.client.get(self.url_photo)
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse["Content-Type"], "image/jpeg")
        contenu = b"".join(reponse.streaming_content)
        self.assertEqual(Image.open(io.BytesIO(contenu)).size, (480, 320))
        self.assertIn(self.url_photo, self.client.get(self.url_dossier).content.decode())

    def test_remplacer_la_photo_efface_l_ancien_fichier(self):
        self.envoyer()
        self.e1.refresh_from_db()
        ancien = self.e1.photo.name
        self.envoyer(fichier=fichier_image(taille=(300, 300)))
        self.e1.refresh_from_db()
        self.assertNotEqual(self.e1.photo.name, ancien)
        self.assertFalse(self.e1.photo.storage.exists(ancien))
        self.assertTrue(self.e1.photo.storage.exists(self.e1.photo.name))

    def test_le_nom_du_fichier_stocke_ne_se_devine_pas(self):
        self.envoyer()
        self.e1.refresh_from_db()
        self.assertNotIn(self.e1.nom, self.e1.photo.name)
        self.assertNotIn(self.e1.matricule, self.e1.photo.name)  # le matricule d'un enfant ne figure pas non plus dans l'adresse de stockage
        self.assertRegex(self.e1.photo.name, r"^photos_eleves/\d+/[0-9a-f]{20}/")

    def test_un_faux_fichier_n_est_pas_enregistre(self):
        faux = SimpleUploadedFile("photo.jpg", b"<script>alert(1)</script>", content_type="image/jpeg")
        reponse = self.client.post(self.url_envoi, {"photo": faux}, follow=True)
        self.e1.refresh_from_db()
        self.assertFalse(self.e1.photo)
        self.assertContains(reponse, "illisible")

    def test_envoyer_sans_fichier_ne_casse_rien(self):
        reponse = self.client.post(self.url_envoi, {}, follow=True)
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Choisissez une image")

    def test_la_suppression_efface_le_fichier(self):
        self.envoyer()
        self.e1.refresh_from_db()
        chemin = self.e1.photo.name
        self.assertEqual(self.client.post(self.url_suppression).status_code, 302)
        self.e1.refresh_from_db()
        self.assertFalse(self.e1.photo)
        self.assertFalse(self.e1.photo.storage.exists(chemin))

    def test_envoi_et_suppression_se_font_en_post_seulement(self):
        self.assertEqual(self.client.get(self.url_envoi).status_code, 405)
        self.assertEqual(self.client.get(self.url_suppression).status_code, 405)

    def test_sans_photo_la_page_de_la_photo_est_introuvable(self):
        self.assertEqual(self.client.get(self.url_photo).status_code, 404)

    def test_les_actions_sont_journalisees_sans_le_contenu(self):
        self.envoyer()
        self.client.post(self.url_suppression)
        operations = [j.details.get("operation") for j in JournalAudit.objects.filter(action="photo_eleve")]
        self.assertEqual(sorted(operations), ["envoi", "suppression"])

    # --- qui voit la photo
    def test_qui_voit_la_photo(self):
        self.envoyer()
        autre_parent = creer_compte(Role.PARENT, "autre-parent@photo.test", self.ecole, telephone="70999777")
        attendus = {
            self.secretaire: 200, self.fondateur: 200, self.parent: 200, self.e1: 200,  # l'élève lui-même
            autre_parent: 403, self.e2: 403,  # un autre parent, un camarade
            self.comptable: 403, self.t1: 403,  # sans le module Élèves
        }
        for compte, code in attendus.items():
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertEqual(self.client.get(self.url_photo).status_code, code)

    def test_un_visiteur_non_connecte_est_renvoye_a_la_connexion(self):
        self.envoyer()
        self.client.logout()
        reponse = self.client.get(self.url_photo)
        self.assertEqual(reponse.status_code, 302)
        self.assertIn("connexion", reponse["Location"])

    def test_la_photo_d_une_autre_ecole_est_introuvable(self):
        self.envoyer()
        self.client.force_login(self.fondateur_b)
        self.assertEqual(self.client.get(self.url_photo).status_code, 404)
        self.assertEqual(self.client.post(self.url_envoi, {"photo": fichier_image()}).status_code, 404)

    def test_seul_le_personnel_autorise_modifie_la_photo(self):
        for compte in (self.parent, self.e1, self.t1, self.comptable, self.censeur):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertEqual(self.client.post(self.url_envoi, {"photo": fichier_image()}).status_code, 403)
                self.assertEqual(self.client.post(self.url_suppression).status_code, 403)
        self.e1.refresh_from_db()
        self.assertFalse(self.e1.photo)

    # --- renseignements complémentaires
    def test_les_renseignements_complementaires_ne_sont_pas_montres_a_tous(self):
        Utilisateur.objects.filter(pk=self.e1.pk).update(
            nom_pere="Zqxpere Traore", nom_mere="Zqxmere Diallo", adresse="Zqxquartier Hamdallaye",
            contact_urgence_nom="Zqxoncle", contact_urgence_telephone="76000000", ecole_origine="Zqxecole Fondamentale",
        )
        for compte in (self.secretaire, self.fondateur, self.parent, self.e1):
            self.client.force_login(compte)
            page = self.client.get(self.url_dossier).content.decode()
            with self.subTest(voit=compte.email):
                for valeur in ("Zqxpere", "Zqxmere", "Zqxquartier", "Zqxoncle", "76000000", "Zqxecole"):
                    self.assertIn(valeur, page)
        # Le censeur voit le dossier d'un élève du lycée, mais pas son état civil (filiation, adresse, urgence).
        Utilisateur.objects.filter(pk=self.e7.pk).update(nom_pere="Zqxpere", adresse="Zqxquartier", contact_urgence_telephone="76000000")
        self.client.force_login(self.censeur)
        reponse = self.client.get(reverse("scolarite:dossier_eleve", args=[self.e7.matricule]))
        self.assertEqual(reponse.status_code, 200)
        for valeur in ("Zqxpere", "Zqxquartier", "76000000", "Renseignements complémentaires"):
            self.assertNotIn(valeur, reponse.content.decode())

    def test_correction_du_dossier_avec_les_nouveaux_champs(self):
        reponse = self.client.post(
            reverse("scolarite:corriger_dossier_eleve", args=[self.e1.matricule]),
            donnees_formulaire(
                self.e1, nom_pere="Zqxpere", nom_mere="Zqxmere", adresse="Zqxquartier", contact_urgence_nom="Zqxoncle",
                contact_urgence_telephone="76000000", ecole_origine="Zqxecole",
            ),
        )
        self.assertEqual(reponse.status_code, 302)
        self.e1.refresh_from_db()
        self.assertEqual(
            (self.e1.nom_pere, self.e1.nom_mere, self.e1.adresse, self.e1.contact_urgence_nom, self.e1.contact_urgence_telephone, self.e1.ecole_origine),
            ("Zqxpere", "Zqxmere", "Zqxquartier", "Zqxoncle", "76000000", "Zqxecole"),
        )
        journal = JournalAudit.objects.filter(action="correction_dossier_eleve").latest("pk")
        for champ in ("nom_pere", "adresse", "contact_urgence_telephone", "ecole_origine"):
            self.assertIn(champ, journal.details["champs"])
        self.assertNotIn("Zqx", str(journal.details))  # le journal garde le NOM des champs changés, jamais leurs valeurs

    # --- inscription avec photo
    def donnees_inscription(self, **extra):
        base = {
            "prenom": "Aminata", "nom": "Zqxtraore", "sexe": "F", "classe": self.c6a.id, "parent_email_1": "parent-photo@t.test",
        }
        base.update(extra)
        return base

    def test_l_inscription_accepte_les_nouveaux_champs_et_la_photo(self):
        reponse = self.client.post(reverse("scolarite:inscrire_eleve"), self.donnees_inscription(
            nom_pere="Zqxpere", adresse="Zqxquartier", ecole_origine="Zqxecole", photo=fichier_image(),
        ))
        self.assertEqual(reponse.status_code, 302)
        eleve = Utilisateur.objects.get(nom="Zqxtraore")
        self.assertEqual((eleve.nom_pere, eleve.adresse, eleve.ecole_origine), ("Zqxpere", "Zqxquartier", "Zqxecole"))
        self.assertTrue(eleve.photo)
        self.assertEqual(Image.open(eleve.photo.open("rb")).size, (480, 320))

    def test_l_inscription_sans_photo_reste_possible(self):
        self.assertEqual(self.client.post(reverse("scolarite:inscrire_eleve"), self.donnees_inscription()).status_code, 302)
        self.assertFalse(Utilisateur.objects.get(nom="Zqxtraore").photo)

    def test_une_fausse_photo_empeche_la_creation_de_l_eleve(self):
        faux = SimpleUploadedFile("photo.jpg", b"pas une image", content_type="image/jpeg")
        reponse = self.client.post(reverse("scolarite:inscrire_eleve"), self.donnees_inscription(photo=faux))
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(Utilisateur.objects.filter(nom="Zqxtraore").exists())

    # --- anonymisation
    def test_l_anonymisation_efface_la_photo_et_les_renseignements(self):
        Utilisateur.objects.filter(pk=self.e1.pk).update(
            nom_pere="Zqxpere", nom_mere="Zqxmere", adresse="Zqxquartier", contact_urgence_nom="Zqxoncle",
            contact_urgence_telephone="76000000", ecole_origine="Zqxecole", prenom_ar="سلمى", nom_ar="كيتا",
        )
        self.envoyer()
        self.e1.refresh_from_db()
        chemin, stockage = self.e1.photo.name, self.e1.photo.storage
        self.assertTrue(stockage.exists(chemin))
        anonymiser_eleve(self.e1)
        self.e1.refresh_from_db()
        self.assertFalse(self.e1.photo)
        self.assertFalse(stockage.exists(chemin))
        for champ in ("nom_pere", "nom_mere", "adresse", "contact_urgence_nom", "contact_urgence_telephone", "ecole_origine", "prenom_ar", "nom_ar"):
            self.assertEqual(getattr(self.e1, champ), "", champ)


class ImportDePhotosTests(StockageTemporaire):
    def setUp(self):
        self.client.force_login(self.secretaire)
        self.url = reverse("scolarite:importer_photos_classe", args=[self.c6a.pk])
        # 6A : e1 (Test eleve1), e2, e3 ; des noms réalistes pour tester la reconnaissance par le nom
        Utilisateur.objects.filter(pk=self.e1.pk).update(prenom="Aminata", nom="Traoré")
        Utilisateur.objects.filter(pk=self.e2.pk).update(prenom="Moussa", nom="Konaté")
        Utilisateur.objects.filter(pk=self.e3.pk).update(prenom="Awa", nom="Diarra")
        for eleve in (self.e1, self.e2, self.e3):
            eleve.refresh_from_db()

    def envoyer(self, fichiers, nom="photos.zip"):
        return self.client.post(self.url, {"archive": SimpleUploadedFile(nom, archive_zip(fichiers), content_type="application/zip")})

    def test_les_photos_sont_rattachees_par_matricule_et_par_nom(self):
        photo = image_octets()
        reponse = self.envoyer({
            f"{self.e1.matricule}.jpg": photo,  # par matricule
            "Konaté_Moussa.JPG": photo,  # nom prénom, accents et casse
            "awa diarra.png": image_octets(format="PNG"),  # prénom nom
        })
        self.assertEqual(reponse.status_code, 200)
        for eleve in (self.e1, self.e2, self.e3):
            eleve.refresh_from_db()
            self.assertTrue(eleve.photo, eleve.nom)
        self.assertEqual(len(reponse.context["bilan"].importees), 3)
        self.assertEqual(reponse.context["bilan"].ignorees, [])

    def test_les_fichiers_non_reconnus_sont_expliques(self):
        photo = image_octets()
        reponse = self.envoyer({
            "Inconnu_Personne.jpg": photo,
            f"{self.e1.matricule}.jpg": b"pas une image",
            "notes.txt": b"bonjour",  # ni image ni erreur : passé sans bruit
            "__MACOSX/._x.jpg": b"x", ".cache.jpg": b"x",
            f"dossier/{self.e2.matricule}.jpg": photo,  # un sous-dossier ne gêne pas
        })
        bilan = reponse.context["bilan"]
        self.assertEqual([eleve.pk for eleve, _ in bilan.importees], [self.e2.pk])
        raisons = {nom: raison for nom, raison in bilan.ignorees}
        self.assertIn("Aucun élève", raisons["Inconnu_Personne.jpg"])
        self.assertIn("illisible", raisons[f"{self.e1.matricule}.jpg"])
        self.assertEqual(len(bilan.ignorees), 2)

    def test_deux_eleves_de_meme_nom_ne_sont_jamais_devines(self):
        Utilisateur.objects.filter(pk=self.e3.pk).update(prenom="Aminata", nom="Traoré")
        reponse = self.envoyer({"Aminata Traoré.jpg": image_octets()})
        bilan = reponse.context["bilan"]
        self.assertEqual(bilan.importees, [])
        self.assertIn("Plusieurs élèves", bilan.ignorees[0][1])
        self.e1.refresh_from_db()
        self.e3.refresh_from_db()
        self.assertFalse(self.e1.photo or self.e3.photo)

    def test_un_eleve_d_une_autre_classe_n_est_pas_atteint(self):
        reponse = self.envoyer({f"{self.e4.matricule}.jpg": image_octets()})  # e4 est en 6B
        self.assertEqual(reponse.context["bilan"].importees, [])
        self.e4.refresh_from_db()
        self.assertFalse(self.e4.photo)

    def test_un_eleve_ne_recoit_qu_une_photo_par_archive(self):
        photo = image_octets()
        bilan = self.envoyer({f"{self.e1.matricule}.jpg": photo, "Aminata Traoré.jpg": photo}).context["bilan"]
        self.assertEqual(len(bilan.importees), 1)
        self.assertEqual(len(bilan.ignorees), 1)

    def test_un_fichier_qui_n_est_pas_un_zip_est_refuse(self):
        reponse = self.client.post(self.url, {"archive": SimpleUploadedFile("photos.zip", b"pas un zip", content_type="application/zip")})
        self.assertContains(reponse, "archive ZIP valide")
        autre = self.client.post(self.url, {"archive": SimpleUploadedFile("photos.rar", b"x")})
        self.assertContains(autre, "fichier .zip")

    def test_une_archive_trop_chargee_est_refusee(self):
        from django.core.exceptions import ValidationError

        trop = archive_zip({f"f{i}.jpg": b"x" for i in range(121)})
        with self.assertRaises(ValidationError):
            importer_archive(self.c6a, io.BytesIO(trop))

    def test_une_archive_qui_se_deploie_en_enorme_est_refusee(self):
        from django.core.exceptions import ValidationError

        tampon = io.BytesIO()
        with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("gros.jpg", b"0" * (201 * 1024 * 1024))  # se compresse en quelques ko
        with self.assertRaises(ValidationError):
            importer_archive(self.c6a, io.BytesIO(tampon.getvalue()))
        self.e1.refresh_from_db()
        self.assertFalse(self.e1.photo)

    def test_les_droits(self):
        for compte, code in ((self.t1, 403), (self.parent, 403), (self.comptable, 403), (self.censeur, 403), (self.secretaire, 200), (self.fondateur, 200)):
            self.client.force_login(compte)
            with self.subTest(compte=compte.email):
                self.assertEqual(self.client.get(self.url).status_code, code)
        self.client.force_login(self.fondateur_b)
        self.assertEqual(self.client.get(self.url).status_code, 404)  # la classe d'une autre école est introuvable

    def test_un_directeur_de_cycle_ne_traite_que_son_cycle(self):
        self.client.force_login(self.dir_1er)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.client.get(reverse("scolarite:importer_photos_classe", args=[self.c9a.pk])).status_code, 404)

    def test_l_import_est_journalise(self):
        self.envoyer({f"{self.e1.matricule}.jpg": image_octets(), "Inconnu.jpg": image_octets()})
        journal = JournalAudit.objects.get(action="import_photos_classe")
        self.assertEqual((journal.details["importees"], journal.details["ignorees"]), (1, 1))


class DossierEnArabeTests(StockageTemporaire):
    def test_le_dossier_et_la_page_des_photos_sont_en_arabe_pur(self):
        Utilisateur.objects.filter(pk=self.e1.pk).update(
            prenom="Aminata", nom="Traoré", prenom_ar="أميناتا", nom_ar="تراوري", nom_pere="Bakary Traoré", adresse="حمدالاي",
        )
        invalider(self.ecole.pk)
        client = client_en(self.secretaire, "ar")
        client.post(reverse("scolarite:envoyer_photo_eleve", args=[self.e1.matricule]), {"photo": fichier_image()})
        pages = [
            reverse("scolarite:dossier_eleve", args=[self.e1.matricule]), reverse("scolarite:importer_photos_classe", args=[self.c6a.pk]),
            reverse("scolarite:inscrire_eleve"), reverse("scolarite:corriger_dossier_eleve", args=[self.e1.matricule]),
        ]
        for adresse in pages:
            reponse = client.get(adresse)
            self.assertEqual(reponse.status_code, 200, adresse)
            with self.subTest(page=adresse):
                self.assertEqual([t for t in restes_latins(reponse.content.decode()) if t not in {"Français"}], [])
