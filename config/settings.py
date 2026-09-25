"""
Configuration Django - plateforme de gestion scolaire (générique).

Le nom, le logo et la devise affichés dans l'application sont ceux de
l'établissement qui déploie la plateforme (voir l'app `etablissement`,
configurable depuis l'espace développeur) - rien n'est propre à un
établissement en particulier dans ce fichier.

Bascule automatique SQLite (développement) <-> PostgreSQL (production)
par variable d'environnement, conformément au cahier des charges
(section « Déploiement »).
"""

from pathlib import Path
import importlib.util
import environ
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
# Charge un fichier .env s'il existe (développement local uniquement ;
# en production, les variables sont injectées par la plateforme d'hébergement).
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

# ---------------------------------------------------------------------------
# Sécurité de base
# ---------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", default="")
DEBUG = env.bool("DEBUG", default=False)

if not DEBUG and (not SECRET_KEY or SECRET_KEY == "django-insecure-CHANGE-ME-EN-PRODUCTION"):
    raise RuntimeError("DJANGO_SECRET_KEY doit être définie avec une valeur aléatoire en production.")

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",

    # Apps internes
    "etablissement",
    "vitrine",
    "comptes",
    "permissions_matrix",
    "scolarite",
    "finances",
    "pedagogie",
    "tests_niveau",
    "assistant",
    "espace_plateforme",
    "bibliotheque",
    "communication",
    "statistiques",
    "espace_developpeur",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Verrouillage de compte après tentatives de connexion échouées
    "comptes.middleware.AxesLikeLockoutMiddleware",
    # Content-Security-Policy (défense en profondeur contre l'injection de script)
    "comptes.middleware.ContentSecurityPolicyMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "comptes.context_processors.etablissement_actif",
                "comptes.context_processors.navigation",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Base de données - SQLite en développement, PostgreSQL en production.
# Bascule unique : la variable d'environnement DATABASE_URL.
#   - absente ou vide  -> SQLite (db.sqlite3), pratique en local
#   - définie          -> PostgreSQL (ou tout backend supporté par dj-database-url)
# ---------------------------------------------------------------------------
DATABASE_URL = env("DATABASE_URL", default="")

if not DEBUG and DATABASE_URL.startswith("sqlite"):
    raise RuntimeError("DATABASE_URL SQLite est interdite en production.")

if DATABASE_URL and not DATABASE_URL.startswith("sqlite"):
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            ssl_require=env.bool("DATABASE_SSL_REQUIRE", default=True),
        )
    }
else:
    sqlite_name = DATABASE_URL.removeprefix("sqlite:///") if DATABASE_URL.startswith("sqlite") else str(BASE_DIR / "db.sqlite3")
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": sqlite_name,
        }
    }

# ---------------------------------------------------------------------------
# Modèle utilisateur personnalisé
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "comptes.Utilisateur"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    # Validateur maison : au moins une majuscule, un chiffre et un caractère spécial
    {"NAME": "comptes.validators.ComplexiteMotDePasseValidator"},
]

LOGIN_URL = "comptes:connexion"
LOGIN_REDIRECT_URL = "comptes:redirection_tableau_de_bord"
LOGOUT_REDIRECT_URL = "comptes:connexion"

from django.contrib.messages import constants as message_constants
MESSAGE_TAGS = {message_constants.ERROR: "danger"}

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Africa/Bamako"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Fichiers statiques / médias
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage" if not DEBUG else \
    "django.contrib.staticfiles.storage.StaticFilesStorage"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Stockage objet compatible S3 (AWS S3, Cloudflare R2, MinIO...).
# Le disque local reste le comportement de développement par défaut.
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", default="")
if AWS_STORAGE_BUCKET_NAME and not DEBUG:
    INSTALLED_APPS += ["storages"]
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "bucket_name": AWS_STORAGE_BUCKET_NAME,
                "region_name": env("AWS_S3_REGION_NAME", default=None),
                "endpoint_url": env("AWS_S3_ENDPOINT_URL", default=None),
                "access_key": env("AWS_ACCESS_KEY_ID", default=""),
                "secret_key": env("AWS_SECRET_ACCESS_KEY", default=""),
                "default_acl": None,
                "querystring_auth": env.bool("AWS_QUERYSTRING_AUTH", default=True),
            },
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Cache - utilisé notamment par les limites de débit (django-ratelimit).
#
# ⚠️ En développement (un seul processus), le cache mémoire local suffit.
# En production avec plusieurs workers gunicorn (voir render.yaml,
# --workers 3), CHAQUE worker a son propre cache mémoire isolé : une limite
# de « 20/heure » devient alors, dans les faits, jusqu'à 60/heure (20 par
# worker). Remplacer par Redis (django-redis, CACHES BACKEND
# django_redis.cache.RedisCache) avant toute mise en production réelle
# pour que la limite soit effectivement partagée entre tous les workers.
# ---------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", default="")
REDIS_CONFIGURE = bool(REDIS_URL and importlib.util.find_spec("django_redis"))
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
} if REDIS_CONFIGURE else {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
}

# ---------------------------------------------------------------------------
# Sécurité renforcée (activée automatiquement hors DEBUG)
# ---------------------------------------------------------------------------
if not DEBUG:
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30  # 30 jours
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    X_FRAME_OPTIONS = "DENY"
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL doit être définie en production.")
    if not REDIS_URL or not REDIS_CONFIGURE:
        raise RuntimeError("REDIS_URL doit être définie en production avec plusieurs workers.")

# Expiration de session : 30 minutes d'inactivité (cf. section Sécurité du cahier des charges)
SESSION_COOKIE_AGE = 60 * 30
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# ---------------------------------------------------------------------------
# Email (vérification à l'inscription, notifications d'annonces)
# ---------------------------------------------------------------------------
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend" if DEBUG
    else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="no-reply@example.com")
EMAIL_ASYNC = env.bool("EMAIL_ASYNC", default=False)

if not DEBUG:
    if not EMAIL_HOST or not EMAIL_HOST_USER or not EMAIL_HOST_PASSWORD:
        raise RuntimeError("La configuration SMTP complète est obligatoire en production.")
    if not AWS_STORAGE_BUCKET_NAME:
        raise RuntimeError("AWS_STORAGE_BUCKET_NAME doit être défini en production pour persister les médias.")

SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.1))
    except ImportError as erreur:
        raise RuntimeError("SENTRY_DSN est défini mais sentry-sdk n'est pas installé.") from erreur

# Nom/slogan du LOGICIEL lui-même (distinct du nom de chaque établissement,
# configurable séparément via etablissement.Etablissement) - utilisé sur la
# page d'accueil publique et dans la documentation.
NOM_PLATEFORME = "L'éducation du Mali au service de l'avenir"

# Assistant - mode génératif optionnel (cahier des charges : « mode sans IA
# générative tant qu'aucune clé API n'est configurée »). Tant que
# GROQ_API_KEY est vide, l'Assistant reste en mode recherche simple.
# La clé ne doit JAMAIS être écrite dans ce fichier ni committée : elle se
# définit uniquement via la variable d'environnement, dans le .env local
# (non versionné) ou les réglages de la plateforme d'hébergement.
GROQ_API_KEY = env("GROQ_API_KEY", default="")
ASSISTANT_MODELE_IA = env("ASSISTANT_MODELE_IA", default="llama-3.3-70b-versatile")

# Durée de validité du code de vérification à l'inscription (en minutes)
DUREE_VALIDITE_CODE_VERIFICATION_MINUTES = 10

# Nombre de tentatives de connexion échouées avant verrouillage temporaire
NB_TENTATIVES_CONNEXION_AVANT_VERROUILLAGE = 5
DUREE_VERROUILLAGE_MINUTES = 15

# ---------------------------------------------------------------------------
# Adresse IP réelle du client à travers le(s) proxy(s) de confiance (voir
# comptes/utils.py::ip_client_fiable). Doit correspondre exactement au
# nombre de sauts entre le client et Django : 1 pour Render seul (valeur par
# défaut), à augmenter si un CDN/reverse-proxy de confiance supplémentaire
# (ex. Cloudflare) est ajouté devant Render. Une valeur trop haute par
# rapport à la topologie réelle réintroduit la falsification via
# X-Forwarded-For ; ne l'augmenter que si chaque saut est réellement de
# confiance.
# ---------------------------------------------------------------------------
NB_PROXYS_CONFIANCE = env.int("NB_PROXYS_CONFIANCE", default=1)

# django-ratelimit (connexion, mot de passe oublié, renvoi de code, Assistant
# IA) doit s'appuyer sur la même résolution d'IP que le journal d'audit, sinon
# le rate-limiting et l'audit peuvent diverger sur l'IP réelle d'un client.
RATELIMIT_IP_META_KEY = "comptes.utils.ip_client_fiable"

# ---------------------------------------------------------------------------
# Journalisation (journal d'audit applicatif - voir comptes/audit.py)
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "[{asctime}] {levelname} {name} - {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "loggers": {
        "audit": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
