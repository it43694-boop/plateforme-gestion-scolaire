from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.crypto import get_random_string

from comptes.models import Utilisateur, creer_avec_matricule_unique, generer_matricule
from comptes.roles import Role, StatutCompte
from scolarite.models import Classe, Inscription, lier_parent_a_eleve


COLONNES_REQUISES = {"prenom", "nom", "classe"}


class Command(BaseCommand):
    help = "Importe des élèves depuis un fichier XLSX avec validation préalable."

    def add_arguments(self, parser):
        parser.add_argument("fichier", type=Path)
        parser.add_argument("--etablissement", type=int, required=True)
        parser.add_argument(
            "--annee-scolaire", type=int, required=True, dest="annee_scolaire",
            help="ID de l'année scolaire cible (voir AnneeScolaire dans l'admin). "
                 "Obligatoire : sans lui, une classe existant sur plusieurs années "
                 "(ex. « 1ère année A » en 2026-2027 et 2027-2028) serait ambiguë.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Valide et affiche le rapport sans écrire.")

    def handle(self, *args, **options):
        try:
            import openpyxl
        except ImportError as erreur:
            raise CommandError("Installez openpyxl avec pip install -r requirements.txt.") from erreur

        fichier = options["fichier"]
        if fichier.suffix.lower() != ".xlsx" or not fichier.exists():
            raise CommandError("Le fichier doit être un fichier .xlsx existant.")

        # Cloisonné par établissement ET par année scolaire précise : deux
        # classes de même nom sur deux années différentes ne doivent jamais
        # pouvoir se confondre (cas courant après un passage de classe).
        classe_qs = Classe.objects.filter(
            annee_scolaire__etablissement_id=options["etablissement"],
            annee_scolaire_id=options["annee_scolaire"],
        )
        if not classe_qs.exists():
            raise CommandError(
                "Aucune classe trouvée pour cet établissement et cette année scolaire. "
                "Vérifiez les identifiants --etablissement et --annee-scolaire."
            )
        classe_par_nom = {classe.nom.strip().lower(): classe for classe in classe_qs}

        feuille = openpyxl.load_workbook(fichier, read_only=True, data_only=True).active
        lignes = feuille.iter_rows(values_only=True)
        try:
            ligne_entete = next(lignes)
        except StopIteration as erreur:
            raise CommandError("Le fichier Excel est vide.") from erreur

        entetes_liste = [str(valeur).strip().lower() if valeur is not None else "" for valeur in ligne_entete]
        entetes = set(entetes_liste) - {""}
        manque = COLONNES_REQUISES - entetes
        if manque:
            raise CommandError(f"Colonnes obligatoires manquantes : {', '.join(sorted(manque))}.")

        rapport = []
        objets = []
        for numero, valeurs in enumerate(lignes, start=2):
            donnees = dict(zip(entetes_liste, valeurs))
            prenom = str(donnees.get("prenom") or "").strip()
            nom = str(donnees.get("nom") or "").strip()
            classe = classe_par_nom.get(str(donnees.get("classe") or "").strip().lower())
            erreurs = []
            if not prenom:
                erreurs.append("prenom obligatoire")
            if not nom:
                erreurs.append("nom obligatoire")
            if classe is None:
                erreurs.append("classe inconnue pour cet établissement et cette année scolaire")
            if erreurs:
                rapport.append(f"Ligne {numero}: ERREUR - {'; '.join(erreurs)}")
                continue
            objets.append((prenom, nom, classe))
            rapport.append(f"Ligne {numero}: OK - {prenom} {nom} -> {classe}")

        for ligne in rapport:
            self.stdout.write(ligne)
        if any("ERREUR" in ligne for ligne in rapport):
            raise CommandError("Import annulé : corrigez les erreurs puis relancez.")
        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS(f"Aperçu valide : {len(objets)} élève(s), aucune écriture."))
            return

        with transaction.atomic():
            for prenom, nom, classe in objets:
                def construire():
                    matricule = generer_matricule()
                    eleve = Utilisateur(
                        email=f"{matricule}@eleves.local", prenom=prenom, nom=nom,
                        role=Role.ELEVE, matricule=matricule,
                        etablissement=classe.annee_scolaire.etablissement,
                        statut=StatutCompte.ACTIF, is_active=True, email_verifie=True,
                    )
                    eleve.set_password(get_random_string(32))
                    eleve.full_clean(exclude=["password"])
                    eleve.save()
                    return eleve
                eleve = creer_avec_matricule_unique(construire)
                Inscription.objects.create(eleve=eleve, classe=classe)
        self.stdout.write(self.style.SUCCESS(f"Import terminé : {len(objets)} élève(s) créé(s)."))
