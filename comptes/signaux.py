"""
Quand un nom change (personne, école, classe), l'index des noms arabes de l'école est reconstruit à la prochaine page (comptes.arabisation).
Les mises à jour en masse (QuerySet.update) ne passent pas par ces signaux : elles appellent `invalider` elles-mêmes.
"""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from comptes.arabisation import invalider
from comptes.models import Utilisateur
from etablissement.models import Etablissement
from scolarite.models import Classe, ParentEnAttente
from tests_niveau.models import Candidat


@receiver([post_save, post_delete], sender=Utilisateur)
def utilisateur_modifie(sender, instance, **kwargs):
    invalider(instance.etablissement_id)


@receiver([post_save, post_delete], sender=Etablissement)
def etablissement_modifie(sender, instance, **kwargs):
    invalider(instance.pk)


@receiver([post_save, post_delete], sender=Classe)
def classe_modifiee(sender, instance, **kwargs):
    try:
        invalider(instance.annee_scolaire.etablissement_id)
    except Exception:  # l'année scolaire n'existe plus (suppression en cascade) : l'index expirera tout seul
        invalider(None)


@receiver([post_save, post_delete], sender=Candidat)
def candidat_modifie(sender, instance, **kwargs):
    try:
        invalider(instance.classe_visee.annee_scolaire.etablissement_id)
    except Exception:
        invalider(None)


@receiver([post_save, post_delete], sender=ParentEnAttente)
def parent_en_attente_modifie(sender, instance, **kwargs):
    try:
        invalider(instance.eleve.etablissement_id)
    except Exception:
        invalider(None)
