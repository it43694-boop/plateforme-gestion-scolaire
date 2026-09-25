from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from comptes.audit import enregistrer_action
from comptes.models import Utilisateur
from comptes.roles import Role, StatutCompte
from espace_developpeur.forms import ParametresEtablissementForm
from espace_plateforme.forms import CreerEtablissementForm
from etablissement.models import Etablissement
from permissions_matrix.models import PermissionMatrix

# Distinction volontaire : le rôle "développeur" gère SON établissement
# (identité, rôles, matrice) ; seul un superutilisateur - le propriétaire
# de la plateforme - peut créer et administrer les établissements
# eux-mêmes. Ce n'est pas un rôle métier de plus, mais le statut technique
# Django déjà utilisé pour le tout premier compte (créé via createsuperuser).
est_proprietaire_plateforme = user_passes_test(lambda u: u.is_authenticated and u.is_superuser)


@est_proprietaire_plateforme
def modifier_etablissement(request, etablissement_id):
    etablissement = get_object_or_404(Etablissement, id=etablissement_id)
    formulaire = ParametresEtablissementForm(request.POST or None, request.FILES or None, instance=etablissement)
    if request.method == "POST" and formulaire.is_valid():
        formulaire.save()
        enregistrer_action(
            acteur=request.user, action="modification_etablissement_par_plateforme",
            cible=etablissement.nom, request=request,
        )
        messages.success(request, f"Établissement « {etablissement.nom} » mis à jour.")
        return redirect("espace_plateforme:liste_etablissements")
    return render(request, "espace_plateforme/modifier_etablissement.html", {
        "formulaire": formulaire, "etablissement": etablissement,
    })


@est_proprietaire_plateforme
def voir_comptes_etablissement(request, etablissement_id):
    etablissement = get_object_or_404(Etablissement, id=etablissement_id)
    comptes = Utilisateur.objects.filter(etablissement=etablissement).order_by("nom", "prenom")
    page_obj = Paginator(comptes, 30).get_page(request.GET.get("page"))
    return render(request, "espace_plateforme/comptes_etablissement.html", {
        "etablissement": etablissement, "page_obj": page_obj, "comptes": page_obj.object_list,
    })


@est_proprietaire_plateforme
def liste_etablissements(request):
    etablissements = Etablissement.objects.all().order_by("nom")
    for etablissement in etablissements:
        etablissement.nb_comptes = etablissement.utilisateurs.count()
    return render(request, "espace_plateforme/liste_etablissements.html", {"etablissements": etablissements})


@est_proprietaire_plateforme
def creer_etablissement(request):
    formulaire = CreerEtablissementForm(request.POST or None)
    if request.method == "POST" and formulaire.is_valid():
        with transaction.atomic():
            etablissement = Etablissement.objects.create(
                nom=formulaire.cleaned_data["nom"], devise=formulaire.cleaned_data["devise"],
            )
            PermissionMatrix.seed_pour(etablissement)
            developpeur = Utilisateur(
                email=formulaire.cleaned_data["email_developpeur"],
                prenom=formulaire.cleaned_data["prenom_developpeur"],
                nom=formulaire.cleaned_data["nom_developpeur"],
                role=Role.DEVELOPPEUR, etablissement=etablissement,
                statut=StatutCompte.ACTIF, is_active=True, email_verifie=True,
            )
            developpeur.set_password(formulaire.cleaned_data["mot_de_passe_developpeur"])
            developpeur.full_clean(exclude=["password"])
            developpeur.save()

        enregistrer_action(
            acteur=request.user, action="creation_etablissement",
            cible=etablissement.nom, details={"developpeur": developpeur.email}, request=request,
        )
        messages.success(
            request,
            f"Établissement « {etablissement.nom} » créé, avec {developpeur.nom_complet} "
            f"comme premier administrateur ({developpeur.email}).",
        )
        return redirect("espace_plateforme:liste_etablissements")
    return render(request, "espace_plateforme/creer_etablissement.html", {"formulaire": formulaire})


@est_proprietaire_plateforme
@require_http_methods(["POST"])
def basculer_actif(request, etablissement_id):
    etablissement = get_object_or_404(Etablissement, id=etablissement_id)
    etablissement.actif = not etablissement.actif
    etablissement.save(update_fields=["actif"])
    enregistrer_action(
        acteur=request.user, action="bascule_actif_etablissement",
        cible=etablissement.nom, details={"actif": etablissement.actif}, request=request,
    )
    messages.success(
        request,
        f"Établissement « {etablissement.nom} » {'réactivé' if etablissement.actif else 'désactivé'}.",
    )
    return redirect("espace_plateforme:liste_etablissements")
