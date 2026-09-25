"""
Mode génératif de l'Assistant (optionnel, cahier des charges section
Assistant : « activable avec une clé API »).

RÈGLE DE SÉCURITÉ NON NÉGOCIABLE : cette fonction ne reçoit et n'envoie à
l'API QUE le dictionnaire `donnees_autorisees` que l'appelant lui fournit.
Elle n'a accès à aucune connexion base de données, aucun outil, aucune
capacité d'aller chercher une information supplémentaire. Si une donnée
n'est pas dans `donnees_autorisees`, elle n'existe pas pour l'IA - c'est
le mécanisme qui garantit que l'assistance ne dépasse jamais le rôle de
la personne qui pose la question : le filtrage a lieu AVANT l'appel, pas
sur la promesse que l'IA se limitera d'elle-même.

Ne jamais modifier cette fonction pour lui donner un accès direct à la
base de données, un exécuteur de requêtes, ou tout autre outil : cela
romprait la garantie ci-dessus, quelle que soit la prudence du prompt.
"""

import json
import logging

from django.conf import settings

logger = logging.getLogger("assistant_ia")


class AssistantIndisponible(Exception):
    """Levée si l'appel à l'API échoue (réseau, clé invalide, quota, etc.)."""


def ia_disponible() -> bool:
    return bool(settings.GROQ_API_KEY)


def repondre_avec_ia(*, donnees_autorisees: dict, question: str) -> str:
    if not ia_disponible():
        raise AssistantIndisponible("Aucune clé API configurée.")

    from groq import Groq

    contexte_json = json.dumps(donnees_autorisees, default=str, ensure_ascii=False, indent=2)

    instructions = (
        "Tu es l'assistant d'une plateforme de gestion scolaire. Un membre du "
        "personnel ou un utilisateur autorisé te pose une question sur UN élève "
        "précis. Voici, au format JSON, EXACTEMENT et UNIQUEMENT les informations "
        "que cette personne a le droit de consulter - des champs ont pu être "
        "omis délibérément si son rôle n'y a pas accès :\n\n"
        f"{contexte_json}\n\n"
        "Consignes strictes :\n"
        "- Réponds uniquement à partir des données ci-dessus.\n"
        "- Si l'information demandée n'y figure pas, dis clairement que tu ne "
        "l'as pas ou que ce n'est pas accessible avec ce rôle - ne l'invente "
        "jamais et ne suppose jamais qu'elle existe ailleurs.\n"
        "- N'émets aucune hypothèse sur des données non fournies (finances, "
        "notes, absences...) : leur absence signifie que la personne n'y a "
        "pas droit, pas qu'elles sont vides ou inconnues d'elle.\n"
        "- Réponds en français, en 2 à 4 phrases, sans formule d'introduction."
    )

    try:
        client = Groq(api_key=settings.GROQ_API_KEY)
        completion = client.chat.completions.create(
            model=settings.ASSISTANT_MODELE_IA,
            max_tokens=400,
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": question},
            ],
        )
        return (completion.choices[0].message.content or "").strip()
    except Exception as erreur:
        logger.warning("Échec de l'appel à l'Assistant IA : %s", erreur)
        raise AssistantIndisponible(str(erreur)) from erreur


def serialiser_resultat(resultat: dict) -> dict:
    """
    Aplatit le résultat déjà construit par la vue (objets Django compris)
    en dictionnaire simple prêt pour le JSON - c'est ce dictionnaire, et
    uniquement lui, qui part vers l'API.
    """
    donnees = {
        "eleve": {
            "nom_complet": resultat["eleve"].nom_complet,
            "matricule": resultat["eleve"].matricule,
        },
        "dossier_complet": resultat.get("dossier_complet"),
    }
    if resultat.get("inscription"):
        donnees["classe"] = str(resultat["inscription"].classe)
    if "dernieres_notes" in resultat:
        donnees["dernieres_notes"] = [
            {
                "matiere": note.affectation.matiere or "Titulaire",
                "trimestre": note.get_trimestre_display(),
                "valeur_sur_20": float(note.valeur),
            }
            for note in resultat["dernieres_notes"]
        ]
    if "total_absences" in resultat:
        donnees["total_absences"] = resultat["total_absences"]
    if "derniers_paiements" in resultat:
        donnees["derniers_paiements"] = [
            {
                "reference": paiement.reference,
                "tranche": paiement.get_tranche_display(),
                "montant_fcfa": paiement.montant,
            }
            for paiement in resultat["derniers_paiements"]
        ]
    return donnees
