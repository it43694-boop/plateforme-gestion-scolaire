from django.conf import settings

from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, ROLES_VALIDATION_COMPTES, Role


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

    from comptes.middleware import est_proprietaire_sans_etablissement

    utilisateur = getattr(request, "user", None)
    if est_proprietaire_sans_etablissement(utilisateur):
        # Le propriétaire de la plateforme n'a pas d'école : ses pages portent la marque de la
        # plateforme, même quand une seule école existe (et serait sinon choisie par défaut).
        return {"etablissement": None}
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


# Icône de chaque lien du menu latéral, par nom d'adresse ; un lien inconnu reçoit un simple point.
ICONES_DES_LIENS = {
    "comptes:liste_notifications": "cloche",
    "scolarite:liste_eleves": "eleves",
    "scolarite:anciens_eleves": "eleves",
    "scolarite:inscrire_eleve": "ajout-utilisateur",
    "scolarite:liste_classes": "classes",
    "scolarite:liste_matieres": "livre",
    "scolarite:calendrier": "calendrier",
    "tests_niveau:liste_candidats": "test",
    "pedagogie:mes_classes": "classes",
    "pedagogie:mensuel_classes": "classes",
    "pedagogie:suivi_des_cours": "suivi",
    "pedagogie:clotures_notes": "cadenas",
    "pedagogie:avancement_programmes": "suivi",
    "pedagogie:devoirs": "livre",
    "finances:suivi_paiements": "tendance",
    "finances:liste_paiements": "carte",
    "finances:frais_annexes": "carte",
    "finances:arrieres": "alerte",
    "finances:tenues_vendre": "boutique",
    "finances:tenues": "boutique",
    "cantine:tableau": "cantine",
    "cantine:appel": "cantine",
    "cantine:inscrire_eleves": "ajout-utilisateur",
    "cantine:formules": "carte",
    "cantine:mon_suivi": "cantine",
    "finances:registre_caisse": "caisse",
    "comptabilite:accueil": "journal",
    "finances:liste_salaires": "mallette",
    "bibliotheque:liste_documents": "favori",
    "communication:liste_annonces": "annonce",
    "communication:liste_conversations": "message",
    "communication:messages_a_envoyer": "envoi",
    "statistiques:vue_ensemble": "graphique",
    "assistant:poser_question": "eclair",
    "comptes:comptes_en_attente": "utilisateur-valide",
    "comptes:noms_en_arabe": "eleves",
    "espace_developpeur:parametres_etablissement": "accueil",
    "espace_developpeur:annees_scolaires": "calendrier",
    "espace_developpeur:liste_comptes": "eleves",
    "espace_developpeur:matrice_permissions": "cadenas",
    "espace_developpeur:journal_audit": "oeil",
    "espace_plateforme:liste_etablissements": "accueil",
    "espace_plateforme:abonnements": "carte",
}


# Ceux qui remplissent ou consultent le bulletin mensuel du premier cycle (voir pedagogie.mensuel.peut_saisir / peut_consulter).
ROLES_BULLETINS_MENSUELS = {
    Role.ENSEIGNANT.value, Role.DIRECTEUR_1ER_CYCLE.value, Role.RESPONSABLE_PEDAGOGIQUE.value, Role.SUPER_ADMINISTRATEUR.value,
    *{r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL},
}


def habiller_les_liens(sections, notifications_non_lues=0):
    """Ajoute à chaque lien son icône et, pour les notifications, le nombre de non lues (pastille du menu)."""
    for section in sections:
        for lien in section["liens"]:
            lien["icone"] = ICONES_DES_LIENS.get(lien["url"], "point")
            if lien["url"] == "comptes:liste_notifications":
                lien["compteur"] = notifications_non_lues
    return sections


def navigation(request):
    """
    Construit la navigation latérale à partir des modules réellement
    autorisés pour le rôle de l'utilisateur connecté (matrice de
    permissions) : la barre latérale est un reflet direct des droits
    d'accès, jamais une liste figée.
    """
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}

    from comptes.middleware import est_proprietaire_sans_etablissement
    from permissions_matrix.models import PermissionMatrix
    from scolarite.models import ROLES_ETAT_CIVIL_ELEVE

    if est_proprietaire_sans_etablissement(request.user):
        # Aucune école : seuls le compte personnel et la gestion des
        # établissements ont un sens (voir ProprietairePlateformeMiddleware).
        from comptes.models import notifications_visibles_pour
        non_lues = notifications_visibles_pour(request.user).filter(lue_le__isnull=True).count()
        return {
            "sections_navigation": habiller_les_liens([
                {"titre": "Compte", "icone": "compte", "liens": [{
                    "label": "Notifications", "url": "comptes:liste_notifications",
                }]},
                {"titre": "Plateforme", "icone": "plateforme", "liens": [
                    {"label": "Établissements", "url": "espace_plateforme:liste_etablissements"},
                    {"label": "Abonnements", "url": "espace_plateforme:abonnements"},
                ]},
            ], non_lues),
            "notifications_non_lues": non_lues, "peut_rechercher_eleves": False, "app_version": settings.APP_VERSION,
        }

    modules_autorises = set(PermissionMatrix.modules_autorises(request.user.role, etablissement=request.user.etablissement))
    role = request.user.role

    sections = []
    from comptes.models import notifications_visibles_pour
    notifications_non_lues = notifications_visibles_pour(request.user).filter(lue_le__isnull=True).count()

    eleves_classes = []
    if "eleves" in modules_autorises:
        eleves_classes.append({"label": "Élèves", "url": "scolarite:liste_eleves"})
        if role not in {Role.PARENT.value, Role.ELEVE.value}:
            eleves_classes.append({"label": "Inscrire un élève", "url": "scolarite:inscrire_eleve"})
        if role in ROLES_ETAT_CIVIL_ELEVE:
            eleves_classes.append({"label": "Anciens élèves", "url": "scolarite:anciens_eleves"})
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
    if "notes_bulletins" in modules_autorises and role in ROLES_BULLETINS_MENSUELS:
        pedagogie.append({"label": "Bulletins mensuels", "url": "pedagogie:mensuel_classes"})
    if "suivi_des_cours" in modules_autorises:
        pedagogie.append({"label": "Suivi des cours", "url": "pedagogie:suivi_des_cours"})
        pedagogie.append({"label": "Avancement des programmes", "url": "pedagogie:avancement_programmes"})
    if role in {Role.PARENT.value, Role.ELEVE.value} and "notes_bulletins" in modules_autorises:
        pedagogie.append({"label": "Devoirs", "url": "pedagogie:devoirs"})
    if request.user.etablissement_id and role in {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL}:
        pedagogie.append({"label": "Clôture des notes", "url": "pedagogie:clotures_notes"})
    if pedagogie:
        sections.append({"titre": "Pédagogie", "icone": "pedagogie", "liens": pedagogie})

    finances = []
    if "finances" in modules_autorises:
        finances.append({"label": "Suivi des paiements", "url": "finances:suivi_paiements"})
        finances.append({"label": "Paiements", "url": "finances:liste_paiements"})
        if role == Role.COMPTABLE.value or role in {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL}:
            finances.append({"label": "Frais annexes", "url": "finances:frais_annexes"})
            finances.append({"label": "Arriérés", "url": "finances:arrieres"})
            finances.append({"label": "Vendre des tenues", "url": "finances:tenues_vendre"})
            finances.append({"label": "Stock des tenues", "url": "finances:tenues"})
    if "caisse" in modules_autorises:
        finances.append({"label": "Caisse", "url": "finances:registre_caisse"})
        if request.user.etablissement_id:
            finances.append({"label": "Comptabilité", "url": "comptabilite:accueil"})
    if "salaires" in modules_autorises:
        finances.append({"label": "Salaires", "url": "finances:liste_salaires"})
    if finances:
        sections.append({"titre": "Finances", "icone": "finances", "liens": finances})

    if "cantine" in modules_autorises and request.user.etablissement_id:
        sections.append({"titre": "Cantine", "icone": "cantine", "liens": [
            {"label": "Cantine", "url": "cantine:tableau"},
            {"label": "Appel du jour", "url": "cantine:appel"},
            {"label": "Inscrire des élèves", "url": "cantine:inscrire_eleves"},
            {"label": "Formules et tarifs", "url": "cantine:formules"},
        ]})

    ressources = []
    if request.user.etablissement_id:
        ressources.append({"label": "Calendrier", "url": "scolarite:calendrier"})
    if role in {Role.PARENT.value, Role.ELEVE.value} and request.user.etablissement_id:
        from cantine.models import FormuleCantine  # import local : évite un cycle au chargement des réglages

        if FormuleCantine.objects.filter(etablissement_id=request.user.etablissement_id, active=True).exists():
            ressources.append({"label": "Cantine", "url": "cantine:mon_suivi"})
    if "bibliotheque" in modules_autorises:
        ressources.append({"label": "Bibliothèque", "url": "bibliotheque:liste_documents"})
    if "communication" in modules_autorises:
        ressources.append({"label": "Annonces", "url": "communication:liste_annonces"})
        if role in {Role.PARENT.value, Role.ENSEIGNANT.value}:
            ressources.append({"label": "Messagerie", "url": "communication:liste_conversations"})
    from communication.diffusion import types_pour_role  # import local : évite un cycle au chargement des réglages

    if request.user.etablissement_id and types_pour_role(role, lambda module: module in modules_autorises):
        ressources.append({"label": "Messages aux familles", "url": "communication:messages_a_envoyer"})
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
        "liens": [{"label": "Notifications", "url": "comptes:liste_notifications"}],
    })
    if role in {r.value for r in ROLES_VALIDATION_COMPTES}:
        administration.append({"label": "Comptes en attente", "url": "comptes:comptes_en_attente"})
    if request.user.etablissement_id and role in {r.value for r in ROLES_VALIDATION_COMPTES}:
        administration.append({"label": "Noms en arabe", "url": "comptes:noms_en_arabe"})
    if role == Role.DEVELOPPEUR.value and request.user.etablissement_id:
        administration.append({"label": "Établissement", "url": "espace_developpeur:parametres_etablissement"})
        administration.append({"label": "Années scolaires", "url": "espace_developpeur:annees_scolaires"})
        administration.append({"label": "Comptes", "url": "espace_developpeur:liste_comptes"})
        administration.append({"label": "Matrice de permissions", "url": "espace_developpeur:matrice_permissions"})
        administration.append({"label": "Journal d'audit", "url": "espace_developpeur:journal_audit"})
    if administration:
        sections.append({"titre": "Administration", "icone": "administration", "liens": administration})

    if getattr(request.user, "is_superuser", False):
        sections.append({
            "titre": "Plateforme",
            "icone": "plateforme",
            "liens": [
                {"label": "Établissements", "url": "espace_plateforme:liste_etablissements"},
                {"label": "Abonnements", "url": "espace_plateforme:abonnements"},
            ],
        })

    return {
        "sections_navigation": habiller_les_liens(sections, notifications_non_lues),
        "notifications_non_lues": notifications_non_lues,
        "peut_rechercher_eleves": "eleves" in modules_autorises,
        "app_version": settings.APP_VERSION,
    }


def acces_delegue(request):
    """Indique au gabarit de base qu'un propriétaire est connecté au compte d'une école (bandeau de retour)."""
    from comptes.middleware import CLE_SESSION_ACCES_DELEGUE

    session = getattr(request, "session", None)
    if session is not None and session.get(CLE_SESSION_ACCES_DELEGUE):
        return {"acces_delegue": True}
    return {}


def identite_plateforme(request):
    """Nom, slogan et description de la plateforme (Yelenova), disponibles dans tous les gabarits."""
    return {
        "nom_plateforme": settings.NOM_PLATEFORME,
        "nom_commercial": settings.NOM_COMMERCIAL,
        "slogan_plateforme": settings.SLOGAN_PLATEFORME,
        "positionnement_plateforme": settings.POSITIONNEMENT_PLATEFORME,
        "description_plateforme": settings.DESCRIPTION_PLATEFORME,
    }
