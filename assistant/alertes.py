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

    select_related/prefetch_related choisis précisément pour que les deux
    fonctions d'alerte ci-dessous n'aient plus besoin d'une requête par
    élève (voir leur historique : 703 requêtes et 2,7s mesurées pour 100
    élèves avant ce correctif - une requête de plus ici coûte bien moins
    cher qu'une requête en moins dans une boucle Python).
    """
    from django.db.models import Prefetch

    from scolarite.models import AideScolarite, Inscription, classes_visibles_pour

    aides_actives = Prefetch(
        "aides_scolarite", queryset=AideScolarite.objects.filter(active=True), to_attr="aides_actives_prefetchees",
    )

    if utilisateur.role == Role.ENSEIGNANT:
        base = Inscription.objects.filter(
            classe__affectations__enseignant=utilisateur,
            statut=Inscription.Statut.EN_COURS,
        ).distinct()
    else:
        classes = classes_visibles_pour(utilisateur)
        base = Inscription.objects.filter(classe__in=classes, statut=Inscription.Statut.EN_COURS)

    return base.select_related("eleve", "classe", "classe__annee_scolaire", "classe__echeancier").prefetch_related(aides_actives)


def _eleves_a_risque_academique(utilisateur):
    """
    Moyenne pondérée par élève, calculée en UNE requête groupée par classe
    (pas une par élève - voir pedagogie.views._calculer_bulletin pour
    l'équivalent "un seul élève", dont ceci reprend exactement le même
    calcul, juste groupé).
    """
    from collections import defaultdict

    from django.db.models import DecimalField, ExpressionWrapper, F, Sum

    from pedagogie.models import Note

    inscriptions = list(_inscriptions_visibles_pour_alertes(utilisateur))
    if not inscriptions:
        return []

    inscriptions_par_classe = defaultdict(list)
    for inscription in inscriptions:
        inscriptions_par_classe[inscription.classe_id].append(inscription)

    a_risque = []
    for classe_id, inscriptions_classe in inscriptions_par_classe.items():
        inscription_par_eleve = {i.eleve_id: i for i in inscriptions_classe}
        lignes = (
            Note.objects.filter(affectation__classe_id=classe_id, eleve_id__in=inscription_par_eleve.keys())
            .values("eleve_id")
            .annotate(
                total_pondere=Sum(
                    ExpressionWrapper(
                        F("valeur") * F("affectation__coefficient"),
                        output_field=DecimalField(max_digits=12, decimal_places=2),
                    ),
                ),
                poids=Sum("affectation__coefficient"),
            )
        )
        for ligne in lignes:
            if not ligne["poids"]:
                continue
            moyenne = ligne["total_pondere"] / ligne["poids"]
            if moyenne < SEUIL_MOYENNE_RISQUE:
                inscription = inscription_par_eleve[ligne["eleve_id"]]
                a_risque.append({"eleve": inscription.eleve, "classe": inscription.classe, "moyenne": round(moyenne, 2)})
    return a_risque


def _familles_impayees(utilisateur):
    """
    total_du réutilise scolarite.models.calculer_total_du tel quel (même
    calcul de remise, pas dupliqué) - rendu sans requête supplémentaire
    par élève grâce au select_related/prefetch_related déjà posés par
    _inscriptions_visibles_pour_alertes (classe__echeancier,
    aides_actives_prefetchees). Seul total_paye est groupé en une requête
    pour tous les élèves d'un coup, au lieu d'une par élève.
    """
    from django.db.models import Sum

    from finances.models import Paiement
    from scolarite.models import calculer_total_du

    aujourdhui = date.today()
    candidates = []
    for inscription in _inscriptions_visibles_pour_alertes(utilisateur):
        annee = inscription.classe.annee_scolaire
        if not annee.est_active:
            continue
        duree_totale = (annee.date_fin - annee.date_debut).days or 1
        ecoule = (aujourdhui - annee.date_debut).days
        avancement = max(Decimal(ecoule) / Decimal(duree_totale), Decimal("0"))
        if avancement >= SEUIL_AVANCEMENT_ANNEE:
            candidates.append(inscription)
    if not candidates:
        return []

    totaux_payes = dict(
        Paiement.objects.filter(
            inscription_id__in=[i.id for i in candidates], est_supprime=False,
        ).values_list("inscription_id").annotate(total=Sum("montant")),
    )

    impayees = []
    for inscription in candidates:
        total_du = calculer_total_du(inscription, aides_actives=inscription.aides_actives_prefetchees)
        total_paye = totaux_payes.get(inscription.id, 0)
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
