"""
Paiement Mobile Money déclaré par un parent : déclaration, validation par la comptabilité, refus.

Le parent n'écrit jamais en caisse : il signale un paiement avec le numéro de transaction de l'opérateur, la comptabilité le vérifie dans son compte Mobile
Money puis l'enregistre comme un paiement ordinaire (voir `enregistrer_paiement_vue`, qui appelle `marquer_valide`). Un parent ne déclare que pour ses enfants.
"""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from comptes.models import Notification, Utilisateur
from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role, StatutCompte
from finances.models import PaiementDeclare, StatutDeclaration, normaliser_reference_transaction


def inscription_en_cours(eleve):
    from scolarite.models import Inscription

    return Inscription.objects.filter(eleve=eleve, statut=Inscription.Statut.EN_COURS).order_by("-date_inscription").first()


def destinataires_de_la_comptabilite(etablissement):
    """Les comptables actifs de l'école ; à défaut, la direction générale (fondateur, administrateur général)."""
    actifs = Utilisateur.objects.filter(etablissement=etablissement, is_active=True, statut=StatutCompte.ACTIF)
    comptables = list(actifs.filter(role=Role.COMPTABLE))
    if comptables:
        return comptables
    direction = {role.value for role in ROLES_ACCES_TOTAL_INCONDITIONNEL} - {Role.DEVELOPPEUR.value}
    return list(actifs.filter(role__in=direction))


def une_transaction_deja_declaree(etablissement, operateur, reference) -> bool:
    """Ce numéro de transaction a-t-il déjà été déclaré (sans avoir été refusé) ?"""
    return PaiementDeclare.objects.filter(
        etablissement=etablissement, operateur=operateur, reference_transaction=normaliser_reference_transaction(reference),
    ).exclude(statut=StatutDeclaration.REFUSE).exists()


def declarer(*, parent, eleve, montant, operateur, reference, date_du_paiement, telephone="", capture=None) -> PaiementDeclare:
    """Enregistre la déclaration d'un parent pour l'un de SES enfants et prévient la comptabilité."""
    if parent.role != Role.PARENT or not eleve.parents_lies.filter(pk=parent.pk).exists():
        raise PermissionDenied("Vous ne pouvez déclarer un paiement que pour vos propres enfants.")
    inscription = inscription_en_cours(eleve)
    if inscription is None:
        raise ValidationError("Cet élève n'a pas d'inscription en cours.")
    with transaction.atomic():
        declaration = PaiementDeclare(
            eleve=eleve, inscription=inscription, declare_par=parent, montant=montant, operateur=operateur, reference_transaction=reference,
            date_du_paiement=date_du_paiement, telephone_payeur=(telephone or "").strip(), capture=capture or None,
        )
        declaration.save()
    prevenir_la_comptabilite(declaration)
    return declaration


def prevenir_la_comptabilite(declaration):
    """Une notification par comptable : ne bloque jamais la déclaration."""
    try:
        devise = getattr(declaration.etablissement, "code_devise", "FCFA")
        message = (
            f"{declaration.declare_par.nom_complet if declaration.declare_par else 'Un parent'} déclare avoir payé {declaration.montant} {devise} "
            f"({declaration.get_operateur_display()}, n° {declaration.reference_transaction}) pour {declaration.eleve.nom_complet} ({declaration.inscription.classe.nom})."
        )
        adresse = reverse("finances:declarations")
        for destinataire in destinataires_de_la_comptabilite(declaration.etablissement):
            Notification.objects.create(
                destinataire=destinataire, etablissement=declaration.etablissement, titre="Paiement à valider", message=message[:500], url=adresse,
            )
    except Exception:  # noqa: BLE001 - la déclaration est déjà enregistrée
        import logging

        logging.getLogger(__name__).exception("Notification de paiement déclaré non envoyée (déclaration %s)", getattr(declaration, "pk", None))


def _prevenir_le_parent(declaration, titre, message, adresse):
    if declaration.declare_par_id:
        Notification.objects.create(
            destinataire=declaration.declare_par, etablissement=declaration.etablissement, titre=titre, message=message[:500], url=adresse,
        )


def marquer_valide(declaration, *, acteur, paiement):
    """La comptabilité a enregistré le paiement : la déclaration est validée et reliée au reçu ; le parent est prévenu."""
    with transaction.atomic():
        declaration.statut = StatutDeclaration.VALIDE
        declaration.traite_par = acteur
        declaration.traite_le = timezone.now()
        declaration.paiement = paiement
        declaration.save()
    _prevenir_le_parent(
        declaration, "Paiement validé", f"Votre paiement de {paiement.montant} pour {declaration.eleve.nom_complet} est enregistré. Reçu n° {paiement.reference}.",
        reverse("finances:liste_paiements"),
    )


def refuser(declaration, *, acteur, motif):
    """La comptabilité ne retrouve pas la transaction (ou le montant diffère) : un motif est toujours donné au parent."""
    motif = " ".join((motif or "").split())
    if not motif:
        raise ValidationError("Indiquez le motif du refus.")
    if declaration.statut != StatutDeclaration.EN_ATTENTE:
        raise ValidationError("Cette déclaration a déjà été traitée.")
    with transaction.atomic():
        declaration.statut = StatutDeclaration.REFUSE
        declaration.traite_par = acteur
        declaration.traite_le = timezone.now()
        declaration.motif_refus = motif[:200]
        declaration.save()
    _prevenir_le_parent(
        declaration, "Paiement non validé", f"Votre déclaration (n° {declaration.reference_transaction}) pour {declaration.eleve.nom_complet} n'a pas été validée : {declaration.motif_refus}",
        reverse("finances:declarer_paiement"),
    )
