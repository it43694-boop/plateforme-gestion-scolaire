from django.core.management.base import BaseCommand

from comptes.entretien import duree_conservation_messages, entretien_quotidien
from etablissement.envoi_factures import relancer_factures_en_retard


class Command(BaseCommand):
    help = (
        "Entretien de la base : efface les messages de plus de N jours (réglage DUREE_CONSERVATION_MESSAGES_JOURS, 30 par "
        "défaut) et les sessions de connexion expirées, puis envoie les rappels des factures d'abonnement en retard. Se lance "
        "aussi tout seul une fois par jour."
    )

    def add_arguments(self, parser):
        parser.add_argument("--jours", type=int, default=None, help="Âge des messages à effacer, en jours (0 = aucun).")
        parser.add_argument("--simulation", action="store_true", help="Compte ce qui serait effacé, sans rien effacer.")

    def handle(self, *args, **options):
        jours = options["jours"] if options["jours"] is not None else duree_conservation_messages()
        bilan = entretien_quotidien(jours=jours, simulation=options["simulation"])
        verbe = "seraient effacés" if options["simulation"] else "effacés"
        if jours:
            self.stdout.write(
                f"Messages de plus de {jours} jours {verbe} : {bilan['messages']} (messagerie), {bilan['messages_equipe']} (fils d'équipe), "
                f"{bilan['notifications_de_messages']} (notifications de messages)"
            )
        else:
            self.stdout.write("Effacement des messages désactivé (durée de conservation à 0).")
        self.stdout.write(f"Sessions de connexion expirées {verbe} : {bilan['sessions']}")
        rappels = relancer_factures_en_retard(simulation=options["simulation"])
        self.stdout.write(
            f"Rappels de factures d'abonnement en retard {'à envoyer' if options['simulation'] else 'envoyés'} : {rappels['rappels']}"
            + (f" ({rappels['sans_adresse']} sans adresse)" if rappels["sans_adresse"] else "")
            + (" - envoi en échec, réessayé demain" if rappels["echecs"] else "")
        )
