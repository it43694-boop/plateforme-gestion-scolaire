"""
Pré-inscription en ligne : le dépôt d'une demande par la famille, puis la réponse du secrétariat (convocation au test ou refus) et, après le test,
la décision. La famille est prévenue par courriel à chaque étape, dans sa langue, si elle a donné une adresse.

Rien d'automatique ne décide à la place de l'école : une demande déposée n'inscrit personne.
"""
import logging
import re

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from comptes.langue import langue_du_compte
from comptes.mail import envoyer_email
from comptes.models import Notification, Utilisateur
from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role, StatutCompte
from scolarite.models import Classe
from tests_niveau.models import Candidat, Decision, StatutDemande

logger = logging.getLogger(__name__)

DEMANDES_MAXIMALES_PAR_CAMPAGNE = 3000  # au-delà, le formulaire public se ferme : un robot ne peut pas remplir la base
ROLES_A_PREVENIR = {Role.SECRETAIRE.value} | {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL if r != Role.DEVELOPPEUR}


def classes_proposees(campagne):
    """Les classes entre lesquelles la famille choisit : celles de l'année de la campagne, dans l'école de la campagne."""
    return Classe.objects.filter(
        annee_scolaire=campagne.annee_scolaire, annee_scolaire__etablissement=campagne.etablissement, annee_scolaire__est_archivee=False,
    ).select_related("annee_scolaire").order_by("cycle", "nom")


def _cle(texte) -> str:
    return re.sub(r"\s+", " ", str(texte or "").strip().lower())


def formulaire_ferme(campagne) -> bool:
    """Le formulaire public ne reçoit plus rien : campagne fermée, hors dates, année archivée, ou trop de demandes déjà reçues."""
    return not campagne.est_ouverte() or campagne.demandes.count() >= DEMANDES_MAXIMALES_PAR_CAMPAGNE


@transaction.atomic
def deposer_une_demande(campagne, donnees, langue: str = "fr"):
    """
    Enregistre la demande d'une famille (`donnees` : le cleaned_data d'un formulaire de pré-inscription valide). Rend (candidat, nouvelle).
    Une demande identique déjà reçue (même enfant, même parent) n'est pas enregistrée deux fois : on rend la première, sans rien dire de plus
    à la famille (elle ne peut pas deviner ce qui existe déjà).
    """
    cle = (_cle(donnees["prenom"]), _cle(donnees["nom"]), donnees.get("date_naissance"), donnees["classe_visee"].pk)
    for existant in campagne.demandes.select_related("classe_visee"):
        if (_cle(existant.prenom), _cle(existant.nom), existant.date_naissance, existant.classe_visee_id) == cle and (
            _cle(existant.email_contact) == _cle(donnees.get("email")) and _cle(existant.telephone_contact) == _cle(donnees.get("telephone"))
        ):
            return existant, False
    candidat = Candidat(
        prenom=donnees["prenom"].strip(), nom=donnees["nom"].strip(), date_naissance=donnees.get("date_naissance"),
        telephone_contact=(donnees.get("telephone") or "").strip(), classe_visee=donnees["classe_visee"], date_test=None,
        campagne=campagne, statut_demande=StatutDemande.RECUE, sexe=donnees.get("sexe") or "", nom_parent=(donnees.get("nom_parent") or "").strip(),
        email_contact=(donnees.get("email") or "").strip().lower(), message=(donnees.get("message") or "").strip(), langue=langue,
        demande_le=timezone.now(),
    )
    candidat.full_clean(exclude=["cree_par"])  # une demande en ligne n'a pas d'auteur dans l'école
    candidat.save()
    return candidat, True


def _ecole_de(candidat):
    return candidat.classe_visee.annee_scolaire.etablissement


def _nom_de_l_ecole(candidat) -> str:
    ecole = _ecole_de(candidat)
    return ecole.nom if ecole is not None else ""


def informer_la_famille(candidat, sujet: str, lignes) -> bool:
    """Un courriel à la famille (dans sa langue) ; rend False s'il n'y a pas d'adresse. Ne lève jamais d'erreur."""
    if not candidat.email_contact:
        return False
    try:
        ecole = _ecole_de(candidat)
        envoyer_email(
            sujet=sujet, contenu="\n".join(ligne for ligne in lignes if ligne), expediteur=settings.DEFAULT_FROM_EMAIL,
            destinataires=[candidat.email_contact],
            langue=candidat.langue or langue_du_compte(None, ecole.langue_par_defaut if ecole else None),
            etablissement_id=ecole.pk if ecole else None,
        )
        return True
    except Exception:  # noqa: BLE001 - un courriel manquant ne doit jamais faire échouer l'action du secrétariat
        logger.exception("Courriel de pré-inscription non envoyé (candidat %s)", getattr(candidat, "pk", None))
        return False


def accuser_reception(candidat) -> bool:
    return informer_la_famille(candidat, f"Demande de pré-inscription reçue - {candidat.nom_complet}", [
        "Bonjour,",
        f"Nous avons bien reçu la demande de pré-inscription de {candidat.nom_complet} en {candidat.classe_visee.nom}.",
        "Le secrétariat l'étudie et vous répondra bientôt.",
        _nom_de_l_ecole(candidat),
    ])


def prevenir_le_secretariat(candidat) -> int:
    """Une notification (dans l'application) pour le secrétariat et la direction de l'école ; rend leur nombre."""
    try:
        ecole = _ecole_de(candidat)
        destinataires = list(Utilisateur.objects.filter(
            etablissement=ecole, role__in=ROLES_A_PREVENIR, is_active=True, statut=StatutCompte.ACTIF,
        ))
        Notification.objects.bulk_create([
            Notification(
                destinataire=personne, etablissement=ecole, titre="Nouvelle demande de pré-inscription",
                message=f"{candidat.nom_complet} - {candidat.classe_visee.nom}", url=f"{reverse('tests_niveau:liste_candidats')}?demande=recue",
            )
            for personne in destinataires
        ])
        return len(destinataires)
    except Exception:  # noqa: BLE001
        logger.exception("Secrétariat non prévenu d'une pré-inscription (candidat %s)", getattr(candidat, "pk", None))
        return 0


@transaction.atomic
def convoquer(candidat, date_test) -> bool:
    """Convoque la famille au test à la date donnée ; rend True si un courriel est parti."""
    candidat.statut_demande = StatutDemande.CONVOQUE
    candidat.date_test = date_test
    candidat.full_clean(exclude=["cree_par"])
    candidat.save(update_fields=["statut_demande", "date_test"])
    return informer_la_famille(candidat, f"Convocation au test de niveau - {candidat.nom_complet}", [
        "Bonjour,",
        f"La demande de pré-inscription de {candidat.nom_complet} en {candidat.classe_visee.nom} est retenue pour la suite.",
        f"Le test de niveau a lieu le {date_test.strftime('%d/%m/%Y')}. Merci de vous présenter à l'établissement ce jour-là.",
        _nom_de_l_ecole(candidat),
    ])


@transaction.atomic
def refuser_la_demande(candidat) -> bool:
    candidat.statut_demande = StatutDemande.REFUSEE
    candidat.save(update_fields=["statut_demande"])
    return informer_la_famille(candidat, f"Réponse à votre demande de pré-inscription - {candidat.nom_complet}", [
        "Bonjour,",
        f"Nous ne pouvons pas donner suite pour le moment à la demande de pré-inscription de {candidat.nom_complet} en {candidat.classe_visee.nom}.",
        "Pour plus d'informations, merci de contacter l'établissement.",
        _nom_de_l_ecole(candidat),
    ])


def annoncer_la_decision(candidat) -> bool:
    """Après le test : la décision (admis ou refusé) est communiquée à la famille qui a donné une adresse."""
    if candidat.decision == Decision.ADMIS:
        return informer_la_famille(candidat, f"Résultat du test de niveau - {candidat.nom_complet}", [
            "Bonjour,",
            f"{candidat.nom_complet} est admis(e) en {candidat.classe_visee.nom}.",
            "Pour finaliser l'inscription, merci de contacter le secrétariat de l'établissement.",
            _nom_de_l_ecole(candidat),
        ])
    if candidat.decision == Decision.REFUSE:
        return informer_la_famille(candidat, f"Résultat du test de niveau - {candidat.nom_complet}", [
            "Bonjour,",
            f"{candidat.nom_complet} n'a pas été admis(e) en {candidat.classe_visee.nom}.",
            "Pour plus d'informations, merci de contacter l'établissement.",
            _nom_de_l_ecole(candidat),
        ])
    return False
