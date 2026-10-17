"""
Écran « Noms en arabe » : l'école relit et corrige l'écriture arabe des noms de ses élèves, parents et personnel, de ses classes et d'elle-même.

Quand la langue est l'arabe, chaque nom est écrit en lettres arabes : celui que l'école a saisi ici, sinon une PROPOSITION automatique
(comptes.transcription) qui n'est pas toujours l'écriture que la famille choisirait. Cet écran affiche la proposition dans chaque case : l'école la
corrige si besoin, puis enregistre ; ce qui est enregistré passe avant la proposition partout.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse

from comptes.arabisation import invalider, nom_d_ecole_arabe, nom_de_classe_arabe
from comptes.audit import enregistrer_action
from comptes.models import Utilisateur
from comptes.roles import ROLES_ACCES_TOTAL_INCONDITIONNEL, Role
from comptes.transcription import transcrire
from comptes.validators import valider_ecriture_arabe
from scolarite.models import Classe

ROLES_NOMS_ARABES = {role.value for role in ROLES_ACCES_TOTAL_INCONDITIONNEL} | {Role.SECRETAIRE.value}
ROLES_DIRECTION = {role.value for role in ROLES_ACCES_TOTAL_INCONDITIONNEL}
GROUPES = (
    ("eleves", "Élèves", False),
    ("parents", "Parents", False),
    ("personnel", "Personnel de l'école", True),
    ("classes", "Classes", True),
    ("ecole", "École", True),
)  # (code, libellé, réservé à la direction)
PAR_PAGE = 40
LONGUEUR_MAX = 100


def _groupes_permis(utilisateur):
    direction = utilisateur.role in ROLES_DIRECTION
    return [(code, libelle) for code, libelle, reserve in GROUPES if direction or not reserve]


def _personnes(utilisateur, groupe):
    comptes = Utilisateur.objects.filter(etablissement=utilisateur.etablissement)
    if groupe == "eleves":
        comptes = comptes.filter(role=Role.ELEVE)
    elif groupe == "parents":
        comptes = comptes.filter(role=Role.PARENT)
    else:
        comptes = comptes.exclude(role__in=[Role.ELEVE, Role.PARENT])
    return comptes.order_by("nom", "prenom", "pk")


def _ligne_personne(compte):
    return {
        "cle": compte.pk,
        "latin": compte.nom_complet,
        "champs": [
            ("prenom_ar", "Prénom en arabe", compte.prenom_ar, transcrire(compte.prenom)),
            ("nom_ar", "Nom en arabe", compte.nom_ar, transcrire(compte.nom)),
        ],
        "saisi": bool(compte.prenom_ar and compte.nom_ar),
    }


def _classes_distinctes(utilisateur):
    """Une ligne par nom de classe (« 6ème A » existe chaque année : une seule écriture arabe pour toutes)."""
    vus, lignes = set(), []
    for classe in Classe.objects.filter(annee_scolaire__etablissement=utilisateur.etablissement).order_by("nom", "-pk"):
        if classe.nom in vus:
            continue
        vus.add(classe.nom)
        lignes.append(classe)
    return lignes


def _ligne_classe(classe):
    return {
        "cle": classe.pk,
        "latin": classe.nom,
        "champs": [("nom_ar", "Nom de la classe en arabe", classe.nom_ar, nom_de_classe_arabe(classe.nom) or transcrire(classe.nom))],
        "saisi": bool(classe.nom_ar),
    }


def _lignes_ecole(etablissement):
    return [{
        "cle": etablissement.pk,
        "latin": etablissement.nom,
        "champs": [("nom_ar", "Nom de l'école en arabe", etablissement.nom_ar, nom_d_ecole_arabe(etablissement.nom) or transcrire(etablissement.nom))] + (
            [("devise_ar", "Devise en arabe", etablissement.devise_ar, nom_d_ecole_arabe(etablissement.devise) or transcrire(etablissement.devise))]
            if etablissement.devise else []
        ),
        "saisi": bool(etablissement.nom_ar),
    }]


def _valeur_valide(texte):
    texte = " ".join((texte or "").split())
    if len(texte) > LONGUEUR_MAX:
        raise ValidationError("Trop long (100 caractères au plus).")
    valider_ecriture_arabe(texte)
    return texte


@login_required
def noms_en_arabe(request):
    utilisateur = request.user
    if utilisateur.role not in ROLES_NOMS_ARABES or utilisateur.etablissement_id is None:
        raise PermissionDenied("Votre rôle ne permet pas d'accéder à cette page.")
    groupes = _groupes_permis(utilisateur)
    codes = [code for code, _ in groupes]
    groupe = request.GET.get("groupe") or request.POST.get("groupe") or codes[0]
    if groupe not in codes:
        raise PermissionDenied("Votre rôle ne permet pas de modifier ces noms.")
    recherche = (request.GET.get("q") or "").strip()
    seulement_a_revoir = request.GET.get("a_revoir") == "1"

    if groupe in ("eleves", "parents", "personnel"):
        comptes = _personnes(utilisateur, groupe)
        if recherche:
            comptes = comptes.filter(
                Q(prenom__icontains=recherche) | Q(nom__icontains=recherche) | Q(prenom_ar__icontains=recherche) | Q(nom_ar__icontains=recherche)
            )
        if seulement_a_revoir:
            comptes = comptes.filter(Q(prenom_ar="") | Q(nom_ar=""))
        page = Paginator(comptes, PAR_PAGE).get_page(request.GET.get("page") or request.POST.get("page"))
        objets = {compte.pk: compte for compte in page.object_list}
        lignes = [_ligne_personne(compte) for compte in page.object_list]
    elif groupe == "classes":
        toutes = _classes_distinctes(utilisateur)
        if recherche:
            toutes = [c for c in toutes if recherche.lower() in c.nom.lower() or recherche in c.nom_ar]
        if seulement_a_revoir:
            toutes = [c for c in toutes if not c.nom_ar]
        page = Paginator(toutes, PAR_PAGE).get_page(request.GET.get("page") or request.POST.get("page"))
        objets = {classe.pk: classe for classe in page.object_list}
        lignes = [_ligne_classe(classe) for classe in page.object_list]
    else:
        page = None
        etablissement = utilisateur.etablissement
        objets = {etablissement.pk: etablissement}
        lignes = _lignes_ecole(etablissement)

    erreurs = {}
    if request.method == "POST":
        modifies = 0
        propositions = {}
        for ligne in lignes:
            for nom_champ, _, _, _ in ligne["champs"]:
                valeur = request.POST.get(f"{nom_champ}_{ligne['cle']}")
                if valeur is None:
                    continue
                try:
                    propositions[(ligne["cle"], nom_champ)] = _valeur_valide(valeur)
                except ValidationError as erreur:
                    erreurs[(ligne["cle"], nom_champ)] = " ".join(erreur.messages)
        if not erreurs:
            with transaction.atomic():
                for (cle, nom_champ), valeur in propositions.items():
                    objet = objets[cle]
                    if getattr(objet, nom_champ) == valeur:
                        continue
                    if groupe == "classes":  # toutes les classes de même nom, quelle que soit l'année
                        Classe.objects.filter(
                            annee_scolaire__etablissement=utilisateur.etablissement, nom=objet.nom,
                        ).update(**{nom_champ: valeur})
                    else:
                        setattr(objet, nom_champ, valeur)
                        objet.save(update_fields=[nom_champ])
                    modifies += 1
            invalider(utilisateur.etablissement_id)
            if modifies:
                enregistrer_action(acteur=utilisateur, action="noms_en_arabe", cible=f"{groupe} : {modifies}", request=request)
            messages.success(request, f"{modifies} écriture(s) enregistrée(s).")
            adresse = reverse("comptes:noms_en_arabe") + f"?groupe={groupe}"
            if recherche:
                adresse += f"&q={recherche}"
            if seulement_a_revoir:
                adresse += "&a_revoir=1"
            if page is not None and page.number > 1:
                adresse += f"&page={page.number}"
            return redirect(adresse)
        messages.error(request, "Certaines écritures contiennent des lettres latines : corrigez-les (en arabe) puis enregistrez de nouveau.")

    # Ce que l'utilisateur vient de taper est remis dans les cases, avec son erreur.
    for ligne in lignes:
        champs = []
        for nom_champ, etiquette, enregistre, propose in ligne["champs"]:
            tape = request.POST.get(f"{nom_champ}_{ligne['cle']}") if request.method == "POST" else None
            champs.append({
                "nom": f"{nom_champ}_{ligne['cle']}", "etiquette": etiquette, "valeur": tape if tape is not None else (enregistre or propose),
                "propose": not enregistre, "erreur": erreurs.get((ligne["cle"], nom_champ), ""),
            })
        ligne["champs"] = champs

    return render(request, "comptes/noms_en_arabe.html", {
        "groupes": groupes, "groupe": groupe, "lignes": lignes, "page": page, "recherche": recherche, "a_revoir": seulement_a_revoir,
    })
