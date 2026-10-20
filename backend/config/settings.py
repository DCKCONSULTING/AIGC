"""
Django settings for DckBrand.
"""

import os
from pathlib import Path

from corsheaders.defaults import default_headers
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
# The Gemini SDK sends GOOGLE_API_KEY when both variables exist, and a video
# status call then fails as two credentials. Omni uses GEMINI_API_KEY only.
if (os.environ.get("GEMINI_API_KEY") or "").strip():
    os.environ.pop("GOOGLE_API_KEY", None)

DEBUG = os.environ.get("DEBUG", "true").lower() in {"1", "true", "yes"}
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "django-insecure-dev-only-not-for-production"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY is required when DEBUG is false.")

SITE_URL = os.environ.get("SITE_URL", "https://brand.dckwebgen.com").rstrip("/")
SITE_HOST = SITE_URL.split("://", 1)[-1].split("/", 1)[0]

ALLOWED_HOSTS = [
    SITE_HOST,
    "localhost",
    "127.0.0.1",
    "172.19.192.1",
]

CSRF_TRUSTED_ORIGINS = [
    SITE_URL,
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://172.19.192.1:3000",
]

# Nginx terminates TLS and forwards X-Forwarded-Proto / Host to Gunicorn.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "accounts",
    "agents",
    "brands",
    "ai",
    "commerce",
    "django_q",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
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
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {
            "timeout": 20,
        },
    }
}

AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "accounts.backends.EmailOrUsernameBackend",
]

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

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = [
    SITE_URL,
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://172.19.192.1:3000",
]
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOW_HEADERS = (
    *default_headers,
    "x-acting-user",
    "x-acting-brand",
)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "accounts.authentication.TokenActingAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or GOOGLE_API_KEY
GOOGLE_CLOUD_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
GOOGLE_CLOUD_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
GOOGLE_APPLICATION_CREDENTIALS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
if GOOGLE_APPLICATION_CREDENTIALS:
    os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", GOOGLE_APPLICATION_CREDENTIALS)

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
OMNI_MODEL = os.environ.get("OMNI_MODEL") or os.environ.get("GEMINI_OMNI_MODEL", "gemini-omni-1.1-flash")
GEMINI_OMNI_MODEL = OMNI_MODEL
GEMINI_OMNI_RESOLUTION = os.environ.get("GEMINI_OMNI_RESOLUTION", "720p")
GEMINI_OMNI_POLL_SECONDS = int(os.environ.get("GEMINI_OMNI_POLL_SECONDS", "5") or 5)
NANO_BANANA_MODEL = os.environ.get("NANO_BANANA_MODEL", "gemini-2.5-flash-image")
VEO_MODEL = os.environ.get("VEO_MODEL", "veo-3.1-generate-preview")
VIDEO_PROVIDER = (os.environ.get("VIDEO_PROVIDER", "omni") or "omni").strip().lower()
INTELLIGENCE_PROVIDER = os.environ.get("INTELLIGENCE_PROVIDER", "gemini")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1")
CLAW_API_KEY = os.environ.get("CLAW_API_KEY", "")
CLAW_API_BASE = os.environ.get("CLAW_API_BASE", "")
CLAW_MODEL = os.environ.get("CLAW_MODEL", "openclaw/default")
SEEDANCE_API_KEY = os.environ.get("SEEDANCE_API_KEY", "") or os.environ.get("BYTEPLUS_API_KEY", "")
SEEDANCE_API_BASE = os.environ.get(
    "SEEDANCE_API_BASE",
    "https://ark.ap-southeast.bytepluses.com/api/v3",
)
# Verified ModelArk ids: dreamina-seedance-2-5-260628 (4–30s quality) or
# dreamina-seedance-2-0-fast-260128 (4–15s; documented faster path for latency).
SEEDANCE_MODEL = os.environ.get("SEEDANCE_MODEL", "dreamina-seedance-2-5-260628")
SEEDANCE_RESOLUTION = os.environ.get("SEEDANCE_RESOLUTION", "720p")
# Queue priority for Dreamina 2.x Endpoints only (0–9). Does not speed up a lone running task.
SEEDANCE_PRIORITY = max(0, min(int(os.environ.get("SEEDANCE_PRIORITY", "5") or 5), 9))
MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
MINIMAX_API_BASE = os.environ.get("MINIMAX_API_BASE", "https://api.minimax.io")
# Verified MiniMax V2 models: MiniMax-H3 | MiniMax-H3-Max
MINIMAX_VIDEO_MODEL = os.environ.get("MINIMAX_VIDEO_MODEL", "MiniMax-H3")
MINIMAX_VIDEO_RESOLUTION = os.environ.get("MINIMAX_VIDEO_RESOLUTION", "768P")
KALODATA_API_KEY = os.environ.get("KALODATA_API_KEY", "")
KALODATA_API_BASE = os.environ.get("KALODATA_API_BASE", "")
FFMPEG_PATH = os.environ.get("FFMPEG_PATH", "")
AI_SYNC_TASKS = os.environ.get("AI_SYNC_TASKS", "false").lower() in {"1", "true", "yes"}
VIDEO_SCENE_CONCURRENCY = max(1, min(int(os.environ.get("VIDEO_SCENE_CONCURRENCY", "6") or 6), 8))
BULK_VIDEO_CONCURRENCY = max(1, min(int(os.environ.get("BULK_VIDEO_CONCURRENCY", "5") or 5), 8))
# Shared cap on in-flight Gemini Omni interactions.create calls (Studio, scene
# regeneration, and bulk). This replaces workers × scenes as the Omni limit.
OMNI_MAX_IN_FLIGHT = max(1, min(int(os.environ.get("OMNI_MAX_IN_FLIGHT", "3") or 3), 8))
# Blocking interactions.create timeout. Healthy Omni creates in this project
# finished in about 56–181 seconds. 300 seconds cuts the old 10-minute hang
# without failing those successful requests.
OMNI_REQUEST_TIMEOUT_SECONDS = max(
    60, min(int(os.environ.get("OMNI_REQUEST_TIMEOUT_SECONDS", "300") or 300), 600)
)
OMNI_MAX_CONTINUOUS_DURATION_SECONDS = max(
    10, min(int(os.environ.get("OMNI_MAX_CONTINUOUS_DURATION_SECONDS", "40") or 40), 40)
)
VEO_MAX_IN_FLIGHT = max(1, min(int(os.environ.get("VEO_MAX_IN_FLIGHT", "3") or 3), 8))
VEO_OPERATION_TIMEOUT_SECONDS = max(
    60, min(int(os.environ.get("VEO_OPERATION_TIMEOUT_SECONDS", "900") or 900), 1800)
)
MINIMAX_MAX_IN_FLIGHT = max(1, min(int(os.environ.get("MINIMAX_MAX_IN_FLIGHT", "3") or 3), 8))
MINIMAX_OPERATION_TIMEOUT_SECONDS = max(
    60, min(int(os.environ.get("MINIMAX_OPERATION_TIMEOUT_SECONDS", "900") or 900), 1800)
)
# Default 3 matches individual ModelArk concurrency; enterprise accounts may raise to 10.
SEEDANCE_MAX_IN_FLIGHT = max(1, min(int(os.environ.get("SEEDANCE_MAX_IN_FLIGHT", "3") or 3), 8))
# Live 2.5 T2V on ap-southeast can exceed 15 minutes; default 1800 avoids premature TIMEOUT
# while the remote task is still running (measured ~27 min wall for a 4s clip).
SEEDANCE_OPERATION_TIMEOUT_SECONDS = max(
    60, min(int(os.environ.get("SEEDANCE_OPERATION_TIMEOUT_SECONDS", "1800") or 1800), 1800)
)
DURATION_TOLERANCE_SECONDS = float(os.environ.get("DURATION_TOLERANCE_SECONDS", "2.0") or 2.0)

_workers = max(1, min(int(os.environ.get("Q_CLUSTER_WORKERS", "6") or 6), 8))
Q_CLUSTER = {
    "name": "dckbrand",
    "workers": _workers,
    "timeout": 7200,
    "retry": 7260,
    "max_attempts": 2,
    "queue_limit": 50,
    "bulk": _workers,
    "orm": "default",
    "sync": AI_SYNC_TASKS,
}
