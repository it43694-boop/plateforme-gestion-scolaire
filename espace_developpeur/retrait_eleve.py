"""
Retirer un élève de la plateforme : suppression définitive (doublon créé par erreur) ou anonymisation (élève qui a un
historique : paiements, notes, absences, documents remis).

Pourquoi deux cas : un élève qui a payé, été noté ou reçu un bulletin laisse des traces que l'école doit conserver
(comptabilité, statistiques officielles, authenticité des documents déjà remis). On ne peut donc pas le supprimer sans
casser ces chiffres : on efface la PERSONNE (nom, coordonnées, famille, messages) et on garde les CHIFFRES.

Réservé au rôle développeur (voir espace_developpeur.views.retirer_eleve), pour un élève de son école, après avoir
retapé le matricule.
"""
import datetime

from django.db import transaction
from django.db.models import Q

from comptes.models import CodeVerificationEmail, Notification, Utilisateur
from comptes.roles import StatutCompte

PREFIXE_MATRICULE_ANONYME = "ANON-"

# Libellés des éléments d'historique (nom de clé -> texte affiché), dans l'ordre d'affichage.
LIBELLES_HISTORIQUE = (
    ("paiements", "paiement(s) enregistré(s)"),
    ("aides", "aide(s) de scolarité"),
    ("notes", "note(s)"),
    ("absences", "absence(s)"),
    ("discipline", "mesure(s) de discipline"),
    ("resultats_examens", "résultat(s) d'examen"),
    ("documents", "document(s) officiel(s) remis (bulletins, attestations)"),
    ("sorties", "sortie(s) en cours d'année (abandon, transfert)"),
    ("messages", "message(s) entre parents et enseignants"),
)


def est_anonymise(eleve) -> bool:
    return bool(eleve.matricule) and eleve.matricule.startswith(PREFIXE_MATRICULE_ANONYME)


def historique_eleve(eleve) -> dict:
    """Ce que l'élève a laissé derrière lui : nombre d'éléments de chaque sorte (inscriptions comprises à part)."""
    from communication.models import Message
    from finances.models import Paiement
    from pedagogie.models import Absence, MesureDiscipline, Note, NoteConduite, VerificationBulletin
    from scolarite.models import Abandon, AideScolarite, ResultatExamen, TransfertEleve, VerificationDocument

    return {
        "paiements": Paiement.objects.filter(eleve=eleve).count(),
        "aides": AideScolarite.objects.filter(inscription__eleve=eleve).count(),
        "notes": Note.objects.filter(eleve=eleve).count() + NoteConduite.objects.filter(eleve=eleve).count(),
        "absences": Absence.objects.filter(eleve=eleve).count(),
        "discipline": MesureDiscipline.objects.filter(eleve=eleve).count(),
        "resultats_examens": ResultatExamen.objects.filter(inscription__eleve=eleve).count(),
        "documents": (
            VerificationDocument.objects.filter(eleve=eleve).count()
            + VerificationBulletin.objects.filter(eleve=eleve).count()
        ),
        "sorties": (
            Abandon.objects.filter(inscription__eleve=eleve).count()
            + TransfertEleve.objects.filter(inscription__eleve=eleve).count()
        ),
        "messages": Message.objects.filter(eleve=eleve).count(),
    }


def historique_lisible(historique) -> list[tuple[int, str]]:
    return [(historique[cle], libelle) for cle, libelle in LIBELLES_HISTORIQUE if historique[cle]]


def mode_de_retrait(eleve, historique) -> str:
    """
    « suppression » : aucun historique, le dossier peut disparaître entièrement (doublon créé par erreur).
    « anonymisation » : il y a un historique à conserver. « deja_anonymise » : il n'y a plus rien à faire.
    """
    if est_anonymise(eleve):
        return "deja_anonymise"
    return "anonymisation" if any(historique.values()) else "suppression"


def _mois_de_naissance(date):
    """Seuls l'année et le mois sont gardés (jour ramené au 1er) : les âges des statistiques restent justes à un mois près."""
    return datetime.date(date.year, date.month, 1) if date else None


@transaction.atomic
def supprimer_eleve(eleve) -> None:
    """Supprime le compte et tout ce qui s'y rattache (inscriptions, famille en attente, notifications). Sans historique seulement."""
    if any(historique_eleve(eleve).values()):
        raise ValueError("Cet élève a un historique : il ne peut qu'être anonymisé.")
    eleve.delete()


@transaction.atomic
def anonymiser_eleve(eleve) -> dict:
    """
    Efface la personne, garde les chiffres. Rend ce qui a été fait (compteurs, jamais de nom ni de numéro).

    Effacé : prénom, nom (et leur écriture arabe), photo, filiation, adresse, personne à prévenir, école d'origine, email,
    téléphone, matricule, lieu et n° d'acte de naissance, jour de naissance, famille en
    attente, lien avec les parents (leurs comptes restent), messages parents-enseignants à son sujet, notifications qui
    le nomment, motifs d'absence, de discipline et de sortie, justificatif de transfert. Le compte est désactivé et sans mot de passe.

    Gardé (les chiffres de l'école et des statistiques officielles) : sexe, année et mois de naissance, situation de
    handicap et de déplacement, inscriptions, notes, absences, paiements, résultats d'examen. Les documents déjà remis
    restent vérifiables (leur page de contrôle n'affiche plus que le pseudonyme).
    """
    from communication.models import Message
    from pedagogie.models import Absence, MesureDiscipline
    from scolarite.models import Abandon, ParentEnAttente, TransfertEleve

    ancien_nom = eleve.nom_complet.strip()
    ancien_matricule = eleve.matricule or ""

    # Notifications (de n'importe quel membre de l'école) qui nomment l'élève ou renvoient vers son dossier.
    criteres = Q()
    if len(ancien_nom) >= 5:
        criteres |= Q(titre__icontains=ancien_nom) | Q(message__icontains=ancien_nom)
    if ancien_matricule:
        criteres |= Q(url__contains=f"/{ancien_matricule}/") | Q(message__icontains=ancien_matricule)
    notifications = Notification.objects.filter(criteres, destinataire__etablissement=eleve.etablissement).delete()[0] if criteres else 0
    notifications += Notification.objects.filter(destinataire=eleve).delete()[0]
    CodeVerificationEmail.objects.filter(utilisateur=eleve).delete()

    messages_supprimes = Message.objects.filter(eleve=eleve).delete()[0]
    parents_en_attente = ParentEnAttente.objects.filter(eleve=eleve).delete()[0]
    parents_delies = eleve.parents_lies.count()
    eleve.parents_lies.clear()

    Absence.objects.filter(eleve=eleve).update(motif="")
    MesureDiscipline.objects.filter(eleve=eleve).update(motif="")  # le motif est un texte libre : il peut nommer l'élève ou d'autres enfants
    Abandon.objects.filter(inscription__eleve=eleve).update(motif="Anonymisé")
    for transfert in TransfertEleve.objects.filter(inscription__eleve=eleve):
        if transfert.justificatif:
            transfert.justificatif.delete(save=False)
        transfert.motif = "Anonymisé"
        transfert.justificatif = ""
        transfert.save(update_fields=["motif", "justificatif"])

    eleve.prenom = "Élève"
    eleve.nom = f"Anonymisé {eleve.pk}"
    eleve.email = f"anonyme-{eleve.pk}@eleves.local"
    eleve.telephone = None
    eleve.matricule = f"{PREFIXE_MATRICULE_ANONYME}{eleve.pk}"
    eleve.lieu_naissance = ""
    eleve.numero_acte_naissance = ""
    eleve.nom_pere = eleve.nom_mere = eleve.adresse = eleve.ecole_origine = ""
    eleve.contact_urgence_nom = eleve.contact_urgence_telephone = ""
    if eleve.photo:
        eleve.photo.delete(save=False)  # la photo d'un enfant ne reste jamais dans le stockage après anonymisation
    eleve.photo = None
    eleve.prenom_ar = eleve.nom_ar = ""
    eleve.date_naissance = _mois_de_naissance(eleve.date_naissance)
    eleve.profession = ""
    eleve.statut = StatutCompte.DESACTIVE
    eleve.is_active = False
    eleve.set_unusable_password()
    eleve.save()

    return {
        "notifications": notifications, "messages": messages_supprimes, "parents_en_attente": parents_en_attente,
        "parents_delies": parents_delies,
    }
