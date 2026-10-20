import base64
import os
import re
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

from comptes.audit import enregistrer_action
from comptes.decorators import module_requis
from comptes.excel import nom_fichier_sur
from comptes.langue import donnees_pour_langue
from comptes.pdf import creer_pdf
from comptes.models import Utilisateur
from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role
from pedagogie.conduite import (
    LIBELLE_CONDUITE, ROLES_SAISIE_CONDUITE, ajouter_la_conduite_aux_totaux, analyser_note, conduite_des_eleves,
    coefficient_conduite, eleves_de_la_classe, enregistrer_conduite,
)
from pedagogie.forms import CreneauForm, SaisirAbsenceForm, SaisirNoteForm
from pedagogie.models import NoteConduite, classe_note_la_conduite
from pedagogie.models import (
    Absence, CreneauEmploiDuTemps, JourSemaine, Note, Trimestre, VerificationBulletin,
    appreciation_pour, saisir_note,
)
from permissions_matrix.modules import Module
from scolarite.views_exports import droits_export_listes
from scolarite.models import (
    Affectation, Classe, CYCLE_PAR_ROLE_DIRECTION, Inscription, classes_visibles_pour, eleve_de_l_etablissement_ou_404,
    eleve_visible_pour,
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
        return _chemin_dans(str(settings.MEDIA_ROOT), uri.replace(settings.MEDIA_URL, "", 1)) or uri
    if uri.startswith(settings.STATIC_URL):
        chemin_relatif = uri.replace(settings.STATIC_URL, "", 1)
        for repertoire in [settings.STATIC_ROOT, *settings.STATICFILES_DIRS]:
            candidat = _chemin_dans(str(repertoire), chemin_relatif)
            if candidat and os.path.isfile(candidat):
                return candidat
    return uri


def _chemin_dans(racine, chemin_relatif):
    """
    Chemin disque de `chemin_relatif` sous `racine`, ou None s'il en sortirait (« ../../etc/passwd ») : un lien d'image ne doit
    jamais pouvoir faire lire un fichier du serveur au générateur de PDF.
    """
    racine = os.path.realpath(racine)
    candidat = os.path.realpath(os.path.join(racine, chemin_relatif))
    return candidat if candidat == racine or candidat.startswith(racine + os.sep) else None


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

    return render(request, "pedagogie/suivi_des_cours.html", {"lignes": lignes, **droits_export_listes(request.user)})


@module_requis(Module.NOTES_BULLETINS)
def mes_classes(request):
    """
    Point d'entrée de navigation pour un enseignant : liste ses affectations
    avec accès direct à la saisie de notes, d'absences et à l'emploi du temps.
    """
    affectations = Affectation.objects.filter(enseignant=request.user).select_related("classe") \
        if request.user.role == Role.ENSEIGNANT else Affectation.objects.none()
    from permissions_matrix.models import PermissionMatrix

    return render(request, "pedagogie/mes_classes.html", {
        "affectations": affectations,
        "peut_discipline": PermissionMatrix.a_acces(request.user.role, "absences", etablissement=request.user.etablissement),
    })


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

    # Requête envoyée par la file de synchronisation hors-ligne (voir
    # static/js/app.js et static/js/sw.js, même mécanisme que la saisie
    # d'absences) : on répond en JSON plutôt que par une redirection.
    est_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    formulaire = SaisirNoteForm(request.POST or None, affectation=affectation)
    if request.method == "POST" and formulaire.is_valid():
        eleve = Utilisateur.objects.get(matricule=formulaire.cleaned_data["matricule_eleve"], role=Role.ELEVE)
        try:
            note = saisir_note(
                eleve=eleve, affectation=affectation,
                trimestre=formulaire.cleaned_data["trimestre"],
                note_classe=formulaire.cleaned_data["note_classe"],
                note_composition=formulaire.cleaned_data["note_composition"],
                enseignant=request.user,
            )
        except ValidationError as erreur:
            if est_ajax:
                return JsonResponse({"ok": False, "erreurs": donnees_pour_langue(request, {"matricule_eleve": erreur.messages})})
            messages.error(request, "; ".join(erreur.messages))
        else:
            enregistrer_action(
                acteur=request.user, action="saisie_note",
                cible=f"{eleve.matricule} - {affectation}", request=request,
            )
            message = f"Note enregistrée pour {eleve.nom_complet}."
            if est_ajax:
                return JsonResponse(donnees_pour_langue(request, {
                    "ok": True, "message": message, "eleve": eleve.nom_complet,
                    "trimestre": note.get_trimestre_display(),
                    "note_classe": "-" if note.note_classe is None else f"{note.note_classe:.2f}",
                    "note_composition": "-" if note.note_composition is None else f"{note.note_composition:.2f}",
                    "valeur": f"{note.valeur:.2f}",
                }))
            messages.success(request, message)
        return redirect("pedagogie:saisir_note", affectation_id=affectation.id)

    if est_ajax and request.method == "POST":
        return JsonResponse({"ok": False, "erreurs": donnees_pour_langue(request, formulaire.errors)})

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

    # Conduite (7ème à 12ème année seulement) : une ligne en plus dans chaque trimestre où l'élève a des notes de matières.
    conduites, coefficient_de_la_conduite = {}, 0
    if inscription and classe_note_la_conduite(inscription.classe):
        coefficient_de_la_conduite = coefficient_conduite(inscription.classe.annee_scolaire.etablissement)
        conduites = {t: v for (_, t), v in conduite_des_eleves(inscription.classe, [eleve.pk]).items()}

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
        conduite = conduites.get(trimestre_valeur)
        if conduite is not None:
            lignes.append({
                "matiere": LIBELLE_CONDUITE, "note_classe": conduite, "note_composition": None,
                "coefficient": coefficient_de_la_conduite, "moyenne": conduite,
                "moyenne_coefficiee": round(conduite * coefficient_de_la_conduite, 2),
                "appreciation": appreciation_pour(conduite), "est_conduite": True,
            })
            total_pondere += conduite * coefficient_de_la_conduite
            poids += coefficient_de_la_conduite
        moyenne = round(total_pondere / poids, 2)

        moyenne_plus_forte = moyenne_plus_faible = rang_trimestre = effectif_trimestre = None
        if inscription:
            moyenne_plus_forte, moyenne_plus_faible, rang_trimestre, effectif_trimestre = _reperes_classe(
                inscription, trimestre_valeur,
            )

        bulletins_trimestre.append({
            "trimestre": trimestre_label, "lignes": lignes,
            "total_coefficients": poids, "total_moyenne_coefficiee": round(total_pondere, 2),
            "moyenne": moyenne, "appreciation": appreciation_pour(moyenne),
            "moyenne_plus_forte": moyenne_plus_forte, "moyenne_plus_faible": moyenne_plus_faible,
            "rang": rang_trimestre, "effectif_classe": effectif_trimestre,
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
    _reperes_classe (rang du trimestre, plus forte/plus faible moyenne,
    affichés sur le bulletin).
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
    totaux = {ligne["eleve_id"]: [ligne["total_pondere"], ligne["poids"]] for ligne in lignes if ligne["poids"]}
    ajouter_la_conduite_aux_totaux(classe, totaux, trimestre)  # même règle que le bulletin : la conduite compte aussi dans le rang
    return {eleve_id: total / poids for eleve_id, (total, poids) in totaux.items()}


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

    return _rang_de_competition(moyennes, inscription.eleve_id), len(eleves_classe)


def _rang_de_competition(moyennes, eleve_id):
    """Rang de l'élève parmi {élève: moyenne}, ex æquo au même rang puis saut (1, 2, 2, 4) ; None s'il n'a pas de moyenne."""
    if eleve_id not in moyennes:
        return None
    return sorted(moyennes.values(), reverse=True).index(moyennes[eleve_id]) + 1


def _reperes_classe(inscription, trimestre):
    """
    (moyenne la plus forte, la plus faible, rang de l'élève, effectif de la classe) pour UN trimestre, affichés sur le
    bulletin à titre de repère. Même règle que le rang de l'année (_calculer_classement) : élèves actuellement inscrits,
    moyenne pondérée par les coefficients, ex æquo au même rang ; seuls ceux qui ont des notes ce trimestre sont classés.
    """
    eleves_classe = set(
        Inscription.objects.filter(
            classe=inscription.classe, statut=Inscription.Statut.EN_COURS,
        ).values_list("eleve_id", flat=True)
    )
    if not eleves_classe:
        return None, None, None, None
    moyennes = _moyennes_generales_par_eleve(inscription.classe, eleves_classe, trimestre=trimestre)
    if not moyennes:
        return None, None, None, len(eleves_classe)
    valeurs = list(moyennes.values())
    return (
        round(max(valeurs), 2), round(min(valeurs), 2), _rang_de_competition(moyennes, inscription.eleve_id),
        len(eleves_classe),
    )


@module_requis(Module.NOTES_BULLETINS)
def bulletin_eleve(request, matricule):
    eleve = eleve_de_l_etablissement_ou_404(request.user, matricule)
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


def _html_du_bulletin(request, eleve, inscription):
    """Le HTML du bulletin d'un élève pour une inscription (avec son jeton de vérification et son QR code), prêt pour le PDF."""
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

    return render_to_string("pedagogie/bulletin_pdf.html", {
        "eleve": eleve, "inscription": inscription, "verification": verification,
        "verification_url": verification_url, "qr_code": qr_code,
        **_calculer_bulletin(eleve, inscription),
    }, request=request)


LIMITE_BULLETINS_PAR_PDF = 150
CORPS_DE_PAGE = re.compile(r"<body[^>]*>(.*)</body>", re.S | re.I)
DEBUT_DU_CORPS = re.compile(r"<body[^>]*>", re.I)


def reunir_les_bulletins(pages_html):
    """Plusieurs bulletins (chacun un document HTML complet) en UN seul document : l'en-tête du premier, puis chaque corps sur sa page."""
    corps = [CORPS_DE_PAGE.search(page).group(1) for page in pages_html]
    entete = DEBUT_DU_CORPS.split(pages_html[0], maxsplit=1)[0]
    return entete + "<body>" + "<pdf:nextpage />".join(corps) + "</body></html>"


@module_requis(Module.NOTES_BULLETINS)
def exporter_bulletins_classe_pdf(request, classe_id):
    """Tous les bulletins d'une classe dans un seul PDF (un bulletin par page), pour la direction et la supervision."""
    from scolarite.models import ROLES_VOIENT_TOUT_ELEVE_DE_LETABLISSEMENT

    if request.user.role not in ROLES_VOIENT_TOUT_ELEVE_DE_LETABLISSEMENT:
        raise PermissionDenied("Vous n'avez pas le droit d'imprimer les bulletins d'une classe.")
    classe = get_object_or_404(classes_visibles_pour(request.user), id=classe_id)
    inscriptions = list(
        Inscription.objects.filter(classe=classe, statut=Inscription.Statut.EN_COURS)
        .select_related("eleve", "classe", "classe__annee_scolaire").order_by("eleve__nom", "eleve__prenom")
    )
    if not inscriptions:
        messages.error(request, "Aucun élève inscrit dans cette classe : aucun bulletin à imprimer.")
        return redirect("scolarite:liste_classes")
    if len(inscriptions) > LIMITE_BULLETINS_PAR_PDF:
        messages.error(request, f"Cette classe a plus de {LIMITE_BULLETINS_PAR_PDF} élèves : imprimez les bulletins un par un.")
        return redirect("scolarite:liste_classes")
    html = reunir_les_bulletins([_html_du_bulletin(request, i.eleve, i) for i in inscriptions])
    reponse = HttpResponse(content_type="application/pdf")
    nom = f"bulletins_{classe.nom}_{classe.annee_scolaire.libelle}".replace(" ", "_").replace("/", "-")
    reponse["Content-Disposition"] = f'attachment; filename="{nom_fichier_sur(nom)}.pdf"'
    if creer_pdf(html, reponse, request=request, link_callback=_lien_pdf).err:
        return HttpResponse("Erreur lors de la génération du PDF.", status=500)
    enregistrer_action(
        acteur=request.user, action="export_bulletins_classe", cible=str(classe), details={"bulletins": len(inscriptions)}, request=request,
    )
    return reponse


@module_requis(Module.NOTES_BULLETINS)
def exporter_bulletin_pdf(request, matricule):
    eleve = eleve_de_l_etablissement_ou_404(request.user, matricule)
    if not _eleve_visible_pour(request.user, eleve):
        raise PermissionDenied("Vous n'avez pas accès au bulletin de cet élève.")

    inscription_id = request.GET.get("inscription")
    inscriptions = Inscription.objects.filter(eleve=eleve).select_related("classe", "classe__annee_scolaire")
    inscription = inscriptions.filter(pk=inscription_id).first() if inscription_id else inscriptions.filter(
        statut=Inscription.Statut.EN_COURS,
    ).first()
    html = _html_du_bulletin(request, eleve, inscription)

    reponse = HttpResponse(content_type="application/pdf")
    reponse["Content-Disposition"] = f'attachment; filename="bulletin_{eleve.matricule}.pdf"'
    resultat = creer_pdf(html, reponse, request=request, link_callback=_lien_pdf)
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

    # Requête envoyée par la file de synchronisation hors-ligne (voir
    # static/js/app.js et static/js/sw.js) : on répond en JSON plutôt que par
    # une redirection, pour que le JS puisse distinguer succès, erreur de
    # saisie et session expirée sans recharger la page.
    est_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

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
        if cree:
            from pedagogie.absences import prevenir_les_parents_de_l_absence

            prevenir_les_parents_de_l_absence(absence)  # ne bloque jamais la saisie
        message = f"Absence {'enregistrée' if cree else 'mise à jour'} pour {eleve.nom_complet}."
        if est_ajax:
            return JsonResponse({
                "ok": True, "message": message, "eleve": eleve.nom_complet,
                "date_absence": absence.date_absence.strftime("%d/%m/%Y"), "justifiee": absence.justifiee,
            })
        messages.success(request, message)
        return redirect("pedagogie:saisir_absence", classe_id=classe.id)

    if est_ajax and request.method == "POST":
        return JsonResponse({"ok": False, "erreurs": formulaire.errors})

    absences_du_jour = Absence.objects.filter(classe=classe).select_related("eleve").order_by("-date_absence")[:50]
    return render(request, "pedagogie/saisir_absence.html", {
        "formulaire": formulaire, "classe": classe, "absences": absences_du_jour,
    })


@module_requis(Module.ABSENCES)
def historique_absences_eleve(request, matricule):
    eleve = eleve_de_l_etablissement_ou_404(request.user, matricule)
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
    resultat = creer_pdf(html, reponse, request=request, link_callback=_lien_pdf)
    if resultat.err:
        return HttpResponse("Erreur lors de la génération du PDF.", status=500)
    return reponse


# ---------------------------------------------------------------------------
# Conduite
# ---------------------------------------------------------------------------

def _texte_de_la_note(valeur):
    """14.50 -> « 14,5 » : la forme que l'on tape."""
    return f"{valeur:.2f}".rstrip("0").rstrip(".").replace(".", ",")


@module_requis(Module.ABSENCES)
def saisir_conduite_vue(request, classe_id):
    """
    Saisie de la conduite de toute une classe pour un trimestre, en une fois (un tableau, une case par élève). Réservée à la
    vie scolaire et à la direction (ROLES_SAISIE_CONDUITE, module « Absences » : discipline et assiduité), pour une classe de
    leur périmètre, de la 7ème à la 12ème année. Tout est enregistré ou rien.
    """
    if request.user.role not in ROLES_SAISIE_CONDUITE:
        raise PermissionDenied("Vous n'avez pas le droit de saisir la conduite.")
    classe = get_object_or_404(classes_visibles_pour(request.user), id=classe_id)
    if not classe_note_la_conduite(classe):
        messages.warning(request, "La conduite se note de la 7ème à la 12ème année : pas dans cette classe.")
        return redirect("scolarite:liste_classes")

    lecture_seule = classe.annee_scolaire.est_archivee
    trimestre = (request.POST if request.method == "POST" else request.GET).get("trimestre", "")
    if trimestre not in dict(Trimestre.choices):
        trimestre = Trimestre.T1.value
    eleves = eleves_de_la_classe(classe)
    erreurs, erreurs_generales, saisies = {}, [], {}

    if request.method == "POST":
        if lecture_seule:
            raise PermissionDenied("Cette année scolaire est archivée.")
        valeurs = {}
        for eleve in eleves:
            saisies[eleve.pk] = request.POST.get(f"note-{eleve.pk}", "")
            try:
                valeurs[eleve.pk] = analyser_note(saisies[eleve.pk])
            except ValueError as erreur:
                erreurs[eleve.pk] = str(erreur)
        if not erreurs:
            try:
                enregistrees, effacees = enregistrer_conduite(classe=classe, trimestre=trimestre, valeurs=valeurs, par=request.user)
            except ValidationError as erreur:
                erreurs_generales = erreur.messages
            else:
                enregistrer_action(
                    acteur=request.user, action="saisie_conduite", cible=str(classe),
                    details={"trimestre": trimestre, "enregistrees": enregistrees, "effacees": effacees}, request=request,
                )
                message = f"Conduite enregistrée : {enregistrees} note(s)"
                messages.success(request, message + (f", {effacees} effacée(s)." if effacees else "."))
                return redirect(f"{reverse('pedagogie:saisir_conduite', args=[classe.id])}?trimestre={trimestre}")

    existantes = {n.eleve_id: n.valeur for n in NoteConduite.objects.filter(classe=classe, trimestre=trimestre)}
    lignes = []
    for eleve in eleves:
        if eleve.pk in saisies:
            saisie = saisies[eleve.pk]
            try:
                valeur = analyser_note(saisie)
            except ValueError:
                valeur = None
        else:
            valeur = existantes.get(eleve.pk)
            saisie = "" if valeur is None else _texte_de_la_note(valeur)
        lignes.append({
            "eleve": eleve, "saisie": saisie, "erreur": erreurs.get(eleve.pk),
            "appreciation": appreciation_pour(valeur),
        })
    return render(request, "pedagogie/saisir_conduite.html", {
        "classe": classe, "trimestre": trimestre, "trimestres": Trimestre.choices, "lignes": lignes,
        "coefficient": coefficient_conduite(classe.annee_scolaire.etablissement), "lecture_seule": lecture_seule,
        "erreurs_generales": erreurs_generales, "nombre_notes": len(existantes),
        "moyenne_classe": round(sum(existantes.values()) / len(existantes), 2) if existantes else None,
    })
