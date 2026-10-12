"""Règles d'accès aux fils d'équipe enseignants."""

from django.db import IntegrityError, transaction
from django.db.models import Count, OuterRef, Subquery

from communication.models import FilEquipe, MessageEquipe, PorteeEquipe, normaliser_matiere
from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role
from scolarite.models import Affectation, AnneeScolaire, classes_visibles_pour

ROLES_SUPERVISION_EQUIPES = {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL} | {
    Role.DIRECTEUR_1ER_CYCLE.value, Role.DIRECTEUR_2EME_CYCLE.value, Role.DIRECTEUR_LYCEE.value,
    Role.CENSEUR.value, Role.RESPONSABLE_PEDAGOGIQUE.value, Role.SUPER_ADMINISTRATEUR.value,
}


def peut_utiliser_equipes(utilisateur) -> bool:
    return bool(
        utilisateur.is_authenticated and utilisateur.etablissement_id
        and (utilisateur.role == Role.ENSEIGNANT or utilisateur.role in ROLES_SUPERVISION_EQUIPES)
    )


def annee_active(utilisateur):
    return AnneeScolaire.active(utilisateur.etablissement_id) if utilisateur.etablissement_id else None


def _affectations_visibles(utilisateur, annee):
    if utilisateur.role == Role.ENSEIGNANT:
        return Affectation.objects.filter(enseignant=utilisateur, classe__annee_scolaire=annee)
    return Affectation.objects.filter(classe__in=classes_visibles_pour(utilisateur).filter(annee_scolaire=annee))


def _classes_visibles(utilisateur, annee):
    if utilisateur.role == Role.ENSEIGNANT:
        return classes_visibles_pour(utilisateur).filter(
            annee_scolaire=annee, affectations__enseignant=utilisateur,
        ).distinct()
    return classes_visibles_pour(utilisateur).filter(annee_scolaire=annee)


def fils_proposes_pour(utilisateur):
    if not peut_utiliser_equipes(utilisateur):
        return []
    annee = annee_active(utilisateur)
    if annee is None:
        return []
    propositions, vus = [], set()

    def ajouter(portee, classe=None, niveau="", matiere="", matiere_affichee=""):
        cle = (portee, classe.pk if classe else None, niveau, matiere)
        if cle not in vus:
            vus.add(cle)
            propositions.append({
                "portee": portee, "classe": classe, "niveau": niveau,
                "matiere": matiere, "matiere_affichee": matiere_affichee,
            })

    for classe in _classes_visibles(utilisateur, annee).order_by("niveau", "nom"):
        ajouter(PorteeEquipe.CLASSE, classe=classe)
    for classe in _classes_visibles(utilisateur, annee).exclude(niveau="").order_by("niveau"):
        ajouter(PorteeEquipe.NIVEAU, niveau=classe.niveau)
    affectations = _affectations_visibles(utilisateur, annee).select_related("classe").exclude(
        matiere="",
    ).exclude(classe__niveau="").order_by("classe__niveau", "matiere")
    for affectation in affectations:
        matiere = normaliser_matiere(affectation.matiere)
        if matiere:
            ajouter(
                PorteeEquipe.MATIERE_NIVEAU, niveau=affectation.classe.niveau, matiere=matiere,
                matiere_affichee=" ".join(affectation.matiere.split()),
            )
    return propositions


def obtenir_ou_creer_fil(utilisateur, proposition) -> FilEquipe:
    annee = annee_active(utilisateur)
    if annee is None:
        raise FilEquipe.DoesNotExist
    classe = proposition["classe"]
    cle = FilEquipe.construire_cle(
        annee.pk, proposition["portee"], classe.pk if classe else None,
        proposition["niveau"], proposition["matiere"],
    )
    defaults = {
        "etablissement_id": utilisateur.etablissement_id,
        "annee_scolaire": annee,
        "portee": proposition["portee"],
        "classe": classe,
        "niveau": proposition["niveau"],
        "matiere": proposition["matiere"],
        "matiere_affichee": proposition["matiere_affichee"],
    }
    try:
        with transaction.atomic():
            fil, _ = FilEquipe.objects.get_or_create(cle=cle, defaults=defaults)
            return fil
    except IntegrityError:
        # Une requête concurrente a pu créer le même fil entre le SELECT et l'INSERT.
        return FilEquipe.objects.get(cle=cle)


def _affectations_du_fil(fil, affectations):
    if fil.portee == PorteeEquipe.CLASSE:
        return affectations.filter(classe_id=fil.classe_id)
    if not fil.niveau:
        return affectations.none()
    par_niveau = affectations.filter(classe__niveau=fil.niveau)
    if fil.portee == PorteeEquipe.NIVEAU:
        return par_niveau
    ids = [
        affectation.pk for affectation in par_niveau.select_related("classe")
        if normaliser_matiere(affectation.matiere) == fil.matiere
    ]
    return affectations.filter(pk__in=ids)


def peut_acceder_fil(utilisateur, fil) -> bool:
    if not peut_utiliser_equipes(utilisateur) or utilisateur.etablissement_id != fil.etablissement_id:
        return False
    annee = annee_active(utilisateur)
    if annee is None or fil.annee_scolaire_id != annee.pk:
        return False
    return _affectations_du_fil(fil, _affectations_visibles(utilisateur, annee)).exists()


def membres_du_fil(fil):
    from comptes.models import Utilisateur

    affectations = Affectation.objects.filter(
        classe__annee_scolaire=fil.annee_scolaire, enseignant__etablissement_id=fil.etablissement_id,
    )
    ids = _affectations_du_fil(fil, affectations).values_list("enseignant_id", flat=True)
    return Utilisateur.objects.filter(
        pk__in=ids, is_active=True, role=Role.ENSEIGNANT,
    ).order_by("nom", "prenom")

def obtenir_ou_creer_fils(utilisateur, propositions) -> list[FilEquipe]:
    """
    Version groupée de obtenir_ou_creer_fil : un nombre de requêtes constant, quel que soit le
    nombre de fils (une direction voit un fil par classe, par niveau et par matière). Les fils
    manquants sont créés d'un coup ; une création concurrente est ignorée (ignore_conflicts) puis
    relue, comme le get_or_create de obtenir_ou_creer_fil.
    """
    annee = annee_active(utilisateur)
    if annee is None:
        raise FilEquipe.DoesNotExist
    cles = [
        FilEquipe.construire_cle(
            annee.pk, p["portee"], p["classe"].pk if p["classe"] else None, p["niveau"], p["matiere"],
        )
        for p in propositions
    ]
    existants = {fil.cle: fil for fil in FilEquipe.objects.filter(cle__in=cles)}
    a_creer = []
    for cle, p in zip(cles, propositions):
        if cle in existants:
            continue
        fil = FilEquipe(
            etablissement_id=utilisateur.etablissement_id, annee_scolaire=annee, portee=p["portee"],
            classe=p["classe"], niveau=p["niveau"], matiere=p["matiere"],
            matiere_affichee=p["matiere_affichee"], cle=cle,
        )
        fil.clean()  # cohérence du modèle ; aucune requête, les objets liés sont déjà chargés
        a_creer.append(fil)
    if a_creer:
        FilEquipe.objects.bulk_create(a_creer, ignore_conflicts=True)
    par_cle = {fil.cle: fil for fil in FilEquipe.objects.filter(cle__in=cles).select_related("classe", "annee_scolaire")}
    return [par_cle[cle] for cle in cles]  # dans l'ordre des propositions (classes triées par niveau puis nom)


def fils_avec_activite(utilisateur) -> list[dict]:
    """
    Les fils proposés à l'utilisateur, avec leur nombre de messages et leur dernier message : 5 à
    10 requêtes au total, que l'école ait 3 ou 300 classes.
    """
    propositions = fils_proposes_pour(utilisateur)
    if not propositions:
        return []
    fils = obtenir_ou_creer_fils(utilisateur, propositions)
    dernier = MessageEquipe.objects.filter(fil=OuterRef("pk")).order_by("-envoye_le", "-pk").values("pk")[:1]
    annotes = list(
        FilEquipe.objects.filter(pk__in=[fil.pk for fil in fils])
        .select_related("classe", "annee_scolaire")
        .annotate(nombre_messages=Count("messages"), dernier_message_id=Subquery(dernier))
    )
    derniers = MessageEquipe.objects.select_related("auteur").in_bulk(
        [fil.dernier_message_id for fil in annotes if fil.dernier_message_id]
    )
    par_pk = {fil.pk: fil for fil in annotes}
    return [
        {
            "fil": par_pk[fil.pk], "dernier_message": derniers.get(par_pk[fil.pk].dernier_message_id),
            "nombre": par_pk[fil.pk].nombre_messages,
        }
        for fil in fils
    ]
