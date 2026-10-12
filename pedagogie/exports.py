"""
Exports Excel d'une classe : relevé de notes (récapitulatif annuel, une feuille par trimestre, détail des notes) et
absences (synthèse par élève, détail).

Les calculs reprennent ceux du bulletin (voir pedagogie.views._calculer_bulletin) : moyenne générale pondérée par le
coefficient de chaque matière, rang « de compétition » (1, 2, 2, 4). Un test compare les deux.
"""
import datetime
from decimal import Decimal

from comptes.excel import ajouter_feuille_tableau, nouveau_classeur
from pedagogie.models import Absence, Note, Trimestre
from scolarite.models import Inscription

DEUX_DECIMALES = Decimal("0.01")
FORMAT_NOTE = "0.00"


def _moyenne_ponderee(notes):
    """Moyenne pondérée par coefficient (Decimal non arrondi) d'un ensemble de notes, ou None s'il n'y en a pas."""
    poids = sum(note.affectation.coefficient for note in notes)
    if not poids:
        return None
    return sum(note.valeur * note.affectation.coefficient for note in notes) / poids


def _arrondie(valeur):
    return None if valeur is None else round(valeur, 2)


def _rangs(moyennes):
    """Rang de compétition : {élève: rang} à partir de {élève: moyenne} (ex-aequo : même rang, puis saut)."""
    classement = sorted(moyennes.values(), reverse=True)
    return {eleve_id: classement.index(valeur) + 1 for eleve_id, valeur in moyennes.items()}


def _population_du_classement(inscriptions):
    """
    Élèves classés : ceux en cours (comme sur le bulletin) ; une fois l'année terminée plus personne n'est « en cours »,
    on classe alors tous ceux qui n'ont pas quitté l'école (abandon ou transfert).
    """
    en_cours = {i.eleve_id for i in inscriptions if i.statut == Inscription.Statut.EN_COURS}
    if en_cours:
        return en_cours
    partis = {Inscription.Statut.ABANDON, Inscription.Statut.TRANSFERE}
    return {i.eleve_id for i in inscriptions if i.statut not in partis}


def libelle_matiere(affectation):
    return f"{affectation.matiere or 'Titulaire'} (coef {affectation.coefficient})"


def releve_notes_classeur(classe, affectations, *, vue_complete):
    """
    Relevé de notes d'une classe. `affectations` : les matières exportées. `vue_complete` : toutes les matières de la
    classe (direction) -> moyenne générale, rang et récapitulatif annuel ; sinon (enseignant) uniquement SES matières,
    sans total ni classement (qui dépendraient de matières qu'il n'a pas à voir).
    """
    affectations = list(affectations)
    inscriptions = list(
        Inscription.objects.filter(classe=classe).select_related("eleve").order_by("eleve__nom", "eleve__prenom")
    )
    eleves = [inscription.eleve for inscription in inscriptions]
    notes = list(
        Note.objects.filter(affectation__in=affectations, eleve__in=eleves).select_related("affectation", "eleve")
    )
    note_de = {(n.eleve_id, n.trimestre, n.affectation_id): n for n in notes}
    notes_par_eleve_trimestre = {}
    notes_par_eleve = {}
    for note in notes:
        notes_par_eleve_trimestre.setdefault((note.eleve_id, note.trimestre), []).append(note)
        notes_par_eleve.setdefault(note.eleve_id, []).append(note)
    population = _population_du_classement(inscriptions)

    infos = [
        ("Établissement", classe.annee_scolaire.etablissement.nom),
        ("Classe", classe.nom),
        ("Année scolaire", classe.annee_scolaire.libelle),
    ]
    if not vue_complete:
        infos.append(("Matière(s)", ", ".join(libelle_matiere(a) for a in affectations)))
    bareme = "Moyenne de la matière = (note de classe sur 20 + note de composition sur 40) / 3."
    if vue_complete:
        bareme += " Moyenne générale pondérée par les coefficients."
    infos.append(("Barème", bareme))
    classeur = nouveau_classeur()

    moyennes_trimestre = {}  # trimestre -> {élève: moyenne non arrondie}
    for valeur_trimestre, libelle_trimestre in Trimestre.choices:
        if not any(n.trimestre == valeur_trimestre for n in notes):
            continue
        entetes = ["N°", "Matricule", "Nom", "Prénom"] + [libelle_matiere(a) for a in affectations]
        if vue_complete:
            entetes += ["Moyenne générale", "Rang"]
        moyennes = {}
        for eleve in eleves:
            moyenne = _moyenne_ponderee(notes_par_eleve_trimestre.get((eleve.pk, valeur_trimestre), []))
            if moyenne is not None and eleve.pk in population:
                moyennes[eleve.pk] = moyenne
        moyennes_trimestre[valeur_trimestre] = moyennes
        rangs = _rangs(moyennes)

        lignes = []
        sommes = [[] for _ in affectations]
        generales = []
        for numero, eleve in enumerate(eleves, start=1):
            ligne = [numero, eleve.matricule, eleve.nom, eleve.prenom]
            for position, affectation in enumerate(affectations):
                note = note_de.get((eleve.pk, valeur_trimestre, affectation.pk))
                ligne.append(note.valeur if note else None)
                if note:
                    sommes[position].append(note.valeur)
            if vue_complete:
                moyenne = _moyenne_ponderee(notes_par_eleve_trimestre.get((eleve.pk, valeur_trimestre), []))
                ligne += [_arrondie(moyenne), rangs.get(eleve.pk)]
                if moyenne is not None:
                    generales.append(moyenne)
            lignes.append(ligne)
        total = ["", "", "Moyenne de la classe", ""] + [
            _arrondie(sum(valeurs) / len(valeurs)) if valeurs else None for valeurs in sommes
        ]
        if vue_complete:
            total += [_arrondie(sum(generales) / len(generales)) if generales else None, ""]
        formats = {colonne: FORMAT_NOTE for colonne in range(5, len(entetes) + 1)}
        if vue_complete:
            formats.pop(len(entetes), None)  # la colonne « Rang » reste un entier
        ajouter_feuille_tableau(
            classeur, libelle_trimestre, f"Relevé de notes - {classe.nom} - {libelle_trimestre}", infos, entetes, lignes,
            total=total, formats=formats,
        )

    if vue_complete:
        annuelles = {
            eleve.pk: _moyenne_ponderee(notes_par_eleve.get(eleve.pk, [])) for eleve in eleves
            if eleve.pk in population and notes_par_eleve.get(eleve.pk)
        }
        rangs_annuels = _rangs(annuelles)
        entetes = ["N°", "Matricule", "Nom", "Prénom"] + [libelle for _, libelle in Trimestre.choices] + [
            "Moyenne annuelle", "Rang annuel",
        ]
        lignes = []
        for numero, eleve in enumerate(eleves, start=1):
            ligne = [numero, eleve.matricule, eleve.nom, eleve.prenom]
            for valeur_trimestre, _ in Trimestre.choices:
                ligne.append(_arrondie(_moyenne_ponderee(notes_par_eleve_trimestre.get((eleve.pk, valeur_trimestre), []))))
            annuelle = _moyenne_ponderee(notes_par_eleve.get(eleve.pk, []))
            ligne += [_arrondie(annuelle), rangs_annuels.get(eleve.pk)]
            lignes.append(ligne)
        feuille = ajouter_feuille_tableau(
            classeur, "Récapitulatif", f"Récapitulatif annuel - {classe.nom}", infos, entetes, lignes,
            formats={5: FORMAT_NOTE, 6: FORMAT_NOTE, 7: FORMAT_NOTE, 8: FORMAT_NOTE},
        )
        classeur.move_sheet(feuille, offset=-(len(classeur.sheetnames) - 1))  # en première position

    entetes = ["Matricule", "Nom", "Prénom", "Matière", "Coefficient", "Trimestre", "Note de classe (/20)",
               "Note de composition (/40)", "Moyenne de la matière (/20)"]
    ordre_trimestre = {valeur: position for position, (valeur, _) in enumerate(Trimestre.choices)}
    detail = sorted(
        notes, key=lambda n: (n.eleve.nom, n.eleve.prenom, ordre_trimestre[n.trimestre], n.affectation.matiere or ""),
    )
    ajouter_feuille_tableau(
        classeur, "Détail des notes", f"Détail des notes - {classe.nom}", infos, entetes,
        [
            [n.eleve.matricule, n.eleve.nom, n.eleve.prenom, n.affectation.matiere or "Titulaire",
             n.affectation.coefficient, n.get_trimestre_display(), n.note_classe, n.note_composition, n.valeur]
            for n in detail
        ],
        formats={7: FORMAT_NOTE, 8: FORMAT_NOTE, 9: FORMAT_NOTE},
    )
    return classeur


def absences_classeur(classe, du=None, au=None):
    inscriptions = list(
        Inscription.objects.filter(classe=classe).select_related("eleve").order_by("eleve__nom", "eleve__prenom")
    )
    absences = Absence.objects.filter(classe=classe, eleve__in=[i.eleve for i in inscriptions]).select_related("eleve")
    if du:
        absences = absences.filter(date_absence__gte=du)
    if au:
        absences = absences.filter(date_absence__lte=au)
    absences = list(absences.order_by("date_absence", "eleve__nom", "eleve__prenom"))

    periode = "Toute l'année"
    if du or au:
        periode = f"Du {du.strftime('%d/%m/%Y') if du else 'début'} au {au.strftime('%d/%m/%Y') if au else 'aujourd’hui'}"
    infos = [
        ("Établissement", classe.annee_scolaire.etablissement.nom),
        ("Classe", classe.nom),
        ("Année scolaire", classe.annee_scolaire.libelle),
        ("Période", periode),
        ("Édité le", datetime.date.today()),
    ]
    par_eleve = {}
    for absence in absences:
        total, justifiees = par_eleve.get(absence.eleve_id, (0, 0))
        par_eleve[absence.eleve_id] = (total + 1, justifiees + (1 if absence.justifiee else 0))

    classeur = nouveau_classeur()
    lignes = []
    for numero, inscription in enumerate(inscriptions, start=1):
        eleve = inscription.eleve
        total, justifiees = par_eleve.get(eleve.pk, (0, 0))
        lignes.append([numero, eleve.matricule, eleve.nom, eleve.prenom, total, justifiees, total - justifiees])
    ajouter_feuille_tableau(
        classeur, "Synthèse", f"Absences - {classe.nom}", infos,
        ["N°", "Matricule", "Nom", "Prénom", "Absences", "dont justifiées", "dont non justifiées"], lignes,
        total=["", "", "Total", "", len(absences), sum(a.justifiee for a in absences),
               len(absences) - sum(a.justifiee for a in absences)],
    )
    ajouter_feuille_tableau(
        classeur, "Détail", f"Détail des absences - {classe.nom}", infos,
        ["Date", "Matricule", "Nom", "Prénom", "Justifiée", "Motif"],
        [
            [a.date_absence, a.eleve.matricule, a.eleve.nom, a.eleve.prenom, a.justifiee, a.motif]
            for a in absences
        ],
    )
    return classeur
