"""
Graphiques du tableau de bord et des statistiques : anneau, barres et colonnes, dessinés en SVG côté serveur.

Aucune bibliothèque (rien à télécharger, rien qui puisse tomber en panne sur une connexion faible) et aucun style en ligne
(la politique de sécurité du site les interdit) : les formes portent des attributs SVG et les couleurs viennent de classes CSS
(`g-bleu`, `g-or`, `g-vert`, `g-rouge`, `g-gris`), donc du thème clair ou sombre. Les nombres qui entrent dans un attribut SVG sont
des TEXTES déjà formatés (« 12.5 ») : le gabarit les écrirait avec une virgule française, qui n'est pas un nombre pour le SVG.

Chaque figure se lit aussi sans la voir : un libellé accessible résume les valeurs, et les valeurs sont écrites en clair à côté.
"""
import datetime
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

MOIS = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")
TEINTES = ("bleu", "or", "vert", "rouge", "gris")
CIRCONFERENCE = 100  # le rayon (100 / 2π) fait 100 unités de tour : un pourcentage est directement une longueur d'arc
RAYON = "15.9155"


def nombre_svg(valeur) -> str:
    """Un nombre prêt pour un attribut SVG : toujours un point, jamais de virgule, trois décimales au plus."""
    return f"{float(valeur):.3f}".rstrip("0").rstrip(".") or "0"


def espaces(valeur) -> str:
    """12345 -> « 12 345 »."""
    return f"{int(valeur):,}".replace(",", " ")


def montant_compact(valeur) -> str:
    """Un montant court pour le haut d'une colonne : 350 k, 1,2 M, 12 (jamais plus de quatre caractères utiles)."""
    valeur = int(valeur or 0)
    if valeur >= 999_500:
        millions = f"{valeur / 1_000_000:.1f}".replace(".", ",")
        return f"{millions[:-2] if millions.endswith(',0') else millions} M"
    if valeur >= 1000:
        return f"{round(valeur / 1000)} k"
    return str(valeur)


def anneau(parts, total_au_centre=True) -> dict:
    """
    Anneau (donut). `parts` : liste de (libellé, valeur, teinte). Rend les arcs à dessiner et la légende ; sans aucune donnée,
    `vide` est vrai et l'anneau reste un cercle gris.
    """
    parts = [(libelle, int(valeur or 0), teinte) for libelle, valeur, teinte in parts]
    total = sum(valeur for _, valeur, _ in parts)
    segments, cumul = [], 0.0
    for libelle, valeur, teinte in parts:
        pourcentage = 100 * valeur / total if total else 0.0
        segments.append({
            "libelle": libelle, "valeur": valeur, "teinte": teinte,
            "pourcentage": f"{pourcentage:.0f}".replace(".", ","), "dessine": valeur > 0,
            "longueur": nombre_svg(pourcentage * CIRCONFERENCE / 100),
            "reste": nombre_svg(CIRCONFERENCE - pourcentage * CIRCONFERENCE / 100),
            "decalage": nombre_svg(25 - cumul),  # 25 : l'arc commence en haut, pas à droite
        })
        cumul += pourcentage * CIRCONFERENCE / 100
    resume = ", ".join(f"{s['libelle']} : {s['valeur']} ({s['pourcentage']} %)" for s in segments) if total else "aucune donnée"
    return {
        "segments": segments, "total": total, "vide": total == 0, "resume": resume, "rayon": RAYON,
        "total_au_centre": total_au_centre,
    }


def _unite(unite) -> str:
    """« FCFA » -> « FCFA » précédé d'une espace, pour écrire « 12 000 FCFA » ; rien si pas d'unité."""
    return f" {unite.strip()}" if unite and unite.strip() else ""


def barres(lignes, unite="") -> dict:
    """
    Barres horizontales. `lignes` : liste de (libellé, valeur) ou (libellé, valeur, teinte). La plus longue prend toute la largeur.
    """
    unite = _unite(unite)
    normalisees = []
    for ligne in lignes:
        libelle, valeur = ligne[0], int(ligne[1] or 0)
        normalisees.append((libelle, valeur, ligne[2] if len(ligne) > 2 else "bleu"))
    maximum = max((valeur for _, valeur, _ in normalisees), default=0) or 1
    resultat = [
        {
            "libelle": libelle, "valeur": valeur, "teinte": teinte, "texte": f"{espaces(valeur)}{unite}",
            "largeur": nombre_svg(100 * valeur / maximum),
        }
        for libelle, valeur, teinte in normalisees
    ]
    return {
        "lignes": resultat, "vide": not resultat,
        "resume": ", ".join(f"{ligne['libelle']} : {ligne['texte']}" for ligne in resultat) or "aucune donnée",
    }


def colonnes(serie, unite="") -> dict:
    """
    Colonnes verticales. `serie` : liste de (libellé, valeur, mise_en_avant). La plus haute prend toute la hauteur (100 unités) ;
    une valeur non nulle garde au moins 2 unités pour rester visible.
    """
    unite = _unite(unite)
    valeurs = [int(valeur or 0) for _, valeur, _ in serie]
    maximum = max(valeurs, default=0) or 1
    resultat = []
    for (libelle, _, mise_en_avant), valeur in zip(serie, valeurs):
        hauteur = max(100 * valeur / maximum, 2 if valeur else 0)
        resultat.append({
            "libelle": libelle, "valeur": valeur, "courant": bool(mise_en_avant), "texte": f"{montant_compact(valeur)}",
            "complet": f"{espaces(valeur)}{unite}", "hauteur": nombre_svg(hauteur), "y": nombre_svg(100 - hauteur),
        })
    return {
        "colonnes": resultat, "vide": not any(valeurs),
        "resume": ", ".join(f"{c['libelle']} : {c['complet']}" for c in resultat) or "aucune donnée",
    }


def encaissements_par_mois(etablissement, nombre=6, aujourdhui=None) -> list:
    """
    Les `nombre` derniers mois (le mois en cours en dernier) avec le total encaissé : [(« oct. », 1_200_000, est_le_mois_courant)].
    Les paiements supprimés et ceux d'une autre école ne comptent jamais.
    """
    from finances.models import Paiement

    aujourdhui = aujourdhui or timezone.localdate()
    mois = []
    annee, numero = aujourdhui.year, aujourdhui.month
    for _ in range(nombre):
        mois.append((annee, numero))
        numero -= 1
        if numero == 0:
            annee, numero = annee - 1, 12
    mois.reverse()
    debut = timezone.make_aware(datetime.datetime(mois[0][0], mois[0][1], 1))
    totaux = {
        (ligne["mois"].year, ligne["mois"].month): ligne["total"] or 0
        for ligne in Paiement.objects.filter(etablissement=etablissement, est_supprime=False, date_paiement__gte=debut)
        .annotate(mois=TruncMonth("date_paiement")).values("mois").annotate(total=Sum("montant"))
    }
    return [
        (MOIS[numero - 1], int(totaux.get((annee, numero), 0)), (annee, numero) == (aujourdhui.year, aujourdhui.month))
        for annee, numero in mois
    ]
