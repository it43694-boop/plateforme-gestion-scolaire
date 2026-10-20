"""Appareils qui reçoivent les notifications (Web Push) : on enregistre ou on retire l'abonnement du téléphone de la personne connectée."""
import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit

from comptes.models import AbonnementPush
from comptes.push import ADRESSE_PAR_DEFAUT, envoyer_a, push_actif

MESSAGES_D_ESSAI = {
    "fr": "Les notifications fonctionnent sur ce téléphone.",
    "ar": "الإشعارات تعمل على هذا الهاتف.",
}


def _corps(request):
    try:
        donnees = json.loads(request.body[:4000].decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return donnees if isinstance(donnees, dict) else None


def _endpoint_valable(endpoint) -> bool:
    return isinstance(endpoint, str) and endpoint.startswith("https://") and len(endpoint) <= 700


@login_required
@require_http_methods(["POST"])
@ratelimit(key="user", rate="60/h", method="POST", block=False)
def abonner_push(request):
    """
    Enregistre l'appareil pour la personne connectée. Un même appareil (même adresse d'envoi) n'appartient qu'à UN compte : s'il passe à une autre
    personne (ordinateur partagé), il quitte la précédente, qui ne reçoit plus rien dessus.
    """
    if not push_actif():
        return JsonResponse({"ok": False}, status=404)
    if getattr(request, "limited", False):
        return JsonResponse({"ok": False}, status=429)
    donnees = _corps(request)
    cles = (donnees or {}).get("keys") or {}
    endpoint, p256dh, auth = (donnees or {}).get("endpoint"), cles.get("p256dh"), cles.get("auth")
    if not _endpoint_valable(endpoint) or not isinstance(p256dh, str) or not isinstance(auth, str) or not (60 <= len(p256dh) <= 120) or not (10 <= len(auth) <= 40):
        return JsonResponse({"ok": False}, status=400)
    AbonnementPush.objects.update_or_create(
        endpoint=endpoint, defaults={
            "utilisateur": request.user, "cle_p256dh": p256dh, "cle_auth": auth, "agent": request.META.get("HTTP_USER_AGENT", "")[:200], "echecs": 0,
        },
    )
    return JsonResponse({"ok": True})


@login_required
@require_http_methods(["POST"])
@ratelimit(key="user", rate="10/h", method="POST", block=False)
def essai_push(request):
    """
    Envoie une notification d'essai aux appareils de la personne connectée, et seulement aux siens (rien n'est enregistré dans ses notifications).
    Réponse : {"ok": au moins un appareil l'a reçue, "appareils": combien sont activés, "envoyees": combien l'ont acceptée}.
    """
    if not push_actif():
        return JsonResponse({"ok": False}, status=404)
    if getattr(request, "limited", False):
        return JsonResponse({"ok": False}, status=429)
    appareils = list(AbonnementPush.objects.filter(utilisateur=request.user))
    langue = "ar" if getattr(request, "LANGUAGE_CODE", "fr") == "ar" else "fr"
    charge = json.dumps({"titre": "Yelenova", "message": MESSAGES_D_ESSAI[langue], "url": ADRESSE_PAR_DEFAUT, "id": "essai"}, ensure_ascii=False)
    envoyees = sum(1 for appareil in appareils if envoyer_a(appareil, charge))
    return JsonResponse({"ok": envoyees > 0, "appareils": len(appareils), "envoyees": envoyees})


@login_required
@require_http_methods(["POST"])
def desabonner_push(request):
    """Retire l'appareil de la personne connectée (bouton « Désactiver », ou déconnexion sur un appareil partagé)."""
    donnees = _corps(request)
    endpoint = (donnees or {}).get("endpoint")
    if not _endpoint_valable(endpoint):
        return JsonResponse({"ok": False}, status=400)
    AbonnementPush.objects.filter(utilisateur=request.user, endpoint=endpoint).delete()
    return JsonResponse({"ok": True})
