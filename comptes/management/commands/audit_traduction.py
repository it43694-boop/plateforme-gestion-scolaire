"""
Liste les textes restés en français sur des pages, pour compléter le catalogue arabe (comptes/traductions/ar.csv).

    python manage.py audit_traduction --email compte@ecole.ml /comptes/tableau-de-bord/ /scolarite/eleves/
    python manage.py audit_traduction --email compte@ecole.ml --a-traduire a_traduire.csv /scolarite/eleves/

Les pages sont ouvertes comme le compte donné les verrait (en français : c'est le texte d'origine qu'on cherche). Avec
`--a-traduire`, les textes sans traduction sont écrits dans un fichier CSV (colonnes francais, arabe, note) prêt à être rempli.
Sans `--email`, les pages sont ouvertes sans être connecté (connexion, accueil...).
"""
import csv

from django.core.management.base import BaseCommand, CommandError
from django.test import Client, override_settings

from comptes.models import Utilisateur
from comptes.traduction import catalogue_pour, chaines_non_traduites


class Command(BaseCommand):
    help = "Liste les textes sans traduction arabe sur des pages."

    def add_arguments(self, parser):
        parser.add_argument("adresses", nargs="*", help="Adresses des pages (ex. /scolarite/eleves/).")
        parser.add_argument("--email", help="Compte avec lequel ouvrir les pages (sinon : visiteur).")
        parser.add_argument("--langue", default="ar", help="Langue du catalogue (ar).")
        parser.add_argument("--a-traduire", dest="fichier", help="Écrit les textes sans traduction dans ce fichier CSV.")

    def handle(self, *args, **options):
        catalogue = catalogue_pour(options["langue"])
        client = Client(HTTP_HOST="localhost")
        client.cookies["nexora_langue"] = "fr"  # le texte d'origine, quelle que soit la langue du compte
        if options["email"]:
            try:
                client.force_login(Utilisateur.objects.get(email=options["email"]))
            except Utilisateur.DoesNotExist:
                raise CommandError("Aucun compte avec cet email.")
        manquants = {}
        # Outil de développement : comme dans les tests, la double authentification ne barre pas la route (le compte est déjà
        # « connecté de force »), sans quoi chaque page renverrait vers la saisie du code.
        with override_settings(TESTING=True):
            for adresse in options["adresses"]:
                reponse = client.get(adresse, follow=True)
                if reponse.status_code != 200:
                    self.stdout.write(self.style.WARNING(f"{adresse} : réponse {reponse.status_code}"))
                    continue
                absents = chaines_non_traduites(reponse.content.decode("utf-8"), catalogue)
                self.stdout.write(f"{adresse} : {len(absents)} texte(s) sans traduction")
                for texte in absents:
                    manquants.setdefault(texte, adresse)
        self.stdout.write(f"\n{len(manquants)} texte(s) à traduire au total ({len(catalogue)} déjà au catalogue).")
        for texte, adresse in manquants.items():
            self.stdout.write(f"  {texte}    <- {adresse}")
        if options["fichier"]:
            with open(options["fichier"], "w", encoding="utf-8-sig", newline="") as fichier:
                ecrivain = csv.writer(fichier)
                ecrivain.writerow(["francais", "arabe", "note"])
                for texte, adresse in manquants.items():
                    ecrivain.writerow([texte, "", adresse])
            self.stdout.write(f"Fichier écrit : {options['fichier']}")
