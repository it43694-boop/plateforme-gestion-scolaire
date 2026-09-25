from django.contrib import admin

from bibliotheque.models import Document
from comptes.admin import EtablissementAdminMixin


@admin.register(Document)
class DocumentAdmin(EtablissementAdminMixin, admin.ModelAdmin):
    list_display = ["titre", "nom_fichier", "taille_octets", "ajoute_par", "ajoute_le"]
    search_fields = ["titre", "description"]
