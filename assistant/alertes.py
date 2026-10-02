"""
Alertes proactives du tableau de bord.

Les chiffres sont TOUJOURS calculés par requête déterministe (jamais par
l'IA) : seule la phrase de synthèse optionnelle (voir
assistant.services.resumer_alertes_avec_ia) passe par Groq, et uniquement
pour reformuler des chiffres déjà exacts - jamais pour les calculer. Si
l'API est indisponible, les alertes restent affichées normalement.

Sécurité : la visibilité de chaque type d'alerte est volontairement une
liste explicite de rôles (ROLES_ALERTE_ACADEMIQUE / ROLES_ALERTE_FINANCIERE),
PAS une simple vérification du module autorisé. Un parent ou un élève ont
le module notes_bulletins/finances dans leur propre matrice, mais pour
consulter UNIQUEMENT leurs propres données (portail_parent, tableau de
bord personnel) - jamais une vue agrégée sur d'autres élèves ou familles.
Dériver la visibilité du module aurait fuité ces agrégats vers eux.
"""

from datetime import date
from decimal import Decimal

from comptes.roles import Role

SEUIL_MOYENNE_RISQUE = Decimal("10")  # seuil de passage classique, sur 20
SEUIL_AVANCEMENT_ANNEE = Decimal("0.4")  # 40% de l'année écoulée avant de signaler un impayé

ROLES_ALERTE_ACADEMIQUE = {
    Role.DEVELOPPEUR, Role.FONDATEUR, Role.ADMINISTRATEUR_GENERAL,
    Role.DIRECTEUR_1ER_CYCLE, Role.DIRECTEUR_2EME_CYCLE,
    Role.RESPONSABLE_PEDAGOGIQUE, Role.ENSEIGNANT,
}
ROLES_ALERTE_FINANCIERE = {
    Role.DEVELOPPEUR, Role.FONDATEUR, Role.ADMINISTRATEUR_GENERAL, Role.COMPTABLE,
}


def _inscriptions_visibles_pour_alertes(utilisateur):
    """
    Même esprit que scolarite.models.eleve_visible_pour, mais en une seule
    requête (pas un eleve_visible_pour par élève) : un enseignant ne voit
    que ses propres classes affectées, les autres rôles de la liste
    d'autorisation voient tout l'établissement (cloisonné par cycle le cas
    échéant, via classes_visibles_pour).
    """
    from scolarite.models import Inscription, classes_visibles_pour

    if utilisateur.role == Role.ENSEIGNANT:
        return Inscription.objects.filter(
            classe__affectations__enseignant=utilisateur,
            statut=Inscription.Statut.EN_COURS,
        ).select_related("eleve", "classe").distinct()

    classes = classes_visibles_pour(utilisateur)
    return Inscription.objects.filter(
        classe__in=classes, statut=Inscription.Statut.EN_COURS,
    ).select_related("eleve", "classe")


def _eleves_a_risque_academique(utilisateur):
    from pedagogie.views import _calculer_bulletin

    a_risque = []
    for inscription in _inscriptions_visibles_pour_alertes(utilisateur):
        resultat = _calculer_bulletin(inscription.eleve, inscription)
        moyenne = resultat["moyenne_generale"]
        if moyenne is not None and moyenne < SEUIL_MOYENNE_RISQUE:
            a_risque.append({"eleve": inscription.eleve, "classe": inscription.classe, "moyenne": moyenne})
    return a_risque


def _familles_impayees(utilisateur):
    from django.db.models import Sum

    from finances.models import Paiement
    from scolarite.models import calculer_total_du

    impayees = []
    for inscription in _inscriptions_visibles_pour_alertes(utilisateur):
        annee = inscription.classe.annee_scolaire
        if not annee.est_active:
            continue
        duree_totale = (annee.date_fin - annee.date_debut).days or 1
        ecoule = (date.today() - annee.date_debut).days
        avancement = max(Decimal(ecoule) / Decimal(duree_totale), Decimal("0"))
        if avancement < SEUIL_AVANCEMENT_ANNEE:
            continue
        total_du = calculer_total_du(inscription)
        total_paye = Paiement.objects.filter(
            inscription=inscription, est_supprime=False,
        ).aggregate(total=Sum("montant"))["total"] or 0
        solde = total_du - total_paye
        if solde > 0:
            impayees.append({"eleve": inscription.eleve, "classe": inscription.classe, "solde": solde})
    return impayees


def construire_alertes(utilisateur):
    """
    Retourne la liste des alertes visibles pour ce rôle - voir le module
    docstring pour la raison des listes de rôles explicites plutôt qu'un
    simple test de module autorisé.
    """
    alertes = []

    if utilisateur.role in {r.value for r in ROLES_ALERTE_ACADEMIQUE}:
        eleves = _eleves_a_risque_academique(utilisateur)
        if eleves:
            alertes.append({
                "type": "academique",
                "titre": f"{len(eleves)} élève(s) en risque de redoublement",
                "description": "Moyenne générale pondérée sous 10/20, tous trimestres saisis confondus.",
                "details": eleves,
            })

    if utilisateur.role in {r.value for r in ROLES_ALERTE_FINANCIERE}:
        familles = _familles_impayees(utilisateur)
        if familles:
            alertes.append({
                "type": "financier",
                "titre": f"{len(familles)} élève(s) avec des frais impayés",
                "description": "Solde dû alors que l'année scolaire est déjà bien avancée.",
                "details": familles,
            })

    return alertes
