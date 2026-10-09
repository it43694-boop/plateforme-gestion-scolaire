import os
import secrets

# Longueur maximale d'un champ fichier Django par défaut (FileField.max_length).
LONGUEUR_MAX_CHEMIN = 100


def chemin_upload_unique(dossier: str, etablissement_id, nom_fichier: str) -> str:
    """
    Chemin de stockage d'un fichier téléversé : `<dossier>/<école>/<jeton>/<nom>`.

    - le jeton aléatoire rend l'adresse impossible à deviner : le stockage objet
      sert les médias par une adresse publique non signée (voir STORAGES dans
      config.settings), le nom du fichier ne doit donc jamais suffire à le retrouver ;
    - il évite aussi que deux fichiers de même nom s'écrasent (le stockage S3 écrase
      par défaut), y compris entre deux écoles ;
    - le nom d'origine est conservé en fin de chemin (affichage, téléchargement),
      tronqué si besoin pour rester dans LONGUEUR_MAX_CHEMIN.
    """
    prefixe = f"{dossier}/{etablissement_id or 'commun'}/{secrets.token_hex(10)}/"
    base, extension = os.path.splitext(os.path.basename(nom_fichier))
    place = max(LONGUEUR_MAX_CHEMIN - len(prefixe) - len(extension), 1)
    return f"{prefixe}{base[:place]}{extension}"
