"""
Note de conduite : une note sur 20, par élève et par trimestre, de la 7ème à la 12ème année (jamais en primaire), qui n'est
pas une matière : pas d'enseignant, pas de composition. Elle compte dans la moyenne avec le coefficient de l'école (1 par
défaut ; 0 = affichée sur le bulletin mais non comptée).

Une seule règle de calcul, partagée par le bulletin, le rang, le relevé Excel et les alertes : la conduite d'un trimestre ne
compte que si l'élève a au moins une note de matière ce trimestre-là (comme le bloc du bulletin, qui n'existe qu'alors).
"""
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role
from pedagogie.models import Note, NoteConduite, Trimestre, classe_note_la_conduite
from scolarite.models import Inscription

# La vie scolaire et la direction. L'enseignant, le parent, l'élève, le secrétariat, la comptabilité n'en saisissent pas. Le
# surveillant général (module « Absences » : discipline et assiduité) en saisit sans avoir accès aux notes des matières.
ROLES_SAISIE_CONDUITE = {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL} | {
    Role.DIRECTEUR_2EME_CYCLE.value, Role.DIRECTEUR_LYCEE.value, Role.CENSEUR.value, Role.SURVEILLANT_GENERAL.value,
    Role.SUPER_ADMINISTRATEUR.value,
}

LIBELLE_CONDUITE = "Conduite"


def coefficient_conduite(etablissement) -> int:
    """Poids de la conduite dans la moyenne pour cette école (1 par défaut, 0 = non comptée)."""
    coefficient = getattr(etablissement, "coefficient_conduite", None)
    return 1 if coefficient is None else int(coefficient)


def eleves_de_la_classe(classe) -> list:
    """Les élèves actuellement inscrits, par ordre alphabétique."""
    from comptes.models import Utilisateur

    return list(
        Utilisateur.objects.filter(
            inscriptions__classe=classe, inscriptions__statut=Inscription.Statut.EN_COURS,
        ).distinct().order_by("nom", "prenom"),
    )


def conduite_des_eleves(classe, eleves_ids=None, trimestre=None) -> dict:
    """{(élève, trimestre): note} de la conduite d'une classe ; vide si la classe ne note pas la conduite."""
    if not classe_note_la_conduite(classe):
        return {}
    notes = NoteConduite.objects.filter(classe=classe)
    if eleves_ids is not None:
        notes = notes.filter(eleve_id__in=list(eleves_ids))
    if trimestre:
        notes = notes.filter(trimestre=trimestre)
    return {(n.eleve_id, n.trimestre): n.valeur for n in notes}


def ajouter_la_conduite_aux_totaux(classe, totaux, trimestre=None):
    """
    `totaux` : {élève: [total pondéré, poids]} calculé sur les matières, complété ICI avec la conduite (même règle que le
    bulletin). Ne fait rien pour une classe qui ne note pas la conduite, ou dont le coefficient est 0.
    """
    coefficient = coefficient_conduite(classe.annee_scolaire.etablissement)
    if not coefficient or not totaux or not classe_note_la_conduite(classe):
        return totaux
    conduites = conduite_des_eleves(classe, totaux.keys(), trimestre)
    if not conduites:
        return totaux
    notes = Note.objects.filter(affectation__classe=classe, eleve_id__in=list(totaux.keys()))
    if trimestre:
        notes = notes.filter(trimestre=trimestre)
    avec_notes = set(notes.values_list("eleve_id", "trimestre").distinct())
    for cle, valeur in conduites.items():
        if cle in avec_notes:
            totaux[cle[0]][0] += valeur * coefficient
            totaux[cle[0]][1] += coefficient
    return totaux


def moyenne_ponderee(notes, conduites_par_trimestre=None, coefficient=0):
    """
    Moyenne pondérée (Decimal non arrondi) de notes de matières, plus la conduite des trimestres où l'élève a des notes ;
    None s'il n'y a rien à moyenner. `conduites_par_trimestre` : {trimestre: note de conduite}.
    """
    notes = list(notes)
    total = sum((n.valeur * n.affectation.coefficient for n in notes), Decimal(0))
    poids = sum(n.affectation.coefficient for n in notes)
    if coefficient and conduites_par_trimestre:
        trimestres_avec_notes = {n.trimestre for n in notes}
        for trimestre, valeur in conduites_par_trimestre.items():
            if trimestre in trimestres_avec_notes:
                total += valeur * coefficient
                poids += coefficient
    return total / poids if poids else None


def analyser_note(texte):
    """
    Ce que la personne a tapé dans la case d'un élève : None si la case est vide (pas de note, ou on efface celle qui existe),
    sinon la note sur 20, virgule ou point accepté. Lève ValueError avec un message clair.
    """
    texte = (texte or "").strip().replace(",", ".")
    if not texte:
        return None
    try:
        valeur = Decimal(texte)
    except InvalidOperation:
        raise ValueError("Saisissez un nombre, par exemple 14 ou 14,5.") from None
    if not valeur.is_finite():
        raise ValueError("Saisissez un nombre, par exemple 14 ou 14,5.")
    if valeur < 0 or valeur > 20:
        raise ValueError("La conduite est notée sur 20 : une note entre 0 et 20.")
    if valeur.as_tuple().exponent < -2:
        raise ValueError("Deux décimales au plus.")
    return valeur.quantize(Decimal("0.01"))


@transaction.atomic
def enregistrer_conduite(*, classe, trimestre, valeurs, par):
    """
    Enregistre la conduite d'une classe pour un trimestre en une seule fois : tout est enregistré ou rien. `valeurs` :
    {élève: note ou None} ; None efface la note de ce trimestre. Seuls les élèves actuellement inscrits dans la classe sont pris
    en compte. Rend (nombre de notes enregistrées ou modifiées, nombre de notes effacées).
    """
    if not classe_note_la_conduite(classe):
        raise ValidationError("La conduite ne se note qu'à partir de la 7ème année.")
    if classe.annee_scolaire.est_archivee:
        raise ValidationError("Cette année scolaire est archivée : elle ne reçoit plus de nouvelles notes.")
    if trimestre not in dict(Trimestre.choices):
        raise ValidationError("Trimestre inconnu.")
    presents = {eleve.pk for eleve in eleves_de_la_classe(classe)}
    existantes = {n.eleve_id: n for n in NoteConduite.objects.filter(classe=classe, trimestre=trimestre)}
    enregistrees = effacees = 0
    for eleve_id, valeur in valeurs.items():
        if eleve_id not in presents:
            continue
        note = existantes.get(eleve_id)
        if valeur is None:
            if note is not None:
                note.delete()
                effacees += 1
        elif note is None:
            NoteConduite(eleve_id=eleve_id, classe=classe, trimestre=trimestre, valeur=valeur, enregistre_par=par).save()
            enregistrees += 1
        elif note.valeur != valeur:
            note.valeur = valeur
            note.enregistre_par = par
            note.save()
            enregistrees += 1
    return enregistrees, effacees
