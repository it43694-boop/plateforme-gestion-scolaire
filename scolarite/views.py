from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.crypto import get_random_string

from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from comptes.models import Utilisateur, creer_avec_matricule_unique, generer_matricule
from comptes.roles import Role, StatutCompte
from permissions_matrix.modules import Module
from scolarite.forms import AffecterEnseignantForm, CreerClasseForm, InscrireEleveForm
from scolarite.models import (
    Affectation, AnneeScolaire, Classe, Inscription, classes_visibles_pour, dossier_complet,
    eleve_visible_pour, lier_parent_a_eleve, passer_eleve, calculer_total_du,
)

DOMAINE_EMAIL_AUTO_ELEVE = "eleves.local"


@module_requis(Module.ELEVES)
def inscrire_eleve(request):
    classes_disponibles = classes_visibles_pour(request.user)
    formulaire = InscrireEleveForm(
        request.POST or None, classes_disponibles=classes_disponibles,
    )

    if request.method == "POST" and formulaire.is_valid():
        def _construire_eleve():
            matricule = formulaire.cleaned_data["matricule"] or generer_matricule()
            email_auto = f"{matricule}@{DOMAINE_EMAIL_AUTO_ELEVE}"
            nouvel_eleve = Utilisateur(
                email=email_auto,
                prenom=formulaire.cleaned_data["prenom"],
                nom=formulaire.cleaned_data["nom"],
                role=Role.ELEVE,
                matricule=matricule,
                etablissement=request.user.etablissement,
                sexe=formulaire.cleaned_data["sexe"],
                date_naissance=formulaire.cleaned_data.get("date_naissance"),
                statut=StatutCompte.ACTIF,
                is_active=True,
                email_verifie=True,
            )
            nouvel_eleve.set_password(get_random_string(32))
            nouvel_eleve.full_clean(exclude=["password"])
            nouvel_eleve.save()
            return nouvel_eleve

        eleve = creer_avec_matricule_unique(_construire_eleve)

        for parent in filter(None, [formulaire.cleaned_data["parent_1"], formulaire.cleaned_data["parent_2"]]):
            lier_parent_a_eleve(eleve, parent)

        Inscription.objects.create(eleve=eleve, classe=formulaire.cleaned_data["classe"])

        enregistrer_action(
            acteur=request.user, action="inscription_eleve",
            cible=f"{eleve.nom_complet} ({eleve.matricule})",
            details={"classe": str(formulaire.cleaned_data["classe"])},
            request=request,
        )

        messages.success(
            request,
            f"Élève inscrit avec succès. Matricule : {eleve.matricule}. "
            f"Dossier {'complet' if dossier_complet(eleve) else 'incomplet - vérifiez la date de naissance et le téléphone du parent'}.",
        )
        return redirect("scolarite:inscrire_eleve")

    return render(request, "scolarite/inscrire_eleve.html", {"formulaire": formulaire})


@module_requis(Module.ELEVES)
def dossier_eleve(request, matricule):
    """
    Vue consolidée d'un élève : son historique complet (classes, notes,
    absences, finances) réuni en une seule page, plutôt qu'éparpillé sur
    quatre écrans différents.
    """
    from django.core.exceptions import PermissionDenied
    from django.db.models import Sum
    from django.shortcuts import get_object_or_404

    eleve = get_object_or_404(Utilisateur, matricule=matricule, role=Role.ELEVE)
    if not eleve_visible_pour(request.user, eleve):
        raise PermissionDenied("Vous n'avez pas accès au dossier de cet élève.")

    from permissions_matrix.models import PermissionMatrix
    peut_voir_notes = PermissionMatrix.a_acces(request.user.role, "notes_bulletins", etablissement=request.user.etablissement)
    peut_voir_absences = PermissionMatrix.a_acces(request.user.role, "absences", etablissement=request.user.etablissement)
    peut_voir_finances = PermissionMatrix.a_acces(request.user.role, "finances", etablissement=request.user.etablissement)

    inscriptions = Inscription.objects.filter(eleve=eleve).select_related(
        "classe", "classe__annee_scolaire",
    ).order_by("-classe__annee_scolaire__date_debut")
    inscription_active = inscriptions.filter(statut=Inscription.Statut.EN_COURS).first()

    contexte = {
        "eleve": eleve, "dossier_complet": dossier_complet(eleve),
        "inscriptions": inscriptions, "inscription_active": inscription_active,
        "parents": eleve.parents_lies.all(),
        "peut_voir_notes": peut_voir_notes, "peut_voir_absences": peut_voir_absences, "peut_voir_finances": peut_voir_finances,
    }

    if peut_voir_absences:
        from pedagogie.models import Absence
        contexte["total_absences"] = Absence.objects.filter(eleve=eleve).count()

    if peut_voir_finances:
        from finances.models import Paiement
        contexte["total_paye"] = Paiement.objects.filter(
            eleve=eleve, est_supprime=False,
        ).aggregate(total=Sum("montant"))["total"] or 0
        if inscription_active:
            echeancier = getattr(inscription_active.classe, "echeancier", None)
            total_du = calculer_total_du(inscription_active)
            paye_annee = Paiement.objects.filter(
                inscription=inscription_active, est_supprime=False,
            ).aggregate(total=Sum("montant"))["total"] or 0
            contexte["solde_annee_active"] = total_du - paye_annee

    return render(request, "scolarite/dossier_eleve.html", contexte)


@module_requis(Module.CLASSES)
def liste_matieres(request):
    """
    Vue d'ensemble des matières enseignées (déduites des affectations
    enseignant/classe), groupées par nom de matière. La matière reste un
    champ libre sur l'affectation - cette page en donne juste une vue
    consolidée, plutôt que de la laisser éparpillée affectation par affectation.
    """
    affectations = Affectation.objects.filter(
        classe__in=classes_visibles_pour(request.user),
    ).exclude(matiere="").select_related("enseignant", "classe").order_by("matiere", "classe__nom")

    matieres = {}
    for affectation in affectations:
        matieres.setdefault(affectation.matiere, []).append(affectation)

    return render(request, "scolarite/liste_matieres.html", {"matieres": matieres})


@module_requis(Module.ELEVES)
def liste_eleves(request):
    from permissions_matrix.models import PermissionMatrix

    classe_id = request.GET.get("classe")
    classes = classes_visibles_pour(request.user)
    inscriptions = Inscription.objects.filter(
        classe__in=classes, statut=Inscription.Statut.EN_COURS,
    ).select_related("eleve", "classe").order_by("classe__nom", "eleve__nom")
    if classe_id:
        inscriptions = inscriptions.filter(classe_id=classe_id)

    page_obj = Paginator(inscriptions, 30).get_page(request.GET.get("page"))
    return render(request, "scolarite/liste_eleves.html", {
        "page_obj": page_obj, "inscriptions": page_obj.object_list,
        "classes": classes, "classe_id": classe_id,
        "peut_voir_bulletin": PermissionMatrix.a_acces(request.user.role, "notes_bulletins", etablissement=request.user.etablissement),
        "peut_voir_absences": PermissionMatrix.a_acces(request.user.role, "absences", etablissement=request.user.etablissement),
    })


@module_requis(Module.CLASSES)
def affecter_enseignant(request):
    classes_disponibles = classes_visibles_pour(request.user)
    formulaire = AffecterEnseignantForm(
        request.POST or None, etablissement=request.user.etablissement, classes_disponibles=classes_disponibles,
    )
    if request.method == "POST" and formulaire.is_valid():
        enseignant = formulaire.cleaned_data["enseignant"]
        classe = formulaire.cleaned_data["classe"]
        matiere = formulaire.cleaned_data["matiere"]
        coefficient = formulaire.cleaned_data["coefficient"] or 1
        if Affectation.objects.filter(enseignant=enseignant, classe=classe, matiere=matiere).exists():
            messages.warning(request, "Cet enseignant est déjà affecté à cette classe pour cette matière.")
        else:
            Affectation.objects.create(enseignant=enseignant, classe=classe, matiere=matiere, coefficient=coefficient)
            enregistrer_action(
                acteur=request.user, action="affectation_enseignant",
                cible=f"{enseignant.nom_complet} - {classe}",
                details={"matiere": matiere or "titulaire"}, request=request,
            )
            messages.success(request, f"{enseignant.nom_complet} affecté(e) à {classe}.")
        return redirect("scolarite:liste_classes")
    return render(request, "scolarite/affecter_enseignant.html", {"formulaire": formulaire})


@module_requis(Module.CLASSES)
def passage_de_classe(request, classe_id):
    """
    Passage de classe en fin d'année : pour chaque élève actuellement
    inscrit dans la classe, décide Admis / Redouble / Transféré, clôt son
    inscription actuelle et crée la nouvelle dans la classe de destination
    choisie. La classe de destination des admis est mémorisée sur la
    classe source pour ne pas être ressaisie l'année suivante.
    """
    from django.core.exceptions import ValidationError
    from django.db import transaction

    classe_source = get_object_or_404(classes_visibles_pour(request.user), id=classe_id)
    annees_destination = AnneeScolaire.objects.filter(
        etablissement=request.user.etablissement,
    ).exclude(pk=classe_source.annee_scolaire_id).order_by("-date_debut")

    annee_destination_id = request.POST.get("annee_destination") or request.GET.get("annee_destination")
    annee_destination = annees_destination.filter(pk=annee_destination_id).first() if annee_destination_id else None
    classes_destination = Classe.objects.filter(annee_scolaire=annee_destination) if annee_destination else Classe.objects.none()

    eleves_en_cours = Inscription.objects.filter(
        classe=classe_source, statut=Inscription.Statut.EN_COURS,
    ).select_related("eleve").order_by("eleve__nom")

    if request.method == "POST" and annee_destination:
        classe_admis_id = request.POST.get("classe_admis") or None
        classe_redouble_id = request.POST.get("classe_redouble") or None
        classe_admis = classes_destination.filter(pk=classe_admis_id).first() if classe_admis_id else None
        classe_redouble = classes_destination.filter(pk=classe_redouble_id).first() if classe_redouble_id else None

        decisions = {
            inscription.id: request.POST.get(f"decision_{inscription.id}", "admis")
            for inscription in eleves_en_cours
        }
        if "admis" in decisions.values() and not classe_admis:
            messages.error(request, "Choisissez une classe de destination pour les élèves admis.")
        elif "redouble" in decisions.values() and not classe_redouble:
            messages.error(request, "Choisissez une classe de destination pour les redoublants.")
        else:
            compteurs = {"admis": 0, "redouble": 0, "transfere": 0}
            with transaction.atomic():
                for inscription in eleves_en_cours:
                    decision_valeur = decisions[inscription.id]
                    if decision_valeur == "admis":
                        passer_eleve(inscription=inscription, decision=Inscription.Statut.ADMIS, classe_destination=classe_admis)
                    elif decision_valeur == "redouble":
                        passer_eleve(inscription=inscription, decision=Inscription.Statut.REDOUBLE, classe_destination=classe_redouble)
                    else:
                        passer_eleve(inscription=inscription, decision=Inscription.Statut.TRANSFERE)
                    compteurs[decision_valeur] += 1
                if classe_admis:
                    classe_source.classe_suivante = classe_admis
                    classe_source.save(update_fields=["classe_suivante"])

            enregistrer_action(
                acteur=request.user, action="passage_de_classe", cible=str(classe_source),
                details=compteurs, request=request,
            )
            messages.success(
                request,
                f"Passage de classe effectué : {compteurs['admis']} admis, "
                f"{compteurs['redouble']} redoublant(s), {compteurs['transfere']} transfert(s).",
            )
            return redirect("scolarite:liste_classes")

    return render(request, "scolarite/passage_de_classe.html", {
        "classe_source": classe_source, "annees_destination": annees_destination,
        "annee_destination": annee_destination, "classes_destination": classes_destination,
        "eleves_en_cours": eleves_en_cours,
    })


@module_requis(Module.CLASSES)
def creer_classe(request):
    formulaire = CreerClasseForm(request.POST or None, etablissement=request.user.etablissement)
    if request.method == "POST" and formulaire.is_valid():
        classe = formulaire.save()
        enregistrer_action(
            acteur=request.user, action="creation_classe", cible=str(classe), request=request,
        )
        messages.success(request, f"Classe « {classe} » créée avec son échéancier de frais.")
        return redirect("scolarite:liste_classes")
    return render(request, "scolarite/creer_classe.html", {"formulaire": formulaire})


@module_requis(Module.CLASSES)
def liste_classes(request):
    classes = classes_visibles_pour(request.user).select_related("annee_scolaire").prefetch_related("affectations")
    from permissions_matrix.models import PermissionMatrix
    return render(request, "scolarite/liste_classes.html", {
        "classes": classes,
        "peut_voir_emploi_du_temps": PermissionMatrix.a_acces(request.user.role, "emploi_du_temps", etablissement=request.user.etablissement),
        "peut_voir_statistiques": PermissionMatrix.a_acces(request.user.role, "statistiques", etablissement=request.user.etablissement),
    })
