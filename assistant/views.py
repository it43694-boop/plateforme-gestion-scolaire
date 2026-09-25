from django.shortcuts import render
from django_ratelimit.core import is_ratelimited

from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from comptes.models import Utilisateur
from comptes.roles import Role
from finances.models import Paiement
from pedagogie.models import Absence, Note
from permissions_matrix.models import PermissionMatrix
from permissions_matrix.modules import Module
from scolarite.models import Inscription, dossier_complet, eleve_visible_pour
from assistant.services import AssistantIndisponible, ia_disponible, repondre_avec_ia, serialiser_resultat


@module_requis(Module.ASSISTANT)
def poser_question(request):
    """
    Recherche d'un élève par matricule, restituant uniquement les données
    que le rôle courant est déjà autorisé à voir - mêmes règles de
    visibilité et mêmes permissions que le reste de l'application, jamais
    un raccourci qui les contournerait.

    Mode génératif optionnel (cahier des charges, section Assistant) :
    si une clé API est configurée ET qu'une question en langage libre est
    posée, cette même sélection de données déjà filtrée est reformulée en
    langage naturel - voir assistant/services.py pour la garantie de
    sécurité associée. Les données brutes restent toujours affichées à
    côté : la réponse de l'IA est un confort de lecture, jamais la seule
    source de vérité.
    """
    matricule = request.GET.get("matricule", "").strip()
    question_libre = request.GET.get("question", "").strip()
    resultat = None
    erreur = None
    reponse_ia = None
    erreur_ia = None

    if matricule:
        eleve = Utilisateur.objects.filter(matricule=matricule, role=Role.ELEVE).first()
        if not eleve:
            erreur = "Aucun élève trouvé avec ce matricule."
        elif not eleve_visible_pour(request.user, eleve):
            erreur = "Vous n'avez pas accès aux informations de cet élève."
        else:
            resultat = {"eleve": eleve, "dossier_complet": dossier_complet(eleve)}
            resultat["inscription"] = Inscription.objects.filter(
                eleve=eleve, statut=Inscription.Statut.EN_COURS,
            ).select_related("classe").first()

            if PermissionMatrix.a_acces(request.user.role, "notes_bulletins", etablissement=request.user.etablissement):
                resultat["dernieres_notes"] = Note.objects.filter(eleve=eleve).select_related(
                    "affectation",
                ).order_by("-modifie_le")[:5]
            if PermissionMatrix.a_acces(request.user.role, "absences", etablissement=request.user.etablissement):
                resultat["total_absences"] = Absence.objects.filter(eleve=eleve).count()
            if PermissionMatrix.a_acces(request.user.role, "finances", etablissement=request.user.etablissement):
                resultat["derniers_paiements"] = Paiement.objects.filter(
                    eleve=eleve, est_supprime=False,
                ).order_by("-date_paiement")[:5]

            if question_libre and ia_disponible():
                limite_atteinte = is_ratelimited(
                    request, group="assistant_ia", key="user", rate="20/h", increment=True,
                )
                if limite_atteinte:
                    erreur_ia = "Limite de questions à l'assistant atteinte pour cette heure. Réessayez plus tard."
                else:
                    try:
                        reponse_ia = repondre_avec_ia(
                            donnees_autorisees=serialiser_resultat(resultat), question=question_libre,
                        )
                        enregistrer_action(
                            acteur=request.user, action="question_assistant_ia",
                            cible=eleve.matricule, details={"question": question_libre}, request=request,
                        )
                    except AssistantIndisponible:
                        erreur_ia = "L'assistant IA est momentanément indisponible. Les données ci-dessous restent à jour."

    return render(request, "assistant/poser_question.html", {
        "matricule": matricule, "question": question_libre,
        "resultat": resultat, "erreur": erreur,
        "reponse_ia": reponse_ia, "erreur_ia": erreur_ia, "ia_disponible": ia_disponible(),
    })
