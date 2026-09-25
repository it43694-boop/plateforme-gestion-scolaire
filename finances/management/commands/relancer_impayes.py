from django.core.management.base import BaseCommand
from django.conf import settings
from django.db.models import Q, Sum
from django.urls import reverse
from django.utils import timezone

from comptes.mail import envoyer_email
from comptes.models import Notification
from finances.models import Paiement
from scolarite.models import Inscription, calculer_total_du


class Command(BaseCommand):
    help = "Crée une notification et un email de relance pour les impayés."

    def handle(self, *args, **options):
        compte = 0
        ignores_sans_parent = 0
        for inscription in Inscription.objects.filter(
            statut=Inscription.Statut.EN_COURS,
        ).select_related("eleve", "classe__annee_scolaire", "eleve__etablissement"):
            total_paye = Paiement.objects.filter(
                inscription=inscription, est_supprime=False,
            ).aggregate(total=Sum("montant"))["total"] or 0
            solde = calculer_total_du(inscription) - total_paye
            if solde <= 0:
                continue
            # Toujours au(x) parent(s) lié(s) — jamais à l'adresse auto-générée
            # de l'élève (matricule@eleves.local), qui n'est lue par personne.
            # Même principe que pour la réinitialisation de mot de passe.
            destinataire = inscription.eleve.parents_lies.exclude(email="").first()
            if not destinataire:
                ignores_sans_parent += 1
                continue
            etablissement = inscription.classe.annee_scolaire.etablissement
            devise = getattr(etablissement, "code_devise", "FCFA")
            titre = "Rappel de paiement scolaire"
            message = f"Le solde scolaire de {inscription.eleve.nom_complet} est de {solde} {devise}."
            deja = Notification.objects.filter(
                destinataire=destinataire, titre=titre, cree_le__date=timezone.localdate(),
            ).exists()
            if deja:
                continue
            Notification.objects.create(
                destinataire=destinataire,
                etablissement=etablissement,
                titre=titre, message=message,
                url=reverse("finances:suivi_paiements"),
            )
            envoyer_email(
                sujet=titre, contenu=message,
                expediteur=settings.DEFAULT_FROM_EMAIL, destinataires=[destinataire.email],
            )
            compte += 1
        self.stdout.write(self.style.SUCCESS(f"{compte} relance(s) créée(s)."))
        if ignores_sans_parent:
            self.stdout.write(self.style.WARNING(
                f"{ignores_sans_parent} élève(s) en impayé ignoré(s) : aucun parent lié avec email."
            ))