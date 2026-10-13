"""
Fiche statistique annuelle d'un établissement : effectifs par niveau et par sexe, parité, redoublants,
âges, enseignants, résultats aux examens, infrastructures.

Les rubriques suivent les statistiques scolaires publiées au Mali (effectifs par niveau et par sexe,
élèves par classe et par maître, filles pour 100 garçons, taux de réussite aux examens...). C'est une
FICHE DE TRAVAIL : le questionnaire officiel de la CPS (Cellule de planification et de statistique) n'a
pas pu être consulté, elle n'en reproduit donc pas la forme exacte.

Les définitions des indicateurs (indice de parité F/G, pourcentage de redoublants, taux de promotion, de redoublement
et d'abandon, élèves par maître) suivent le « Rapport de suivi des indicateurs du système éducatif 2017-2018 à
2021-2022 » de la CPS (mai 2022), qui est un rapport national et non le questionnaire de collecte.

Définitions utilisées (rappelées sur la page) :
- inscrits : toutes les inscriptions de l'année dans les classes visibles, quel que soit leur statut
  (une année terminée n'a plus d'élève « en cours » : compter ceux-là donnerait zéro) ;
- redoublants : inscrits qui ont redoublé l'année précédente (décision « redouble ») ;
- nouveaux : inscrits sans aucune inscription antérieure dans l'établissement ;
- redoublants et nouveaux ne sont calculés que si l'année précédente contient des inscriptions
  (sinon la première année d'utilisation ferait passer tout le monde pour « nouveau »).

Tout est limité aux classes visibles de l'utilisateur (établissement, puis cycle pour un directeur de cycle).
"""
from collections import Counter

from django.db.models import Count, Exists, OuterRef

from comptes.models import FormationPedagogique, SituationHandicap, StatutDeplacement, StatutPersonnel, Utilisateur
from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role
from scolarite.models import (
    CYCLE_PAR_ROLE_CLOISONNE, Affectation, AnneeScolaire, Cycle, Examen, FicheInfrastructure, Inscription, Niveau,
    ResultatExamen, Serie, DomaineProfessionnel, ROLES_ETAT_CIVIL_ELEVE, classes_visibles_pour,
)

ORDRE_CYCLES = [
    Cycle.PRESCOLAIRE.value, Cycle.PREMIER_CYCLE.value, Cycle.DEUXIEME_CYCLE.value,
    Cycle.LYCEE.value, Cycle.PROFESSIONNEL.value,
]
ORDRE_NIVEAUX = [niveau.value for niveau in Niveau]
LIBELLES_NIVEAUX = dict(Niveau.choices)
LIBELLE_NIVEAU_INCONNU = "Niveau non précisé"
LIBELLES_SERIES = dict(Serie.choices)
LIBELLES_DOMAINES = dict(DomaineProfessionnel.choices)

# Le directeur d'un cycle ne voit pas les chiffres des autres cycles : les ratios calculés sur
# l'effectif de TOUTE l'école (infrastructures) lui sont donc masqués.
ROLES_ACCES_TOUS_CYCLES = {r.value for r in ROLES_ACCES_TOTAL_INCONDITIONNEL}


def _cle_sexe(sexe):
    return {"M": "garcons", "F": "filles"}.get(sexe, "inconnu")


def _compteur_sexe():
    return {"garcons": 0, "filles": 0, "inconnu": 0}


def _parite(filles, garcons):
    """Filles pour 100 garçons (None si aucun garçon)."""
    return round(100 * filles / garcons, 1) if garcons else None


def _rapport(numerateur, denominateur):
    return round(numerateur / denominateur, 1) if denominateur else None


def _taux(admis, presentes):
    return round(100 * admis / presentes, 1) if presentes else None


def _indice_parite(filles, garcons):
    """Indice de parité F/G tel que publié par la CPS (0,97 = 97 filles pour 100 garçons) ; None si aucun garçon."""
    return round(filles / garcons, 2) if garcons else None


def _pourcentage(partie, total):
    return round(100 * partie / total, 1) if total else None


def annee_precedente_avec_donnees(annee):
    """Année scolaire précédente de l'établissement, si elle contient des inscriptions (sinon None)."""
    precedente = AnneeScolaire.objects.filter(
        etablissement_id=annee.etablissement_id, date_debut__lt=annee.date_debut,
    ).order_by("-date_debut").first()
    if precedente is not None and Inscription.objects.filter(classe__annee_scolaire=precedente).exists():
        return precedente
    return None


def age_au(date_naissance, reference):
    return reference.year - date_naissance.year - ((reference.month, reference.day) < (date_naissance.month, date_naissance.day))


def _effectifs(classes, annee, precedente):
    nombre_classes = Counter(classes.values_list("cycle", "niveau"))

    base = Inscription.objects.filter(classe__in=classes)
    champs = ["classe__cycle", "classe__niveau", "eleve__sexe"]
    if precedente is not None:
        base = base.annotate(
            redoublant=Exists(Inscription.objects.filter(
                eleve=OuterRef("eleve"), classe__annee_scolaire=precedente, statut=Inscription.Statut.REDOUBLE,
            )),
            ancien=Exists(Inscription.objects.filter(
                eleve=OuterRef("eleve"), classe__annee_scolaire__etablissement_id=annee.etablissement_id,
                classe__annee_scolaire__date_debut__lt=annee.date_debut,
            )),
        )
        champs += ["redoublant", "ancien"]

    lignes = {}
    for ligne in base.values(*champs).annotate(n=Count("id")):
        cle = (ligne["classe__cycle"], ligne["classe__niveau"])
        entree = lignes.setdefault(cle, {**_compteur_sexe(), "total": 0, "redoublants": 0, "nouveaux": 0})
        entree[_cle_sexe(ligne["eleve__sexe"])] += ligne["n"]
        entree["total"] += ligne["n"]
        if precedente is not None:
            if ligne["redoublant"]:
                entree["redoublants"] += ligne["n"]
            if not ligne["ancien"]:
                entree["nouveaux"] += ligne["n"]
    # une classe sans aucun inscrit doit quand même apparaître (effectif 0)
    for cle in nombre_classes:
        lignes.setdefault(cle, {**_compteur_sexe(), "total": 0, "redoublants": 0, "nouveaux": 0})

    def ordre(cle):
        cycle, niveau = cle
        return (
            ORDRE_CYCLES.index(cycle) if cycle in ORDRE_CYCLES else len(ORDRE_CYCLES),
            ORDRE_NIVEAUX.index(niveau) if niveau in ORDRE_NIVEAUX else len(ORDRE_NIVEAUX),
        )

    resultat = []
    totaux = {**_compteur_sexe(), "total": 0, "redoublants": 0, "nouveaux": 0, "classes": 0}
    for cle in sorted(lignes, key=ordre):
        cycle, niveau = cle
        entree = lignes[cle]
        classes_du_niveau = nombre_classes.get(cle, 0)
        resultat.append({
            "cycle": cycle, "cycle_libelle": Cycle(cycle).label, "niveau": niveau,
            "niveau_libelle": LIBELLES_NIVEAUX.get(niveau, LIBELLE_NIVEAU_INCONNU),
            "classes": classes_du_niveau, **entree,
            "parite": _parite(entree["filles"], entree["garcons"]),
            "eleves_par_classe": _rapport(entree["total"], classes_du_niveau),
            "redoublants": entree["redoublants"] if precedente is not None else None,
            "nouveaux": entree["nouveaux"] if precedente is not None else None,
        })
        for champ in ("garcons", "filles", "inconnu", "total", "redoublants", "nouveaux"):
            totaux[champ] += entree[champ]
        totaux["classes"] += classes_du_niveau
    totaux["parite"] = _parite(totaux["filles"], totaux["garcons"])
    totaux["eleves_par_classe"] = _rapport(totaux["total"], totaux["classes"])
    if precedente is None:
        totaux["redoublants"] = totaux["nouveaux"] = None
    return resultat, totaux


def _ages(classes, annee):
    comptes = {}
    sans_date = _compteur_sexe()
    for sexe, naissance in Inscription.objects.filter(classe__in=classes).values_list(
        "eleve__sexe", "eleve__date_naissance",
    ):
        if naissance is None:
            sans_date[_cle_sexe(sexe)] += 1
            continue
        age = age_au(naissance, annee.date_debut)
        comptes.setdefault(age, _compteur_sexe())[_cle_sexe(sexe)] += 1
    lignes = [
        {"age": age, **comptes[age], "total": sum(comptes[age].values())} for age in sorted(comptes)
    ]
    return lignes, {**sans_date, "total": sum(sans_date.values())}


def _enseignants(classes, annee, total_inscrits):
    enseignants = list(
        Utilisateur.objects.filter(
            role=Role.ENSEIGNANT, etablissement_id=annee.etablissement_id, affectations__classe__in=classes,
        ).values_list("pk", "sexe", "statut_personnel", "formation_pedagogique").distinct()
    )
    libelles = dict(StatutPersonnel.choices)
    par_statut = {}
    for _, sexe, statut, _formation in enseignants:
        entree = par_statut.setdefault(statut, {**_compteur_sexe(), "total": 0})
        entree[_cle_sexe(sexe)] += 1
        entree["total"] += 1
    ordre = [valeur for valeur, _ in StatutPersonnel.choices] + [""]
    lignes = [
        {"statut": libelles.get(statut, "Situation non renseignée"), **par_statut[statut]}
        for statut in ordre if statut in par_statut
    ]
    formations = Counter(formation for _, _, _, formation in enseignants)
    libelles_formation = dict(FormationPedagogique.choices)
    total = len(enseignants)
    par_sexe = Counter(_cle_sexe(sexe) for _, sexe, _, _ in enseignants)
    return {
        "total": total, "par_statut": lignes,
        # Part des femmes calculée sur les enseignants dont le sexe est renseigné (sinon elle serait sous-estimée).
        "hommes": par_sexe["garcons"], "femmes": par_sexe["filles"], "sexe_inconnu": par_sexe["inconnu"],
        "pourcentage_femmes": _pourcentage(par_sexe["filles"], par_sexe["garcons"] + par_sexe["filles"]),
        "formation": [
            {"libelle": libelles_formation.get(valeur, "Formation non renseignée"), "total": formations[valeur]}
            for valeur in [v for v, _ in FormationPedagogique.choices] + [""] if formations.get(valeur)
        ],
        "qualifies": formations.get(FormationPedagogique.FORME.value, 0),
        "eleves_par_enseignant": _rapport(total_inscrits, total),
    }


def _indicateurs_par_cycle(classes, annee, precedente):
    """
    Un tableau par cycle (préscolaire, 1er cycle, ...) comme dans le rapport de la CPS : indice de parité F/G,
    élèves par classe (groupe pédagogique), pourcentage de redoublants par sexe, enseignants dont femmes, élèves par
    enseignant. Un enseignant qui intervient dans deux cycles est compté dans chacun (la somme des cycles peut donc
    dépasser le nombre d'enseignants de l'école). Limité aux classes visibles de l'utilisateur.
    """
    nombre_classes = Counter(classes.values_list("cycle", flat=True))
    base = Inscription.objects.filter(classe__in=classes)
    champs = ["classe__cycle", "eleve__sexe"]
    if precedente is not None:
        base = base.annotate(redoublant=Exists(Inscription.objects.filter(
            eleve=OuterRef("eleve"), classe__annee_scolaire=precedente, statut=Inscription.Statut.REDOUBLE,
        )))
        champs.append("redoublant")

    eleves = {cycle: {**_compteur_sexe(), "total": 0, "red": _compteur_sexe(), "red_total": 0} for cycle in nombre_classes}
    for ligne in base.values(*champs).annotate(n=Count("id")):
        entree = eleves.setdefault(
            ligne["classe__cycle"], {**_compteur_sexe(), "total": 0, "red": _compteur_sexe(), "red_total": 0},
        )
        cle = _cle_sexe(ligne["eleve__sexe"])
        entree[cle] += ligne["n"]
        entree["total"] += ligne["n"]
        if precedente is not None and ligne["redoublant"]:
            entree["red"][cle] += ligne["n"]
            entree["red_total"] += ligne["n"]

    enseignants = {}
    for enseignant_id, sexe, cycle in Affectation.objects.filter(
        classe__in=classes, enseignant__role=Role.ENSEIGNANT, enseignant__etablissement_id=annee.etablissement_id,
    ).values_list("enseignant_id", "enseignant__sexe", "classe__cycle").distinct():
        enseignants.setdefault(cycle, {})[enseignant_id] = _cle_sexe(sexe)

    lignes = []
    for cycle in sorted(eleves, key=lambda c: ORDRE_CYCLES.index(c) if c in ORDRE_CYCLES else len(ORDRE_CYCLES)):
        e = eleves[cycle]
        profs = enseignants.get(cycle, {})
        femmes = sum(1 for sexe in profs.values() if sexe == "filles")
        sexe_connu = sum(1 for sexe in profs.values() if sexe != "inconnu")
        calcule = precedente is not None
        lignes.append({
            "cycle": cycle, "cycle_libelle": Cycle(cycle).label, "classes": nombre_classes.get(cycle, 0),
            "garcons": e["garcons"], "filles": e["filles"], "inconnu": e["inconnu"], "total": e["total"],
            "indice_parite": _indice_parite(e["filles"], e["garcons"]),
            "eleves_par_classe": _rapport(e["total"], nombre_classes.get(cycle, 0)),
            "redoublants_garcons": e["red"]["garcons"] if calcule else None,
            "redoublants_filles": e["red"]["filles"] if calcule else None,
            "redoublants": e["red_total"] if calcule else None,
            "pourcentage_redoublants_garcons": _pourcentage(e["red"]["garcons"], e["garcons"]) if calcule else None,
            "pourcentage_redoublants_filles": _pourcentage(e["red"]["filles"], e["filles"]) if calcule else None,
            "pourcentage_redoublants": _pourcentage(e["red_total"], e["total"]) if calcule else None,
            "enseignants": len(profs), "enseignantes": femmes,
            "pourcentage_femmes": _pourcentage(femmes, sexe_connu),
            "eleves_par_enseignant": _rapport(e["total"], len(profs)),
        })
    return lignes


def _efficacite_interne(classes):
    """
    Taux de promotion, de redoublement et d'abandon par niveau et par sexe, d'après les décisions de fin d'année
    enregistrées sur les inscriptions (admis, redouble, abandon). Les élèves transférés vers une autre école et ceux dont
    la décision n'est pas encore prise ne sont pas comptés : on ne sait pas ce qu'ils deviennent, ou rien n'est décidé.
    Méthode propre à l'établissement : la CPS, elle, suit les effectifs d'une année à l'autre à l'échelle nationale.
    """
    decisions = (Inscription.Statut.ADMIS.value, Inscription.Statut.REDOUBLE.value, Inscription.Statut.ABANDON.value)
    groupes = {}
    for ligne in Inscription.objects.filter(classe__in=classes, statut__in=decisions).values(
        "classe__cycle", "classe__niveau", "eleve__sexe", "statut",
    ).annotate(n=Count("id")):
        niveau = groupes.setdefault((ligne["classe__cycle"], ligne["classe__niveau"]), {
            "garcons": Counter(), "filles": Counter(), "ensemble": Counter(),
        })
        cle = _cle_sexe(ligne["eleve__sexe"])
        if cle in ("garcons", "filles"):
            niveau[cle][ligne["statut"]] += ligne["n"]
        niveau["ensemble"][ligne["statut"]] += ligne["n"]

    def ordre(cle):
        cycle, niveau = cle
        return (
            ORDRE_CYCLES.index(cycle) if cycle in ORDRE_CYCLES else len(ORDRE_CYCLES),
            ORDRE_NIVEAUX.index(niveau) if niveau in ORDRE_NIVEAUX else len(ORDRE_NIVEAUX),
        )

    libelles_groupes = {"garcons": "Garçons", "filles": "Filles", "ensemble": "Ensemble"}

    def ligne_de(groupe, compte, **identite):
        decides = sum(compte.values())
        if not decides:
            return None
        promus, redoublent, abandons = (compte[statut] for statut in decisions)
        return {
            **identite, "groupe": libelles_groupes[groupe], "decides": decides,
            "promus": promus, "redoublent": redoublent, "abandons": abandons,
            "taux_promotion": _pourcentage(promus, decides), "taux_redoublement": _pourcentage(redoublent, decides),
            "taux_abandon": _pourcentage(abandons, decides),
        }

    lignes, totaux = [], {"garcons": Counter(), "filles": Counter(), "ensemble": Counter()}
    for cle in sorted(groupes, key=ordre):
        cycle, niveau = cle
        premiere = True  # le nom du niveau ne s'affiche que sur sa première ligne
        for groupe in ("garcons", "filles", "ensemble"):
            totaux[groupe].update(groupes[cle][groupe])
            ligne = ligne_de(
                groupe, groupes[cle][groupe], cycle_libelle=Cycle(cycle).label,
                niveau_libelle=LIBELLES_NIVEAUX.get(niveau, LIBELLE_NIVEAU_INCONNU), debut_niveau=premiere,
            )
            if ligne:
                lignes.append(ligne)
                premiere = False
    lignes_totales = [
        ligne for ligne in (ligne_de(groupe, totaux[groupe]) for groupe in ("garcons", "filles", "ensemble")) if ligne
    ]
    inscriptions = Inscription.objects.filter(classe__in=classes)
    return {
        "lignes": lignes, "totaux": lignes_totales,
        "transferes": inscriptions.filter(statut=Inscription.Statut.TRANSFERE).count(),
        "sans_decision": inscriptions.filter(statut=Inscription.Statut.EN_COURS).count(),
    }


def _sensibles(classes):
    """Nombre d'élèves en situation de handicap ou déplacés (agrégats uniquement ; rôles autorisés)."""
    inscriptions = Inscription.objects.filter(classe__in=classes)
    libelles_handicap = dict(SituationHandicap.choices)
    libelles_deplacement = dict(StatutDeplacement.choices)
    handicap = [
        {"libelle": libelles_handicap.get(ligne["eleve__handicap"], ligne["eleve__handicap"]), "total": ligne["n"]}
        for ligne in inscriptions.exclude(eleve__handicap="").values("eleve__handicap").annotate(n=Count("id")).order_by("eleve__handicap")
    ]
    deplacement = [
        {"libelle": libelles_deplacement.get(ligne["eleve__statut_deplacement"], ligne["eleve__statut_deplacement"]), "total": ligne["n"]}
        for ligne in inscriptions.exclude(eleve__statut_deplacement="").values("eleve__statut_deplacement").annotate(n=Count("id")).order_by("eleve__statut_deplacement")
    ]
    return {
        "handicap": handicap, "deplacement": deplacement,
        "total_handicap": sum(ligne["total"] for ligne in handicap),
        "total_deplacement": sum(ligne["total"] for ligne in deplacement),
    }


def statistiques_examens(classes):
    libelles = dict(Examen.choices)
    ordre = [valeur for valeur, _ in Examen.choices]
    groupes = {}
    for ligne in ResultatExamen.objects.filter(inscription__classe__in=classes).values(
        "examen", "resultat", "inscription__eleve__sexe", "inscription__classe__serie",
        "inscription__classe__domaine_professionnel",
    ).annotate(n=Count("id")):
        examen = ligne["examen"]
        sous = ""
        if examen == Examen.BAC.value and ligne["inscription__classe__serie"]:
            sous = LIBELLES_SERIES.get(ligne["inscription__classe__serie"], ligne["inscription__classe__serie"])
        elif examen in {Examen.CAP.value, Examen.BT.value} and ligne["inscription__classe__domaine_professionnel"]:
            sous = LIBELLES_DOMAINES.get(
                ligne["inscription__classe__domaine_professionnel"], ligne["inscription__classe__domaine_professionnel"],
            )
        entree = groupes.setdefault((examen, sous), {
            "admis": 0, "ajournes": 0, "absents": 0, "admis_garcons": 0, "presentes_garcons": 0,
            "admis_filles": 0, "presentes_filles": 0,
        })
        n = ligne["n"]
        sexe = ligne["inscription__eleve__sexe"]
        if ligne["resultat"] == ResultatExamen.Resultat.ABSENT:
            entree["absents"] += n
            continue
        if ligne["resultat"] == ResultatExamen.Resultat.ADMIS:
            entree["admis"] += n
        else:
            entree["ajournes"] += n
        if sexe in ("M", "F"):
            cle = "garcons" if sexe == "M" else "filles"
            entree[f"presentes_{cle}"] += n
            if ligne["resultat"] == ResultatExamen.Resultat.ADMIS:
                entree[f"admis_{cle}"] += n

    lignes = []
    for (examen, sous) in sorted(groupes, key=lambda cle: (ordre.index(cle[0]), cle[1])):
        entree = groupes[(examen, sous)]
        presentes = entree["admis"] + entree["ajournes"]
        lignes.append({
            "examen": examen, "libelle": libelles[examen], "sous_groupe": sous,
            "admis": entree["admis"], "ajournes": entree["ajournes"], "absents": entree["absents"],
            "presentes": presentes, "taux": _taux(entree["admis"], presentes),
            "taux_garcons": _taux(entree["admis_garcons"], entree["presentes_garcons"]),
            "taux_filles": _taux(entree["admis_filles"], entree["presentes_filles"]),
        })
    return lignes


def _infrastructures(utilisateur, annee, total_ecole):
    fiche = FicheInfrastructure.objects.filter(
        etablissement_id=annee.etablissement_id, annee_scolaire=annee,
    ).first()
    if fiche is None:
        return None
    resultat = {"fiche": fiche, "ratios": None}
    # Ratios sur l'effectif de toute l'école : réservés aux rôles qui voient tous les cycles.
    if utilisateur.role in ROLES_ACCES_TOUS_CYCLES or utilisateur.role == Role.SUPER_ADMINISTRATEUR.value:
        resultat["ratios"] = {
            "eleves_par_salle": _rapport(total_ecole, fiche.salles_classe),
            "eleves_par_place": _rapport(total_ecole, fiche.places_assises),
            "manuels_lecture_par_eleve": round(fiche.manuels_lecture / total_ecole, 2) if total_ecole else None,
            "manuels_calcul_par_eleve": round(fiche.manuels_calcul / total_ecole, 2) if total_ecole else None,
            "part_cantine": round(100 * fiche.cantine_beneficiaires / total_ecole, 1) if total_ecole else None,
        }
    return resultat


def construire_fiche(utilisateur, annee) -> dict:
    """Toutes les rubriques de la fiche annuelle pour les classes visibles de l'utilisateur."""
    etablissement = utilisateur.etablissement
    classes = classes_visibles_pour(utilisateur).filter(annee_scolaire=annee)
    precedente = annee_precedente_avec_donnees(annee)

    lignes_effectifs, totaux = _effectifs(classes, annee, precedente)
    ages, ages_inconnus = _ages(classes, annee)
    partis = Inscription.objects.filter(
        classe__in=classes, statut__in=[Inscription.Statut.ABANDON, Inscription.Statut.TRANSFERE],
    ).count()
    cycle_limite = CYCLE_PAR_ROLE_CLOISONNE.get(utilisateur.role)

    # Effectif de toute l'école (hors filtre de cycle) pour les ratios d'infrastructures.
    total_ecole = Inscription.objects.filter(
        classe__annee_scolaire=annee, classe__annee_scolaire__etablissement_id=annee.etablissement_id,
    ).count()

    return {
        "etablissement": etablissement,
        "annee": annee,
        "annee_precedente": precedente,
        "portee": f"Cycle « {Cycle(cycle_limite).label} » uniquement" if cycle_limite else "Toute l'école",
        "effectifs": lignes_effectifs,
        "totaux": totaux,
        "cycles": _indicateurs_par_cycle(classes, annee, precedente),
        "efficacite": _efficacite_interne(classes),
        "partis": partis,
        "ages": ages,
        "ages_inconnus": ages_inconnus,
        "enseignants": _enseignants(classes, annee, totaux["total"]),
        "sensibles": _sensibles(classes) if utilisateur.role in ROLES_ETAT_CIVIL_ELEVE else None,
        "examens": statistiques_examens(classes),
        "infrastructures": _infrastructures(utilisateur, annee, total_ecole),
    }


# ---------------------------------------------------------------------------
# Export CSV
# ---------------------------------------------------------------------------

def cellule_csv(valeur):
    """
    Texte sûr pour un tableur : une cellule qui commence par = + - @ serait interprétée comme une
    formule (injection de formule via un nom d'école ou de classe saisi par un utilisateur).
    """
    if isinstance(valeur, str) and valeur[:1] in {"=", "+", "-", "@", "\t", "\r"}:
        return "'" + valeur
    return "" if valeur is None else valeur


def lignes_csv(fiche) -> list[list]:
    """La fiche en lignes de CSV (sections séparées par une ligne vide)."""
    etablissement = fiche["etablissement"]
    lignes = [
        ["FICHE STATISTIQUE ANNUELLE (fiche de travail - format officiel de la CPS non reproduit)"],
        ["Établissement", etablissement.nom],
        ["Code d'établissement", etablissement.code_etablissement],
        ["Statut", etablissement.get_statut_juridique_display()],
        ["Région / cercle / commune", " / ".join(filter(None, [etablissement.region, etablissement.cercle, etablissement.commune]))],
        ["Année scolaire", fiche["annee"].libelle],
        ["Portée", fiche["portee"]],
        [],
        ["EFFECTIFS PAR NIVEAU"],
        ["Cycle", "Niveau", "Classes", "Garçons", "Filles", "Sexe non renseigné", "Total", "Filles pour 100 garçons",
         "Élèves par classe", "Redoublants", "Nouveaux inscrits"],
    ]
    for ligne in fiche["effectifs"]:
        lignes.append([
            ligne["cycle_libelle"], ligne["niveau_libelle"], ligne["classes"], ligne["garcons"], ligne["filles"],
            ligne["inconnu"], ligne["total"], ligne["parite"], ligne["eleves_par_classe"], ligne["redoublants"],
            ligne["nouveaux"],
        ])
    totaux = fiche["totaux"]
    lignes.append([
        "TOTAL", "", totaux["classes"], totaux["garcons"], totaux["filles"], totaux["inconnu"], totaux["total"],
        totaux["parite"], totaux["eleves_par_classe"], totaux["redoublants"], totaux["nouveaux"],
    ])
    lignes += [["Élèves ayant quitté l'établissement en cours d'année (abandon ou transfert)", fiche["partis"]], []]

    lignes += [["INDICATEURS PAR CYCLE"]]
    if fiche["cycles"]:
        lignes.append([
            "Cycle", "Classes", "Garçons", "Filles", "Total", "Indice de parité (F/G)", "Élèves par classe",
            "Redoublants garçons", "Redoublants filles", "Redoublants (total)", "% redoublants garçons",
            "% redoublants filles", "% redoublants (total)", "Enseignants", "dont femmes", "% de femmes",
            "Élèves par enseignant",
        ])
        for cycle in fiche["cycles"]:
            lignes.append([
                cycle["cycle_libelle"], cycle["classes"], cycle["garcons"], cycle["filles"], cycle["total"],
                cycle["indice_parite"], cycle["eleves_par_classe"], cycle["redoublants_garcons"],
                cycle["redoublants_filles"], cycle["redoublants"], cycle["pourcentage_redoublants_garcons"],
                cycle["pourcentage_redoublants_filles"], cycle["pourcentage_redoublants"], cycle["enseignants"],
                cycle["enseignantes"], cycle["pourcentage_femmes"], cycle["eleves_par_enseignant"],
            ])
        lignes.append(["Un enseignant qui intervient dans plusieurs cycles est compté dans chacun."])
    else:
        lignes.append(["Aucune classe pour cette année"])
    lignes.append([])

    efficacite = fiche["efficacite"]
    lignes.append(["PROMOTION, REDOUBLEMENT ET ABANDON (décisions de fin d'année)"])
    if efficacite["lignes"]:
        lignes.append([
            "Cycle", "Niveau", "Élèves", "Décidés", "Promus", "Redoublent", "Abandons", "Taux de promotion (%)",
            "Taux de redoublement (%)", "Taux d'abandon (%)",
        ])
        for ligne in efficacite["lignes"]:
            lignes.append([
                ligne["cycle_libelle"], ligne["niveau_libelle"], ligne["groupe"], ligne["decides"], ligne["promus"],
                ligne["redoublent"], ligne["abandons"], ligne["taux_promotion"], ligne["taux_redoublement"],
                ligne["taux_abandon"],
            ])
        for ligne in efficacite["totaux"]:
            lignes.append([
                "TOTAL", "", ligne["groupe"], ligne["decides"], ligne["promus"], ligne["redoublent"],
                ligne["abandons"], ligne["taux_promotion"], ligne["taux_redoublement"], ligne["taux_abandon"],
            ])
    else:
        lignes.append(["Aucune décision de fin d'année (admis, redouble, abandon) enregistrée pour cette année"])
    lignes += [
        ["Transférés vers une autre école (non comptés dans les taux)", efficacite["transferes"]],
        ["Sans décision de fin d'année (non comptés dans les taux)", efficacite["sans_decision"]],
        [],
    ]

    lignes += [["ÂGE DES ÉLÈVES (au début de l'année scolaire)"], ["Âge", "Garçons", "Filles", "Sexe non renseigné", "Total"]]
    for ligne in fiche["ages"]:
        lignes.append([f"{ligne['age']} ans", ligne["garcons"], ligne["filles"], ligne["inconnu"], ligne["total"]])
    inconnus = fiche["ages_inconnus"]
    lignes += [["Date de naissance non renseignée", inconnus["garcons"], inconnus["filles"], inconnus["inconnu"], inconnus["total"]], []]

    enseignants = fiche["enseignants"]
    lignes += [
        ["ENSEIGNANTS"],
        ["Nombre d'enseignants", enseignants["total"]],
        ["Élèves par enseignant", enseignants["eleves_par_enseignant"]],
        ["Enseignants formés (formation pédagogique)", enseignants["qualifies"]],
        ["Enseignantes (femmes)", enseignants["femmes"]],
        ["Part de femmes parmi les enseignants dont le sexe est renseigné (%)", enseignants["pourcentage_femmes"]],
        ["Situation administrative", "Hommes", "Femmes", "Sexe non renseigné", "Total"],
    ]
    for ligne in enseignants["par_statut"]:
        lignes.append([ligne["statut"], ligne["garcons"], ligne["filles"], ligne["inconnu"], ligne["total"]])
    lignes.append([])

    if fiche["sensibles"] is not None:
        sensibles = fiche["sensibles"]
        lignes += [["ÉLÈVES EN SITUATION DE HANDICAP", sensibles["total_handicap"]]]
        lignes += [[ligne["libelle"], ligne["total"]] for ligne in sensibles["handicap"]]
        lignes += [["ÉLÈVES DÉPLACÉS OU RÉFUGIÉS", sensibles["total_deplacement"]]]
        lignes += [[ligne["libelle"], ligne["total"]] for ligne in sensibles["deplacement"]]
        lignes.append([])

    lignes += [["RÉSULTATS AUX EXAMENS"], ["Examen", "Détail", "Présentés", "Admis", "Ajournés", "Absents", "Taux de réussite (%)",
                                           "Taux garçons (%)", "Taux filles (%)"]]
    for ligne in fiche["examens"]:
        lignes.append([
            ligne["libelle"], ligne["sous_groupe"], ligne["presentes"], ligne["admis"], ligne["ajournes"],
            ligne["absents"], ligne["taux"], ligne["taux_garcons"], ligne["taux_filles"],
        ])
    lignes.append([])

    infra = fiche["infrastructures"]
    lignes.append(["INFRASTRUCTURES"])
    if infra is None:
        lignes.append(["Fiche d'infrastructures non renseignée pour cette année"])
    else:
        f = infra["fiche"]
        oui = lambda valeur: "oui" if valeur else "non"  # noqa: E731
        lignes += [
            ["Salles de classe", f.salles_classe], ["dont en bon état", f.salles_bon_etat],
            ["dont en matériaux provisoires", f.salles_provisoires], ["Places assises", f.places_assises],
            ["Points d'eau", f.points_eau], ["Eau potable toute l'année", oui(f.eau_potable_toute_annee)],
            ["Latrines", f.latrines], ["dont fonctionnelles", f.latrines_fonctionnelles],
            ["Latrines séparées filles / garçons", oui(f.latrines_separees)],
            ["Lavage des mains", oui(f.lavage_mains)], ["Électricité", oui(f.electricite)],
            ["Manuels de lecture", f.manuels_lecture], ["Manuels de calcul", f.manuels_calcul],
            ["Cantine scolaire", oui(f.cantine)], ["Bénéficiaires de la cantine", f.cantine_beneficiaires],
        ]
        if infra["ratios"]:
            ratios = infra["ratios"]
            lignes += [
                ["Élèves par salle", ratios["eleves_par_salle"]], ["Élèves par place assise", ratios["eleves_par_place"]],
                ["Manuels de lecture par élève", ratios["manuels_lecture_par_eleve"]],
                ["Manuels de calcul par élève", ratios["manuels_calcul_par_eleve"]],
                ["Part des élèves bénéficiant de la cantine (%)", ratios["part_cantine"]],
            ]
    return lignes


def infrastructures_avec_ratios(utilisateur, annee):
    """Fiche d'infrastructures de l'année (ou None) avec ses ratios, si le rôle voit tous les cycles."""
    total_ecole = Inscription.objects.filter(
        classe__annee_scolaire=annee, classe__annee_scolaire__etablissement_id=annee.etablissement_id,
    ).count()
    return _infrastructures(utilisateur, annee, total_ecole)
