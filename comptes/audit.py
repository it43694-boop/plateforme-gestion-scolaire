import logging

logger = logging.getLogger("audit")


def enregistrer_action(acteur, action: str, cible: str = "", details: dict | None = None, request=None):
    """
    Enregistre une action sensible dans le journal d'audit (base de données)
    et dans les logs applicatifs. À appeler explicitement à chaque point
    sensible : suppression, changement de rôle, modification de la matrice
    de permissions, validation de compte, etc.
    """
    from comptes.models import JournalAudit  # import tardif : évite les imports circulaires
    from comptes.utils import ip_client_fiable

    adresse_ip = ip_client_fiable(request) or None if request is not None else None

    JournalAudit.objects.create(
        acteur=acteur if getattr(acteur, "is_authenticated", False) else None,
        etablissement=getattr(acteur, "etablissement", None) if getattr(acteur, "is_authenticated", False) else None,
        action=action,
        cible=cible,
        details=details or {},
        adresse_ip=adresse_ip,
    )
    logger.info("%s | acteur=%s | cible=%s | details=%s", action, acteur, cible, details or {})
