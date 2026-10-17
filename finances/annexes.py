"""
Frais annexes et arriérés.

Un arriéré est ce qui reste dû pour une inscription d'une année déjà passée (élève admis, redoublant, transféré ou parti sans avoir tout payé) :
calculé avec la classe de l'époque (son échéancier, ses aides, ses frais annexes), jamais avec la classe actuelle.
"""
from django.db.models import Sum

from finances.models import FraisAnnexe, Paiement, TypeTranche
from scolarite.models import Inscription, calculer_scolarite_nette, calculer_total_du, classes_visibles_pour

TRANCHES_DE_SCOLARITE = (TypeTranche.INSCRIPTION, TypeTranche.VERSEMENT)


def totaux_annexes(inscriptions):
    """
    Pour une série d'inscriptions : une fonction `total(inscription)` qui rend la somme de leurs frais annexes, avec UNE seule requête
    (à utiliser dans une boucle à la place d'une requête par élève).
    """
    inscriptions = list(inscriptions)
    annees = {i.classe.annee_scolaire_id for i in inscriptions}
    frais = list(FraisAnnexe.objects.filter(annee_scolaire_id__in=annees).values_list("annee_scolaire_id", "classe_id", "montant")) if annees else []

    def total(inscription) -> int:
        classe = inscription.classe
        return sum(
            montant for annee_id, classe_id, montant in frais
            if annee_id == classe.annee_scolaire_id and (classe_id is None or classe_id == classe.pk)
        )

    return total


def total_paye(inscription) -> int:
    return Paiement.objects.filter(inscription=inscription, est_supprime=False).aggregate(total=Sum("montant"))["total"] or 0


def reste_a_payer(inscription) -> int:
    """Ce qui reste dû pour cette inscription (scolarité et frais annexes), jamais négatif."""
    return max(calculer_total_du(inscription) - total_paye(inscription), 0)


def limite_de_paiement(inscription, tranche, frais_annexe=None):
    """
    Le plus qu'un paiement peut encore verser pour cette tranche, ou None s'il n'y a rien à comparer (l'école n'a défini aucun échéancier pour cette
    classe : elle enregistre ses reçus sans montant attendu).
    - frais annexe : le montant du frais moins ce que cet élève en a déjà réglé ;
    - scolarité : la scolarité nette des aides moins ce qui en a déjà été réglé (hors frais annexes).
    """
    if tranche == TypeTranche.ANNEXE:
        if frais_annexe is None:
            return None
        deja = Paiement.objects.filter(
            eleve_id=inscription.eleve_id, frais_annexe=frais_annexe, est_supprime=False,
        ).aggregate(total=Sum("montant"))["total"] or 0
        return max(frais_annexe.montant - deja, 0)
    nette = calculer_scolarite_nette(inscription)
    if not nette:
        return None
    deja = Paiement.objects.filter(
        inscription=inscription, tranche__in=TRANCHES_DE_SCOLARITE, est_supprime=False,
    ).aggregate(total=Sum("montant"))["total"] or 0
    return max(nette - deja, 0)


def frais_annexes_de(inscription):
    """Les frais annexes que cette inscription doit (de sa classe et de toute l'école, pour son année)."""
    from django.db.models import Q

    classe = inscription.classe
    return FraisAnnexe.objects.filter(annee_scolaire_id=classe.annee_scolaire_id).filter(Q(classe__isnull=True) | Q(classe_id=classe.pk))


def lignes_d_arrieres(inscriptions):
    """
    Les arriérés d'une série d'inscriptions d'années passées : [{inscription, total_du, total_paye, solde}] pour celles qui n'ont pas tout payé,
    les plus gros soldes d'abord. Quelques requêtes en tout, quel que soit le nombre d'inscriptions.
    """
    from django.db.models import Prefetch

    from scolarite.models import AideScolarite

    inscriptions = list(
        Inscription.objects.filter(pk__in=[i.pk for i in inscriptions]).select_related(
            "eleve", "classe", "classe__echeancier", "classe__annee_scolaire",
        ).prefetch_related(Prefetch("aides_scolarite", queryset=AideScolarite.objects.filter(active=True), to_attr="aides_actives_prefetchees"))
    )
    annexes = totaux_annexes(inscriptions)
    payes = dict(
        Paiement.objects.filter(inscription__in=inscriptions, est_supprime=False).values_list("inscription_id").annotate(total=Sum("montant"))
    )
    lignes = []
    for inscription in inscriptions:
        du = calculer_total_du(inscription, aides_actives=inscription.aides_actives_prefetchees, annexes=annexes(inscription))
        paye = payes.get(inscription.pk, 0)
        if du - paye > 0:
            lignes.append({"inscription": inscription, "total_du": du, "total_paye": paye, "solde": du - paye})
    return sorted(lignes, key=lambda ligne: (-ligne["solde"], ligne["inscription"].eleve.nom, ligne["inscription"].pk))


def inscriptions_passees(utilisateur, eleves=None):
    """Les inscriptions d'années passées (plus en cours) des classes que cet utilisateur voit, pour tous les élèves ou ceux donnés."""
    inscriptions = Inscription.objects.filter(classe__in=classes_visibles_pour(utilisateur)).exclude(statut=Inscription.Statut.EN_COURS)
    if eleves is not None:
        inscriptions = inscriptions.filter(eleve__in=eleves)
    return inscriptions


def arrieres_des_eleves(eleves, utilisateur) -> dict:
    """{eleve_id: total des arriérés} pour ces élèves (ceux qui n'en ont pas n'apparaissent pas)."""
    resultat = {}
    for ligne in lignes_d_arrieres(inscriptions_passees(utilisateur, eleves)):
        eleve_id = ligne["inscription"].eleve_id
        resultat[eleve_id] = resultat.get(eleve_id, 0) + ligne["solde"]
    return resultat
