from django.db import models

from comptes.roles import Role, ROLES_ACCES_TOTAL_INCONDITIONNEL
from permissions_matrix.modules import Module


class PermissionMatrix(models.Model):
    """
    Matrice de permissions modulable depuis l'espace développeur, sans
    toucher au code (cahier des charges, section « Espace développeur »).
    Propre à CHAQUE établissement : le développeur d'une école ne modifie
    que la matrice de sa propre école, jamais celle d'une autre.

    Ce réglage prend le dessus sur l'accès par défaut décrit dans le
    tableau des rôles dès qu'une ligne existe pour le couple (rôle, module).
    Les rôles de la liste ROLES_ACCES_TOTAL_INCONDITIONNEL (développeur,
    fondateur, administrateur_general) ne sont jamais soumis à la matrice :
    leur accès complet est garanti par construction.
    """

    etablissement = models.ForeignKey(
        "etablissement.Etablissement", on_delete=models.CASCADE, related_name="matrice_permissions",
        null=True, blank=True,
    )
    role = models.CharField(max_length=40, choices=Role.choices)
    module = models.CharField(max_length=40, choices=Module.choices)
    autorise = models.BooleanField(default=False)
    modifie_le = models.DateTimeField(auto_now=True)
    modifie_par = models.ForeignKey(
        "comptes.Utilisateur", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="modifications_matrice",
    )

    class Meta:
        verbose_name = "règle de la matrice de permissions"
        verbose_name_plural = "matrice de permissions"
        unique_together = ("etablissement", "role", "module")
        ordering = ["etablissement", "role", "module"]

    def __str__(self):
        etat = "autorisé" if self.autorise else "refusé"
        return f"{self.get_role_display()} - {self.get_module_display()} : {etat}"

    @classmethod
    def a_acces(cls, role: str, module: str, etablissement=None) -> bool:
        """
        Point d'entrée unique pour vérifier un accès. À utiliser partout
        dans l'application plutôt que de coder les règles en dur.

        Filtre puis prend la première ligne plutôt qu'un get() : avec
        etablissement=None, SQL ne considère pas deux NULL comme égaux,
        donc unique_together ("etablissement", "role", "module") ne peut
        pas empêcher deux lignes "historiques" (sans établissement) pour
        le même rôle/module - un get() lèverait alors MultipleObjectsReturned
        au lieu de répondre simplement par l'autorisation trouvée.
        """
        if role in {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL}:
            return True
        return bool(
            cls.objects.filter(role=role, module=module, etablissement=etablissement)
            .values_list("autorise", flat=True).first()
        )

    @classmethod
    def modules_autorises(cls, role: str, etablissement=None) -> list[str]:
        if role in {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL}:
            return [m.value for m in Module]
        return list(
            cls.objects.filter(role=role, autorise=True, etablissement=etablissement).values_list("module", flat=True)
        )

    @classmethod
    def seed_pour(cls, etablissement):
        """Crée la matrice par défaut pour un établissement qui vient d'être créé."""
        from permissions_matrix.matrice_par_defaut import generer_lignes
        cls.objects.bulk_create(
            [cls(etablissement=etablissement, **ligne) for ligne in generer_lignes()],
            ignore_conflicts=True,
        )
