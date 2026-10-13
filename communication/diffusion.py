"""
Messages aux familles : une liste de liens WhatsApp et SMS prêts à envoyer.

AUCUN ENVOI PAR LE SERVEUR. Chaque lien ouvre WhatsApp (ou l'application de SMS) sur le téléphone ou l'ordinateur de la
personne connectée, avec le numéro de la famille et le message déjà écrits ; rien ne part tant qu'elle n'appuie pas
elle-même sur « Envoyer », et le message part de SON numéro. Pas de fournisseur, pas de clé, pas de coût.

Quatre types de message :
- annonce : le même texte pour toutes les familles (une ligne par numéro) ; seul type qu'on peut copier dans un groupe ;
- convocation : une ligne par parent et par élève, avec le nom de l'élève ;
- absence : les parents des élèves absents à une date ;
- paiement : les parents des élèves dont le solde de scolarité n'est pas à zéro.

Confidentialité : seuls les rôles qui voient déjà les coordonnées des familles y accèdent (jamais un enseignant, un parent
ou un élève), limités aux classes que l'utilisateur voit (un directeur de cycle ne voit que son cycle). Un message qui
contient un nom d'élève ou un montant ne peut pas être copié dans un groupe : il n'existe que sous forme de liens
individuels.
"""
import re
from collections import OrderedDict

from django.db.models import Prefetch, Q, Sum
from django.db.models.functions import Coalesce

from comptes.roles import Role
from comptes.utils import lien_sms, lien_whatsapp, numero_international
from pedagogie.models import Absence
from permissions_matrix.models import PermissionMatrix
from scolarite.models import (
    ROLES_ETAT_CIVIL_ELEVE, ROLES_VOIENT_TOUT_ELEVE_DE_LETABLISSEMENT, AideScolarite, Inscription, calculer_total_du,
)

ANNONCE, CONVOCATION, ABSENCE, PAIEMENT = "annonce", "convocation", "absence", "paiement"

LONGUEUR_MAX_MODELE = 500

TYPES = OrderedDict([
    (ANNONCE, {
        "libelle": "Annonce à toute la classe",
        "aide": "Le même message pour toutes les familles ; une seule ligne par numéro, même avec plusieurs enfants.",
        "modele": "Bonjour, {ecole} vous informe : (à compléter).",
        "individuel": False, "avec_date": False,
    }),
    (CONVOCATION, {
        "libelle": "Convocation d'un parent",
        "aide": "Une ligne par parent et par élève : n'envoyez que celles dont vous avez besoin.",
        "modele": "Bonjour, {ecole} vous prie de passer à l'école au sujet de {eleve} ({classe}) le {date}.",
        "individuel": True, "avec_date": True,
    }),
    (ABSENCE, {
        "libelle": "Élèves absents",
        "aide": "Les parents des élèves marqués absents à la date choisie.",
        "modele": "Bonjour, {eleve} ({classe}) était absent(e) le {date}. Merci de nous contacter pour le justifier. {ecole}",
        "individuel": True, "avec_date": True,
    }),
    (PAIEMENT, {
        "libelle": "Relance de scolarité",
        "aide": "Les parents des élèves dont le solde n'est pas réglé.",
        "modele": "Bonjour, rappel de {ecole} : le solde de scolarité de {eleve} ({classe}) est de {solde}. Merci de régulariser.",
        "individuel": True, "avec_date": False,
    }),
])

# Rôles qui voient déjà les coordonnées des familles (état civil des élèves) + surveillant général.
ROLES_CONTACT_FAMILLES = ROLES_ETAT_CIVIL_ELEVE | {Role.SURVEILLANT_GENERAL.value}

_MARQUEURS = re.compile(r"\{(prenom|eleve|classe|ecole|date|solde)\}")
MARQUEUR_DATE = "{date}"


def types_pour_role(role, a_acces) -> list[str]:
    """Types de message qu'un rôle peut préparer ; `a_acces(module)` dit si le module est ouvert à ce rôle."""
    types = set()
    if role in ROLES_CONTACT_FAMILLES:
        if a_acces("communication"):
            types |= {ANNONCE, CONVOCATION}
        if a_acces("absences"):
            types.add(ABSENCE)
    if role in ROLES_VOIENT_TOUT_ELEVE_DE_LETABLISSEMENT and a_acces("finances"):
        types.add(PAIEMENT)
    return [type_ for type_ in TYPES if type_ in types]


def types_autorises(utilisateur) -> list[str]:
    if not utilisateur.is_authenticated or not utilisateur.etablissement_id:
        return []
    etablissement = utilisateur.etablissement
    return types_pour_role(
        utilisateur.role, lambda module: PermissionMatrix.a_acces(utilisateur.role, module, etablissement=etablissement),
    )


def appliquer_modele(modele: str, valeurs: dict) -> str:
    """
    Remplace uniquement les marqueurs connus ({eleve}, {prenom}, {classe}, {ecole}, {date}, {solde}). Pas de
    str.format : un texte tapé par l'utilisateur ne peut jamais lire un attribut d'objet ni provoquer d'erreur.
    """
    return _MARQUEURS.sub(lambda trouve: valeurs.get(trouve.group(1), ""), modele)


def _contacts(eleve) -> list[tuple[str, str]]:
    """
    (libellé, téléphone) de chaque parent qui a un numéro - ceux qui ont un compte, puis ceux qui n'en ont pas encore
    (numéro donné à l'inscription, ParentEnAttente) ; à défaut, le numéro de l'élève lui-même.
    """
    parents = sorted((p for p in eleve.parents_lies.all() if p.telephone), key=lambda p: (p.nom, p.prenom, p.pk))
    contacts = [(parent.nom_complet, parent.telephone) for parent in parents]
    deja = {telephone for _, telephone in contacts}
    for attente in sorted(eleve.parents_en_attente.all(), key=lambda a: (a.cree_le, a.pk)):
        if attente.telephone and attente.telephone not in deja:
            contacts.append((f"{attente.prenom} {attente.nom}".strip() or attente.email, attente.telephone))
            deja.add(attente.telephone)
    if contacts:
        return contacts
    if eleve.telephone:
        return [(f"{eleve.nom_complet} (élève)", eleve.telephone)]
    return []


def _inscriptions(classes, type_, date):
    """Inscriptions concernées par le type de message, dans l'ordre classe puis nom ; (inscription, solde) pour la scolarité."""
    inscriptions = Inscription.objects.filter(classe__in=classes, statut=Inscription.Statut.EN_COURS)
    if type_ == ABSENCE:
        inscriptions = inscriptions.filter(eleve__in=Absence.objects.filter(
            classe__in=classes, date_absence=date,
        ).values("eleve"))
    inscriptions = inscriptions.select_related("eleve", "classe", "classe__echeancier").prefetch_related(
        "eleve__parents_lies", "eleve__parents_en_attente",
    ).order_by("classe__nom", "eleve__nom", "eleve__prenom", "pk")
    if type_ != PAIEMENT:
        return [(inscription, None) for inscription in inscriptions]

    inscriptions = inscriptions.prefetch_related(Prefetch(
        "aides_scolarite", queryset=AideScolarite.objects.filter(active=True), to_attr="aides_actives_prefetchees",
    )).annotate(total_paye=Coalesce(Sum("paiements__montant", filter=Q(paiements__est_supprime=False)), 0))
    resultat = []
    for inscription in inscriptions:
        solde = calculer_total_du(inscription, aides_actives=inscription.aides_actives_prefetchees) - inscription.total_paye
        if solde > 0:
            resultat.append((inscription, solde))
    return resultat


def preparer_messages(*, type_, classes, modele, ecole, date=None, une_seule_classe=None, devise="FCFA") -> dict:
    """
    Les lignes à afficher : {"lignes": [...], "sans_numero": [noms], "eleves": n}. Chaque ligne porte le message déjà
    personnalisé et les liens WhatsApp et SMS.
    """
    individuel = TYPES[type_]["individuel"]
    date_texte = date.strftime("%d/%m/%Y") if date else ""
    lignes, sans_numero, par_numero = [], [], OrderedDict()
    eleves = 0
    for inscription, solde in _inscriptions(classes, type_, date):
        eleves += 1
        eleve = inscription.eleve
        contacts = []
        for libelle, telephone in _contacts(eleve):
            chiffres, sur = numero_international(telephone)
            if chiffres:
                contacts.append((libelle, telephone, chiffres, sur))
        if not contacts:
            sans_numero.append(f"{eleve.nom_complet} ({inscription.classe.nom})")
            continue
        if individuel:
            message = appliquer_modele(modele, {
                "prenom": eleve.prenom, "eleve": eleve.nom_complet, "classe": inscription.classe.nom, "ecole": ecole,
                "date": date_texte, "solde": f"{solde:,} {devise}".replace(",", " ") if solde is not None else "",
            })
            for libelle, telephone, chiffres, sur in contacts:
                lignes.append({
                    "famille": libelle, "telephone": telephone, "a_verifier": not sur, "eleves": [eleve.nom_complet],
                    "message": message, "whatsapp": lien_whatsapp(telephone, message), "sms": lien_sms(telephone, message),
                })
        else:
            for libelle, telephone, chiffres, sur in contacts:
                ligne = par_numero.get(chiffres)
                if ligne is None:
                    ligne = par_numero[chiffres] = {
                        "famille": libelle, "telephone": telephone, "a_verifier": not sur, "eleves": [],
                    }
                ligne["eleves"].append(eleve.nom_complet)
    if not individuel:
        message = message_neutre(modele, ecole, date_texte, une_seule_classe)
        for ligne in par_numero.values():
            ligne.update({
                "message": message, "whatsapp": lien_whatsapp(ligne["telephone"], message),
                "sms": lien_sms(ligne["telephone"], message),
            })
            lignes.append(ligne)
    return {"lignes": lignes, "sans_numero": sans_numero, "eleves": eleves}


def message_neutre(modele, ecole, date_texte="", classe=None) -> str:
    """Le message sans aucune donnée propre à un élève (ni nom, ni montant) : le seul qu'on peut coller dans un groupe."""
    return appliquer_modele(modele, {
        "prenom": "votre enfant", "eleve": "votre enfant", "classe": classe.nom if classe else "", "ecole": ecole,
        "date": date_texte, "solde": "",
    })
