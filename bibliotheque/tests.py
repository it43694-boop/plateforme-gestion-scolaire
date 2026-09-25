import io
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
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
