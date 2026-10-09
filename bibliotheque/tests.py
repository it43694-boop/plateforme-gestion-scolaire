import io
import tempfile
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from comptes.models import Utilisateur
from comptes.roles import Role, StatutCompte
from bibliotheque.models import Document


def creer_utilisateur_actif(email, role, **kwargs):
    utilisateur = Utilisateur(email=email, prenom="Test", nom="Utilisateur", role=role, **kwargs)
    utilisateur.set_password("MotDePasse#2026")
    utilisateur.statut = StatutCompte.ACTIF
    utilisateur.is_active = True
    utilisateur.full_clean(exclude=["password"])
    utilisateur.save()
    return utilisateur


def creer_zip_en_memoire(fichiers: dict) -> bytes:
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as zip_fichier:
        for nom, contenu in fichiers.items():
            zip_fichier.writestr(nom, contenu)
    return tampon.getvalue()


class BibliothequeTests(TestCase):
    def setUp(self):
        self.bibliothecaire = creer_utilisateur_actif("biblio@example.com", Role.BIBLIOTHECAIRE)

    def test_ajout_unitaire(self):
        self.client.force_login(self.bibliothecaire)
        fichier = SimpleUploadedFile("cours.pdf", b"contenu pdf factice")
        reponse = self.client.post(reverse("bibliotheque:ajouter_document"), {
            "titre": "Cours de mathématiques", "description": "Chapitre 1", "fichier": fichier,
        })
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(Document.objects.count(), 1)
        self.assertEqual(Document.objects.first().titre, "Cours de mathématiques")

    def test_fichier_executable_refuse(self):
        self.client.force_login(self.bibliothecaire)
        fichier = SimpleUploadedFile("virus.exe", b"MZ...contenu binaire factice")
        self.client.post(reverse("bibliotheque:ajouter_document"), {
            "titre": "Document suspect", "description": "", "fichier": fichier,
        })
        self.assertEqual(Document.objects.count(), 0)

    def test_import_zip_cree_un_document_par_fichier(self):
        self.client.force_login(self.bibliothecaire)
        contenu_zip = creer_zip_en_memoire({
            "livre1.pdf": b"contenu 1", "livre2.pdf": b"contenu 2", "dossier/": b"",
        })
        archive = SimpleUploadedFile("archive.zip", contenu_zip, content_type="application/zip")
        reponse = self.client.post(reverse("bibliotheque:importer_zip"), {"archive": archive})
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(Document.objects.count(), 2)

    def test_import_refuse_fichier_non_zip(self):
        self.client.force_login(self.bibliothecaire)
        fichier = SimpleUploadedFile("pasunzip.txt", b"contenu")
        reponse = self.client.post(reverse("bibliotheque:importer_zip"), {"archive": fichier}, follow=True)
        self.assertEqual(Document.objects.count(), 0)

    def test_export_zip_contient_tous_les_documents(self):
        self.client.force_login(self.bibliothecaire)
        Document.objects.create(titre="A", fichier=SimpleUploadedFile("a.pdf", b"AAA"), ajoute_par=self.bibliothecaire)
        Document.objects.create(titre="B", fichier=SimpleUploadedFile("b.pdf", b"BBB"), ajoute_par=self.bibliothecaire)
        reponse = self.client.get(reverse("bibliotheque:exporter_zip"))
        self.assertEqual(reponse["Content-Type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(reponse.content)) as zip_fichier:
            self.assertEqual(len(zip_fichier.namelist()), 2)

    def test_enseignant_sans_acces_bibliotheque_par_defaut_est_bloque(self):
        enseignant = creer_utilisateur_actif("prof-bib@example.com", Role.ENSEIGNANT)
        # L'enseignant A ACCÈS par défaut (voir matrice) : on vérifie ici le rôle SANS accès.
        secretaire = creer_utilisateur_actif("sec-bib@example.com", Role.SECRETAIRE)
        self.client.force_login(secretaire)
        reponse = self.client.get(reverse("bibliotheque:liste_documents"))
        self.assertEqual(reponse.status_code, 403)


class GestionBibliothequeRoleTests(TestCase):
    """
    Correctif de sécurité : un enseignant ou un élève a accès au module
    Bibliothèque pour CONSULTER le catalogue, pas pour y déposer des
    documents au nom de l'établissement - réservé au personnel qui la
    gère (bibliothécaire, direction).
    """

    def setUp(self):
        self.enseignant = creer_utilisateur_actif("prof-gestion-bib@example.com", Role.ENSEIGNANT)
        self.eleve = creer_utilisateur_actif("eleve-gestion-bib@example.com", Role.ELEVE)
        self.directeur = creer_utilisateur_actif("dir-gestion-bib@example.com", Role.DIRECTEUR_LYCEE)

    def test_enseignant_ne_peut_pas_ajouter_un_document(self):
        self.client.force_login(self.enseignant)
        fichier = SimpleUploadedFile("cours.pdf", b"contenu pdf factice")
        reponse = self.client.post(reverse("bibliotheque:ajouter_document"), {
            "titre": "Cours ajouté par un enseignant", "description": "", "fichier": fichier,
        })
        self.assertEqual(reponse.status_code, 403)
        self.assertEqual(Document.objects.count(), 0)

    def test_eleve_ne_peut_pas_ajouter_un_document(self):
        self.client.force_login(self.eleve)
        fichier = SimpleUploadedFile("cours.pdf", b"contenu pdf factice")
        reponse = self.client.post(reverse("bibliotheque:ajouter_document"), {
            "titre": "Cours ajouté par un élève", "description": "", "fichier": fichier,
        })
        self.assertEqual(reponse.status_code, 403)
        self.assertEqual(Document.objects.count(), 0)

    def test_eleve_ne_peut_pas_importer_une_archive(self):
        self.client.force_login(self.eleve)
        contenu_zip = creer_zip_en_memoire({"livre1.pdf": b"contenu 1"})
        archive = SimpleUploadedFile("archive.zip", contenu_zip, content_type="application/zip")
        reponse = self.client.post(reverse("bibliotheque:importer_zip"), {"archive": archive})
        self.assertEqual(reponse.status_code, 403)
        self.assertEqual(Document.objects.count(), 0)

    def test_eleve_peut_toujours_consulter_le_catalogue(self):
        self.client.force_login(self.eleve)
        reponse = self.client.get(reverse("bibliotheque:liste_documents"))
        self.assertEqual(reponse.status_code, 200)
        self.assertIsNone(reponse.context["formulaire_ajout"])
        self.assertFalse(reponse.context["peut_gerer"])

    def test_directeur_peut_ajouter_un_document(self):
        self.client.force_login(self.directeur)
        fichier = SimpleUploadedFile("cours.pdf", b"contenu pdf factice")
        reponse = self.client.post(reverse("bibliotheque:ajouter_document"), {
            "titre": "Cours ajouté par la direction", "description": "", "fichier": fichier,
        })
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(Document.objects.count(), 1)


class IsolationBibliothequeTests(TestCase):
    def test_bibliothecaire_ne_voit_que_les_documents_de_son_ecole(self):
        from etablissement.models import Etablissement
        from permissions_matrix.models import PermissionMatrix
        ecole_a = Etablissement.objects.create(nom="École Biblio A")
        ecole_b = Etablissement.objects.create(nom="École Biblio B")
        PermissionMatrix.seed_pour(ecole_a)
        PermissionMatrix.seed_pour(ecole_b)
        biblio_a = creer_utilisateur_actif("biblio-a@example.com", Role.BIBLIOTHECAIRE, etablissement=ecole_a)
        biblio_b = creer_utilisateur_actif("biblio-b@example.com", Role.BIBLIOTHECAIRE, etablissement=ecole_b)

        Document.objects.create(titre="Doc École A", fichier=SimpleUploadedFile("a.pdf", b"AAA"), ajoute_par=biblio_a, etablissement=ecole_a)
        Document.objects.create(titre="Doc École B", fichier=SimpleUploadedFile("b.pdf", b"BBB"), ajoute_par=biblio_b, etablissement=ecole_b)

        self.client.force_login(biblio_a)
        reponse = self.client.get(reverse("bibliotheque:liste_documents"))
        titres = [d.titre for d in reponse.context["documents"]]
        self.assertIn("Doc École A", titres)
        self.assertNotIn("Doc École B", titres)

    def test_export_zip_ne_contient_pas_les_documents_dune_autre_ecole(self):
        from etablissement.models import Etablissement
        from permissions_matrix.models import PermissionMatrix
        ecole_a = Etablissement.objects.create(nom="École Export A")
        ecole_b = Etablissement.objects.create(nom="École Export B")
        PermissionMatrix.seed_pour(ecole_a)
        PermissionMatrix.seed_pour(ecole_b)
        biblio_a = creer_utilisateur_actif("export-a@example.com", Role.BIBLIOTHECAIRE, etablissement=ecole_a)
        biblio_b = creer_utilisateur_actif("export-b@example.com", Role.BIBLIOTHECAIRE, etablissement=ecole_b)

        Document.objects.create(titre="A", fichier=SimpleUploadedFile("a.pdf", b"AAA"), ajoute_par=biblio_a, etablissement=ecole_a)
        Document.objects.create(titre="B", fichier=SimpleUploadedFile("b.pdf", b"BBB"), ajoute_par=biblio_b, etablissement=ecole_b)

        self.client.force_login(biblio_a)
        reponse = self.client.get(reverse("bibliotheque:exporter_zip"))
        with zipfile.ZipFile(io.BytesIO(reponse.content)) as zip_fichier:
            self.assertEqual(len(zip_fichier.namelist()), 1)
            self.assertTrue(zip_fichier.namelist()[0].startswith("a"))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CheminsDeFichiersTests(TestCase):
    """
    Les fichiers téléversés sont servis par une adresse publique non signée et le
    stockage S3 écrase un fichier de même nom : le chemin doit donc contenir un
    jeton aléatoire (adresse non devinable) et l'école (pas d'écrasement entre écoles).
    """

    def test_chemin_unique_contient_ecole_jeton_et_nom_dorigine(self):
        from comptes.uploads import chemin_upload_unique
        chemin = chemin_upload_unique("bibliotheque", 7, "reglement.pdf")
        self.assertRegex(chemin, r"^bibliotheque/7/[0-9a-f]{20}/reglement\.pdf$")

    def test_deux_envois_du_meme_nom_donnent_deux_chemins_differents(self):
        from comptes.uploads import chemin_upload_unique
        self.assertNotEqual(
            chemin_upload_unique("bibliotheque", 1, "reglement.pdf"), chemin_upload_unique("bibliotheque", 1, "reglement.pdf"),
        )

    def test_nom_tres_long_tronque_sans_perdre_lextension_ni_depasser_la_limite(self):
        from comptes.uploads import LONGUEUR_MAX_CHEMIN, chemin_upload_unique
        chemin = chemin_upload_unique("annonces", 12345, "a" * 300 + ".pdf")
        self.assertLessEqual(len(chemin), LONGUEUR_MAX_CHEMIN)
        self.assertTrue(chemin.endswith(".pdf"))

    def test_nom_avec_dossiers_neutralise(self):
        from comptes.uploads import chemin_upload_unique
        self.assertNotIn("..", chemin_upload_unique("bibliotheque", 1, "../../secret.pdf"))

    def test_deux_ecoles_envoyant_le_meme_nom_gardent_chacune_leur_fichier(self):
        from django.core.files.base import ContentFile
        from etablissement.models import Etablissement
        ecole_a, ecole_b = Etablissement.objects.create(nom="École A fichiers"), Etablissement.objects.create(nom="École B fichiers")
        doc_a = Document.objects.create(titre="A", etablissement=ecole_a, fichier=ContentFile(b"contenu A", name="reglement.pdf"))
        doc_b = Document.objects.create(titre="B", etablissement=ecole_b, fichier=ContentFile(b"contenu B", name="reglement.pdf"))
        self.assertNotEqual(doc_a.fichier.name, doc_b.fichier.name)
        self.assertIn(f"/{ecole_a.id}/", doc_a.fichier.name)
        self.assertEqual(doc_a.nom_fichier, "reglement.pdf")  # le nom d'origine reste affiché
        doc_a.fichier.open("rb")
        self.assertEqual(doc_a.fichier.read(), b"contenu A")
        doc_a.fichier.close()
