"""
Envoi des factures d'abonnement par email (le PDF en pièce jointe) et rappels automatiques des factures en retard.

Réservé au propriétaire de la plateforme (voir espace_plateforme) ; l'école ne voit jamais ses factures dans l'application,
elle les reçoit par email. Rien n'est envoyé sans une demande du propriétaire (case cochée à l'émission, bouton « Envoyer »)
et les rappels ne concernent que les factures déjà envoyées par email.

Rappels : une facture émise, envoyée par email et dont l'échéance est dépassée reçoit un premier rappel dès le lendemain de
l'échéance, puis un autre tous les JOURS_ENTRE_DEUX_RAPPELS jours, NOMBRE_MAXIMAL_DE_RAPPELS au plus. Une facture payée ou
annulée n'en reçoit plus jamais. Ils partent avec l'entretien quotidien (comptes.entretien : première visite de la journée,
ou `manage.py entretien`) : le plan gratuit de Render n'a pas de tâches planifiées.
"""
import datetime
import logging
from dataclasses import dataclass, field

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from comptes.audit import enregistrer_action
from comptes.mail import envoyer_email_avec_pieces_jointes
from comptes.models import Utilisateur
from comptes.roles import ROLES_DIRECTION_GENERALE, Role, StatutCompte
from comptes.utils import lien_whatsapp
from etablissement.models import FactureAbonnement

logger = logging.getLogger(__name__)

STATUT = FactureAbonnement.Statut
JOURS_ENTRE_DEUX_RAPPELS = 7
NOMBRE_MAXIMAL_DE_RAPPELS = 3
# Un passage de l'entretien est déclenché par la visite d'un utilisateur : on borne le nombre d'envois (et on s'arrête au
# premier échec, un serveur d'email injoignable faisant attendre à chaque essai) pour ne jamais le ralentir longtemps.
ENVOIS_MAXIMAUX_PAR_PASSAGE = 10


@dataclass
class ResultatEnvoi:
    envoyee: bool
    destinataires: list = field(default_factory=list)
    raison: str = ""  # "", "statut", "aucune_adresse", "pdf" ou "echec"


def pdf_de_la_facture(facture, request=None):
    """Les octets du PDF de la facture, ou None si sa génération échoue."""
    from io import BytesIO

    from comptes.pdf import creer_pdf

    html = render_to_string("espace_plateforme/facture_pdf.html", {
        "facture": facture, "editeur": {
            "nom": settings.EDITEUR_NOM, "statut": settings.EDITEUR_STATUT, "adresse": settings.EDITEUR_ADRESSE,
            "email": settings.EDITEUR_EMAIL, "telephone": settings.EDITEUR_TELEPHONE,
            "immatriculation": settings.EDITEUR_IMMATRICULATION,
        },
        "instructions_paiement": settings.ABONNEMENT_INSTRUCTIONS_PAIEMENT,
        "nom_commercial": settings.NOM_COMMERCIAL,
    }, request=request)
    sortie = BytesIO()
    # Demandée par une personne : dans sa langue ; envoyée par le serveur (rappel automatique) : dans la langue par défaut de l'école.
    langue = None if request is not None else facture.etablissement.langue_par_defaut
    if creer_pdf(html, sortie, request=request, langue=langue, etablissement_id=facture.etablissement_id).err:
        return None
    return sortie.getvalue()


def destinataires_de_facturation(etablissement) -> list[str]:
    """
    À qui part la facture : l'adresse de facturation de l'école si elle est renseignée ; sinon les comptes de direction
    actifs de CETTE école (fondateur, administrateur général) ; sinon le compte de son développeur. Jamais un compte d'une
    autre école ; liste vide si rien n'est trouvé.
    """
    if etablissement.email_facturation:
        return [etablissement.email_facturation.strip().lower()]
    comptes = Utilisateur.objects.filter(etablissement=etablissement, is_active=True, statut=StatutCompte.ACTIF)
    for roles in (ROLES_DIRECTION_GENERALE, (Role.DEVELOPPEUR,)):
        adresses = sorted({
            email.strip().lower() for email in comptes.filter(role__in=[r.value for r in roles]).values_list("email", flat=True)
            if email
        })
        if adresses:
            return adresses
    return []


def telephones_de_facturation(etablissements) -> dict:
    """
    {id de l'école : numéro auquel écrire sur WhatsApp} : le numéro de facturation de l'école ; sinon le numéro d'un compte actif
    de CETTE école (direction d'abord, puis développeur) ; les écoles sans aucun numéro sont absentes. Une seule requête pour
    toutes les écoles demandées.
    """
    etablissements = list(etablissements)
    resultat = {e.pk: e.telephone_facturation.strip() for e in etablissements if (e.telephone_facturation or "").strip()}
    manquantes = [e.pk for e in etablissements if e.pk not in resultat]
    if manquantes:
        rang = {role.value: 0 for role in ROLES_DIRECTION_GENERALE} | {Role.DEVELOPPEUR.value: 1}
        comptes = Utilisateur.objects.filter(
            etablissement_id__in=manquantes, is_active=True, statut=StatutCompte.ACTIF, role__in=list(rang),
            telephone__isnull=False,
        ).exclude(telephone="").order_by("etablissement_id", "id")
        meilleur = {}
        for compte in comptes:
            if compte.etablissement_id not in meilleur or rang[compte.role] < meilleur[compte.etablissement_id][0]:
                meilleur[compte.etablissement_id] = (rang[compte.role], compte.telephone)
        resultat.update({ecole: telephone for ecole, (_, telephone) in meilleur.items()})
    return resultat


def message_whatsapp(facture, aujourdhui=None) -> str:
    """Le texte pré-écrit du message WhatsApp : un rappel si l'échéance est dépassée, sinon la facture à payer."""
    aujourdhui = aujourdhui or timezone.localdate()
    plateforme = settings.NOM_COMMERCIAL
    echeance = f"{facture.date_echeance:%d/%m/%Y}"
    if facture.date_echeance < aujourdhui:
        jours = (aujourdhui - facture.date_echeance).days
        debut = (
            f"Bonjour, rappel : la facture {facture.numero} de l'abonnement de « {facture.etablissement.nom} » à {plateforme} "
            f"n'est pas encore réglée. Elle était à payer avant le {echeance} ({jours} jour{'s' if jours > 1 else ''} de retard)."
        )
    else:
        debut = (
            f"Bonjour, voici la facture {facture.numero} de l'abonnement de « {facture.etablissement.nom} » à {plateforme}, "
            f"à payer avant le {echeance}."
        )
    lignes = [debut, f"Montant : {_montant(facture.montant)} FCFA."]
    if settings.ABONNEMENT_INSTRUCTIONS_PAIEMENT:
        lignes.append(f"Comment payer : {settings.ABONNEMENT_INSTRUCTIONS_PAIEMENT}")
    lignes.append("Merci d'indiquer le numéro de la facture lors du règlement.")
    from comptes.langue import texte_en_langue

    # Le message part chez l'école : dans sa langue (par défaut), pas dans celle de la personne qui clique.
    return texte_en_langue("\n".join(lignes), facture.etablissement.langue_par_defaut, facture.etablissement_id)


def ajouter_les_liens_whatsapp(factures, aujourdhui=None) -> list:
    """
    Pose `lien_whatsapp` sur chaque facture : le lien wa.me pré-rempli pour une facture émise dont l'école a un numéro, sinon "".
    Rien n'est envoyé par le serveur : la personne ouvre WhatsApp avec le message déjà écrit et clique elle-même sur Envoyer.
    """
    factures = list(factures)
    aujourdhui = aujourdhui or timezone.localdate()
    ecoles = {f.etablissement_id: f.etablissement for f in factures if f.statut == STATUT.EMISE}
    telephones = telephones_de_facturation(ecoles.values())
    for facture in factures:
        telephone = telephones.get(facture.etablissement_id) if facture.statut == STATUT.EMISE else None
        facture.lien_whatsapp = lien_whatsapp(telephone, message_whatsapp(facture, aujourdhui)) if telephone else ""
    return factures


def _montant(valeur) -> str:
    return f"{valeur:,}".replace(",", " ")


def _sujet_et_contenu(facture, *, rappel, aujourdhui):
    plateforme = settings.NOM_COMMERCIAL
    echeance = f"{facture.date_echeance:%d/%m/%Y}"
    if rappel:
        jours = (aujourdhui - facture.date_echeance).days
        sujet = f"{plateforme} - Rappel : facture {facture.numero} en retard de {jours} jour{'s' if jours > 1 else ''}"
        introduction = (
            f"Sauf erreur de notre part, la facture {facture.numero} de l'abonnement de « {facture.etablissement.nom} » "
            f"n'est pas encore réglée : elle était à payer avant le {echeance} ({jours} jour{'s' if jours > 1 else ''} de retard). "
            "Vous la retrouvez en pièce jointe."
        )
    else:
        sujet = f"{plateforme} - Facture {facture.numero} : {_montant(facture.montant)} FCFA à payer avant le {echeance}"
        introduction = (
            f"Veuillez trouver ci-joint la facture {facture.numero} de l'abonnement de « {facture.etablissement.nom} » à {plateforme}."
        )
    lignes = [
        "Bonjour,", "", introduction, "",
        f"Désignation : {facture.libelle}",
        f"Période : du {facture.periode_debut:%d/%m/%Y} au {facture.periode_fin:%d/%m/%Y}",
        f"Montant : {_montant(facture.montant)} FCFA",
        f"À payer avant le : {echeance}",
    ]
    if settings.ABONNEMENT_INSTRUCTIONS_PAIEMENT:
        lignes += ["", "Comment payer :", settings.ABONNEMENT_INSTRUCTIONS_PAIEMENT]
    lignes += ["", "Merci d'indiquer le numéro de la facture lors du règlement. Si vous avez déjà payé, ne tenez pas compte de ce message." if rappel
               else "Merci d'indiquer le numéro de la facture lors du règlement."]
    signature = settings.EDITEUR_NOM or plateforme
    lignes += ["", signature]
    return sujet, "\n".join(lignes)


def envoyer_facture(facture, *, rappel=False, acteur=None, request=None, aujourdhui=None) -> ResultatEnvoi:
    """
    Envoie la facture (PDF joint) à l'école. Seule une facture émise part. En cas de succès : date d'envoi ou compteur de
    rappels mis à jour, et une ligne au journal d'audit (nombre de destinataires seulement, jamais leurs adresses).
    Ne lève jamais d'erreur d'envoi : le résultat dit pourquoi rien n'est parti.
    """
    aujourdhui = aujourdhui or timezone.localdate()
    facture = FactureAbonnement.objects.select_related("etablissement").get(pk=facture.pk)
    if facture.statut != STATUT.EMISE:
        return ResultatEnvoi(False, [], "statut")
    destinataires = destinataires_de_facturation(facture.etablissement)
    if not destinataires:
        return ResultatEnvoi(False, [], "aucune_adresse")
    pdf = pdf_de_la_facture(facture)
    if pdf is None:
        return ResultatEnvoi(False, destinataires, "pdf")
    sujet, contenu = _sujet_et_contenu(facture, rappel=rappel, aujourdhui=aujourdhui)
    envoye = envoyer_email_avec_pieces_jointes(
        sujet=sujet, contenu=contenu, expediteur=settings.DEFAULT_FROM_EMAIL, destinataires=destinataires,
        pieces_jointes=[(f"facture_{facture.numero}.pdf", pdf, "application/pdf")],
        repondre_a=settings.EDITEUR_EMAIL or None,
        langue=facture.etablissement.langue_par_defaut, etablissement_id=facture.etablissement_id,  # la langue de l'école qui reçoit
    )
    if not envoye:
        return ResultatEnvoi(False, destinataires, "echec")
    if rappel:
        facture.nombre_rappels += 1
        facture.dernier_rappel_le = aujourdhui
        facture.save(update_fields=["nombre_rappels", "dernier_rappel_le"])
    else:
        facture.envoyee_le = timezone.now()
        facture.save(update_fields=["envoyee_le"])
    enregistrer_action(
        acteur=acteur, action="rappel_facture_abonnement" if rappel else "envoi_facture_abonnement", cible=facture.numero,
        details={"etablissement": facture.etablissement.nom, "destinataires": len(destinataires)}, request=request,
    )
    return ResultatEnvoi(True, destinataires, "")


def rappel_du(facture, aujourdhui) -> bool:
    """Cette facture doit-elle recevoir un rappel aujourd'hui ? (voir la règle en tête de ce module)"""
    if facture.statut != STATUT.EMISE or facture.envoyee_le is None or facture.date_echeance >= aujourdhui:
        return False
    if facture.nombre_rappels >= NOMBRE_MAXIMAL_DE_RAPPELS:
        return False
    if facture.dernier_rappel_le is None:
        return True
    return (aujourdhui - facture.dernier_rappel_le) >= datetime.timedelta(days=JOURS_ENTRE_DEUX_RAPPELS)


def relancer_factures_en_retard(*, aujourdhui=None, simulation=False, maximum=ENVOIS_MAXIMAUX_PAR_PASSAGE) -> dict:
    """
    Envoie les rappels dus aujourd'hui. Rend {"rappels": envoyés (ou à envoyer en simulation), "sans_adresse": factures sans
    destinataire, "echecs": 0 ou 1}. S'arrête au premier échec d'envoi (réessayé demain, le compteur n'ayant pas bougé).
    """
    aujourdhui = aujourdhui or timezone.localdate()
    bilan = {"rappels": 0, "sans_adresse": 0, "echecs": 0}
    candidates = FactureAbonnement.objects.filter(
        statut=STATUT.EMISE, date_echeance__lt=aujourdhui, envoyee_le__isnull=False,
        nombre_rappels__lt=NOMBRE_MAXIMAL_DE_RAPPELS,
    ).select_related("etablissement").order_by("date_echeance", "id")
    for facture in candidates:
        if not rappel_du(facture, aujourdhui):
            continue
        if bilan["rappels"] >= maximum:
            break
        if simulation:
            bilan["rappels"] += 1
            continue
        resultat = envoyer_facture(facture, rappel=True, aujourdhui=aujourdhui)
        if resultat.envoyee:
            bilan["rappels"] += 1
        elif resultat.raison == "aucune_adresse":
            bilan["sans_adresse"] += 1
        elif resultat.raison in ("echec", "pdf"):
            bilan["echecs"] = 1
            break
    return bilan
