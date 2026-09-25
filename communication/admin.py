from django.contrib import admin

from communication.models import Annonce, Message
from comptes.admin import EtablissementAdminMixin


@admin.register(Annonce)
class AnnonceAdmin(EtablissementAdminMixin, admin.ModelAdmin):
    list_display = ["titre", "portee", "classe_ciblee", "auteur", "date_publication"]
    list_filter = ["portee"]
    search_fields = ["titre", "contenu"]


@admin.register(Message)
class MessageAdmin(EtablissementAdminMixin, admin.ModelAdmin):
    """Lecture seule : messagerie privée entre parent et enseignant, jamais éditée depuis l'admin."""

    list_display = ["eleve", "expediteur", "destinataire", "envoye_le", "lu_le"]
    search_fields = ["eleve__nom", "eleve__prenom", "expediteur__nom", "destinataire__nom", "contenu"]
    readonly_fields = [f.name for f in Message._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
