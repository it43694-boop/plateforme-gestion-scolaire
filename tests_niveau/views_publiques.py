"""Pages publiques de la pré-inscription en ligne : le formulaire d'une campagne (lien secret) et la page de remerciement."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django_ratelimit.decorators import ratelimit

from tests_niveau.forms_publics import PreinscriptionForm
from tests_niveau.models import CampagnePreinscription
from tests_niveau.preinscription import accuser_reception, deposer_une_demande, formulaire_ferme, prevenir_le_secretariat


def _campagne(request, jeton):
    """La campagne de ce lien (404 si le lien n'existe pas), et l'école qu'elle représente pour toute la page (nom, logo, langue)."""
    campagne = get_object_or_404(CampagnePreinscription.objects.select_related("etablissement", "annee_scolaire"), jeton=jeton)
    request.session["etablissement_id"] = campagne.etablissement_id
    return campagne


@ratelimit(key="ip", rate="5/m", method="POST", block=False)
@ratelimit(key="ip", rate="30/h", method="POST", block=False)
def preinscription(request, jeton):
    campagne = _campagne(request, jeton)
    if not campagne.etablissement.actif or formulaire_ferme(campagne):
        return render(request, "tests_niveau/preinscription_fermee.html", {"campagne": campagne, "etablissement": campagne.etablissement})
    formulaire = PreinscriptionForm(request.POST or None, campagne=campagne)
    if request.method == "POST":
        if getattr(request, "limited", False):
            # Sans limite, ce formulaire public permettrait d'inonder le secrétariat de fausses demandes.
            messages.error(request, "Trop de demandes depuis cette adresse. Réessayez un peu plus tard.")
        elif formulaire.is_valid():
            if not formulaire.est_un_robot:  # un robot reçoit la même réponse qu'une personne, sans que rien ne soit enregistré
                candidat, nouvelle = deposer_une_demande(campagne, formulaire.cleaned_data, langue=getattr(request, "LANGUAGE_CODE", "fr"))
                if nouvelle:
                    accuser_reception(candidat)
                    prevenir_le_secretariat(candidat)
            return redirect("tests_niveau:preinscription_merci", jeton=campagne.jeton)
    return render(request, "tests_niveau/preinscription.html", {
        "campagne": campagne, "formulaire": formulaire, "etablissement": campagne.etablissement,
    })


def preinscription_merci(request, jeton):
    campagne = _campagne(request, jeton)
    return render(request, "tests_niveau/preinscription_merci.html", {"campagne": campagne, "etablissement": campagne.etablissement})
