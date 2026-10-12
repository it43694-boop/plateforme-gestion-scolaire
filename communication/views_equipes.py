from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from communication.equipes import fils_avec_activite, membres_du_fil, peut_acceder_fil, peut_utiliser_equipes
from communication.forms import EnvoyerMessageEquipeForm
from communication.models import FilEquipe, MessageEquipe, PorteeEquipe
from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from comptes.models import Notification
from permissions_matrix.modules import Module

NOMBRE_MESSAGES_AFFICHES = 100


@module_requis(Module.COMMUNICATION)
def liste_equipes(request):
    if not peut_utiliser_equipes(request.user):
        raise PermissionDenied("Les fils d'équipe sont réservés aux enseignants et à la direction pédagogique.")

    groupes = {PorteeEquipe.CLASSE: [], PorteeEquipe.NIVEAU: [], PorteeEquipe.MATIERE_NIVEAU: []}
    for entree in fils_avec_activite(request.user):
        groupes[entree["fil"].portee].append(entree)

    return render(request, "communication/liste_equipes.html", {
        "groupes": [
            ("Mes classes", groupes[PorteeEquipe.CLASSE]),
            ("Mes niveaux (toutes les sections)", groupes[PorteeEquipe.NIVEAU]),
            ("Ma matière dans un niveau", groupes[PorteeEquipe.MATIERE_NIVEAU]),
        ],
        "aucun_fil": not any(groupes.values()),
    })


@module_requis(Module.COMMUNICATION)
def fil_equipe(request, fil_id):
    fil = get_object_or_404(
        FilEquipe.objects.select_related("classe", "annee_scolaire"),
        pk=fil_id, etablissement_id=request.user.etablissement_id,
    )
    if not peut_acceder_fil(request.user, fil):
        raise PermissionDenied("Vous ne faites pas partie de cette équipe.")

    if request.method == "POST":
        formulaire = EnvoyerMessageEquipeForm(request.POST)
        if formulaire.is_valid():
            message = formulaire.save(commit=False)
            message.fil = fil
            message.auteur = request.user
            message.save()
            adresse = reverse("communication:fil_equipe", args=[fil.pk])
            Notification.objects.bulk_create([
                Notification(
                    destinataire=membre, etablissement_id=fil.etablissement_id,
                    titre="Nouveau message d'équipe",
                    message="Un nouveau message est disponible dans votre espace équipes.", url=adresse,
                )
                for membre in membres_du_fil(fil).exclude(pk=request.user.pk)
            ])
            enregistrer_action(acteur=request.user, action="message_equipe", cible=fil.libelle, request=request)
            messages.success(request, "Message envoyé à l'équipe.")
            return redirect("communication:fil_equipe", fil_id=fil.pk)
    else:
        formulaire = EnvoyerMessageEquipeForm()

    messages_fil = list(fil.messages.select_related("auteur").order_by("-envoye_le")[:NOMBRE_MESSAGES_AFFICHES])
    messages_fil.reverse()
    return render(request, "communication/fil_equipe.html", {
        "fil": fil, "messages_fil": messages_fil, "formulaire": formulaire, "membres": membres_du_fil(fil),
    })