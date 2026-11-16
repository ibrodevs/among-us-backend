import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY or (not DEBUG and SECRET_KEY.startswith("change-me")):
    raise ImproperlyConfigured("Set a secure DJANGO_SECRET_KEY in .env")

ALLOWED_HOSTS = [
    v.strip()
    for v in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if v.strip()
]
CORS_ALLOWED_ORIGINS = [
    v.strip()
    for v in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if v.strip()
]

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "channels",
    "players",
    "rooms",
    "game",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": dj_database_url.parse(
        os.getenv("DATABASE_URL", "sqlite:///" + str(BASE_DIR / "db.sqlite3")),
        conn_max_age=0,
    )
}

if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
    DATABASES["default"]["OPTIONS"] = {
        "pool": {"min_size": 2, "max_size": 16, "timeout": 5}
    }

REDIS_URL = os.getenv("REDIS_URL", "").strip()
if not DEBUG and not REDIS_URL:
    raise ImproperlyConfigured("REDIS_URL is required when DJANGO_DEBUG=false")
CHANNEL_LAYERS = {
    "default": (
        {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
        if REDIS_URL
        else {"BACKEND": "channels.layers.InMemoryChannelLayer"}
    )
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["players.authentication.GuestAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Production must fail closed rather than quietly falling back to SQLite.
if not DEBUG and DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
    raise ImproperlyConfigured("PostgreSQL DATABASE_URL is required in production")
if not DEBUG and (len(SECRET_KEY) < 50 or "*" in ALLOWED_HOSTS):
    raise ImproperlyConfigured(
        "Production requires a strong key and explicit allowed hosts"
    )
SECURE_SSL_REDIRECT = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
# Enable only behind the documented proxy that overwrites this header.
if os.getenv("TRUST_PROXY_HTTPS", "false").lower() == "true":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "KEY_PREFIX": "crew",
        }
    }
REST_FRAMEWORK["EXCEPTION_HANDLER"] = "config.exceptions.api_exception_handler"
