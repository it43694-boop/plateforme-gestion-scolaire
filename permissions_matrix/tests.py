from django.test import TestCase

from comptes.roles import Role
from etablissement.models import Etablissement
from permissions_matrix.matrice_par_defaut import MATRICE_PAR_DEFAUT
from permissions_matrix.models import PermissionMatrix
from permissions_matrix.modules import Module


class AccesRolesPleinPouvoirTests(TestCase):
    """
    Développeur, fondateur, administrateur général : accès total garanti
    par construction, jamais soumis à la matrice - aucune ligne créée ne
    doit pouvoir le restreindre.
    """

    def test_acces_total_sans_aucune_ligne_en_base(self):
        self.assertTrue(PermissionMatrix.a_acces(Role.DEVELOPPEUR.value, Module.ASSISTANT.value))
        self.assertTrue(PermissionMatrix.a_acces(Role.FONDATEUR.value, Module.FINANCES.value))
        self.assertTrue(PermissionMatrix.a_acces(Role.ADMINISTRATEUR_GENERAL.value, Module.ESPACE_DEVELOPPEUR.value))

    def test_modules_autorises_retourne_tous_les_modules(self):
        self.assertEqual(
            set(PermissionMatrix.modules_autorises(Role.DEVELOPPEUR.value)),
            {m.value for m in Module},
        )

    def test_une_ligne_refusee_ne_restreint_pas_un_role_plein_pouvoir(self):
        etablissement = Etablissement.objects.create(nom="École pleins pouvoirs")
        PermissionMatrix.objects.create(
            etablissement=etablissement, role=Role.FONDATEUR.value, module=Module.FINANCES.value, autorise=False,
        )
        self.assertTrue(PermissionMatrix.a_acces(Role.FONDATEUR.value, Module.FINANCES.value, etablissement=etablissement))


class AccesFailClosedTests(TestCase):
    """
    Pour tout autre rôle, l'absence de règle doit toujours se traduire par
    un refus - jamais par un accès accordé par défaut.
    """

    def test_aucune_ligne_en_base_refuse_lacces(self):
        etablissement = Etablissement.objects.create(nom="École sans matrice")
        self.assertFalse(PermissionMatrix.a_acces(Role.COMPTABLE.value, Module.FINANCES.value, etablissement=etablissement))
        self.assertEqual(PermissionMatrix.modules_autorises(Role.COMPTABLE.value, etablissement=etablissement), [])

    def test_ligne_autorise_false_refuse_lacces(self):
        etablissement = Etablissement.objects.create(nom="École règle refusée")
        PermissionMatrix.objects.create(
            etablissement=etablissement, role=Role.SECRETAIRE.value, module=Module.FINANCES.value, autorise=False,
        )
        self.assertFalse(PermissionMatrix.a_acces(Role.SECRETAIRE.value, Module.FINANCES.value, etablissement=etablissement))

    def test_ligne_autorise_true_accorde_lacces(self):
        etablissement = Etablissement.objects.create(nom="École règle accordée")
        PermissionMatrix.objects.create(
            etablissement=etablissement, role=Role.SECRETAIRE.value, module=Module.ELEVES.value, autorise=True,
        )
        self.assertTrue(PermissionMatrix.a_acces(Role.SECRETAIRE.value, Module.ELEVES.value, etablissement=etablissement))

    def test_deux_lignes_historiques_sans_etablissement_ne_font_pas_planter_a_acces(self):
        """
        SQL ne considère pas deux NULL comme égaux : unique_together
        ("etablissement", "role", "module") ne peut donc pas empêcher deux
        lignes « historiques » (etablissement=None) pour le même rôle/
        module - déjà arrivé en pratique sur une base reconstruite depuis
        zéro (migrations de données successives y ajoutant chacune une
        ligne). a_acces() doit répondre, pas lever MultipleObjectsReturned.
        """
        # Repart de zéro pour ce couple rôle/module : le seed historique y a
        # déjà une ligne (etablissement=None, comme toute ligne « globale »
        # antérieure au multi-établissement) - le bug ne se manifeste que
        # lorsque plusieurs lignes existent ET s'accordent sur la même
        # valeur, comme deux migrations de données redondantes l'ont
        # vraiment produit pour (directeur_lycee, bibliotheque).
        PermissionMatrix.objects.filter(
            role=Role.BIBLIOTHECAIRE.value, module=Module.STATISTIQUES.value, etablissement=None,
        ).delete()
        PermissionMatrix.objects.create(
            etablissement=None, role=Role.BIBLIOTHECAIRE.value, module=Module.STATISTIQUES.value, autorise=True,
        )
        PermissionMatrix.objects.create(
            etablissement=None, role=Role.BIBLIOTHECAIRE.value, module=Module.STATISTIQUES.value, autorise=True,
        )
        self.assertEqual(
            PermissionMatrix.objects.filter(
                role=Role.BIBLIOTHECAIRE.value, module=Module.STATISTIQUES.value, etablissement=None,
            ).count(), 2,
        )
        self.assertTrue(PermissionMatrix.a_acces(Role.BIBLIOTHECAIRE.value, Module.STATISTIQUES.value, etablissement=None))


class CloisonnementParEtablissementTests(TestCase):
    """
    Garantie multi-tenant critique : une règle créée pour un établissement
    ne doit jamais s'appliquer à un autre, ni au « global » (etablissement
    None) et réciproquement.
    """

    def setUp(self):
        self.ecole_a = Etablissement.objects.create(nom="École A")
        self.ecole_b = Etablissement.objects.create(nom="École B")

    def test_regle_dune_ecole_najoute_pas_dacces_dans_lautre(self):
        PermissionMatrix.objects.create(
            etablissement=self.ecole_a, role=Role.COMPTABLE.value, module=Module.FINANCES.value, autorise=True,
        )
        self.assertTrue(PermissionMatrix.a_acces(Role.COMPTABLE.value, Module.FINANCES.value, etablissement=self.ecole_a))
        self.assertFalse(PermissionMatrix.a_acces(Role.COMPTABLE.value, Module.FINANCES.value, etablissement=self.ecole_b))

    def test_regle_par_etablissement_najoute_pas_dacces_global(self):
        # ELEVES n'est pas dans MATRICE_PAR_DEFAUT pour COMPTABLE : la migration
        # 0002 ne seed donc aucune ligne globale (etablissement=None) pour ce
        # couple - un vrai « aucune règle nulle part » pour cette assertion,
        # contrairement à FINANCES qui existe déjà globalement pour ce rôle.
        PermissionMatrix.objects.create(
            etablissement=self.ecole_a, role=Role.COMPTABLE.value, module=Module.ELEVES.value, autorise=True,
        )
        self.assertFalse(PermissionMatrix.a_acces(Role.COMPTABLE.value, Module.ELEVES.value, etablissement=None))

    def test_regle_globale_najoute_pas_dacces_dans_un_etablissement_precis(self):
        # ELEVES : voir la remarque du test symétrique ci-dessus - la migration
        # 0002 ne seed rien pour ce couple, la ligne créée ici est donc la seule.
        PermissionMatrix.objects.create(
            etablissement=None, role=Role.COMPTABLE.value, module=Module.ELEVES.value, autorise=True,
        )
        self.assertFalse(PermissionMatrix.a_acces(Role.COMPTABLE.value, Module.ELEVES.value, etablissement=self.ecole_a))

    def test_modules_autorises_ne_mélange_pas_deux_etablissements(self):
        PermissionMatrix.objects.create(
            etablissement=self.ecole_a, role=Role.COMPTABLE.value, module=Module.FINANCES.value, autorise=True,
        )
        PermissionMatrix.objects.create(
            etablissement=self.ecole_b, role=Role.COMPTABLE.value, module=Module.CAISSE.value, autorise=True,
        )
        self.assertEqual(PermissionMatrix.modules_autorises(Role.COMPTABLE.value, etablissement=self.ecole_a), [Module.FINANCES.value])
        self.assertEqual(PermissionMatrix.modules_autorises(Role.COMPTABLE.value, etablissement=self.ecole_b), [Module.CAISSE.value])


class SeedPourTests(TestCase):
    """
    seed_pour() doit reproduire fidèlement MATRICE_PAR_DEFAUT pour
    l'établissement donné, sans toucher aux autres, et rester
    sans danger si on l'appelle deux fois (idempotence).
    """

    def test_seed_pour_applique_la_matrice_par_defaut(self):
        etablissement = Etablissement.objects.create(nom="École seed")
        PermissionMatrix.seed_pour(etablissement)

        for role, modules_attendus in MATRICE_PAR_DEFAUT.items():
            modules_obtenus = set(PermissionMatrix.modules_autorises(role.value, etablissement=etablissement))
            self.assertEqual(modules_obtenus, {m.value for m in modules_attendus}, f"rôle {role.value}")

    def test_seed_pour_ne_touche_pas_un_autre_etablissement(self):
        ecole_seedee = Etablissement.objects.create(nom="École seedée")
        ecole_vierge = Etablissement.objects.create(nom="École vierge")
        PermissionMatrix.seed_pour(ecole_seedee)

        self.assertFalse(PermissionMatrix.a_acces(Role.COMPTABLE.value, Module.FINANCES.value, etablissement=ecole_vierge))
        self.assertEqual(PermissionMatrix.modules_autorises(Role.COMPTABLE.value, etablissement=ecole_vierge), [])

    def test_seed_pour_est_idempotent(self):
        etablissement = Etablissement.objects.create(nom="École seed double")
        PermissionMatrix.seed_pour(etablissement)
        nombre_apres_premier_seed = PermissionMatrix.objects.filter(etablissement=etablissement).count()

        PermissionMatrix.seed_pour(etablissement)
        nombre_apres_second_seed = PermissionMatrix.objects.filter(etablissement=etablissement).count()

        self.assertEqual(nombre_apres_premier_seed, nombre_apres_second_seed)
        self.assertGreater(nombre_apres_premier_seed, 0)

    def test_censeur_et_surveillant_general_nont_pas_lacces_classes(self):
        """
        Le Censeur (adjoint du proviseur) et le Surveillant général ne
        doivent jamais pouvoir créer/administrer une classe - réservé à la
        direction (DIRECTEUR_LYCEE). Vérifié indépendamment du round-trip
        générique ci-dessus, car c'est la garantie de sécurité centrale.
        """
        etablissement = Etablissement.objects.create(nom="École censeur seed")
        PermissionMatrix.seed_pour(etablissement)
        self.assertFalse(PermissionMatrix.a_acces(Role.CENSEUR.value, Module.CLASSES.value, etablissement=etablissement))
        self.assertFalse(PermissionMatrix.a_acces(Role.SURVEILLANT_GENERAL.value, Module.CLASSES.value, etablissement=etablissement))
        self.assertFalse(PermissionMatrix.a_acces(Role.SURVEILLANT_GENERAL.value, Module.NOTES_BULLETINS.value, etablissement=etablissement))

    def test_seed_pour_ne_cree_aucune_ligne_pour_les_roles_pleins_pouvoirs(self):
        etablissement = Etablissement.objects.create(nom="École pleins pouvoirs seed")
        PermissionMatrix.seed_pour(etablissement)

        from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL

        for role in ROLES_ACCES_TOTAL_INCONDITIONNEL:
            self.assertFalse(
                PermissionMatrix.objects.filter(etablissement=etablissement, role=role.value).exists(),
                f"rôle {role.value} ne devrait jamais figurer dans la matrice",
            )


class UniciteRoleModuleEtablissementTests(TestCase):
    def test_deux_lignes_identiques_sont_impossibles(self):
        from django.db import IntegrityError, transaction

        etablissement = Etablissement.objects.create(nom="École unicité")
        PermissionMatrix.objects.create(
            etablissement=etablissement, role=Role.SECRETAIRE.value, module=Module.ELEVES.value, autorise=True,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PermissionMatrix.objects.create(
                    etablissement=etablissement, role=Role.SECRETAIRE.value, module=Module.ELEVES.value, autorise=False,
                )
