from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.utils import timezone

from comptes.audit import enregistrer_action
from comptes.mail import envoyer_email
from comptes.decorators import module_requis
from comptes.models import Notification, Utilisateur
from comptes.roles import Role
from communication.forms import EnvoyerMessageForm, PublierAnnonceForm
from communication.models import Annonce, Message, Portee
from permissions_matrix.modules import Module
from scolarite.models import Inscription, classes_visibles_pour


def _destinataires(annonce) -> list[str]:
    """Détermine les emails à notifier selon la portée de l'annonce (toujours au sein du même établissement)."""
    if annonce.portee == Portee.TOUTE_ECOLE:
        emails = set(
            Utilisateur.objects.filter(is_active=True, etablissement=annonce.etablissement)
            .exclude(email="").values_list("email", flat=True)
        )
    else:
        eleves = Utilisateur.objects.filter(
            role=Role.ELEVE, inscriptions__classe=annonce.classe_ciblee,
        )
        parents = Utilisateur.objects.filter(enfants_lies__in=eleves)
        emails = set(eleves.values_list("email", flat=True)) | set(parents.values_list("email", flat=True))
    return list(emails)


def _envoyer_notifications(annonce):
    destinataires = _destinataires(annonce)
    if not destinataires:
        return
    nom_etablissement = annonce.auteur.etablissement.nom if annonce.auteur and annonce.auteur.etablissement_id else settings.NOM_PLATEFORME
    envoyer_email(
        sujet=f"{nom_etablissement} - {annonce.titre}",
        contenu=annonce.contenu,
        expediteur=settings.DEFAULT_FROM_EMAIL,
        destinataires=destinataires,
    )


@module_requis(Module.COMMUNICATION)
def publier_annonce(request):
    portees_disponibles = list(Portee) if request.user.role != Role.ENSEIGNANT else [Portee.MA_CLASSE]
    classes_disponibles = classes_visibles_pour(request.user)

    formulaire = PublierAnnonceForm(
        request.POST or None, request.FILES or None,
        classes_disponibles=classes_disponibles, portees_disponibles=portees_disponibles,
    )
    if request.method == "POST" and formulaire.is_valid():
        annonce = formulaire.save(commit=False)
        annonce.auteur = request.user
        annonce.etablissement = request.user.etablissement
        annonce.full_clean()
        annonce.save()
        _envoyer_notifications(annonce)
        enregistrer_action(
            acteur=request.user, action="publication_annonce", cible=annonce.titre, request=request,
        )
        messages.success(request, "Annonce publiée et notifications envoyées.")
        return redirect("communication:liste_annonces")

    return render(request, "communication/publier_annonce.html", {"formulaire": formulaire})


@module_requis(Module.COMMUNICATION)
def liste_annonces(request):
    annonces = Annonce.objects.filter(
        etablissement=request.user.etablissement,
    ).select_related("classe_ciblee", "auteur")
    if request.user.role == Role.ELEVE:
        classes_de_leleve = request.user.inscriptions.values_list("classe_id", flat=True)
        from django.db.models import Q
        annonces = annonces.filter(Q(portee=Portee.TOUTE_ECOLE) | Q(classe_ciblee__in=classes_de_leleve))
    elif request.user.role == Role.PARENT:
        from django.db.models import Q
        classes_des_enfants = request.user.enfants_lies.values_list("inscriptions__classe_id", flat=True)
        annonces = annonces.filter(Q(portee=Portee.TOUTE_ECOLE) | Q(classe_ciblee__in=classes_des_enfants))
    page_obj = Paginator(annonces, 15).get_page(request.GET.get("page"))
    return render(request, "communication/liste_annonces.html", {"page_obj": page_obj, "annonces": page_obj.object_list})


# ---------------------------------------------------------------------------
# Messagerie directe parent <-> enseignant, à propos d'un élève précis.
# ---------------------------------------------------------------------------

def _enseignants_de(eleve):
    """Enseignants réellement affectés à la classe actuelle (inscription en cours) de cet élève."""
    return Utilisateur.objects.filter(
        role=Role.ENSEIGNANT,
        affectations__classe__inscriptions__eleve=eleve,
        affectations__classe__inscriptions__statut=Inscription.Statut.EN_COURS,
    ).distinct()


def _contacts_disponibles(utilisateur):
    """Paires (élève, correspondant) avec qui l'utilisateur a le droit d'ouvrir une conversation."""
    paires = []
    if utilisateur.role == Role.PARENT:
        for enfant in utilisateur.enfants_lies.all():
            for enseignant in _enseignants_de(enfant):
                paires.append((enfant, enseignant))
    elif utilisateur.role == Role.ENSEIGNANT:
        eleves = Utilisateur.objects.filter(
            role=Role.ELEVE,
            inscriptions__classe__affectations__enseignant=utilisateur,
            inscriptions__statut=Inscription.Statut.EN_COURS,
        ).distinct()
        for eleve in eleves:
            for parent in eleve.parents_lies.all():
                paires.append((eleve, parent))
    return paires


def _verifier_acces_conversation(utilisateur, eleve, autre):
    """Même règle que Message.clean() - vérifiée aussi côté vue pour refuser l'accès avant tout envoi."""
    if utilisateur.role == Role.PARENT:
        if not eleve.parents_lies.filter(pk=utilisateur.pk).exists():
            raise PermissionDenied("Vous n'êtes pas lié à cet élève.")
        if autre.role != Role.ENSEIGNANT or not _enseignants_de(eleve).filter(pk=autre.pk).exists():
            raise PermissionDenied("Cet enseignant n'enseigne pas à cet élève.")
    elif utilisateur.role == Role.ENSEIGNANT:
        if not _enseignants_de(eleve).filter(pk=utilisateur.pk).exists():
            raise PermissionDenied("Vous n'enseignez pas à cet élève.")
        if autre.role != Role.PARENT or not eleve.parents_lies.filter(pk=autre.pk).exists():
            raise PermissionDenied("Ce compte n'est pas un parent lié à cet élève.")
    else:
        raise PermissionDenied("La messagerie n'est ouverte qu'aux parents et aux enseignants.")


@module_requis(Module.COMMUNICATION)
def liste_conversations(request):
    if request.user.role not in {Role.PARENT, Role.ENSEIGNANT}:
        raise PermissionDenied("La messagerie n'est ouverte qu'aux parents et aux enseignants.")

    messages_lies = Message.objects.filter(
        Q(expediteur=request.user) | Q(destinataire=request.user),
    ).select_related("eleve", "expediteur", "destinataire").order_by("-envoye_le")

    fils = {}
    for message in messages_lies:
        autre = message.destinataire if message.expediteur_id == request.user.id else message.expediteur
        cle = (message.eleve_id, autre.id)
        if cle not in fils:
            non_lus = Message.objects.filter(
                eleve_id=message.eleve_id, expediteur=autre, destinataire=request.user, lu_le__isnull=True,
            ).count()
            fils[cle] = {"eleve": message.eleve, "autre": autre, "dernier_message": message, "non_lus": non_lus}

    return render(request, "communication/liste_conversations.html", {
        "fils": list(fils.values()), "contacts_disponibles": _contacts_disponibles(request.user),
    })


@module_requis(Module.COMMUNICATION)
def conversation(request, eleve_id, autre_id):
    eleve = get_object_or_404(Utilisateur, id=eleve_id, role=Role.ELEVE)
    autre = get_object_or_404(Utilisateur, id=autre_id)
    _verifier_acces_conversation(request.user, eleve, autre)

    if request.method == "POST":
        formulaire = EnvoyerMessageForm(request.POST)
        if formulaire.is_valid():
            message = formulaire.save(commit=False)
            message.eleve = eleve
            message.expediteur = request.user
            message.destinataire = autre
            message.full_clean()
            message.save()
            Notification.objects.create(
                destinataire=autre, etablissement=message.etablissement,
                titre=f"Nouveau message de {request.user.nom_complet}",
                message=message.contenu[:200],
                url=reverse("communication:conversation", args=[eleve.id, request.user.id]),
            )
            enregistrer_action(
                acteur=request.user, action="envoi_message", cible=f"{autre} - {eleve.nom_complet}", request=request,
            )
            return redirect("communication:conversation", eleve_id=eleve.id, autre_id=autre.id)
    else:
        formulaire = EnvoyerMessageForm()

    fil = Message.objects.filter(eleve=eleve).filter(
        Q(expediteur=request.user, destinataire=autre) | Q(expediteur=autre, destinataire=request.user),
    ).order_by("envoye_le")
    fil.filter(destinataire=request.user, lu_le__isnull=True).update(lu_le=timezone.now())

    return render(request, "communication/conversation.html", {
        "eleve": eleve, "autre": autre, "fil": fil, "formulaire": formulaire,
    })
