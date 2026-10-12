"""Règles de stockage des médias, isolées des réglages pour pouvoir être testées sans démarrer toute la configuration."""


def signer_les_liens(domaine_public, signature_demandee):
    """
    Faut-il signer les liens vers les fichiers (logos, documents, justificatifs) ?

    - Sans domaine public, le lien pointe vers l'API S3 du stockage, qui exige une signature : un lien non signé
      répond « Missing signature » et le fichier ne s'affiche jamais (logo cassé). On signe donc TOUJOURS, quelle que
      soit la valeur de AWS_QUERYSTRING_AUTH : cette variable ne doit pas pouvoir casser les médias.
    - Avec un domaine public (bucket public, déconseillé), la signature est inutile : la variable décide.
    """
    return bool(signature_demandee) if domaine_public else True
