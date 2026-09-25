from comptes.roles import ROLES_VALIDATION_COMPTES, Role


def etablissement_actif(request):
    """
    Résout l'établissement dont l'identité (nom, logo, devise) doit être
    affichée sur la page courante :
    - utilisateur connecté -> son propre établissement ;
    - visiteur non connecté ayant choisi une école dans l'annuaire ->
      celle mémorisée en session ;
    - sinon, s'il n'existe qu'un seul établissement sur l'installation
      (déploiement mono-établissement classique) -> celui-là par défaut ;
    - sinon (plusieurs établissements, aucun choisi) -> None : la page
      affiche une identité générique (c'est le cas de l'annuaire public
      lui-même).
    """
    from etablissement.models import Etablissement

    utilisateur = getattr(request, "user", None)
    if utilisateur is not None and utilisateur.is_authenticated and utilisateur.etablissement_id:
        return {"etablissement": utilisateur.etablissement}

    etablissement_id = request.session.get("etablissement_id")
    if etablissement_id:
        etablissement = Etablissement.objects.filter(pk=etablissement_id, actif=True).first()
        if etablissement:
            return {"etablissement": etablissement}

    if Etablissement.objects.count() == 1:
        return {"etablissement": Etablissement.objects.first()}

    return {"etablissement": None}


def navigation(request):
    """
    Construit la navigation latérale à partir des modules réellement
    autorisés pour le rôle de l'utilisateur connecté (matrice de
    permissions) : la barre latérale est un reflet direct des droits
    d'accès, jamais une liste figée.
    """
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}

    from permissions_matrix.models import PermissionMatrix

    modules_autorises = set(PermissionMatrix.modules_autorises(request.user.role, etablissement=request.user.etablissement))
    role = request.user.role

    sections = []
    from comptes.models import Notification
    notifications_non_lues = Notification.objects.filter(
        destinataire=request.user, lue_le__isnull=True,
    ).count()

    eleves_classes = []
    if "eleves" in modules_autorises:
        eleves_classes.append({"label": "Élèves", "url": "scolarite:liste_eleves"})
        eleves_classes.append({"label": "Inscrire un élève", "url": "scolarite:inscrire_eleve"})
    if "classes" in modules_autorises:
        eleves_classes.append({"label": "Classes", "url": "scolarite:liste_classes"})
        eleves_classes.append({"label": "Matières", "url": "scolarite:liste_matieres"})
    if "tests_de_niveau" in modules_autorises:
        eleves_classes.append({"label": "Tests de niveau", "url": "tests_niveau:liste_candidats"})
    if eleves_classes:
        sections.append({"titre": "Élèves & classes", "icone": "eleves", "liens": eleves_classes})

    pedagogie = []
    if role == Role.ENSEIGNANT.value and ("notes_bulletins" in modules_autorises or "absences" in modules_autorises):
        pedagogie.append({"label": "Mes classes", "url": "pedagogie:mes_classes"})
    if "suivi_des_cours" in modules_autorises:
        pedagogie.append({"label": "Suivi des cours", "url": "pedagogie:suivi_des_cours"})
    if pedagogie:
        sections.append({"titre": "Pédagogie", "icone": "pedagogie", "liens": pedagogie})

    finances = []
    if "finances" in modules_autorises:
        finances.append({"label": "Suivi des paiements", "url": "finances:suivi_paiements"})
        finances.append({"label": "Paiements", "url": "finances:liste_paiements"})
    if "caisse" in modules_autorises:
        finances.append({"label": "Caisse", "url": "finances:registre_caisse"})
    if "salaires" in modules_autorises:
        finances.append({"label": "Salaires", "url": "finances:liste_salaires"})
    if finances:
        sections.append({"titre": "Finances", "icone": "finances", "liens": finances})

    ressources = []
    if "bibliotheque" in modules_autorises:
        ressources.append({"label": "Bibliothèque", "url": "bibliotheque:liste_documents"})
    if "communication" in modules_autorises:
        ressources.append({"label": "Annonces", "url": "communication:liste_annonces"})
        if role in {Role.PARENT.value, Role.ENSEIGNANT.value}:
            ressources.append({"label": "Messagerie", "url": "communication:liste_conversations"})
    if "statistiques" in modules_autorises:
        ressources.append({"label": "Statistiques", "url": "statistiques:vue_ensemble"})
    if "assistant" in modules_autorises:
        ressources.append({"label": "Assistant", "url": "assistant:poser_question"})
    if ressources:
        sections.append({"titre": "Ressources", "icone": "ressources", "liens": ressources})

    administration = []
    sections.insert(0, {
        "titre": "Compte",
        "icone": "compte",
        "liens": [{
            "label": f"Notifications ({notifications_non_lues})" if notifications_non_lues else "Notifications",
            "url": "comptes:liste_notifications",
        }],
    })
    if role in {r.value for r in ROLES_VALIDATION_COMPTES}:
        administration.append({"label": "Comptes en attente", "url": "comptes:comptes_en_attente"})
    if role == Role.DEVELOPPEUR.value and request.user.etablissement_id:
        administration.append({"label": "Établissement", "url": "espace_developpeur:parametres_etablissement"})
        administration.append({"label": "Comptes", "url": "espace_developpeur:liste_comptes"})
        administration.append({"label": "Matrice de permissions", "url": "espace_developpeur:matrice_permissions"})
        administration.append({"label": "Journal d'audit", "url": "espace_developpeur:journal_audit"})
    if administration:
        sections.append({"titre": "Administration", "icone": "administration", "liens": administration})

    if getattr(request.user, "is_superuser", False):
        sections.append({
            "titre": "Plateforme",
            "icone": "plateforme",
            "liens": [{"label": "Établissements", "url": "espace_plateforme:liste_etablissements"}],
        })

    return {"sections_navigation": sections, "notifications_non_lues": notifications_non_lues}
