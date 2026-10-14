"""
Entretien quotidien de la base : efface ce qui n'a plus d'utilité, pour ne pas la laisser grossir sans fin.

- Messages de la messagerie (parent-enseignant) et des fils d'équipe de plus de `DUREE_CONSERVATION_MESSAGES_JOURS` jours
  (30 par défaut ; 0 = ne jamais effacer). Lus ou non : au bout d'un mois, ils n'ont plus d'intérêt et moins on garde de
  données personnelles, mieux c'est.
- Sessions de connexion expirées : Django ne les supprime jamais lui-même (il faut lancer `clearsessions`), et chaque
  connexion en ajoute une ligne. Une session expirée ne peut plus servir à personne : personne n'est déconnecté.

Ne touche à rien d'autre : ni les annonces, ni les notifications, ni les notes, paiements ou dossiers.

Deux façons de le lancer, sans fournisseur de tâches planifiées (le plan gratuit de Render n'a pas de cron) :
- automatiquement, au plus UNE fois par jour, à la première visite d'un utilisateur connecté
  (comptes.middleware.EntretienQuotidienMiddleware) ;
- à la main ou par une tâche planifiée : `python manage.py entretien` (`--simulation` pour voir sans effacer).

Il envoie aussi les rappels des factures d'abonnement en retard (etablissement.envoi_factures), à part : leur échec ne
gêne pas les purges et inversement.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.utils import timezone

from comptes.audit import enregistrer_action

logger = logging.getLogger(__name__)

CLE_CACHE_ENTRETIEN = "entretien-quotidien"
DUREE_ENTRE_DEUX_ENTRETIENS = 24 * 3600


def duree_conservation_messages() -> int:
    """Durée de conservation des messages en jours ; 0 (ou moins) = jamais effacés."""
    return max(0, int(getattr(settings, "DUREE_CONSERVATION_MESSAGES_JOURS", 0) or 0))


def purger_messages_anciens(*, jours=None, maintenant=None, simulation=False) -> dict:
    """
    Efface les messages de plus de `jours` jours (par défaut le réglage). Rend {"messages": n, "messages_equipe": m}.
    Avec `simulation`, compte sans effacer. Une durée à 0 désactive l'effacement.
    """
    from django.urls import reverse

    from communication.models import Message, MessageEquipe
    from comptes.models import Notification

    jours = duree_conservation_messages() if jours is None else max(0, int(jours))
    if jours == 0:
        return {"messages": 0, "messages_equipe": 0, "notifications_de_messages": 0}
    limite = (maintenant or timezone.now()) - timedelta(days=jours)
    resultat = {}
    for cle, modele in (("messages", Message), ("messages_equipe", MessageEquipe)):
        anciens = modele.objects.filter(envoye_le__lt=limite)
        resultat[cle] = anciens.count() if simulation else anciens.delete()[0]
    # Chaque message envoyé crée une notification qui en garde les 200 premiers caractères : elle part avec lui, sinon le
    # texte « effacé » resterait lisible dans la liste des notifications de son destinataire.
    notifications = Notification.objects.filter(
        cree_le__lt=limite, url__startswith=reverse("communication:liste_conversations"),
    )
    resultat["notifications_de_messages"] = notifications.count() if simulation else notifications.delete()[0]
    return resultat


def purger_sessions_expirees(*, maintenant=None, simulation=False) -> int:
    """Efface les sessions de connexion dont l'heure d'expiration est passée ; personne n'est déconnecté."""
    expirees = Session.objects.filter(expire_date__lt=maintenant or timezone.now())
    return expirees.count() if simulation else expirees.delete()[0]


def entretien_quotidien(*, jours=None, simulation=False) -> dict:
    """
    Lance les deux purges. Une ligne du journal d'audit (compteurs seulement, jamais un texte de message) quand quelque
    chose a été effacé.
    """
    bilan = {**purger_messages_anciens(jours=jours, simulation=simulation), "sessions": purger_sessions_expirees(simulation=simulation)}
    if not simulation and any(bilan.values()):
        enregistrer_action(acteur=None, action="entretien_quotidien", cible="base de données", details=bilan)
    return bilan


def entretien_si_du() -> dict | None:
    """
    Lance l'entretien s'il n'a pas déjà eu lieu dans les dernières 24 heures (marqueur dans le cache : partagé entre les
    processus avec Redis, par processus sinon - sans gravité, les purges sont sans effet une seconde fois).
    Un échec n'est pas retenté avant demain : une base en panne ne doit pas ralentir chaque page.
    """
    if not getattr(settings, "ENTRETIEN_AUTOMATIQUE", True):
        return None
    if not cache.add(CLE_CACHE_ENTRETIEN, "1", DUREE_ENTRE_DEUX_ENTRETIENS):
        return None
    bilan = None
    try:
        bilan = entretien_quotidien()
    except Exception:  # un entretien raté ne doit jamais casser la page de l'utilisateur
        logger.exception("Entretien quotidien échoué")
    try:
        from etablissement.envoi_factures import relancer_factures_en_retard

        relancer_factures_en_retard()
    except Exception:
        logger.exception("Rappels des factures d'abonnement échoués")
    return bilan
