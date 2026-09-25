from django.contrib import admin

from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL
from comptes.admin import EtablissementAdminMixin
from finances.models import MouvementCaisse, Paiement, Salaire, SequenceReference


class SuppressionReserveeDirectionMixin:
    """Interdit la suppression depuis l'admin à quiconque n'est pas de la direction."""

    def has_delete_permission(self, request, obj=None):
        return request.user.role in {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL}


@admin.register(Paiement)
class PaiementAdmin(EtablissementAdminMixin, SuppressionReserveeDirectionMixin, admin.ModelAdmin):
    list_display = ["reference", "eleve", "tranche", "montant", "mode_paiement", "date_paiement", "est_supprime"]
    list_filter = ["tranche", "mode_paiement", "est_supprime"]
    search_fields = ["reference", "eleve__nom", "eleve__prenom", "eleve__matricule"]
    readonly_fields = ["reference", "date_paiement", "est_supprime", "supprime_par", "supprime_le"]
    autocomplete_fields = ["eleve", "inscription"]


@admin.register(Salaire)
class SalaireAdmin(EtablissementAdminMixin, SuppressionReserveeDirectionMixin, admin.ModelAdmin):
    list_display = ["employe", "periode", "montant", "statut", "date_paiement", "est_supprime"]
    list_filter = ["statut", "est_supprime"]
    search_fields = ["employe__nom", "employe__prenom", "periode"]
    readonly_fields = ["reference", "date_paiement", "est_supprime", "supprime_par", "supprime_le"]
    autocomplete_fields = ["employe"]


@admin.register(MouvementCaisse)
class MouvementCaisseAdmin(EtablissementAdminMixin, admin.ModelAdmin):
    list_display = ["reference", "type_mouvement", "montant", "description", "date_mouvement", "annule"]
    list_filter = ["type_mouvement", "annule"]
    search_fields = ["reference", "description"]
    readonly_fields = [f.name for f in MouvementCaisse._meta.fields]

    def has_add_permission(self, request):
        # Aucune saisie manuelle : une ligne de Caisse ne naît que d'un
        # paiement ou d'un salaire payé (voir finances.models).
        return False

    def has_delete_permission(self, request, obj=None):
        # Jamais de suppression, même pour la direction : on annule, on n'efface pas.
        return False


@admin.register(SequenceReference)
class SequenceReferenceAdmin(EtablissementAdminMixin, admin.ModelAdmin):
    list_display = ["etablissement", "prefixe", "annee", "dernier_numero"]
    list_filter = ["prefixe", "annee"]
    readonly_fields = [f.name for f in SequenceReference._meta.fields]

    def has_add_permission(self, request):
        # Lecture seule : modifier ce compteur à la main romprait la
        # continuité des références (doublon si diminué, trou si augmenté).
        return False

    def has_delete_permission(self, request, obj=None):
        return False
