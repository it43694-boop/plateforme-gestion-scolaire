"""
Création d'un élève, de ses liens avec ses parents et de son inscription.

Une seule règle, utilisée par le formulaire d'inscription d'un élève ET par l'import Excel : les deux ne peuvent donc
pas se mettre à créer des comptes différemment.
"""
from django.db import transaction
from django.utils.crypto import get_random_string

from comptes.models import Utilisateur, creer_avec_matricule_unique, generer_matricule
from comptes.roles import Role, StatutCompte
from scolarite.models import Inscription, ParentEnAttente, lier_parent_a_eleve

DOMAINE_EMAIL_AUTO_ELEVE = "eleves.local"


def creer_eleve_inscrit(donnees, etablissement):
    """
    Crée l'élève (compte sans mot de passe utilisable : on lui en remet un provisoire depuis son dossier), lie ses
    parents (ou mémorise leur email s'ils n'ont pas encore de compte) et l'inscrit dans sa classe.

    `donnees` est le `cleaned_data` d'un `InscrireEleveForm` valide. À appeler dans une transaction ouverte par
    l'appelant : si une étape échoue, l'élève tout juste créé ne doit jamais rester sans classe ni parent.
    """
    def construire():
        matricule = donnees.get("matricule") or generer_matricule()
        eleve = Utilisateur(
            email=f"{matricule}@{DOMAINE_EMAIL_AUTO_ELEVE}",
            prenom=donnees["prenom"],
            nom=donnees["nom"],
            prenom_ar=(donnees.get("prenom_ar") or "").strip(),
            nom_ar=(donnees.get("nom_ar") or "").strip(),
            role=Role.ELEVE,
            matricule=matricule,
            etablissement=etablissement,
            sexe=donnees["sexe"],
            date_naissance=donnees.get("date_naissance"),
            lieu_naissance=(donnees.get("lieu_naissance") or "").strip(),
            numero_acte_naissance=(donnees.get("numero_acte_naissance") or "").strip(),
            nom_pere=(donnees.get("nom_pere") or "").strip(),
            nom_mere=(donnees.get("nom_mere") or "").strip(),
            adresse=(donnees.get("adresse") or "").strip(),
            contact_urgence_nom=(donnees.get("contact_urgence_nom") or "").strip(),
            contact_urgence_telephone=(donnees.get("contact_urgence_telephone") or "").strip(),
            ecole_origine=(donnees.get("ecole_origine") or "").strip(),
            handicap=donnees.get("handicap") or "",
            statut_deplacement=donnees.get("statut_deplacement") or "",
            statut=StatutCompte.ACTIF,
            is_active=True,
            email_verifie=True,
        )
        eleve.set_password(get_random_string(32))
        eleve.full_clean(exclude=["password"])
        # Point de sauvegarde : une collision de matricule (requête simultanée) fait réessayer sans casser la
        # transaction englobante.
        with transaction.atomic():
            eleve.save()
        return eleve

    eleve = creer_avec_matricule_unique(construire)

    for parent in filter(None, [donnees.get("parent_1"), donnees.get("parent_2")]):
        lier_parent_a_eleve(eleve, parent)
    for info in donnees.get("parents_en_attente", []):
        ParentEnAttente.objects.create(eleve=eleve, **info)
    Inscription.objects.create(eleve=eleve, classe=donnees["classe"])
    photo = donnees.get("photo")  # déjà préparée par le formulaire ; enregistrée en dernier pour ne laisser aucun fichier orphelin
    if photo is not None:  # (un fichier sans nom est « faux » pour Python : on compare à None)
        eleve.photo.save(f"{eleve.matricule}.jpg", photo, save=False)
        eleve.save(update_fields=["photo"])
    return eleve
