"""
Ce que ce dépôt PUBLIC et la configuration de production ne doivent jamais exposer : identifiants de projet,
mots de passe par défaut, médias lisibles par quiconque.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from config.stockage import signer_les_liens

RACINE = Path(settings.BASE_DIR)


def lignes_actives(chemin):
    """Lignes d'un fichier de configuration, commentaires exclus."""
    return [ligne for ligne in (RACINE / chemin).read_text(encoding="utf-8").splitlines() if not ligne.lstrip().startswith("#")]


class MediasEnLiensSignesTests(SimpleTestCase):
    def test_aucun_identifiant_de_projet_ni_domaine_de_stockage_dans_les_reglages(self):
        for ligne in lignes_actives("config/settings.py"):
            self.assertNotIn("supabase.co", ligne)
            self.assertNotIn("/object/public/", ligne)

    def test_le_domaine_public_n_est_utilise_que_s_il_est_demande_explicitement(self):
        source = (RACINE / "config" / "settings.py").read_text(encoding="utf-8")
        self.assertIn('env("AWS_S3_CUSTOM_DOMAIN", default="")', source)
        self.assertIn('"signature_version": "s3v4"', source)
        self.assertIn('"file_overwrite": False', source)

    def test_exemple_d_environnement_laisse_le_domaine_public_vide(self):
        lignes = [ligne.strip() for ligne in lignes_actives(".env.example")]
        self.assertIn("AWS_S3_CUSTOM_DOMAIN=", lignes)

    def test_un_fichier_est_servi_par_un_lien_signe_temporaire_vers_le_stockage_prive(self):
        """Même configuration que la production, avec de fausses clés : aucun accès réseau (la signature est locale)."""
        from storages.backends.s3 import S3Storage

        stockage = S3Storage(
            bucket_name="medias", endpoint_url="https://projet-fictif.example/storage/v1/s3", region_name="eu-west-3",
            access_key="AKIAFAUXFAUXFAUXFAUX", secret_key="secret-fictif-ne-doit-jamais-apparaitre",
            default_acl=None, file_overwrite=False, addressing_style="path", signature_version="s3v4",
            custom_domain=None, querystring_auth=signer_les_liens(None, False), querystring_expire=3600,
        )
        lien = stockage.url("transferts/12/0123456789abcdef0123/justificatif.pdf")
        self.assertIn("X-Amz-Signature=", lien)
        self.assertIn("X-Amz-Algorithm=AWS4-HMAC-SHA256", lien)
        self.assertIn("X-Amz-Expires=3600", lien)
        self.assertNotIn("/object/public/", lien)
        self.assertNotIn("secret-fictif", lien)
        # Sans signature (chemin brut) le même fichier n'est pas lisible : la signature fait partie du lien.
        self.assertGreater(len(lien.split("?", 1)[1]), 100)


class LiensSignesToujoursSansDomainePublicTests(SimpleTestCase):
    """
    Régression : avec AWS_QUERYSTRING_AUTH=False sur Render et sans domaine public, l'adresse du logo pointait vers
    l'API S3 SANS signature : le stockage répondait « AccessDenied - Missing signature » et le logo s'affichait cassé.
    """

    def test_regle(self):
        self.assertTrue(signer_les_liens(None, True))
        self.assertTrue(signer_les_liens(None, False))  # le cas qui cassait les logos
        self.assertTrue(signer_les_liens("", False))
        self.assertFalse(signer_les_liens("public.exemple/medias", False))  # bucket public : la signature est inutile
        self.assertTrue(signer_les_liens("public.exemple/medias", True))

    def reglages_de_production(self, signature, domaine_public=None):
        """Charge la VRAIE configuration de production (processus séparé, variables fictives) et rend les options S3."""
        environnement = {
            **os.environ, "DEBUG": "False", "DJANGO_SECRET_KEY": "x" * 60, "ALLOWED_HOSTS": "exemple.test",
            "DATABASE_URL": "postgres://u:p@localhost:5432/d", "REDIS_URL": "redis://localhost:6379/0",
            "EMAIL_HOST": "smtp.fictif.test", "EMAIL_HOST_USER": "u", "EMAIL_HOST_PASSWORD": "p",
            "SECURE_SSL_REDIRECT": "False", "AWS_STORAGE_BUCKET_NAME": "medias",
            "AWS_S3_ENDPOINT_URL": "https://projet-fictif.example/storage/v1/s3", "AWS_S3_REGION_NAME": "eu-west-3",
            "AWS_ACCESS_KEY_ID": "AKIAFAUX", "AWS_SECRET_ACCESS_KEY": "fictif", "AWS_QUERYSTRING_AUTH": signature,
        }
        environnement.pop("AWS_S3_CUSTOM_DOMAIN", None)
        if domaine_public:
            environnement["AWS_S3_CUSTOM_DOMAIN"] = domaine_public
        resultat = subprocess.run(
            [sys.executable, "-c", "import json, config.settings as s; print(json.dumps(s.STORAGES['default']['OPTIONS']))"],
            cwd=RACINE, env=environnement, capture_output=True, text=True, timeout=120, check=False,
        )
        self.assertEqual(resultat.returncode, 0, resultat.stderr[-800:])
        return json.loads(resultat.stdout.strip().splitlines()[-1])

    def test_la_production_signe_les_liens_meme_si_la_variable_est_a_false(self):
        for valeur in ("False", "false", "0", "True"):
            with self.subTest(AWS_QUERYSTRING_AUTH=valeur):
                options = self.reglages_de_production(valeur)
                self.assertTrue(options["querystring_auth"])
                self.assertIsNone(options["custom_domain"])

    def test_le_domaine_public_reste_possible_si_on_le_demande_explicitement(self):
        options = self.reglages_de_production("False", domaine_public="public.exemple/medias")
        self.assertEqual(options["custom_domain"], "public.exemple/medias")
        self.assertFalse(options["querystring_auth"])


class ComposeSansMotDePasseParDefautTests(SimpleTestCase):
    def test_aucun_mot_de_passe_de_base_de_donnees_ecrit_dans_le_fichier(self):
        source = (RACINE / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertNotIn("plateforme:plateforme@", source)
        self.assertNotIn("POSTGRES_PASSWORD: plateforme", source)
        self.assertEqual(source.count("${POSTGRES_PASSWORD:?"), 2)  # la base ET l'adresse de connexion l'exigent

    def test_le_compose_ne_publie_ni_la_base_ni_redis(self):
        source = (RACINE / "docker-compose.yml").read_text(encoding="utf-8")
        for service in ("db:", "redis:"):
            bloc = source.split(f"\n  {service}")[1].split("\n  ")[0]
            self.assertNotIn("ports:", bloc)


class DepotPublicSansDonneesTests(SimpleTestCase):
    """Le dépôt GitHub est public : aucun fichier de données, de clés ou de sauvegarde ne doit y être suivi."""

    def test_fichiers_ignores_par_git(self):
        regles = (RACINE / ".gitignore").read_text(encoding="utf-8")
        for motif in (".env", "*.sqlite3", "media/"):
            self.assertIn(motif, regles)

    def test_aucun_fichier_sensible_dans_l_arborescence_suivie(self):
        import subprocess
        suivis = subprocess.run(
            ["git", "ls-files"], cwd=RACINE, capture_output=True, text=True, check=False,
        ).stdout.splitlines()
        if not suivis:
            self.skipTest("dépôt Git indisponible")
        interdits = [
            f for f in suivis
            if f.endswith((".sqlite3", ".pem", ".key", ".p12")) or f in {".env"} or f.startswith("media/") or "sauvegarde_" in f
        ]
        self.assertEqual(interdits, [])
