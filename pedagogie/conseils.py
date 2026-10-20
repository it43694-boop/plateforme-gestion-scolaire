"""
Conseil de classe : le tableau des élèves d'une classe pour un trimestre (moyenne, rang, conduite, absences, discipline) et les décisions que le
conseil y note (distinction, sanction, décision de passage au 3ème trimestre).

Les moyennes et les rangs viennent des mêmes fonctions que le bulletin (pedagogie.views) : un élève a donc, au conseil, exactement la moyenne et le
rang de son bulletin. Les distinctions et les passages proposés ne sont que des SUGGESTIONS calculées avec les seuils du conseil : la décision est
celle qui est enregistrée.

Qui voit et prépare un conseil : la direction (cloisonnée par cycle pour les directeurs de cycle et le censeur), le responsable pédagogique. Un
enseignant n'y a pas accès : le tableau montre la moyenne générale de tous les élèves, toutes matières confondues.
"""
import datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q

from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role
from pedagogie.clotures import ROLES_CLOTURE
from pedagogie.conduite import conduite_des_eleves
from pedagogie.models import (
    Absence, ConseilDeClasse, DecisionConseil, DecisionDePassage, Distinction, MesureDiscipline, SanctionDuConseil, Trimestre,
    TypeMesureDiscipline, appreciation_pour, classe_note_la_conduite,
)
from scolarite.models import Inscription

ROLES_CONSEIL = {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL} | {
    Role.SUPER_ADMINISTRATEUR.value, Role.DIRECTEUR_1ER_CYCLE.value, Role.DIRECTEUR_2EME_CYCLE.value, Role.DIRECTEUR_LYCEE.value,
    Role.CENSEUR.value, Role.RESPONSABLE_PEDAGOGIQUE.value,
}
ROLES_REOUVERTURE_CONSEIL = ROLES_CLOTURE  # seuls le fondateur, l'administrateur général et le développeur rouvrent un conseil validé

DISTINCTIONS_VALIDES = set(Distinction.values)
SANCTIONS_VALIDES = set(SanctionDuConseil.values)
PASSAGES_VALIDES = set(DecisionDePassage.values)
LIBELLES_DISTINCTION = dict(Distinction.choices)
LIBELLES_SANCTION = dict(SanctionDuConseil.choices)
LIBELLES_PASSAGE = dict(DecisionDePassage.choices)
LONGUEUR_OBSERVATION_ELEVE = 255
LONGUEUR_OBSERVATIONS_GENERALES = 1000


def peut_tenir_un_conseil(utilisateur) -> bool:
    return bool(utilisateur.etablissement_id) and utilisateur.role in ROLES_CONSEIL


def trimestre_valide(valeur) -> bool:
    return valeur in dict(Trimestre.choices)


def conseil_existant(classe, trimestre):
    return ConseilDeClasse.objects.filter(classe=classe, trimestre=trimestre).first()


def nouveau_conseil(classe, trimestre) -> ConseilDeClasse:
    """Un conseil pas encore enregistré, avec les seuils du dernier conseil de l'école (ou les seuils habituels)."""
    conseil = ConseilDeClasse(classe=classe, trimestre=trimestre)
    dernier = ConseilDeClasse.objects.filter(classe__annee_scolaire__etablissement_id=classe.annee_scolaire.etablissement_id).order_by("-modifie_le").first()
    if dernier:
        for champ in ("seuil_tableau_d_honneur", "seuil_encouragements", "seuil_felicitations", "seuil_passage"):
            setattr(conseil, champ, getattr(dernier, champ))
    return conseil


def distinction_suggeree(moyenne, conseil):
    """La distinction que la moyenne du trimestre permet (la plus haute atteinte), ou « »."""
    if moyenne is None:
        return ""
    if moyenne >= conseil.seuil_felicitations:
        return Distinction.FELICITATIONS.value
    if moyenne >= conseil.seuil_encouragements:
        return Distinction.ENCOURAGEMENTS.value
    if moyenne >= conseil.seuil_tableau_d_honneur:
        return Distinction.TABLEAU_D_HONNEUR.value
    return ""


def passage_suggere(moyenne_annuelle, conseil):
    if moyenne_annuelle is None or conseil.trimestre != Trimestre.T3.value:
        return ""
    return DecisionDePassage.ADMIS.value if moyenne_annuelle >= conseil.seuil_passage else DecisionDePassage.REDOUBLE.value


def _arrondi(valeur):
    return None if valeur is None else Decimal(valeur).quantize(Decimal("0.01"))


def lignes_du_conseil(conseil) -> dict:
    """
    Tout ce que la page et les documents du conseil montrent : une ligne par élève actuellement inscrit (rang d'abord, puis ordre alphabétique pour
    ceux qui n'ont pas de moyenne), et les repères de la classe.
    """
    from pedagogie.views import _moyennes_generales_par_eleve, _rang_de_competition  # même calcul que le bulletin

    classe, trimestre = conseil.classe, conseil.trimestre
    inscriptions = list(
        Inscription.objects.filter(classe=classe, statut=Inscription.Statut.EN_COURS).select_related("eleve").order_by("eleve__nom", "eleve__prenom")
    )
    ids = [i.eleve_id for i in inscriptions]
    moyennes = _moyennes_generales_par_eleve(classe, ids, trimestre=trimestre) if ids else {}
    annuelles = _moyennes_generales_par_eleve(classe, ids) if ids and trimestre == Trimestre.T3.value else {}
    note_la_conduite = classe_note_la_conduite(classe)
    conduites = conduite_des_eleves(classe, ids, trimestre) if note_la_conduite else {}

    absences = {
        ligne["eleve_id"]: ligne for ligne in Absence.objects.filter(classe=classe, eleve_id__in=ids).values("eleve_id").annotate(
            total=Count("id"), non_justifiees=Count("id", filter=Q(justifiee=False)),
        )
    }
    mesures = {
        ligne["eleve_id"]: ligne["total"] for ligne in MesureDiscipline.objects.filter(
            classe=classe, eleve_id__in=ids, type_mesure__in=[TypeMesureDiscipline.AVERTISSEMENT, TypeMesureDiscipline.BLAME],
        ).values("eleve_id").annotate(total=Count("id"))
    }
    decisions = {d.eleve_id: d for d in conseil.decisions.all()} if conseil.pk else {}

    lignes = []
    for inscription in inscriptions:
        eleve = inscription.eleve
        moyenne = _arrondi(moyennes.get(eleve.pk))
        annuelle = _arrondi(annuelles.get(eleve.pk))
        decision = decisions.get(eleve.pk)
        lignes.append({
            "eleve": eleve,
            "moyenne": moyenne,
            "appreciation": appreciation_pour(moyenne) if moyenne is not None else "",
            "rang": _rang_de_competition(moyennes, eleve.pk),
            "conduite": conduites.get((eleve.pk, trimestre)),
            "absences": absences.get(eleve.pk, {}).get("total", 0),
            "absences_non_justifiees": absences.get(eleve.pk, {}).get("non_justifiees", 0),
            "mesures": mesures.get(eleve.pk, 0),
            "moyenne_annuelle": annuelle,
            "distinction_suggeree": distinction_suggeree(moyenne, conseil),
            "passage_suggere": passage_suggere(annuelle, conseil),
            "distinction": decision.distinction if decision else "",
            "sanction": decision.sanction if decision else "",
            "decision_passage": decision.decision_passage if decision else "",
            "observation": decision.observation if decision else "",
        })
    for ligne in lignes:
        ligne["distinction_libelle"] = LIBELLES_DISTINCTION.get(ligne["distinction"], "")
        ligne["sanction_libelle"] = LIBELLES_SANCTION.get(ligne["sanction"], "")
        ligne["passage_libelle"] = LIBELLES_PASSAGE.get(ligne["decision_passage"], "")
        ligne["distinction_suggeree_libelle"] = LIBELLES_DISTINCTION.get(ligne["distinction_suggeree"], "")
        ligne["passage_suggere_libelle"] = LIBELLES_PASSAGE.get(ligne["passage_suggere"], "")
    lignes.sort(key=lambda ligne: (ligne["rang"] is None, ligne["rang"] or 0, ligne["eleve"].nom, ligne["eleve"].prenom))

    valeurs = [ligne["moyenne"] for ligne in lignes if ligne["moyenne"] is not None]
    reperes = {
        "effectif": len(lignes), "classes": len(valeurs),
        "moyenne_de_la_classe": _arrondi(sum(valeurs) / len(valeurs)) if valeurs else None,
        "plus_forte": max(valeurs) if valeurs else None, "plus_faible": min(valeurs) if valeurs else None,
        "note_la_conduite": note_la_conduite,
        "au_troisieme_trimestre": trimestre == Trimestre.T3.value,
        "nombre_distinctions": sum(1 for ligne in lignes if ligne["distinction"]),
        "nombre_sanctions": sum(1 for ligne in lignes if ligne["sanction"]),
        "nombre_admis": sum(1 for ligne in lignes if ligne["decision_passage"] == DecisionDePassage.ADMIS),
        "nombre_redoublants": sum(1 for ligne in lignes if ligne["decision_passage"] == DecisionDePassage.REDOUBLE),
    }
    return {"lignes": lignes, "reperes": reperes}


def superposer_la_saisie(lignes, donnees):
    """Remet dans le tableau ce que la personne avait tapé quand l'enregistrement a été refusé : elle ne perd pas son travail."""
    for ligne in lignes:
        pk = ligne["eleve"].pk
        for cle, champ in (("distinction", "distinction"), ("sanction", "sanction"), ("passage", "decision_passage"), ("observation", "observation")):
            if f"{cle}_{pk}" in donnees:
                ligne[champ] = (donnees.get(f"{cle}_{pk}") or "").strip()
    return lignes


def _decimal(valeur):
    try:
        nombre = Decimal(str(valeur).replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        raise ValidationError("Un seuil doit être un nombre.")
    if not nombre.is_finite() or not (0 <= nombre <= 20):
        raise ValidationError("Un seuil doit être compris entre 0 et 20.")
    return nombre.quantize(Decimal("0.01"))


def lire_les_reglages(conseil, donnees):
    """Applique à `conseil` (sans l'enregistrer) la date, les seuils et les observations générales envoyés par le formulaire."""
    # Un champ absent de l'envoi laisse la valeur actuelle : seul un champ envoyé vide l'efface.
    if "date_conseil" in donnees:
        texte_date = (donnees.get("date_conseil") or "").strip()
        if texte_date:
            try:
                conseil.date_conseil = datetime.date.fromisoformat(texte_date)
            except ValueError:
                raise ValidationError("La date du conseil n'est pas valide.")
        else:
            conseil.date_conseil = None
    for champ in ("seuil_tableau_d_honneur", "seuil_encouragements", "seuil_felicitations", "seuil_passage"):
        if donnees.get(champ) not in (None, ""):
            setattr(conseil, champ, _decimal(donnees.get(champ)))
    if "observations" in donnees:
        observations = (donnees.get("observations") or "").strip()
        if len(observations) > LONGUEUR_OBSERVATIONS_GENERALES:
            raise ValidationError("Les observations générales sont limitées à 1000 caractères.")
        conseil.observations = observations
    conseil.full_clean(exclude=["classe", "trimestre", "valide_par"])


def enregistrer_le_conseil(conseil, donnees, *, suggestions=False):
    """
    Enregistre les réglages et les décisions de chaque élève de la classe (les champs inconnus ou invalides sont refusés, un élève d'une autre
    classe n'est jamais atteint ; un champ absent de l'envoi ne change rien). Avec `suggestions`, la distinction et la décision de passage de TOUS les élèves sont remplacées par celles
    que les moyennes permettent. Une ligne entièrement vide n'est pas gardée.
    """
    if conseil.valide:
        raise ValidationError("Ce conseil est validé : il faut d'abord le rouvrir pour le modifier.")
    lire_les_reglages(conseil, donnees)
    with transaction.atomic():
        conseil.save()
        tableau = lignes_du_conseil(conseil)["lignes"]
        existantes = {d.eleve_id: d for d in conseil.decisions.all()}
        for ligne in tableau:
            eleve = ligne["eleve"]
            decision = existantes.get(eleve.pk)

            def valeur(nom, actuelle):
                cle = f"{nom}_{eleve.pk}"
                return (donnees.get(cle) or "").strip() if cle in donnees else actuelle  # absent de l'envoi : inchangé

            actuelles = (decision.distinction, decision.sanction, decision.decision_passage, decision.observation) if decision else ("", "", "", "")
            if suggestions:
                distinction, passage = ligne["distinction_suggeree"], ligne["passage_suggere"]
            else:
                distinction, passage = valeur("distinction", actuelles[0]), valeur("passage", actuelles[2])
            sanction, observation = valeur("sanction", actuelles[1]), valeur("observation", actuelles[3])
            if distinction and distinction not in DISTINCTIONS_VALIDES:
                raise ValidationError("Distinction inconnue.")
            if sanction and sanction not in SANCTIONS_VALIDES:
                raise ValidationError("Sanction inconnue.")
            if passage and (passage not in PASSAGES_VALIDES or conseil.trimestre != Trimestre.T3.value):
                raise ValidationError("Décision de passage invalide.")
            if len(observation) > LONGUEUR_OBSERVATION_ELEVE:
                raise ValidationError("L'observation d'un élève est limitée à 255 caractères.")
            if not (distinction or sanction or passage or observation):
                if decision:
                    decision.delete()
                continue
            if decision is None:
                decision = DecisionConseil(conseil=conseil, eleve=eleve)
            decision.distinction, decision.sanction, decision.decision_passage, decision.observation = distinction, sanction, passage, observation
            decision.save()
    return conseil


def valider_le_conseil(conseil, utilisateur):
    if conseil.valide:
        raise ValidationError("Ce conseil est déjà validé.")
    from django.utils import timezone

    conseil.valide_le, conseil.valide_par = timezone.now(), utilisateur
    conseil.save(update_fields=["valide_le", "valide_par", "modifie_le"])


def rouvrir_le_conseil(conseil):
    if not conseil.valide:
        raise ValidationError("Ce conseil n'est pas validé.")
    conseil.valide_le, conseil.valide_par = None, None
    conseil.save(update_fields=["valide_le", "valide_par", "modifie_le"])


def decisions_de_passage_du_conseil(classe) -> dict:
    """{élève: décision} du conseil validé du 3ème trimestre de la classe : sert à préremplir le passage de classe."""
    conseil = ConseilDeClasse.objects.filter(classe=classe, trimestre=Trimestre.T3.value, valide_le__isnull=False).first()
    if conseil is None:
        return {}
    return {d.eleve_id: d.decision_passage for d in conseil.decisions.exclude(decision_passage="")}
