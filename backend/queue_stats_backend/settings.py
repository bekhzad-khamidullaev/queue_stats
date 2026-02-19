"""
Django settings for queue_stats_backend project.

The configuration favours environment-based overrides so the project can talk to
the legacy Asterisk MySQL databases without hardcoding credentials.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import json
from typing import Any, Dict

from django.core.management.utils import get_random_secret_key

BASE_DIR = Path(__file__).resolve().parent.parent


# --- Core --------------------------------------------------------------------

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", get_random_secret_key())

DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"

ALLOWED_HOSTS: list[str] = [
    host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]


# --- Applications ------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "channels",
    "accounts",
    "stats",
    "settings",
]

ASGI_APPLICATION = "queue_stats_backend.asgi.application"

# Channel layers configuration for WebSocket
# For development, use InMemoryChannelLayer
# For production with multiple workers, use Redis:
if os.environ.get('DJANGO_ENV') == 'production':
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [(os.environ.get('REDIS_HOST', '127.0.0.1'), int(os.environ.get('REDIS_PORT', 6379)))],
            },
        },
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer"
        }
    }


# --- Middleware --------------------------------------------------------------

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


ROOT_URLCONF = "queue_stats_backend.urls"

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
            ],
        },
    },
]

WSGI_APPLICATION = "queue_stats_backend.wsgi.application"


# --- Database ----------------------------------------------------------------


def _mysql_database() -> Dict[str, Any]:
    return {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.getenv("DB_NAME", "asteriskcdrdb"),
        "USER": os.getenv("DB_USER", "root"),
        "PASSWORD": os.getenv("DB_PASSWORD", "t3sl@admin"),
        "HOST": os.getenv("DB_HOST", "10.10.134.62"),
        "PORT": os.getenv("DB_PORT", "3306"),
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }


def _sqlite_database() -> Dict[str, Any]:
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }

DATABASE_ENGINE = os.getenv("DB_ENGINE", "mysql").lower()
if DATABASE_ENGINE == "sqlite":
    DATABASES: Dict[str, Dict[str, Any]] = {"default": _sqlite_database()}
else:
    DATABASES = {"default": _mysql_database()}
DATABASE_ROUTERS = ["queue_stats_backend.db_router.StatsRouter"]

# Optional external Asterisk DB alias used by report queries.
asterisk_db_config_path = BASE_DIR / "asterisk_db.json"
if asterisk_db_config_path.exists():
    with open(asterisk_db_config_path) as f:
        DATABASES["asterisk"] = json.load(f)
else:
    DATABASES["asterisk"] = DATABASES["default"].copy()

if 'test' in sys.argv:
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
    DATABASES['asterisk'] = DATABASES['default']


# --- Password validation -----------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# --- Internationalization ----------------------------------------------------

LANGUAGE_CODE = "ru-ru"

TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "UTC")

USE_I18N = True

USE_TZ = True


# --- Static files ------------------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "static"

# --- Default primary key field type -----------------------------------------

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"


# --- Legacy integration tweaks ----------------------------------------------

ASTERISK_MONITOR_PATH = os.getenv("ASTERISK_MONITOR_PATH", "/var/spool/asterisk/monitor/")
ASTERISK_AJAM_URL = os.getenv("ASTERISK_AJAM_URL", "http://10.10.134.62:8088/asterisk/rawman")
ASTERISK_AJAM_USERNAME = os.getenv("ASTERISK_AJAM_USERNAME", "ajamuser")
ASTERISK_AJAM_SECRET = os.getenv("ASTERISK_AJAM_SECRET", "t3sl@admin")
ASTERISK_AJAM_AUTHTYPE = os.getenv("ASTERISK_AJAM_AUTHTYPE", "plaintext")

# --- CORS --------------------------------------------------------------------

_cors_origins = os.getenv("DJANGO_CORS_ORIGINS")
if _cors_origins:
    CORS_ALLOWED_ORIGINS = [origin.strip() for origin in _cors_origins.split(",") if origin.strip()]
else:
    CORS_ALLOWED_ORIGINS = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8080",
    ]
CORS_ALLOW_CREDENTIALS = True
