import base64
import os
from io import BytesIO

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from xhtml2pdf import pisa

from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from comptes.models import Utilisateur
from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role
from pedagogie.forms import CreneauForm, SaisirAbsenceForm, SaisirNoteForm
from pedagogie.models import (
    Absence, CreneauEmploiDuTemps, JourSemaine, Note, Trimestre, VerificationBulletin,
    appreciation_pour, saisir_note,
)
from permissions_matrix.modules import Module
from scolarite.models import (
    Affectation, Classe, CYCLE_PAR_ROLE_DIRECTION, Inscription, classes_visibles_pour, eleve_visible_pour,
)


def _eleve_visible_pour(utilisateur, eleve) -> bool:
    return eleve_visible_pour(utilisateur, eleve)


def _lien_pdf(uri, rel):
    """
    link_callback pour xhtml2pdf : contrairement à un navigateur, xhtml2pdf
    ne sait pas résoudre une URL relative comme /media/... ou /static/... ; il
    lui faut un chemin disque. Les URLs absolues (ex. logo servi depuis un
    bucket S3 en production) sont laissées telles quelles - xhtml2pdf sait
    déjà les récupérer directement en HTTP.
    """
    if uri.startswith("http://") or uri.startswith("https://") or uri.startswith("data:"):
        return uri
    if uri.startswith(settings.MEDIA_URL):
        return os.path.join(str(settings.MEDIA_ROOT), uri.replace(settings.MEDIA_URL, "", 1))
    if uri.startswith(settings.STATIC_URL):
        chemin_relatif = uri.replace(settings.STATIC_URL, "", 1)
        for repertoire in [settings.STATIC_ROOT, *settings.STATICFILES_DIRS]:
            candidat = os.path.join(str(repertoire), chemin_relatif)
            if os.path.isfile(candidat):
                return candidat
    return uri


# ---------------------------------------------------------------------------
# Notes et bulletins
# ---------------------------------------------------------------------------

@module_requis(Module.SUIVI_DES_COURS)
def suivi_des_cours(request):
    """
    Vue d'ensemble, pour la direction, de l'activité pédagogique par classe
    (nombre d'affectations, notes saisies, absences saisies, dernière
    activité) - cloisonnée par cycle (cahier des charges, section Suivi
    des cours).
    """
    from django.db.models import Count, Max

    classes = classes_visibles_pour(request.user).annotate(
        nb_affectations=Count("affectations", distinct=True),
        nb_notes=Count("affectations__notes", distinct=True),
        nb_absences=Count("absences", distinct=True),
        derniere_note=Max("affectations__notes__modifie_le"),
        derniere_absence=Max("absences__saisie_le"),
    ).select_related("annee_scolaire").order_by("annee_scolaire", "cycle", "nom")

    lignes = []
    for classe in classes:
        nb_notes = classe.nb_notes
        nb_absences = classe.nb_absences
        derniere_note = classe.derniere_note
        derniere_absence = classe.derniere_absence
        dates = [d for d in [derniere_note, derniere_absence] if d]
        lignes.append({
            "classe": classe,
            "nb_affectations": classe.nb_affectations,
            "nb_notes": nb_notes,
            "nb_absences": nb_absences,
            "derniere_activite": max(dates) if dates else None,
        })

    return render(request, "pedagogie/suivi_des_cours.html", {"lignes": lignes})


@module_requis(Module.NOTES_BULLETINS)
def mes_classes(request):
    """
    Point d'entrée de navigation pour un enseignant : liste ses affectations
    avec accès direct à la saisie de notes, d'absences et à l'emploi du temps.
    """
    affectations = Affectation.objects.filter(enseignant=request.user).select_related("classe") \
        if request.user.role == Role.ENSEIGNANT else Affectation.objects.none()
    return render(request, "pedagogie/mes_classes.html", {"affectations": affectations})


ROLES_SAISIE_NOTE_INTERDITE = {Role.PARENT.value, Role.ELEVE.value}


@module_requis(Module.NOTES_BULLETINS)
def saisir_note_vue(request, affectation_id):
    """
    Un parent ou un élève a accès au module Notes/Bulletins pour
    CONSULTER son propre bulletin (ou celui de son enfant), jamais pour
    saisir une note au nom d'un enseignant - le garde-fou ci-dessous ne
    visait jusqu'ici que l'enseignant (restreint à sa propre affectation),
    sans exclure ces deux rôles, qui pouvaient donc noter n'importe quel
    élève de l'école (voir aussi pedagogie.models.saisir_note).
    """
    if request.user.role in ROLES_SAISIE_NOTE_INTERDITE:
        raise PermissionDenied("Vous n'avez pas le droit de saisir une note.")
    affectation = get_object_or_404(
        Affectation,
        id=affectation_id,
        classe__in=classes_visibles_pour(request.user),
    )
    if request.user.role == Role.ENSEIGNANT and affectation.enseignant_id != request.user.id:
        raise PermissionDenied("Vous n'êtes pas l'enseignant affecté à cette matière pour cette classe.")

    formulaire = SaisirNoteForm(request.POST or None, affectation=affectation)
    if request.method == "POST" and formulaire.is_valid():
        eleve = Utilisateur.objects.get(matricule=formulaire.cleaned_data["matricule_eleve"], role=Role.ELEVE)
        try:
            saisir_note(
                eleve=eleve, affectation=affectation,
                trimestre=formulaire.cleaned_data["trimestre"],
                note_classe=formulaire.cleaned_data["note_classe"],
                note_composition=formulaire.cleaned_data["note_composition"],
                enseignant=request.user,
            )
        except ValidationError as erreur:
            messages.error(request, "; ".join(erreur.messages))
        else:
            enregistrer_action(
                acteur=request.user, action="saisie_note",
                cible=f"{eleve.matricule} - {affectation}", request=request,
            )
            messages.success(request, f"Note enregistrée pour {eleve.nom_complet}.")
        return redirect("pedagogie:saisir_note", affectation_id=affectation.id)

    notes_existantes = Note.objects.filter(affectation=affectation).select_related("eleve")
    return render(request, "pedagogie/saisir_note.html", {
        "formulaire": formulaire, "affectation": affectation, "notes_existantes": notes_existantes,
    })


def _calculer_bulletin(eleve, inscription=None):
    """
    Format conforme à un bulletin malien réel (vérifié sur des bulletins
    authentiques, lycée et fondamental) : pour chaque trimestre, un bloc
    avec une ligne par matière (note de classe, note de composition,
    coefficient, moyenne, moyenne coefficiée, appréciation), un total de
    coefficients/moyenne coefficiée, la moyenne obtenue par l'élève, et
    les moyennes la plus forte/la plus faible de la classe à titre de
    repère. La moyenne générale (tous trimestres confondus) reste
    pondérée par le coefficient de chaque matière
    (scolarite.models.Affectation.coefficient, 1 par défaut).
    """
    notes = Note.objects.filter(eleve=eleve)
    if inscription:
        notes = notes.filter(affectation__classe=inscription.classe)
    notes = notes.select_related("affectation").order_by("trimestre", "affectation__matiere")

    notes_par_trimestre = {}
    for note in notes:
        notes_par_trimestre.setdefault(note.trimestre, []).append(note)

    moyennes_par_trimestre = []
    bulletins_trimestre = []
    total_pondere_general, poids_general = 0, 0
    for trimestre_valeur, trimestre_label in Trimestre.choices:
        notes_du_trimestre = notes_par_trimestre.get(trimestre_valeur)
        if not notes_du_trimestre:
            continue

        lignes = [
            {
                "matiere": note.affectation.matiere or "Titulaire",
                "note_classe": note.note_classe,
                "note_composition": note.note_composition,
                "coefficient": note.affectation.coefficient,
                "moyenne": note.valeur,
                "moyenne_coefficiee": round(note.valeur * note.affectation.coefficient, 2),
                "appreciation": appreciation_pour(note.valeur),
            }
            for note in notes_du_trimestre
        ]
        total_pondere = sum(n.valeur * n.affectation.coefficient for n in notes_du_trimestre)
        poids = sum(n.affectation.coefficient for n in notes_du_trimestre)
        moyenne = round(total_pondere / poids, 2)

        moyenne_plus_forte, moyenne_plus_faible = (None, None)
        if inscription:
            moyenne_plus_forte, moyenne_plus_faible = _moyennes_extremes_classe(inscription.classe, trimestre_valeur)

        bulletins_trimestre.append({
            "trimestre": trimestre_label, "lignes": lignes,
            "total_coefficients": poids, "total_moyenne_coefficiee": round(total_pondere, 2),
            "moyenne": moyenne, "appreciation": appreciation_pour(moyenne),
            "moyenne_plus_forte": moyenne_plus_forte, "moyenne_plus_faible": moyenne_plus_faible,
        })
        moyennes_par_trimestre.append({"trimestre": trimestre_label, "moyenne": moyenne})
        total_pondere_general += total_pondere
        poids_general += poids

    moyenne_generale = round(total_pondere_general / poids_general, 2) if poids_general else None

    rang, effectif_classe = (None, None)
    if inscription and moyenne_generale is not None:
        rang, effectif_classe = _calculer_classement(inscription)

    return {
        "notes": notes, "bulletins_trimestre": bulletins_trimestre,
        "moyennes_par_trimestre": moyennes_par_trimestre, "moyenne_generale": moyenne_generale,
        "rang": rang, "effectif_classe": effectif_classe,
    }


def _moyennes_generales_par_eleve(classe, eleves_ids, trimestre=None):
    """
    Moyenne générale pondérée (par coefficient de matière) de chaque
    élève d'une classe, sur un trimestre donné ou tous confondus - calcul
    partagé par _calculer_classement (rang d'un élève précis) et
    _moyennes_extremes_classe (plus forte/plus faible moyenne, affichées
    sur le bulletin).
    """
    from django.db.models import DecimalField, ExpressionWrapper, F, Sum

    notes = Note.objects.filter(affectation__classe=classe, eleve_id__in=eleves_ids)
    if trimestre:
        notes = notes.filter(trimestre=trimestre)
    lignes = notes.values("eleve_id").annotate(
        total_pondere=Sum(
            ExpressionWrapper(
                F("valeur") * F("affectation__coefficient"),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
        ),
        poids=Sum("affectation__coefficient"),
    )
    return {ligne["eleve_id"]: ligne["total_pondere"] / ligne["poids"] for ligne in lignes if ligne["poids"]}


def _calculer_classement(inscription):
    """
    Rang de l'élève dans sa classe selon la moyenne générale pondérée
    (tous trimestres confondus), parmi les élèves actuellement inscrits.
    Ex-aequo : même rang pour une moyenne identique (convention de
    classement par compétition - 1, 2, 2, 4).
    """
    eleves_classe = set(
        Inscription.objects.filter(
            classe=inscription.classe, statut=Inscription.Statut.EN_COURS,
        ).values_list("eleve_id", flat=True)
    )
    if not eleves_classe:
        return None, None

    moyennes = _moyennes_generales_par_eleve(inscription.classe, eleves_classe)
    if inscription.eleve_id not in moyennes:
        return None, len(eleves_classe)

    classement = sorted(moyennes.values(), reverse=True)
    rang = classement.index(moyennes[inscription.eleve_id]) + 1
    return rang, len(eleves_classe)


def _moyennes_extremes_classe(classe, trimestre):
    """Moyenne générale la plus forte et la plus faible de la classe pour un trimestre, affichées sur le bulletin à titre de repère."""
    eleves_classe = set(
        Inscription.objects.filter(classe=classe, statut=Inscription.Statut.EN_COURS).values_list("eleve_id", flat=True)
    )
    if not eleves_classe:
        return None, None
    moyennes = list(_moyennes_generales_par_eleve(classe, eleves_classe, trimestre=trimestre).values())
    if not moyennes:
        return None, None
    return round(max(moyennes), 2), round(min(moyennes), 2)


@module_requis(Module.NOTES_BULLETINS)
def bulletin_eleve(request, matricule):
    eleve = get_object_or_404(Utilisateur, matricule=matricule, role=Role.ELEVE)
    if not _eleve_visible_pour(request.user, eleve):
        raise PermissionDenied("Vous n'avez pas accès au bulletin de cet élève.")
    inscription_id = request.GET.get("inscription")
    inscriptions = Inscription.objects.filter(eleve=eleve).select_related("classe", "classe__annee_scolaire")
    inscription = inscriptions.filter(pk=inscription_id).first() if inscription_id else inscriptions.filter(
        statut=Inscription.Statut.EN_COURS,
    ).first()
    return render(request, "pedagogie/bulletin_eleve.html", {
        "eleve": eleve, "inscriptions": inscriptions, "inscription": inscription,
        **_calculer_bulletin(eleve, inscription),
    })


@module_requis(Module.NOTES_BULLETINS)
def exporter_bulletin_pdf(request, matricule):
    eleve = get_object_or_404(Utilisateur, matricule=matricule, role=Role.ELEVE)
    if not _eleve_visible_pour(request.user, eleve):
        raise PermissionDenied("Vous n'avez pas accès au bulletin de cet élève.")

    inscription_id = request.GET.get("inscription")
    inscriptions = Inscription.objects.filter(eleve=eleve).select_related("classe", "classe__annee_scolaire")
    inscription = inscriptions.filter(pk=inscription_id).first() if inscription_id else inscriptions.filter(
        statut=Inscription.Statut.EN_COURS,
    ).first()
    verification = VerificationBulletin.objects.filter(
        eleve=eleve, inscription=inscription, actif=True,
    ).first() if inscription else None
    if inscription and verification is None:
        verification = VerificationBulletin.objects.create(eleve=eleve, inscription=inscription)
    verification_url = request.build_absolute_uri(reverse(
        "pedagogie:verifier_bulletin", kwargs={"jeton": verification.jeton},
    )) if verification else ""
    qr_code = ""
    if verification_url:
        try:
            import qrcode
            image = qrcode.make(verification_url)
            tampon = BytesIO()
            image.save(tampon, format="PNG")
            qr_code = "data:image/png;base64," + base64.b64encode(tampon.getvalue()).decode("ascii")
        except ImportError:
            pass

    html = render_to_string("pedagogie/bulletin_pdf.html", {
        "eleve": eleve, "inscription": inscription, "verification": verification,
        "verification_url": verification_url, "qr_code": qr_code,
        **_calculer_bulletin(eleve, inscription),
    }, request=request)

    reponse = HttpResponse(content_type="application/pdf")
    reponse["Content-Disposition"] = f'attachment; filename="bulletin_{eleve.matricule}.pdf"'
    resultat = pisa.CreatePDF(html, dest=reponse, encoding="utf-8", link_callback=_lien_pdf)
    if resultat.err:
        return HttpResponse("Erreur lors de la génération du PDF.", status=500)
    return reponse


def verifier_bulletin(request, jeton):
    verification = get_object_or_404(
        VerificationBulletin.objects.select_related("eleve", "inscription__classe"),
        jeton=jeton, actif=True,
    )
    return JsonResponse({
        "valide": True,
        "eleve": verification.eleve.nom_complet,
        "matricule": verification.eleve.matricule,
        "classe": str(verification.inscription.classe),
        "etablissement": verification.inscription.classe.annee_scolaire.etablissement.nom,
        "emis_le": verification.cree_le.isoformat(),
    })


# ---------------------------------------------------------------------------
# Absences
# ---------------------------------------------------------------------------

ROLES_SAISIE_ABSENCE_INTERDITE = {Role.PARENT.value, Role.ELEVE.value}


@module_requis(Module.ABSENCES)
def saisir_absence_vue(request, classe_id):
    """
    Même garde-fou manquant que saisir_note_vue : un parent ou un élève a
    accès au module Absences pour CONSULTER son propre historique (ou
    celui de son enfant), jamais pour en saisir au nom d'un enseignant.
    """
    if request.user.role in ROLES_SAISIE_ABSENCE_INTERDITE:
        raise PermissionDenied("Vous n'avez pas le droit de saisir une absence.")
    classe = get_object_or_404(classes_visibles_pour(request.user), id=classe_id)
    if request.user.role == Role.ENSEIGNANT and not Affectation.objects.filter(
        enseignant=request.user, classe=classe,
    ).exists():
        raise PermissionDenied("Vous n'êtes pas affecté à cette classe.")

    formulaire = SaisirAbsenceForm(request.POST or None, classe=classe)
    if request.method == "POST" and formulaire.is_valid():
        eleve = Utilisateur.objects.get(matricule=formulaire.cleaned_data["matricule_eleve"], role=Role.ELEVE)
        absence, cree = Absence.objects.update_or_create(
            eleve=eleve, date_absence=formulaire.cleaned_data["date_absence"],
            defaults={
                "classe": classe, "justifiee": formulaire.cleaned_data["justifiee"],
                "motif": formulaire.cleaned_data["motif"], "enregistre_par": request.user,
            },
        )
        enregistrer_action(
            acteur=request.user, action="saisie_absence",
            cible=f"{eleve.matricule} - {absence.date_absence}", request=request,
        )
        messages.success(request, f"Absence {'enregistrée' if cree else 'mise à jour'} pour {eleve.nom_complet}.")
        return redirect("pedagogie:saisir_absence", classe_id=classe.id)

    absences_du_jour = Absence.objects.filter(classe=classe).select_related("eleve").order_by("-date_absence")[:50]
    return render(request, "pedagogie/saisir_absence.html", {
        "formulaire": formulaire, "classe": classe, "absences": absences_du_jour,
    })


@module_requis(Module.ABSENCES)
def historique_absences_eleve(request, matricule):
    eleve = get_object_or_404(Utilisateur, matricule=matricule, role=Role.ELEVE)
    if not _eleve_visible_pour(request.user, eleve):
        raise PermissionDenied("Vous n'avez pas accès à l'historique de cet élève.")
    absences_qs = Absence.objects.filter(eleve=eleve).order_by("-date_absence")
    total = absences_qs.count()
    justifiees = absences_qs.filter(justifiee=True).count()
    page_obj = Paginator(absences_qs, 30).get_page(request.GET.get("page"))
    return render(request, "pedagogie/historique_absences.html", {
        "eleve": eleve, "absences": page_obj.object_list, "page_obj": page_obj,
        "total_absences": total, "total_justifiees": justifiees, "total_non_justifiees": total - justifiees,
    })


# ---------------------------------------------------------------------------
# Emploi du temps
# ---------------------------------------------------------------------------

ROLES_GESTION_TOTALE_EMPLOI_DU_TEMPS = {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL} | {
    Role.SUPER_ADMINISTRATEUR.value,
}


def _peut_gerer_emploi_du_temps(utilisateur):
    """
    Seule la direction crée l'emploi du temps (cahier des charges) : un
    enseignant le consulte uniquement, jamais ne le modifie - même pour
    sa propre classe. La direction reste cloisonnée par cycle via
    classes_visibles_pour.
    """
    return utilisateur.role in ROLES_GESTION_TOTALE_EMPLOI_DU_TEMPS or utilisateur.role in CYCLE_PAR_ROLE_DIRECTION


def _verifier_classe_visible_emploi_du_temps(utilisateur, classe):
    """
    classes_visibles_pour ne restreint un enseignant ou un élève que par
    établissement, jamais par affectation/inscription : à vérifier ici.
    """
    if utilisateur.role == Role.ELEVE.value:
        visible = Inscription.objects.filter(
            eleve=utilisateur, classe=classe, statut=Inscription.Statut.EN_COURS,
        ).exists()
        if not visible:
            raise PermissionDenied("Vous ne pouvez consulter que l'emploi du temps de votre propre classe.")
    elif utilisateur.role == Role.ENSEIGNANT.value:
        if not Affectation.objects.filter(enseignant=utilisateur, classe=classe).exists():
            raise PermissionDenied("Vous n'êtes pas affecté à cette classe.")


def _creneaux_visibles(utilisateur, classe):
    """
    Un enseignant ne voit que les jours/heures qui lui ont été donnés - pas
    le planning entier de la classe (les autres matières ne le concernent
    pas). La direction et l'élève voient le planning complet de la classe.
    """
    queryset = classe.creneaux.select_related("affectation__enseignant").order_by("jour_semaine", "heure_debut")
    if utilisateur.role == Role.ENSEIGNANT.value:
        queryset = queryset.filter(affectation__enseignant=utilisateur)
    return queryset


@module_requis(Module.EMPLOI_DU_TEMPS)
def gerer_emploi_du_temps(request, classe_id):
    classe = get_object_or_404(classes_visibles_pour(request.user), id=classe_id)
    _verifier_classe_visible_emploi_du_temps(request.user, classe)
    peut_gerer = _peut_gerer_emploi_du_temps(request.user)

    formulaire = None
    if peut_gerer:
        formulaire = CreneauForm(request.POST or None, classe=classe)
        if request.method == "POST":
            if formulaire.is_valid():
                try:
                    formulaire.instance.full_clean()
                    formulaire.save()
                except ValidationError as erreur:
                    messages.error(request, "; ".join(erreur.messages))
                else:
                    enregistrer_action(
                        acteur=request.user, action="ajout_creneau_emploi_du_temps",
                        cible=str(classe), request=request,
                    )
                    messages.success(request, "Créneau ajouté.")
                    return redirect("pedagogie:gerer_emploi_du_temps", classe_id=classe.id)
    elif request.method == "POST":
        raise PermissionDenied("Vous n'avez pas le droit de modifier cet emploi du temps.")

    creneaux = list(_creneaux_visibles(request.user, classe))
    jours = [
        {"valeur": valeur, "label": label, "creneaux": [c for c in creneaux if c.jour_semaine == valeur]}
        for valeur, label in JourSemaine.choices
    ]
    return render(request, "pedagogie/emploi_du_temps.html", {
        "classe": classe, "formulaire": formulaire, "peut_gerer": peut_gerer, "creneaux": creneaux, "jours": jours,
    })


@module_requis(Module.EMPLOI_DU_TEMPS)
@require_http_methods(["POST"])
def supprimer_creneau(request, creneau_id):
    creneau = get_object_or_404(
        CreneauEmploiDuTemps.objects.select_related("classe"),
        id=creneau_id, classe__in=classes_visibles_pour(request.user),
    )
    if not _peut_gerer_emploi_du_temps(request.user):
        raise PermissionDenied("Vous n'avez pas le droit de modifier cet emploi du temps.")
    classe_id = creneau.classe_id
    description = str(creneau)
    creneau.delete()
    enregistrer_action(acteur=request.user, action="suppression_creneau_emploi_du_temps", cible=description, request=request)
    messages.success(request, "Créneau supprimé.")
    return redirect("pedagogie:gerer_emploi_du_temps", classe_id=classe_id)


@module_requis(Module.EMPLOI_DU_TEMPS)
def exporter_emploi_du_temps_pdf(request, classe_id):
    classe = get_object_or_404(classes_visibles_pour(request.user), id=classe_id)
    _verifier_classe_visible_emploi_du_temps(request.user, classe)
    creneaux = _creneaux_visibles(request.user, classe)
    html = render_to_string(
        "pedagogie/emploi_du_temps_pdf.html", {"classe": classe, "creneaux": creneaux}, request=request,
    )

    reponse = HttpResponse(content_type="application/pdf")
    reponse["Content-Disposition"] = f'attachment; filename="emploi_du_temps_{classe.nom}.pdf"'
    resultat = pisa.CreatePDF(html, dest=reponse, encoding="utf-8", link_callback=_lien_pdf)
    if resultat.err:
        return HttpResponse("Erreur lors de la génération du PDF.", status=500)
    return reponse
