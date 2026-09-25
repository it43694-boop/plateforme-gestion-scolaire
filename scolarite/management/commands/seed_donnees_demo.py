import datetime

from django.core.management.base import BaseCommand

from comptes.models import Utilisateur
from comptes.roles import Role, StatutCompte
from etablissement.models import Etablissement
from permissions_matrix.models import PermissionMatrix
from scolarite.models import AnneeScolaire, Affectation, Classe, Cycle, EcheancierFrais


class Command(BaseCommand):
    help = (
        "Crée des données de démonstration (établissement, année scolaire, classes, "
        "frais, comptes de test). À usage exclusif de développement/démo - ne jamais "
        "exécuter en production."
    )

    def handle(self, *args, **options):
        etablissement, cree = Etablissement.objects.get_or_create(
            nom="École Démonstration",
            defaults={"devise": "Remplacez ce nom depuis l'espace développeur"},
        )
        self.stdout.write(self.style.SUCCESS(f"Établissement : {etablissement.nom} ({'créé' if cree else 'existant'})"))

        if not PermissionMatrix.objects.filter(etablissement=etablissement).exists():
            PermissionMatrix.seed_pour(etablissement)
            self.stdout.write(self.style.SUCCESS("Matrice de permissions générée pour cet établissement."))

        annee, cree = AnneeScolaire.objects.get_or_create(
            libelle="2026-2027", etablissement=etablissement,
            defaults={
                "date_debut": datetime.date(2026, 10, 1),
                "date_fin": datetime.date(2027, 7, 31),
                "est_active": True,
            },
        )
        self.stdout.write(self.style.SUCCESS(f"Année scolaire : {annee} ({'créée' if cree else 'existante'})"))

        classes_demo = [
            ("1ère année A", Cycle.PREMIER_CYCLE, 15000, 15000, 15000),
            ("6ème année A", Cycle.PREMIER_CYCLE, 20000, 20000, 20000),
            ("7ème année A", Cycle.DEUXIEME_CYCLE, 25000, 25000, 25000),
            ("9ème année A", Cycle.DEUXIEME_CYCLE, 30000, 25000, 25000),
        ]
        for nom, cycle, insc, t1, t2 in classes_demo:
            classe, cree = Classe.objects.get_or_create(
                nom=nom, annee_scolaire=annee, defaults={"cycle": cycle},
            )
            EcheancierFrais.objects.get_or_create(
                classe=classe,
                defaults={"montant_inscription": insc, "montant_tranche_1": t1, "montant_tranche_2": t2},
            )
            self.stdout.write(f"  Classe : {classe} ({'créée' if cree else 'existante'})")

        if not Utilisateur.objects.filter(email="developpeur-demo@ecole-demo.local").exists():
            developpeur = Utilisateur(
                email="developpeur-demo@ecole-demo.local", prenom="Aïcha", nom="Sangaré",
                role=Role.DEVELOPPEUR, etablissement=etablissement,
                statut=StatutCompte.ACTIF, is_active=True, email_verifie=True,
            )
            developpeur.set_password("Developpeur#2026!")
            developpeur.full_clean(exclude=["password"])
            developpeur.save()
            self.stdout.write(self.style.SUCCESS(
                "Compte développeur de démo créé (rattaché à l'établissement) : "
                "developpeur-demo@ecole-demo.local / Developpeur#2026!"
            ))

        if not Utilisateur.objects.filter(email="secretariat-demo@ecole-demo.local").exists():
            secretaire = Utilisateur(
                email="secretariat-demo@ecole-demo.local", prenom="Assitan", nom="Koné",
                role=Role.SECRETAIRE, etablissement=etablissement,
                statut=StatutCompte.ACTIF, is_active=True, email_verifie=True,
            )
            secretaire.set_password("Secretariat#2026!")
            secretaire.full_clean(exclude=["password"])
            secretaire.save()
            self.stdout.write(self.style.SUCCESS(
                "Compte secrétariat de démo créé : secretariat-demo@ecole-demo.local / Secretariat#2026!"
            ))

        if not Utilisateur.objects.filter(email="comptable-demo@ecole-demo.local").exists():
            comptable = Utilisateur(
                email="comptable-demo@ecole-demo.local", prenom="Boubacar", nom="Diallo",
                role=Role.COMPTABLE, etablissement=etablissement,
                statut=StatutCompte.ACTIF, is_active=True, email_verifie=True,
            )
            comptable.set_password("Comptable#2026!")
            comptable.full_clean(exclude=["password"])
            comptable.save()
            self.stdout.write(self.style.SUCCESS(
                "Compte comptable de démo créé : comptable-demo@ecole-demo.local / Comptable#2026!"
            ))

        if not Utilisateur.objects.filter(email="enseignant-demo@ecole-demo.local").exists():
            enseignant = Utilisateur(
                email="enseignant-demo@ecole-demo.local", prenom="Seydou", nom="Coulibaly",
                role=Role.ENSEIGNANT, etablissement=etablissement,
                statut=StatutCompte.ACTIF, is_active=True, email_verifie=True,
            )
            enseignant.set_password("Enseignant#2026!")
            enseignant.full_clean(exclude=["password"])
            enseignant.save()
            Affectation.objects.get_or_create(
                enseignant=enseignant, classe=Classe.objects.get(nom="1ère année A", annee_scolaire=annee),
                matiere="", defaults={},
            )
            self.stdout.write(self.style.SUCCESS(
                "Compte enseignant de démo créé (affecté à 1ère année A) : "
                "enseignant-demo@ecole-demo.local / Enseignant#2026!"
            ))

        self.stdout.write(self.style.SUCCESS("Données de démonstration prêtes."))
