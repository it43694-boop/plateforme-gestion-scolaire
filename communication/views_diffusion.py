import datetime
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import render

from communication.diffusion import (
    LONGUEUR_MAX_MODELE, TYPES, contient_marqueur_date, message_neutre, preparer_messages, types_autorises,
)
from comptes.langue import texte_pour_langue
from comptes.audit import enregistrer_action
from scolarite.models import AnneeScolaire, classes_visibles_pour

LIGNES_PAR_PAGE = 50


@login_required
def messages_a_envoyer(request):
    """
    Liste de liens WhatsApp et SMS prêts à envoyer aux familles (voir communication.diffusion) : le serveur n'envoie
    rien, la personne connectée envoie elle-même depuis son téléphone.
    """
    utilisateur = request.user
    autorises = types_autorises(utilisateur)
    if not autorises:
        raise PermissionDenied("Vous n'avez pas le droit d'écrire aux familles.")

    annee = AnneeScolaire.active(utilisateur.etablissement)
    classes = list(
        classes_visibles_pour(utilisateur).filter(annee_scolaire=annee).order_by("cycle", "nom"),
    ) if annee else []

    type_code = request.GET.get("type", "").strip()
    classe_choisie = request.GET.get("classe", "").strip()
    date_texte = request.GET.get("date", "").strip()
    texte = request.GET.get("texte", "").strip()

    if type_code and type_code not in TYPES:
        raise Http404("Type de message inconnu.")
    if type_code and type_code not in autorises:
        raise PermissionDenied("Vous n'avez pas le droit de préparer ce type de message.")
    if classe_choisie not in ("", "toutes") and not classe_choisie.isdigit():
        raise Http404("Classe introuvable.")
    date = None
    if date_texte:
        try:
            date = datetime.date.fromisoformat(date_texte)
        except ValueError:
            raise Http404("Date invalide.")

    contexte = {
        "types": [(code, TYPES[code]["libelle"]) for code in autorises], "classes": classes,
        "type_code": type_code, "classe_choisie": classe_choisie, "date_texte": date_texte,
        "type_infos": TYPES.get(type_code), "annee": annee, "erreur": "", "resultat": None,
        "aide_types": [(TYPES[code]["libelle"], TYPES[code]["aide"]) for code in autorises],
    }
    if not type_code:
        contexte["texte"] = texte
        return render(request, "communication/messages_a_envoyer.html", contexte)

    infos = TYPES[type_code]
    langue = getattr(request, "LANGUAGE_CODE", "fr")
    modele = texte or (infos["modele_ar"] if langue == "ar" else infos["modele"])  # le message proposé suit la langue de la page
    contexte["texte"] = modele

    # Classes sur lesquelles porte le message : uniquement celles que l'utilisateur voit (une autre classe est « introuvable »).
    une_classe = None
    if classe_choisie == "toutes":
        concernees = classes
    elif classe_choisie:
        une_classe = next((classe for classe in classes if classe.pk == int(classe_choisie)), None)
        if une_classe is None:
            raise Http404("Classe introuvable.")
        concernees = [une_classe]
    else:
        contexte["erreur"] = "Choisissez une classe, ou « Toutes mes classes »."
        return render(request, "communication/messages_a_envoyer.html", contexte)

    if len(modele) > LONGUEUR_MAX_MODELE:
        contexte["erreur"] = f"Le message est trop long ({len(modele)} caractères, {LONGUEUR_MAX_MODELE} au plus)."
        return render(request, "communication/messages_a_envoyer.html", contexte)
    if type_code == "absence" and date is None:
        date = datetime.date.today()  # sans date choisie : les absences d'aujourd'hui
        contexte["date_texte"] = date.isoformat()
    if type_code == "absence" and date > datetime.date.today():
        contexte["erreur"] = "Une absence ne peut pas être dans le futur."
        return render(request, "communication/messages_a_envoyer.html", contexte)
    if contient_marqueur_date(modele) and date is None:
        contexte["erreur"] = "Choisissez une date : le message contient {date}."
        return render(request, "communication/messages_a_envoyer.html", contexte)

    etablissement = utilisateur.etablissement
    resultat = preparer_messages(
        type_=type_code, classes=concernees, modele=modele, ecole=etablissement.nom, date=date,
        une_seule_classe=une_classe, devise=getattr(etablissement, "code_devise", None) or "FCFA",
        langue=langue, ecrire=lambda texte: texte_pour_langue(request, texte),
    )
    page = Paginator(resultat["lignes"], LIGNES_PAR_PAGE).get_page(request.GET.get("page"))
    parametres = {cle: valeur for cle, valeur in request.GET.items() if cle != "page"}
    contexte.update({
        "resultat": resultat, "page_obj": page, "lignes": page.object_list,
        "parametres_page": urlencode(parametres),
        "apercu": resultat["lignes"][0]["message"] if resultat["lignes"] else "",
        # Collable dans un groupe WhatsApp : uniquement un message sans donnée d'élève, pour une seule classe.
        "message_groupe": message_neutre(
            modele, etablissement.nom, date.strftime("%d/%m/%Y") if date else "", une_classe,
            langue=langue, ecrire=lambda texte: texte_pour_langue(request, texte),
        ) if not infos["individuel"] and une_classe else "",
    })
    if request.GET.get("page") in (None, "", "1"):  # un clic sur « page suivante » ne se note pas une deuxième fois
        enregistrer_action(
            acteur=utilisateur, action="preparation_messages_familles", cible=type_code,
            details={
                "classe": une_classe.pk if une_classe else "toutes", "lignes": len(resultat["lignes"]),
                "sans_numero": len(resultat["sans_numero"]),
            },
            request=request,
        )
    return render(request, "communication/messages_a_envoyer.html", contexte)
