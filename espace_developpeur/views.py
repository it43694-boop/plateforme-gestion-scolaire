from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from comptes.audit import enregistrer_action
from comptes.decorators import role_requis
from comptes.models import Utilisateur
from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role
from espace_developpeur.forms import CreerAnneeScolaireForm, ModifierCompteForm, ParametresEtablissementForm
from etablissement.models import Etablissement
from permissions_matrix.models import PermissionMatrix
from permissions_matrix.modules import Module
from scolarite.models import AnneeScolaire

# Cahier des charges : « Seul rôle pouvant attribuer les rôles/statuts et
# gérer la matrice de permissions. » - une restriction volontairement plus
# stricte que ROLES_ACCES_TOTAL_INCONDITIONNEL (qui inclut fondateur et
# administrateur_general, lesquels n'ont PAS ce pouvoir précis).
ROLE_ESPACE_DEVELOPPEUR = (Role.DEVELOPPEUR,)

# Rôles dont l'accès est total et inconditionnel : la matrice ne les
# concerne pas, on ne les affiche donc pas comme éditables dans la grille.
ROLES_HORS_MATRICE = {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL}
ROLES_EDITABLES_DANS_LA_MATRICE = [r for r in Role if r.value not in ROLES_HORS_MATRICE]


def _filtre_recherche(recherche):
    from django.db.models import Q
    return (
        Q(email__icontains=recherche) | Q(nom__icontains=recherche)
        | Q(prenom__icontains=recherche) | Q(matricule__icontains=recherche)
    )


@role_requis(*ROLE_ESPACE_DEVELOPPEUR)
def parametres_etablissement(request):
    etablissement = request.user.etablissement
    if etablissement is None:
        messages.error(request, "Votre compte n'est rattaché à aucun établissement.")
        return redirect("comptes:redirection_tableau_de_bord")
    formulaire = ParametresEtablissementForm(
        request.POST or None, request.FILES or None, instance=etablissement,
    )
    if request.method == "POST" and formulaire.is_valid():
        formulaire.save()
        enregistrer_action(
            acteur=request.user, action="modification_etablissement",
            cible=etablissement.nom, request=request,
        )
        messages.success(request, "Identité de l'établissement mise à jour.")
        return redirect("espace_developpeur:parametres_etablissement")
    return render(request, "espace_developpeur/parametres_etablissement.html", {
        "formulaire": formulaire, "etablissement": etablissement,
    })


@role_requis(*ROLE_ESPACE_DEVELOPPEUR)
def liste_comptes(request):
    recherche = request.GET.get("q", "").strip()
    comptes = Utilisateur.objects.filter(etablissement=request.user.etablissement).order_by("nom", "prenom")
    if recherche:
        comptes = comptes.filter(_filtre_recherche(recherche))
    page_obj = Paginator(comptes, 30).get_page(request.GET.get("page"))
    return render(request, "espace_developpeur/liste_comptes.html", {
        "page_obj": page_obj, "comptes": page_obj.object_list, "recherche": recherche,
    })


@role_requis(*ROLE_ESPACE_DEVELOPPEUR)
def modifier_compte(request, utilisateur_id):
    compte = get_object_or_404(Utilisateur, id=utilisateur_id, etablissement=request.user.etablissement)
    est_soi_meme = compte.id == request.user.id

    formulaire = ModifierCompteForm(request.POST or None, etablissement=request.user.etablissement, initial={
        "role": compte.role, "statut": compte.statut,
    })
    if request.method == "POST" and formulaire.is_valid():
        if est_soi_meme and formulaire.cleaned_data["role"] != compte.role:
            messages.error(request, "Vous ne pouvez pas modifier votre propre rôle depuis cette page.")
            return redirect("espace_developpeur:modifier_compte", utilisateur_id=compte.id)

        ancien_role, ancien_statut = compte.role, compte.statut
        compte.role = formulaire.cleaned_data["role"]
        compte.statut = formulaire.cleaned_data["statut"]
        compte.is_active = compte.statut == "actif"
        compte.save(update_fields=["role", "statut", "is_active"])

        enregistrer_action(
            acteur=request.user, action="modification_compte_espace_developpeur",
            cible=compte.email,
            details={
                "role": f"{ancien_role} -> {compte.role}", "statut": f"{ancien_statut} -> {compte.statut}",
            },
            request=request,
        )
        messages.success(request, f"Compte de {compte.nom_complet} mis à jour.")
        return redirect("espace_developpeur:liste_comptes")

    return render(request, "espace_developpeur/modifier_compte.html", {
        "formulaire": formulaire, "compte": compte, "est_soi_meme": est_soi_meme,
    })


@role_requis(*ROLE_ESPACE_DEVELOPPEUR)
@require_http_methods(["POST"])
def reinitialiser_2fa_compte(request, utilisateur_id):
    """
    Filet de secours quand un compte a perdu à la fois son appareil TOTP et
    ses codes de secours : désactive complètement la 2FA du compte, qui
    devra la reconfigurer entièrement à sa prochaine connexion (voir
    ForcerActivation2FAMiddleware pour les rôles où elle est obligatoire).
    """
    compte = get_object_or_404(Utilisateur, id=utilisateur_id, etablissement=request.user.etablissement)
    if compte.id == request.user.id:
        messages.error(request, "Vous ne pouvez pas réinitialiser votre propre 2FA depuis cette page.")
        return redirect("espace_developpeur:modifier_compte", utilisateur_id=compte.id)

    compte.totp_secret = ""
    compte.deux_facteurs_actif = False
    compte.save(update_fields=["totp_secret", "deux_facteurs_actif"])
    compte.codes_secours_2fa.all().delete()
    enregistrer_action(
        acteur=request.user, action="reinitialisation_2fa_espace_developpeur",
        cible=compte.email, request=request,
    )
    messages.success(
        request,
        f"Double authentification réinitialisée pour {compte.nom_complet}. "
        "Le compte devra la reconfigurer à sa prochaine connexion.",
    )
    return redirect("espace_developpeur:modifier_compte", utilisateur_id=compte.id)


@role_requis(*ROLE_ESPACE_DEVELOPPEUR)
def matrice_permissions_vue(request):
    etablissement = request.user.etablissement
    if etablissement is None:
        messages.error(request, "Votre compte n'est rattaché à aucun établissement.")
        return redirect("comptes:redirection_tableau_de_bord")

    if request.method == "POST":
        modifications = 0
        for role in ROLES_EDITABLES_DANS_LA_MATRICE:
            for module in Module:
                cle = f"{role.value}__{module.value}"
                autorise = cle in request.POST
                regle, _ = PermissionMatrix.objects.get_or_create(
                    role=role.value, module=module.value, etablissement=etablissement,
                )
                if regle.autorise != autorise:
                    regle.autorise = autorise
                    regle.modifie_par = request.user
                    regle.save()
                    modifications += 1
        enregistrer_action(
            acteur=request.user, action="modification_matrice_permissions_espace_developpeur",
            details={"nombre_changements": modifications}, request=request,
        )
        messages.success(request, f"Matrice mise à jour ({modifications} changement(s)).")
        return redirect("espace_developpeur:matrice_permissions")

    lignes = []
    for role in ROLES_EDITABLES_DANS_LA_MATRICE:
        cellules = []
        for module in Module:
            autorise = PermissionMatrix.a_acces(role.value, module.value, etablissement=etablissement)
            cellules.append({"module": module, "autorise": autorise, "cle": f"{role.value}__{module.value}"})
        lignes.append({"role": role, "cellules": cellules})

    return render(request, "espace_developpeur/matrice_permissions.html", {
        "lignes": lignes, "modules": list(Module), "roles_acces_total": ROLES_ACCES_TOTAL_INCONDITIONNEL,
    })


@role_requis(*ROLE_ESPACE_DEVELOPPEUR)
def annees_scolaires(request):
    """
    Seule façon de créer une année scolaire jusqu'ici : l'interface
    d'administration Django (/admin/), réservée à un compte superutilisateur
    technique - pas au rôle « développeur » de l'application elle-même.
    """
    etablissement = request.user.etablissement
    if etablissement is None:
        messages.error(request, "Votre compte n'est rattaché à aucun établissement.")
        return redirect("comptes:redirection_tableau_de_bord")

    formulaire = CreerAnneeScolaireForm(request.POST or None, etablissement=etablissement)
    if request.method == "POST" and formulaire.is_valid():
        annee = formulaire.save()
        enregistrer_action(
            acteur=request.user, action="creation_annee_scolaire", cible=annee.libelle, request=request,
        )
        messages.success(request, f"Année scolaire « {annee.libelle} » créée.")
        return redirect("espace_developpeur:annees_scolaires")

    annees = AnneeScolaire.objects.filter(etablissement=etablissement).order_by("-date_debut")
    return render(request, "espace_developpeur/annees_scolaires.html", {
        "formulaire": formulaire, "annees": annees,
    })


@role_requis(*ROLE_ESPACE_DEVELOPPEUR)
@require_http_methods(["POST"])
def activer_annee_scolaire(request, annee_id):
    annee = get_object_or_404(AnneeScolaire, id=annee_id, etablissement=request.user.etablissement)
    if annee.est_archivee:
        messages.error(request, "Une année archivée ne peut pas être réactivée depuis cette page.")
        return redirect("espace_developpeur:annees_scolaires")
    annee.est_active = True
    annee.save()
    enregistrer_action(
        acteur=request.user, action="activation_annee_scolaire", cible=annee.libelle, request=request,
    )
    messages.success(request, f"« {annee.libelle} » est maintenant l'année active.")
    return redirect("espace_developpeur:annees_scolaires")


@role_requis(*ROLE_ESPACE_DEVELOPPEUR)
@require_http_methods(["POST"])
def archiver_annee_scolaire(request, annee_id):
    annee = get_object_or_404(AnneeScolaire, id=annee_id, etablissement=request.user.etablissement)
    annee.est_active = False
    annee.est_archivee = True
    annee.save()
    enregistrer_action(
        acteur=request.user, action="archivage_annee_scolaire", cible=annee.libelle, request=request,
    )
    messages.success(request, f"« {annee.libelle} » archivée : elle ne peut plus recevoir de nouvelles écritures.")
    return redirect("espace_developpeur:annees_scolaires")


@role_requis(*ROLE_ESPACE_DEVELOPPEUR)
def journal_audit(request):
    from comptes.models import JournalAudit

    recherche = request.GET.get("q", "").strip()
    entrees = JournalAudit.objects.filter(
        etablissement=request.user.etablissement,
    ).select_related("acteur").order_by("-horodatage")
    if recherche:
        from django.db.models import Q
        entrees = entrees.filter(
            Q(action__icontains=recherche) | Q(cible__icontains=recherche)
            | Q(acteur__nom__icontains=recherche) | Q(acteur__prenom__icontains=recherche)
        )
    page_obj = Paginator(entrees, 50).get_page(request.GET.get("page"))
    return render(request, "espace_developpeur/journal_audit.html", {
        "page_obj": page_obj, "entrees": page_obj.object_list, "recherche": recherche,
    })
