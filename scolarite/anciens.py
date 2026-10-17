"""
Anciens élèves : ceux qui ont quitté l'établissement (transfert, abandon) et n'ont plus d'inscription en cours ; leur réintégration.

Réintégrer un élève : s'il avait déjà une inscription close cette année-là, elle est rouverte (dans la classe choisie) ; sinon une nouvelle
inscription est créée. La décision de sortie (transfert ou abandon) est alors effacée : le journal d'audit en garde la trace.
"""
from django.core.exceptions import ValidationError
from django.db import transaction

from comptes.models import Utilisateur
from comptes.roles import Role
from scolarite.models import Inscription, classes_visibles_pour

STATUTS_DE_SORTIE = (Inscription.Statut.TRANSFERE, Inscription.Statut.ABANDON)
PREFIXE_ANONYME = "ANON-"


def derniere_sortie_par_eleve(utilisateur, *, annee_id=None, recherche=""):
    """
    Les anciens élèves visibles pour cet utilisateur : une ligne par élève, avec sa dernière inscription close, les plus récents d'abord.
    [{eleve, inscription, type, date, destination}]
    """
    sorties = Inscription.objects.filter(
        classe__in=classes_visibles_pour(utilisateur), statut__in=STATUTS_DE_SORTIE,
    ).exclude(eleve__matricule__startswith=PREFIXE_ANONYME).select_related(
        "eleve", "classe__annee_scolaire", "transfert", "abandon",
    )
    if annee_id:
        sorties = sorties.filter(classe__annee_scolaire_id=annee_id)
    if recherche:
        from django.db.models import Q

        sorties = sorties.filter(
            Q(eleve__nom__icontains=recherche) | Q(eleve__prenom__icontains=recherche) | Q(eleve__matricule__icontains=recherche),
        )
    sorties = sorties.exclude(
        eleve_id__in=Inscription.objects.filter(statut=Inscription.Statut.EN_COURS).values("eleve_id"),
    ).order_by("-classe__annee_scolaire__date_debut", "-pk")
    lignes, vus = [], set()
    for inscription in sorties:
        if inscription.eleve_id in vus:
            continue
        vus.add(inscription.eleve_id)
        transfert = getattr(inscription, "transfert", None) if inscription.statut == Inscription.Statut.TRANSFERE else None
        abandon = getattr(inscription, "abandon", None) if inscription.statut == Inscription.Statut.ABANDON else None
        lignes.append({
            "eleve": inscription.eleve, "inscription": inscription, "type": inscription.get_statut_display(),
            "date": transfert.date_transfert if transfert else (abandon.date_abandon if abandon else None),
            "destination": (transfert.destination_libelle or (transfert.etablissement_destination.nom if transfert.etablissement_destination_id else "")) if transfert else "",
        })
    return sorted(lignes, key=lambda ligne: (ligne["date"] is None, -(ligne["date"].toordinal() if ligne["date"] else 0), ligne["eleve"].nom))


def est_ancien_eleve(eleve) -> bool:
    inscriptions = list(Inscription.objects.filter(eleve=eleve).values_list("statut", flat=True))
    return bool(inscriptions) and Inscription.Statut.EN_COURS not in inscriptions and any(s in STATUTS_DE_SORTIE for s in inscriptions)


def classes_de_reintegration(utilisateur):
    """Les classes où l'on peut remettre un élève : celles de l'établissement dont l'année n'est pas archivée."""
    return classes_visibles_pour(utilisateur).filter(annee_scolaire__est_archivee=False).order_by("annee_scolaire__date_debut", "nom")


@transaction.atomic
def reintegrer(eleve, classe) -> Inscription:
    """
    Remet l'élève en cours dans `classe`. Lève ValidationError s'il est déjà inscrit quelque part, si l'année de la classe est archivée ou s'il
    n'a jamais quitté l'école. Rend l'inscription (rouverte ou nouvelle).
    """
    if eleve.role != Role.ELEVE:
        raise ValidationError("Seul un élève peut être réintégré.")
    if Inscription.objects.filter(eleve=eleve, statut=Inscription.Statut.EN_COURS).exists():
        raise ValidationError("Cet élève est déjà inscrit dans une classe.")
    if classe.annee_scolaire.est_archivee:
        raise ValidationError("Cette année scolaire est archivée : on ne peut plus y inscrire d'élève.")
    if eleve.etablissement_id != classe.annee_scolaire.etablissement_id:
        raise ValidationError("L'élève et la classe doivent appartenir au même établissement.")
    sortie = Inscription.objects.filter(eleve=eleve, classe__annee_scolaire=classe.annee_scolaire, statut__in=STATUTS_DE_SORTIE).first()
    if sortie is not None:  # il revient dans l'année même où il est parti : son inscription est rouverte, dans la classe choisie
        for decision in ("transfert", "abandon"):
            lien = getattr(sortie, decision, None)
            if lien is not None:
                if getattr(lien, "justificatif", None):
                    lien.justificatif.delete(save=False)
                lien.delete()
        sortie = Inscription.objects.get(pk=sortie.pk)  # relu : les liens supprimés ne sont plus en mémoire
        sortie.classe = classe
        sortie.statut = Inscription.Statut.EN_COURS
        sortie.save()
        return sortie
    return Inscription.objects.create(eleve=eleve, classe=classe)
