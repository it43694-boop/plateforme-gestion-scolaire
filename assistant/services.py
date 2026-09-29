"""
Mode génératif de l'Assistant (optionnel, cahier des charges section
Assistant : « activable avec une clé API »).

RÈGLE DE SÉCURITÉ NON NÉGOCIABLE, valable pour les deux modes de ce fichier
(élève précis et vue générale) : les fonctions `repondre_*_avec_ia`
ne reçoivent et n'envoient à l'API QUE le dictionnaire `donnees_autorisees`
que l'appelant leur fournit. Elles n'ont accès à aucune connexion base de
données, aucun outil, aucune capacité d'aller chercher une information
supplémentaire. Si une donnée n'est pas dans `donnees_autorisees`, elle
n'existe pas pour l'IA - c'est le mécanisme qui garantit que l'assistance
ne dépasse jamais le rôle de la personne qui pose la question : le
filtrage a lieu AVANT l'appel, pas sur la promesse que l'IA se limitera
d'elle-même.

Ne jamais modifier ces fonctions pour leur donner un accès direct à la
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


def _interroger_groq(*, instructions: str, question: str) -> str:
    """
    Appel bas niveau, partagé par les deux modes (élève précis / vue
    générale scopée au rôle). Ne construit jamais lui-même le contexte :
    il reçoit des `instructions` déjà entièrement rédigées par l'appelant,
    contenant le JSON filtré - voir la garantie de sécurité en tête de
    fichier, valable pour les deux modes.
    """
    if not ia_disponible():
        raise AssistantIndisponible("Aucune clé API configurée.")

    from groq import Groq

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


def repondre_avec_ia(*, donnees_autorisees: dict, question: str) -> str:
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
    return _interroger_groq(instructions=instructions, question=question)


def repondre_question_generale_avec_ia(*, donnees_autorisees: dict, question: str) -> str:
    """
    Variante « vue d'ensemble » : la question ne porte plus sur un élève
    mais sur l'établissement, avec les mêmes garanties - le dictionnaire
    reçu a déjà été construit UNIQUEMENT à partir des modules que le rôle
    de la personne a le droit de consulter (voir assistant/views.py,
    construire_donnees_generales), jamais par une requête que l'IA
    déclencherait elle-même.
    """
    contexte_json = json.dumps(donnees_autorisees, default=str, ensure_ascii=False, indent=2)

    instructions = (
        "Tu es l'assistant d'une plateforme de gestion scolaire. Un membre du "
        "personnel te pose une question générale sur son établissement. Voici, "
        "au format JSON, EXACTEMENT et UNIQUEMENT les indicateurs que son rôle "
        "l'autorise à consulter - des chiffres ont pu être omis délibérément si "
        "son rôle n'a pas accès au module correspondant :\n\n"
        f"{contexte_json}\n\n"
        "Consignes strictes :\n"
        "- Réponds uniquement à partir des chiffres ci-dessus.\n"
        "- Si l'information demandée n'y figure pas, dis clairement que tu ne "
        "l'as pas ou que ce n'est pas accessible avec ce rôle - ne l'invente "
        "jamais et ne suppose jamais qu'elle existe ailleurs.\n"
        "- Ne mentionne jamais un élève, un employé ou un paiement nommément : "
        "tu ne disposes que d'agrégats, jamais de dossiers individuels.\n"
        "- Réponds en français, en 2 à 4 phrases, sans formule d'introduction."
    )
    return _interroger_groq(instructions=instructions, question=question)


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
