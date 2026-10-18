"""
Vente de tenues : arrivages, ventes au comptoir, annulation (direction), corrections d'inventaire.

Chaque opération est atomique : le stock ne descend jamais sous zéro, chaque changement de stock laisse une ligne d'historique, et une vente
crée sa ligne de Caisse. Les articles sont verrouillés dans l'ordre de leur numéro pour que deux ventes simultanées ne se bloquent pas.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL
from finances.models import (
    ArticleTenue, LigneVenteTenue, MotifStockTenue, MouvementCaisse, MouvementStockTenue, VenteTenue, generer_reference,
)


def _verrouiller(etablissement, ids):
    """Les articles de l'école, verrouillés et rangés par numéro ; ValidationError si l'un n'existe pas dans cette école."""
    articles = {a.pk: a for a in ArticleTenue.objects.select_for_update().filter(etablissement=etablissement, pk__in=sorted(set(ids))).order_by("pk")}
    if len(articles) != len(set(ids)):
        raise ValidationError("Un article demandé n'existe pas dans cet établissement.")
    return articles


def _mouvement(article, quantite, motif, acteur, *, vente=None, note=""):
    article.stock += quantite
    article.save(update_fields=["stock"])
    MouvementStockTenue.objects.create(
        article=article, quantite=quantite, motif=motif, vente=vente, note=note[:255], stock_apres=article.stock, cree_par=acteur,
    )


def approvisionner(*, article, quantite: int, note: str, acteur) -> ArticleTenue:
    """Un arrivage : le stock augmente de `quantite`."""
    if quantite <= 0:
        raise ValidationError("La quantité reçue doit être supérieure à zéro.")
    with transaction.atomic():
        verrouille = _verrouiller(article.etablissement, [article.pk])[article.pk]
        _mouvement(verrouille, quantite, MotifStockTenue.ARRIVAGE, acteur, note=note)
    return verrouille


def corriger_stock(*, article, nouveau_stock: int, note: str, acteur) -> ArticleTenue:
    """Un inventaire : le stock devient `nouveau_stock` ; le motif est obligatoire (il est gardé dans l'historique)."""
    if nouveau_stock < 0:
        raise ValidationError("Le stock ne peut pas être négatif.")
    if not (note or "").strip():
        raise ValidationError("Indiquez le motif de la correction.")
    with transaction.atomic():
        verrouille = _verrouiller(article.etablissement, [article.pk])[article.pk]
        ecart = nouveau_stock - verrouille.stock
        if ecart == 0:
            raise ValidationError(f"Le stock est déjà de {verrouille.stock}.")
        _mouvement(verrouille, ecart, MotifStockTenue.CORRECTION, acteur, note=note.strip())
    return verrouille


def vendre(*, etablissement, quantites: dict, eleve, acheteur: str, mode_paiement: str, acteur) -> VenteTenue:
    """
    Enregistre une vente : `quantites` = {numéro de l'article: quantité}. Refuse un article retiré de la vente, une quantité supérieure au
    stock, une vente vide. Crée la vente, ses lignes, les sorties de stock et la ligne de Caisse.
    """
    demandes = {int(pk): int(quantite) for pk, quantite in quantites.items() if int(quantite) > 0}
    if not demandes:
        raise ValidationError("Indiquez au moins un article à vendre.")
    with transaction.atomic():
        articles = _verrouiller(etablissement, demandes)
        total = 0
        for pk, quantite in demandes.items():
            article = articles[pk]
            if not article.actif:
                raise ValidationError(f"« {article.nom_complet} » n'est plus en vente.")
            if quantite > article.stock:
                raise ValidationError(f"Stock insuffisant pour « {article.nom_complet} » : il en reste {article.stock}.")
            total += article.prix * quantite
        vente = VenteTenue(
            etablissement=etablissement, eleve=eleve, acheteur=(acheteur or "").strip()[:120] if eleve is None else "", mode_paiement=mode_paiement,
            total=total, enregistre_par=acteur, reference=generer_reference("TEN", etablissement),
        )
        vente.full_clean()
        vente.save()
        for pk in sorted(demandes):
            article, quantite = articles[pk], demandes[pk]
            LigneVenteTenue.objects.create(
                vente=vente, article=article, libelle=article.nom_complet[:160], quantite=quantite, prix_unitaire=article.prix,
            )
            _mouvement(article, -quantite, MotifStockTenue.VENTE, acteur, vente=vente)
        MouvementCaisse.objects.create(
            type_mouvement=MouvementCaisse.TypeMouvement.ENTREE, montant=total, etablissement=etablissement,
            description=f"Vente de tenues - {vente.nom_acheteur}", reference=generer_reference("CAI", etablissement), vente_tenue=vente,
        )
    return vente


def annuler_vente(*, vente, motif: str, acteur) -> None:
    """Annulation réservée à la direction : les articles retournent en stock, la vente et sa ligne de Caisse restent, marquées « annulées »."""
    if acteur.role not in {role.value for role in ROLES_ACCES_TOTAL_INCONDITIONNEL}:
        raise ValidationError("Seule la direction peut annuler une vente.")
    if not (motif or "").strip():
        raise ValidationError("Indiquez le motif de l'annulation.")
    maintenant = timezone.now()
    with transaction.atomic():
        vente = VenteTenue.objects.select_for_update().get(pk=vente.pk)
        if vente.annulee:
            raise ValidationError("Cette vente est déjà annulée.")
        lignes = list(vente.lignes.select_related("article"))
        articles = _verrouiller(vente.etablissement, [ligne.article_id for ligne in lignes])
        for ligne in lignes:
            _mouvement(articles[ligne.article_id], ligne.quantite, MotifStockTenue.ANNULATION, acteur, vente=vente, note=f"Annulation de {vente.reference}")
        vente.annulee, vente.annulee_par, vente.annulee_le, vente.motif_annulation = True, acteur, maintenant, motif.strip()[:255]
        vente.save(update_fields=["annulee", "annulee_par", "annulee_le", "motif_annulation"])
        mouvement = getattr(vente, "mouvement_caisse", None)
        if mouvement is not None and not mouvement.annule:
            mouvement.annule, mouvement.annule_par, mouvement.annule_le = True, acteur, maintenant
            mouvement.save(update_fields=["annule", "annule_par", "annule_le"])
