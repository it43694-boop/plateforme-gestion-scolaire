from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import PasswordResetConfirmView
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit

from comptes.audit import enregistrer_action
from comptes.mail import envoyer_email
from comptes.decorators import role_requis
from comptes.forms import (
    ChangerEmailForm, ChangerMotDePasseForm, ConnexionForm, DefinirNouveauMotDePasseForm, InscriptionForm,
    MotDePasseOublieForm, VerificationEmailForm,
)
from comptes.models import CodeVerificationEmail, Notification, Utilisateur
from comptes.roles import ROLES_VALIDATION_COMPTES, Role, StatutCompte


# ---------------------------------------------------------------------------
# Inscription et vérification de l'email
# ---------------------------------------------------------------------------

def _envoyer_code_verification(utilisateur):
    nom_etablissement = utilisateur.etablissement.nom if utilisateur.etablissement_id else settings.NOM_PLATEFORME
    code = CodeVerificationEmail.generer_code()
    CodeVerificationEmail.objects.create(utilisateur=utilisateur, code=code)
    envoyer_email(
        sujet=f"{nom_etablissement} - Vérification de votre email",
        contenu=(
            f"Bonjour {utilisateur.prenom},\n\n"
            f"Votre code de vérification est : {code}\n"
            f"Il est valable {settings.DUREE_VALIDITE_CODE_VERIFICATION_MINUTES} minutes.\n\n"
            f"{nom_etablissement}"
        ),
        destinataires=[utilisateur.email],
        expediteur=settings.DEFAULT_FROM_EMAIL,
    )


def _resoudre_etablissement_inscription(request):
    """
    Détermine l'établissement auquel rattacher une nouvelle inscription :
    celui choisi dans l'annuaire (session), ou l'unique établissement de
    l'installation en mode mono-établissement. Renvoie None si impossible
    à déterminer (plusieurs établissements existent, aucun choisi).
    """
    from etablissement.models import Etablissement

    etablissement_id = request.session.get("etablissement_id")
    if etablissement_id:
        etablissement = Etablissement.objects.filter(pk=etablissement_id, actif=True).first()
        if etablissement:
            return etablissement
    if Etablissement.objects.count() == 1:
        return Etablissement.objects.first()
    return None


def inscription(request):
    etablissement = _resoudre_etablissement_inscription(request)
    if etablissement is None:
        messages.warning(request, "Choisissez d'abord votre établissement pour vous inscrire.")
        return redirect("vitrine:accueil")

    if request.method == "POST":
        formulaire = InscriptionForm(request.POST)
        if formulaire.is_valid():
            utilisateur = formulaire.save(commit=False)
            utilisateur.etablissement = etablissement
            utilisateur.save()
            _envoyer_code_verification(utilisateur)
            request.session["utilisateur_en_verification_id"] = utilisateur.id
            enregistrer_action(
                acteur=utilisateur, action="inscription_creee",
                cible=utilisateur.email, request=request,
            )
            messages.success(
                request,
                "Compte créé. Un code de vérification à 6 chiffres vient de vous être envoyé par email.",
            )
            return redirect("comptes:verifier_email")
    else:
        formulaire = InscriptionForm()
    return render(request, "comptes/inscription.html", {"formulaire": formulaire, "etablissement": etablissement})


def verifier_email(request):
    utilisateur_id = request.session.get("utilisateur_en_verification_id")
    if not utilisateur_id:
        messages.error(request, "Session expirée, veuillez recommencer l'inscription.")
        return redirect("comptes:inscription")
    utilisateur = get_object_or_404(Utilisateur, id=utilisateur_id)

    if request.method == "POST":
        formulaire = VerificationEmailForm(request.POST)
        if formulaire.is_valid():
            code_saisi = formulaire.cleaned_data["code"]
            code_actif = utilisateur.codes_verification.filter(
                utilise=False, expire_le__gte=timezone.now(),
            ).order_by("-cree_le").first()

            if code_actif and code_actif.code == code_saisi and code_actif.est_valide():
                code_actif.utilise = True
                code_actif.save(update_fields=["utilise"])
                utilisateur.email_verifie = True
                utilisateur.statut = StatutCompte.EN_ATTENTE_VALIDATION
                utilisateur.save(update_fields=["email_verifie", "statut"])
                del request.session["utilisateur_en_verification_id"]
                enregistrer_action(
                    acteur=utilisateur, action="email_verifie",
                    cible=utilisateur.email, request=request,
                )
                messages.success(
                    request,
                    "Email vérifié. Votre demande de compte a été transmise au secrétariat "
                    "pour validation. Vous recevrez une notification dès son activation.",
                )
                return redirect("comptes:connexion")
            else:
                if code_actif:
                    code_actif.enregistrer_echec()
                    if code_actif.utilise:  # verrouillé après 5 échecs
                        formulaire.add_error(
                            "code",
                            "Trop de tentatives incorrectes. Demandez un nouveau code.",
                        )
                    else:
                        formulaire.add_error("code", "Code invalide ou expiré.")
                else:
                    formulaire.add_error("code", "Code invalide ou expiré. Demandez un nouveau code.")
    else:
        formulaire = VerificationEmailForm()
    return render(request, "comptes/verifier_email.html", {
        "formulaire": formulaire, "email": utilisateur.email,
    })


@require_http_methods(["POST"])
@ratelimit(key="ip", rate="3/m", method="POST", block=False)
def renvoyer_code(request):
    if getattr(request, "limited", False):
        messages.error(request, "Trop de demandes. Réessayez dans une minute.")
        return redirect("comptes:verifier_email")
    utilisateur_id = request.session.get("utilisateur_en_verification_id")
    if not utilisateur_id:
        messages.error(request, "Session expirée, veuillez recommencer l'inscription.")
        return redirect("comptes:inscription")
    utilisateur = get_object_or_404(Utilisateur, id=utilisateur_id)
    _envoyer_code_verification(utilisateur)
    messages.info(request, "Un nouveau code vient de vous être envoyé.")
    return redirect("comptes:verifier_email")


# ---------------------------------------------------------------------------
# Connexion / déconnexion
# ---------------------------------------------------------------------------

@ratelimit(key="ip", rate="10/m", method="POST", block=False)
def connexion(request):
    if getattr(request, "limited", False):
        messages.error(request, "Trop de tentatives depuis cette adresse. Réessayez dans une minute.")
        return render(request, "comptes/connexion.html", {"formulaire": ConnexionForm()})
    if request.user.is_authenticated:
        return redirect("comptes:redirection_tableau_de_bord")

    formulaire = ConnexionForm(request.POST or None)
    if request.method == "POST" and formulaire.is_valid():
        email = formulaire.cleaned_data["email"].strip().lower()
        mot_de_passe = formulaire.cleaned_data["mot_de_passe"]

        try:
            utilisateur_cible = Utilisateur.objects.get(email=email)
        except Utilisateur.DoesNotExist:
            utilisateur_cible = None

        if utilisateur_cible and utilisateur_cible.verrouille():
            messages.error(
                request,
                "Ce compte est temporairement verrouillé suite à plusieurs échecs de connexion. "
                "Réessayez plus tard.",
            )
            return render(request, "comptes/connexion.html", {"formulaire": formulaire})

        utilisateur = authenticate(request, username=email, password=mot_de_passe)

        if utilisateur is None:
            if utilisateur_cible is not None:
                utilisateur_cible.enregistrer_echec_connexion()
                enregistrer_action(
                    acteur=utilisateur_cible, action="echec_connexion",
                    cible=email, request=request,
                )
            messages.error(request, "Email ou mot de passe incorrect.")
        elif utilisateur.statut == StatutCompte.EN_ATTENTE_VERIFICATION_EMAIL:
            messages.warning(request, "Veuillez d'abord vérifier votre adresse email.")
            request.session["utilisateur_en_verification_id"] = utilisateur.id
            return redirect("comptes:verifier_email")
        elif utilisateur.statut == StatutCompte.EN_ATTENTE_VALIDATION:
            messages.warning(
                request,
                "Votre compte est en attente de validation par le secrétariat ou la direction.",
            )
        elif utilisateur.statut in {StatutCompte.SUSPENDU, StatutCompte.DESACTIVE}:
            messages.error(request, "Ce compte n'est plus actif. Contactez l'administration.")
        elif utilisateur.etablissement_id and not utilisateur.etablissement.actif:
            messages.error(
                request,
                "Cet établissement est temporairement suspendu. Contactez l'administrateur de la plateforme.",
            )
        else:
            utilisateur.reinitialiser_tentatives_connexion()
            if utilisateur.deux_facteurs_actif:
                # Mot de passe déjà vérifié à ce stade, mais pas de session
                # ouverte avant le second facteur : login() n'est appelé que
                # depuis verifier_2fa(), une fois le code confirmé.
                request.session["utilisateur_en_attente_2fa_id"] = utilisateur.id
                return redirect("comptes:verifier_2fa")
            login(request, utilisateur)
            # L'établissement du compte fait foi pour la suite de la session,
            # quel que soit celui éventuellement présélectionné dans l'annuaire.
            request.session["etablissement_id"] = utilisateur.etablissement_id
            enregistrer_action(acteur=utilisateur, action="connexion_reussie", request=request)
            return redirect("comptes:redirection_tableau_de_bord")

    return render(request, "comptes/connexion.html", {"formulaire": formulaire})


@ratelimit(key="ip", rate="10/m", method="POST", block=False)
def verifier_2fa(request):
    """Second facteur (TOTP) après un mot de passe déjà validé par connexion()."""
    utilisateur_id = request.session.get("utilisateur_en_attente_2fa_id")
    if not utilisateur_id:
        return redirect("comptes:connexion")
    utilisateur = get_object_or_404(Utilisateur, id=utilisateur_id, deux_facteurs_actif=True)

    if getattr(request, "limited", False):
        messages.error(request, "Trop de tentatives. Réessayez dans une minute.")
        return render(request, "comptes/verifier_2fa.html")

    if request.method == "POST":
        code = request.POST.get("code", "")
        if utilisateur.verifier_code_2fa(code):
            del request.session["utilisateur_en_attente_2fa_id"]
            login(request, utilisateur)
            request.session["etablissement_id"] = utilisateur.etablissement_id
            enregistrer_action(acteur=utilisateur, action="connexion_reussie_2fa", request=request)
            return redirect("comptes:redirection_tableau_de_bord")
        enregistrer_action(acteur=utilisateur, action="echec_code_2fa", request=request)
        messages.error(request, "Code invalide.")

    return render(request, "comptes/verifier_2fa.html")


@require_http_methods(["POST"])
def deconnexion(request):
    if request.user.is_authenticated:
        enregistrer_action(acteur=request.user, action="deconnexion", request=request)
    logout(request)
    return redirect("comptes:connexion")


@login_required
def redirection_tableau_de_bord(request):
    """
    Point d'entrée unique après connexion. Les tableaux de bord détaillés par
    rôle seront construits dans les phases suivantes ; pour l'instant cette
    page confirme le rôle et les modules autorisés (utile pour vérifier la
    matrice de permissions).
    """
    from django.db.models import Sum
    from permissions_matrix.models import PermissionMatrix
    from permissions_matrix.modules import Module
    from comptes.models import Notification
    from scolarite.models import Inscription, calculer_total_du, classes_visibles_pour

    valeurs_autorisees = PermissionMatrix.modules_autorises(request.user.role, etablissement=request.user.etablissement)
    modules = [m.label for m in Module if m.value in valeurs_autorisees]
    if request.user.role == Role.PARENT:
        return redirect("comptes:portail_parent")

    indicateurs = []
    actions_rapides = []
    classes = classes_visibles_pour(request.user)
    if Module.ELEVES.value in valeurs_autorisees:
        indicateurs.append({
            "label": "Élèves inscrits",
            "valeur": Inscription.objects.filter(
                classe__in=classes, statut=Inscription.Statut.EN_COURS,
            ).count(),
        })
        actions_rapides.append({"label": "Voir les élèves", "url": "scolarite:liste_eleves"})
    if Module.CLASSES.value in valeurs_autorisees:
        indicateurs.append({
            "label": "Classes actives",
            "valeur": classes.filter(annee_scolaire__est_active=True).count(),
        })
        actions_rapides.append({"label": "Gérer les classes", "url": "scolarite:liste_classes"})
    if Module.FINANCES.value in valeurs_autorisees:
        from finances.models import Paiement
        total = Paiement.objects.filter(
            etablissement=request.user.etablissement, est_supprime=False,
        ).aggregate(total=Sum("montant"))["total"] or 0
        devise = getattr(request.user.etablissement, "code_devise", "FCFA")
        indicateurs.append({"label": "Encaissements", "valeur": f"{total} {devise}"})
        actions_rapides.append({"label": "Suivre les paiements", "url": "finances:suivi_paiements"})
    if Module.ABSENCES.value in valeurs_autorisees:
        from pedagogie.models import Absence
        indicateurs.append({"label": "Absences enregistrées", "valeur": Absence.objects.filter(classe__in=classes).count()})
    if Module.SUIVI_DES_COURS.value in valeurs_autorisees:
        actions_rapides.append({"label": "Suivi des cours", "url": "pedagogie:suivi_des_cours"})
    if Module.COMMUNICATION.value in valeurs_autorisees:
        actions_rapides.append({"label": "Publier une annonce", "url": "communication:publier_annonce"})
    return render(request, "comptes/tableau_de_bord.html", {
        "modules": modules, "indicateurs": indicateurs, "actions_rapides": actions_rapides,
        "notifications": Notification.objects.filter(
            destinataire=request.user, lue_le__isnull=True,
        )[:5],
    })


@role_requis(Role.PARENT)
def portail_parent(request):
    """
    Portail parent limité aux enfants effectivement liés au compte.

    Les quatre indicateurs par enfant (inscription, total payé, absences,
    moyenne) sont calculés en requêtes groupées sur l'ensemble de la fratrie
    plutôt qu'en boucle par enfant, pour éviter un N+1 sur la page la plus
    consultée du portail parent.
    """
    from django.db.models import Avg, Count, Q, Sum
    from finances.models import Paiement
    from pedagogie.models import Absence, Note
    from scolarite.models import Inscription

    enfants = list(request.user.enfants_lies.filter(
        etablissement=request.user.etablissement, role=Role.ELEVE,
    ).order_by("nom", "prenom"))

    inscriptions_par_eleve = {
        inscription.eleve_id: inscription
        for inscription in Inscription.objects.filter(
            eleve__in=enfants, statut=Inscription.Statut.EN_COURS,
        ).select_related("classe", "classe__echeancier")
    }

    totaux_payes_par_inscription = {
        ligne["inscription_id"]: ligne["total"]
        for ligne in Paiement.objects.filter(
            inscription__in=inscriptions_par_eleve.values(), est_supprime=False,
        ).values("inscription_id").annotate(total=Sum("montant"))
    }

    absences_par_eleve = dict(
        Absence.objects.filter(eleve__in=enfants)
        .values("eleve_id").annotate(total=Count("id")).values_list("eleve_id", "total")
    )

    filtre_moyennes = Q()
    for inscription in inscriptions_par_eleve.values():
        filtre_moyennes |= Q(eleve_id=inscription.eleve_id, affectation__classe_id=inscription.classe_id)
    moyennes_par_eleve = {
        ligne["eleve_id"]: ligne["moyenne"]
        for ligne in (
            Note.objects.filter(filtre_moyennes).values("eleve_id").annotate(moyenne=Avg("valeur"))
            if inscriptions_par_eleve else Note.objects.none()
        )
    }

    dossiers = []
    for enfant in enfants:
        inscription = inscriptions_par_eleve.get(enfant.id)
        total_paye = totaux_payes_par_inscription.get(inscription.id, 0) if inscription else 0
        total_du = calculer_total_du(inscription) if inscription else 0
        dossiers.append({
            "eleve": enfant,
            "inscription": inscription,
            "absences": absences_par_eleve.get(enfant.id, 0),
            "moyenne": moyennes_par_eleve.get(enfant.id) if inscription else None,
            "solde": max(total_du - total_paye, 0),
        })
    return render(request, "comptes/portail_parent.html", {"dossiers": dossiers})


@login_required
def liste_notifications(request):
    from django.core.paginator import Paginator
    notifications = Notification.objects.filter(destinataire=request.user)
    page_obj = Paginator(notifications, 25).get_page(request.GET.get("page"))
    return render(request, "comptes/notifications.html", {"page_obj": page_obj, "notifications": page_obj.object_list})


@login_required
@require_http_methods(["POST"])
def marquer_notifications_lues(request):
    Notification.objects.filter(destinataire=request.user, lue_le__isnull=True).update(lue_le=timezone.now())
    return redirect("comptes:liste_notifications")


@login_required
@require_http_methods(["POST"])
def marquer_notification_lue(request, notification_id):
    notification = get_object_or_404(Notification, pk=notification_id, destinataire=request.user)
    notification.lue_le = timezone.now()
    notification.save(update_fields=["lue_le"])
    return redirect(notification.url or "comptes:liste_notifications")


@login_required
def changer_email(request):
    if request.method == "POST":
        formulaire = ChangerEmailForm(request.user, request.POST)
        if formulaire.is_valid():
            ancien_email = request.user.email
            nouvel_email = formulaire.cleaned_data["nouvel_email"]
            request.user.email = nouvel_email
            request.user.save(update_fields=["email"])
            enregistrer_action(
                acteur=request.user, action="changement_email",
                cible=f"{ancien_email} -> {nouvel_email}", request=request,
            )
            # Notification de sécurité à l'ancienne adresse : permet de réagir
            # si ce changement n'est pas à l'origine du titulaire du compte.
            nom_etablissement = request.user.etablissement.nom if request.user.etablissement_id else settings.NOM_PLATEFORME
            envoyer_email(
                sujet=f"{nom_etablissement} - Votre adresse email a été modifiée",
                contenu=(
                    f"Bonjour {request.user.prenom},\n\n"
                    f"L'adresse email de connexion de votre compte vient d'être changée pour "
                    f"{nouvel_email}.\n\nSi vous n'êtes pas à l'origine de cette action, "
                    "contactez immédiatement le secrétariat ou la direction."
                ),
                expediteur=settings.DEFAULT_FROM_EMAIL, destinataires=[ancien_email],
            )
            messages.success(request, "Adresse email modifiée avec succès.")
            return redirect("comptes:redirection_tableau_de_bord")
    else:
        formulaire = ChangerEmailForm(request.user)
    return render(request, "comptes/changer_email.html", {"formulaire": formulaire})


@login_required
def changer_mot_de_passe(request):
    if request.method == "POST":
        formulaire = ChangerMotDePasseForm(request.user, request.POST)
        if formulaire.is_valid():
            utilisateur = formulaire.save()
            update_session_auth_hash(request, utilisateur)  # évite une déconnexion forcée
            enregistrer_action(acteur=utilisateur, action="changement_mot_de_passe", request=request)
            messages.success(request, "Mot de passe modifié avec succès.")
            return redirect("comptes:redirection_tableau_de_bord")
    else:
        formulaire = ChangerMotDePasseForm(request.user)
    return render(request, "comptes/changer_mot_de_passe.html", {"formulaire": formulaire})


# ---------------------------------------------------------------------------
# Authentification à deux facteurs (TOTP) - activation/désactivation en
# self-service, recommandée en particulier pour les rôles à privilège élevé.
# ---------------------------------------------------------------------------

@login_required
def activer_2fa(request):
    if request.user.deux_facteurs_actif:
        messages.info(request, "L'authentification à deux facteurs est déjà activée sur ce compte.")
        return redirect("comptes:redirection_tableau_de_bord")

    if request.method == "POST":
        secret = request.session.get("secret_2fa_en_attente")
        code = request.POST.get("code", "")
        if secret and request.user.verifier_code_2fa(code, secret=secret):
            request.user.totp_secret = secret
            request.user.deux_facteurs_actif = True
            request.user.save(update_fields=["totp_secret", "deux_facteurs_actif"])
            del request.session["secret_2fa_en_attente"]
            enregistrer_action(acteur=request.user, action="activation_2fa", request=request)
            messages.success(request, "Authentification à deux facteurs activée.")
            return redirect("comptes:redirection_tableau_de_bord")
        messages.error(request, "Code invalide. Réessayez.")
    else:
        request.session["secret_2fa_en_attente"] = request.user.generer_secret_2fa()

    secret = request.session["secret_2fa_en_attente"]
    qr_code = ""
    try:
        import base64
        from io import BytesIO
        import qrcode
        image = qrcode.make(request.user.uri_provisionnement_2fa(secret))
        tampon = BytesIO()
        image.save(tampon, format="PNG")
        qr_code = "data:image/png;base64," + base64.b64encode(tampon.getvalue()).decode("ascii")
    except ImportError:
        pass

    return render(request, "comptes/activer_2fa.html", {"secret": secret, "qr_code": qr_code})


@login_required
def desactiver_2fa(request):
    if not request.user.deux_facteurs_actif:
        return redirect("comptes:redirection_tableau_de_bord")

    if request.method == "POST":
        code = request.POST.get("code", "")
        if request.user.verifier_code_2fa(code):
            request.user.totp_secret = ""
            request.user.deux_facteurs_actif = False
            request.user.save(update_fields=["totp_secret", "deux_facteurs_actif"])
            enregistrer_action(acteur=request.user, action="desactivation_2fa", request=request)
            messages.success(request, "Authentification à deux facteurs désactivée.")
            return redirect("comptes:redirection_tableau_de_bord")
        messages.error(request, "Code invalide.")

    return render(request, "comptes/desactiver_2fa.html")


# ---------------------------------------------------------------------------
# Mot de passe oublié - email standard OU matricule (élève -> parents)
# ---------------------------------------------------------------------------

def _construire_lien_reinitialisation(request, utilisateur):
    uidb64 = urlsafe_base64_encode(force_bytes(utilisateur.pk))
    token = default_token_generator.make_token(utilisateur)
    chemin = reverse("comptes:reinitialiser_mot_de_passe", kwargs={"uidb64": uidb64, "token": token})
    return request.build_absolute_uri(chemin)


@ratelimit(key="ip", rate="5/m", method="POST", block=False)
def mot_de_passe_oublie(request):
    if getattr(request, "limited", False):
        messages.error(request, "Trop de demandes. Réessayez dans une minute.")
        return render(request, "comptes/mot_de_passe_oublie.html", {"formulaire": MotDePasseOublieForm()})
    formulaire = MotDePasseOublieForm(request.POST or None)
    if request.method == "POST" and formulaire.is_valid():
        identifiant = formulaire.cleaned_data["identifiant"].strip()

        if "@" in identifiant:
            utilisateur = Utilisateur.objects.filter(email__iexact=identifiant).first()
            if utilisateur:
                nom_etablissement = utilisateur.etablissement.nom if utilisateur.etablissement_id else settings.NOM_PLATEFORME
                lien = _construire_lien_reinitialisation(request, utilisateur)
                envoyer_email(
                    sujet=f"{nom_etablissement} - Réinitialisation du mot de passe",
                    contenu=f"Bonjour {utilisateur.prenom},\n\nCliquez sur ce lien pour choisir un "
                    f"nouveau mot de passe :\n{lien}\n\nCe lien est à usage unique.",
                    expediteur=settings.DEFAULT_FROM_EMAIL, destinataires=[utilisateur.email],
                )
        else:
            # Recherche par matricule (élève) : le lien part chez le(s) parent(s) lié(s),
            # jamais sur l'adresse générée automatiquement à l'inscription.
            eleve = Utilisateur.objects.filter(
                role=Role.ELEVE, matricule=identifiant,
            ).first()
            if eleve:
                parents = eleve.parents_lies.all()
                if parents.exists():
                    nom_etablissement = eleve.etablissement.nom if eleve.etablissement_id else settings.NOM_PLATEFORME
                    lien = _construire_lien_reinitialisation(request, eleve)
                    for parent in parents:
                        envoyer_email(
                            sujet=f"{nom_etablissement} - Réinitialisation du mot de passe de votre enfant",
                            contenu=f"Bonjour {parent.prenom},\n\nUne demande de réinitialisation du mot "
                            f"de passe du compte de {eleve.nom_complet} (matricule {eleve.matricule}) "
                            f"a été effectuée.\n\nCliquez sur ce lien pour choisir un nouveau mot "
                            f"de passe :\n{lien}\n\nSi vous n'êtes pas à l'origine de cette demande, "
                            "ignorez cet email.",
                            expediteur=settings.DEFAULT_FROM_EMAIL, destinataires=[parent.email],
                        )
                    enregistrer_action(
                        acteur=None, action="demande_reinitialisation_mdp_eleve",
                        cible=eleve.matricule, request=request,
                    )

        # Message volontairement identique dans tous les cas (compte trouvé ou non)
        # pour ne pas révéler l'existence d'un compte.
        messages.success(
            request,
            "Si les informations correspondent à un compte, un lien de réinitialisation "
            "vient d'être envoyé.",
        )
        return redirect("comptes:connexion")

    return render(request, "comptes/mot_de_passe_oublie.html", {"formulaire": formulaire})


class ReinitialiserMotDePasseView(PasswordResetConfirmView):
    template_name = "comptes/reinitialiser_mot_de_passe.html"
    form_class = DefinirNouveauMotDePasseForm
    success_url = reverse_lazy("comptes:connexion")

    def form_valid(self, form):
        reponse = super().form_valid(form)
        messages.success(self.request, "Mot de passe modifié avec succès. Vous pouvez vous connecter.")
        enregistrer_action(
            acteur=None, action="mot_de_passe_reinitialise",
            cible=str(self.user.pk) if getattr(self, "user", None) else "",
            request=self.request,
        )
        return reponse


# ---------------------------------------------------------------------------
# Validation des comptes (secrétariat ou direction)
# ---------------------------------------------------------------------------

@role_requis(*ROLES_VALIDATION_COMPTES)
def comptes_en_attente(request):
    en_attente = Utilisateur.objects.filter(
        statut=StatutCompte.EN_ATTENTE_VALIDATION, etablissement=request.user.etablissement,
    ).order_by("date_creation")
    return render(request, "comptes/comptes_en_attente.html", {"comptes": en_attente})


@role_requis(*ROLES_VALIDATION_COMPTES)
@require_http_methods(["POST"])
def valider_compte(request, utilisateur_id):
    utilisateur = get_object_or_404(
        Utilisateur, id=utilisateur_id, statut=StatutCompte.EN_ATTENTE_VALIDATION,
        etablissement=request.user.etablissement,
    )
    utilisateur.statut = StatutCompte.ACTIF
    utilisateur.is_active = True
    utilisateur.save(update_fields=["statut", "is_active"])
    enregistrer_action(
        acteur=request.user, action="validation_compte",
        cible=utilisateur.email, request=request,
    )
    messages.success(request, f"Le compte de {utilisateur.nom_complet} a été activé.")
    return redirect("comptes:comptes_en_attente")


@role_requis(*ROLES_VALIDATION_COMPTES)
@require_http_methods(["POST"])
def refuser_compte(request, utilisateur_id):
    utilisateur = get_object_or_404(
        Utilisateur, id=utilisateur_id, statut=StatutCompte.EN_ATTENTE_VALIDATION,
        etablissement=request.user.etablissement,
    )
    utilisateur.statut = StatutCompte.DESACTIVE
    utilisateur.save(update_fields=["statut"])
    enregistrer_action(
        acteur=request.user, action="refus_compte",
        cible=utilisateur.email, request=request,
    )
    messages.info(request, f"La demande de {utilisateur.nom_complet} a été refusée.")
    return redirect("comptes:comptes_en_attente")
