"""
Le numéro d'un élève dans chaque cycle.

Le matricule d'origine ne change jamais (identifiant de connexion, clé du dossier, adresses des pages). Chaque cycle (1er cycle, 2ème
cycle, lycée, professionnel) peut en plus donner SON numéro, imprimé sur les documents de ce cycle (carte, bulletin, attestation,
certificats, listes). Un cycle sans numéro propre garde le matricule d'origine : rien ne change tant qu'on n'a rien saisi.
"""
import re
from collections import Counter

from django.db import transaction
from django.db.models import F

from comptes.arabisation import chiffres_ascii
from comptes.models import Utilisateur
from scolarite.models import Classe, Inscription, NumeroCycle

# Des chiffres, des lettres, et ./-_ ou espace au milieu (« 12-345/A ») : jamais un texte libre ni un caractère de formule Excel.
FORME_NUMERO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ./_-]{0,19}$")


def numero_du_cycle(eleve, cycle) -> str:
    """Le numéro de l'élève dans ce cycle, sinon son matricule d'origine. Passe par `numeros_cycle.all()` : préchargeable en liste."""
    for ligne in eleve.numeros_cycle.all():
        if ligne.cycle == cycle:
            return ligne.numero
    return eleve.matricule or ""


def ajouter_les_numeros(inscriptions) -> list:
    """
    Pose `numero_cycle` sur chaque inscription (le numéro de l'élève dans le cycle de SA classe), avec une seule requête pour toute la
    liste. Rend la liste, pour s'enchaîner avec un filtre.
    """
    inscriptions = list(inscriptions)
    propres = {
        (ligne.eleve_id, ligne.cycle): ligne.numero
        for ligne in NumeroCycle.objects.filter(eleve_id__in={inscription.eleve_id for inscription in inscriptions})
    }
    for inscription in inscriptions:
        inscription.numero_cycle = propres.get((inscription.eleve_id, inscription.classe.cycle), inscription.eleve.matricule or "")
    return inscriptions


def numero_de_l_inscription(inscription) -> str:
    """Le numéro de l'élève dans le cycle de la classe de cette inscription."""
    return numero_du_cycle(inscription.eleve, inscription.classe.cycle)


def numeros_des_eleves(eleves_ids, annee=None, classes=None) -> dict:
    """
    `{id de l'élève: son numéro}` pour toute une liste, en trois requêtes : le numéro du cycle de sa classe de l'année `annee` (si elle est
    donnée), sinon de sa classe en cours, sinon de sa classe la plus récente. Un élève sans inscription garde son matricule d'origine.
    `classes` (un queryset) limite le choix aux classes que la personne peut voir : jamais le numéro d'un cycle qui ne la concerne pas.
    Sert aux pages qui ne partent pas d'une inscription (reçus de tenues, de cantine, recherche d'un élève).
    """
    eleves_ids = list(eleves_ids)
    inscriptions = Inscription.objects.filter(eleve_id__in=eleves_ids).select_related("classe__annee_scolaire")
    if annee is not None:
        inscriptions = inscriptions.filter(classe__annee_scolaire=annee)
    if classes is not None:
        inscriptions = inscriptions.filter(classe__in=classes)
    cycles = {}
    for inscription in sorted(
        inscriptions, key=lambda i: (i.statut != Inscription.Statut.EN_COURS, -i.classe.annee_scolaire.date_debut.toordinal()),
    ):
        cycles.setdefault(inscription.eleve_id, inscription.classe.cycle)
    propres = {(ligne.eleve_id, ligne.cycle): ligne.numero for ligne in NumeroCycle.objects.filter(eleve_id__in=cycles)}
    matricules = dict(Utilisateur.objects.filter(pk__in=eleves_ids).values_list("pk", "matricule"))
    return {
        eleve_id: propres.get((eleve_id, cycles.get(eleve_id)), matricules.get(eleve_id) or "") for eleve_id in eleves_ids
    }


def ajouter_les_numeros_de_la_classe(eleves, classe_id) -> list:
    """Pose `numero_cycle` (le numéro dans le cycle de cette classe, sinon le matricule) sur ces élèves ; rend la liste."""
    eleves = list(eleves)
    cycle = Classe.objects.filter(pk=classe_id).values_list("cycle", flat=True).first()
    propres = {
        ligne.eleve_id: ligne.numero for ligne in NumeroCycle.objects.filter(eleve_id__in=[eleve.pk for eleve in eleves], cycle=cycle)
    }
    for eleve in eleves:
        eleve.numero_cycle = propres.get(eleve.pk, eleve.matricule or "")
    return eleves


def eleves_dont_le_numero_contient(etablissement, texte):
    """
    Sous-requête des ids d'élèves de cette école dont le numéro DANS LE CYCLE DE LEUR CLASSE EN COURS contient `texte` (pour une recherche
    `eleve_id__in=...`). Le numéro d'un ancien cycle ne désigne plus personne dans les pages de la classe actuelle.
    """
    return Inscription.objects.filter(
        classe__annee_scolaire__etablissement=etablissement, statut=Inscription.Statut.EN_COURS,
        eleve__numeros_cycle__numero__icontains=texte, eleve__numeros_cycle__cycle=F("classe__cycle"),
    ).values("eleve_id")


def _nettoyer(texte) -> str:
    """Espaces simples, chiffres de 0 à 9 (un fichier ou un clavier en chiffres arabes-indiens donne le même numéro)."""
    return " ".join(chiffres_ascii(texte or "").split())


def eleves_de_la_classe(classe) -> dict:
    """`{id: élève}` des élèves dont on peut régler le numéro dans cette classe (pas ceux qui ont quitté l'école)."""
    inscriptions = Inscription.objects.filter(classe=classe).exclude(
        statut__in=[Inscription.Statut.ABANDON, Inscription.Statut.TRANSFERE],
    ).select_related("eleve")
    return {inscription.eleve_id: inscription.eleve for inscription in inscriptions}


def _verifier(classe, saisies):
    """`(élèves de la classe, {id: numéro voulu ou None}, {id: message d'erreur})` pour ces saisies, sans rien écrire."""
    eleves = eleves_de_la_classe(classe)
    voulus = {}
    erreurs = {}
    for eleve_id, texte in saisies.items():
        eleve = eleves.get(eleve_id)
        if eleve is None:
            continue
        valeur = _nettoyer(texte)
        if not valeur or valeur == eleve.matricule:
            voulus[eleve_id] = None
        elif not FORME_NUMERO.match(valeur):
            erreurs[eleve_id] = "Chiffres, lettres, espace, point, tiret ou barre oblique seulement (20 signes au plus)."
        else:
            voulus[eleve_id] = valeur

    etablissement_id = classe.annee_scolaire.etablissement_id
    clefs = Counter(valeur.casefold() for valeur in voulus.values() if valeur)
    for eleve_id, valeur in voulus.items():
        if valeur and clefs[valeur.casefold()] > 1:
            erreurs.setdefault(eleve_id, "Ce numéro est saisi deux fois dans la liste.")

    a_verifier = {valeur.casefold() for valeur in voulus.values() if valeur}
    if a_verifier:
        pris = {
            ligne.numero.casefold(): ligne.eleve_id
            for ligne in NumeroCycle.objects.filter(etablissement_id=etablissement_id, cycle=classe.cycle).exclude(eleve_id__in=voulus)
        }
        # Seulement les matricules des élèves de CETTE classe (déjà écrits dans la page) : refuser le matricule d'un élève d'une autre classe
        # ou d'un autre cycle dirait à une personne de ce cycle qu'il existe, alors qu'il ne la concerne pas.
        matricules = {eleve.matricule.casefold(): pk for pk, eleve in eleves.items() if eleve.matricule and eleve.matricule.casefold() in a_verifier}
        for eleve_id, valeur in voulus.items():
            if not valeur or eleve_id in erreurs:
                continue
            if valeur.casefold() in pris:
                erreurs[eleve_id] = "Ce numéro est déjà celui d'un autre élève dans ce cycle."
            elif matricules.get(valeur.casefold(), eleve_id) != eleve_id:
                erreurs[eleve_id] = "Ce numéro est le matricule d'un autre élève de la classe."
    return eleves, voulus, erreurs


def verifier_les_numeros(classe, saisies) -> dict:
    """Les refus que `enregistrer_les_numeros` opposerait à ces saisies (`{id de l'élève: message}`), sans rien écrire."""
    return _verifier(classe, saisies)[2]


def enregistrer_les_numeros(classe, saisies) -> tuple[dict, dict]:
    """
    Enregistre les numéros du cycle de `classe` pour les élèves de sa liste (`saisies` : `{id de l'élève: texte tapé}`, un élève absent de
    la liste est ignoré). Un champ vide ou égal au matricule d'origine efface le numéro propre (le matricule reprend sa place).

    Rend `(compteurs, erreurs)`. Au moindre refus (forme, doublon dans la saisie, numéro déjà pris dans ce cycle de l'école, ou matricule
    d'un autre élève), RIEN n'est écrit et `erreurs` dit pourquoi, élève par élève (`{id: message}`).
    """
    eleves, voulus, erreurs = _verifier(classe, saisies)
    if erreurs:
        return {}, erreurs

    actuels = {
        ligne.eleve_id: ligne for ligne in NumeroCycle.objects.filter(eleve_id__in=voulus, cycle=classe.cycle)
    }
    compteurs = {"ajoutes": 0, "modifies": 0, "supprimes": 0}
    a_creer = []
    with transaction.atomic():
        # Les lignes qui changent ou disparaissent sont retirées D'ABORD : deux élèves peuvent ainsi échanger leurs numéros.
        for eleve_id, valeur in voulus.items():
            ligne = actuels.get(eleve_id)
            if ligne is not None and ligne.numero != valeur:
                ligne.delete()
                compteurs["supprimes" if valeur is None else "modifies"] += 1
            if valeur and (ligne is None or ligne.numero != valeur):
                if ligne is None:
                    compteurs["ajoutes"] += 1
                a_creer.append(NumeroCycle(eleve=eleves[eleve_id], cycle=classe.cycle, numero=valeur))
        for nouveau in a_creer:
            nouveau.save()
    return compteurs, {}
