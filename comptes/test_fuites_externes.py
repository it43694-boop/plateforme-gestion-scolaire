"""
Ce que ce dépôt PUBLIC et la configuration de production ne doivent jamais exposer : identifiants de projet,
mots de passe par défaut, médias lisibles par quiconque.
"""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

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
            custom_domain=None, querystring_auth=True, querystring_expire=3600,
        )
        lien = stockage.url("transferts/12/0123456789abcdef0123/justificatif.pdf")
        self.assertIn("X-Amz-Signature=", lien)
        self.assertIn("X-Amz-Algorithm=AWS4-HMAC-SHA256", lien)
        self.assertIn("X-Amz-Expires=3600", lien)
        self.assertNotIn("/object/public/", lien)
        self.assertNotIn("secret-fictif", lien)
        # Sans signature (chemin brut) le même fichier n'est pas lisible : la signature fait partie du lien.
        self.assertGreater(len(lien.split("?", 1)[1]), 100)


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
