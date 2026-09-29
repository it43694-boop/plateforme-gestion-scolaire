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
from assistant.services import (
    AssistantIndisponible,
    ia_disponible,
    repondre_avec_ia,
    repondre_question_generale_avec_ia,
    serialiser_resultat,
)


def construire_donnees_generales(utilisateur):
    """
    Vue d'ensemble de l'établissement, scopée aux modules que le rôle de
    l'utilisateur autorise déjà - même logique que les indicateurs du
    tableau de bord (comptes.views.redirection_tableau_de_bord), mais
    reformulée en liste plate directement exploitable par l'Assistant.

    Retourne une liste de {"cle", "label", "valeur"} : jamais de dossier
    individuel (élève, employé, paiement nommé), uniquement des agrégats.
    """
    if not utilisateur.etablissement_id:
        return []

    from django.db.models import Case, F, IntegerField, Sum, When

    from bibliotheque.models import Document
    from communication.models import Annonce
    from finances.models import MouvementCaisse, Salaire
    from scolarite.models import classes_visibles_pour

    valeurs_autorisees = PermissionMatrix.modules_autorises(utilisateur.role, etablissement=utilisateur.etablissement)
    classes = classes_visibles_pour(utilisateur)
    devise = getattr(utilisateur.etablissement, "code_devise", "FCFA")
    items = []

    if Module.ELEVES.value in valeurs_autorisees:
        items.append({
            "cle": "eleves_inscrits", "label": "Élèves inscrits",
            "valeur": Inscription.objects.filter(classe__in=classes, statut=Inscription.Statut.EN_COURS).count(),
        })
    if Module.CLASSES.value in valeurs_autorisees:
        items.append({
            "cle": "classes_actives", "label": "Classes actives",
            "valeur": classes.filter(annee_scolaire__est_active=True).count(),
        })
    if Module.ENSEIGNANTS.value in valeurs_autorisees:
        items.append({
            "cle": "enseignants", "label": "Enseignants actifs",
            "valeur": Utilisateur.objects.filter(
                etablissement=utilisateur.etablissement, role=Role.ENSEIGNANT, is_active=True,
            ).count(),
        })
    if Module.ABSENCES.value in valeurs_autorisees:
        items.append({
            "cle": "absences_enregistrees", "label": "Absences enregistrées",
            "valeur": Absence.objects.filter(classe__in=classes).count(),
        })
    if Module.FINANCES.value in valeurs_autorisees:
        total = Paiement.objects.filter(
            etablissement=utilisateur.etablissement, est_supprime=False,
        ).aggregate(total=Sum("montant"))["total"] or 0
        items.append({"cle": "total_encaissements", "label": "Total encaissé", "valeur": f"{total} {devise}"})
    if Module.CAISSE.value in valeurs_autorisees:
        solde = MouvementCaisse.objects.filter(
            etablissement=utilisateur.etablissement, annule=False,
        ).aggregate(solde=Sum(Case(
            When(type_mouvement=MouvementCaisse.TypeMouvement.ENTREE, then=F("montant")),
            When(type_mouvement=MouvementCaisse.TypeMouvement.SORTIE, then=-F("montant")),
            output_field=IntegerField(),
        )))["solde"] or 0
        items.append({"cle": "solde_caisse", "label": "Solde de caisse", "valeur": f"{solde} {devise}"})
    if Module.SALAIRES.value in valeurs_autorisees:
        salaires = Salaire.objects.filter(etablissement=utilisateur.etablissement, est_supprime=False)
        items.append({
            "cle": "salaires_en_attente", "label": "Salaires en attente de paiement",
            "valeur": salaires.filter(statut=Salaire.Statut.EN_ATTENTE).count(),
        })
    if Module.BIBLIOTHEQUE.value in valeurs_autorisees:
        items.append({
            "cle": "documents_bibliotheque", "label": "Documents en bibliothèque",
            "valeur": Document.objects.filter(etablissement=utilisateur.etablissement).count(),
        })
    if Module.COMMUNICATION.value in valeurs_autorisees:
        items.append({
            "cle": "annonces_publiees", "label": "Annonces publiées",
            "valeur": Annonce.objects.filter(etablissement=utilisateur.etablissement).count(),
        })
    return items


@module_requis(Module.ASSISTANT)
def poser_question(request):
    """
    Deux modes, tous deux restitués uniquement à partir des données que le
    rôle courant est déjà autorisé à voir - mêmes règles de visibilité et
    mêmes permissions que le reste de l'application, jamais un raccourci
    qui les contournerait :

    - avec un matricule : dossier d'UN élève précis (notes, absences,
      paiements selon les modules autorisés) ;
    - sans matricule mais avec une question : vue d'ensemble de
      l'établissement, agrégée par construire_donnees_generales() selon
      les mêmes modules.

    Mode génératif optionnel (cahier des charges, section Assistant) :
    si une clé API est configurée ET qu'une question en langage libre est
    posée, la sélection de données déjà filtrée (l'un ou l'autre mode) est
    reformulée en langage naturel - voir assistant/services.py pour la
    garantie de sécurité associée. Les données brutes restent toujours
    affichées à côté : la réponse de l'IA est un confort de lecture,
    jamais la seule source de vérité.
    """
    matricule = request.GET.get("matricule", "").strip()
    question_libre = request.GET.get("question", "").strip()
    resultat = None
    resultat_general = None
    erreur = None
    reponse_ia = None
    erreur_ia = None

    if not matricule and question_libre:
        if not ia_disponible():
            erreur = "Indiquez le matricule d'un élève pour lancer une recherche - la question générale nécessite l'Assistant IA, non configuré ici."
        else:
            resultat_general = construire_donnees_generales(request.user)
            limite_atteinte = is_ratelimited(
                request, group="assistant_ia", key="user", rate="20/h", increment=True,
            )
            if limite_atteinte:
                erreur_ia = "Limite de questions à l'assistant atteinte pour cette heure. Réessayez plus tard."
            else:
                try:
                    donnees_autorisees = {item["cle"]: item["valeur"] for item in resultat_general}
                    reponse_ia = repondre_question_generale_avec_ia(
                        donnees_autorisees=donnees_autorisees, question=question_libre,
                    )
                    enregistrer_action(
                        acteur=request.user, action="question_assistant_ia_generale",
                        cible=getattr(request.user.etablissement, "nom", ""),
                        details={"question": question_libre}, request=request,
                    )
                except AssistantIndisponible:
                    erreur_ia = "L'assistant IA est momentanément indisponible. Les données ci-dessous restent à jour."

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
        "resultat": resultat, "resultat_general": resultat_general, "erreur": erreur,
        "reponse_ia": reponse_ia, "erreur_ia": erreur_ia, "ia_disponible": ia_disponible(),
    })
