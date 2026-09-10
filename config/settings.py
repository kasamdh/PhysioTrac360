"""Settings for the Source Motion PT clinical workspace.

Source Motion PT is operated by Source Motion Physical Therapy.

The defaults are intentionally developer-friendly. Production must supply
environment variables, managed secrets, encrypted storage, and a PostgreSQL
database before it can be used with protected health information.
"""
from pathlib import Path
import os

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "django-insecure-development-only-change-before-deployment",
)
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() == "true"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

# Base URL of the React frontend, used to build links sent outside the app
# (client-admin invitations, etc.). Must be updated to the real domain before
# deployment — left at the Vite dev server address until then.
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173").rstrip("/")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "care",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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
        "DIRS": [BASE_DIR / "templates"],
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
ASGI_APPLICATION = "config.asgi.application"

if os.getenv("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.environ["POSTGRES_USER"],
            "PASSWORD": os.environ["POSTGRES_PASSWORD"],
            "HOST": os.getenv("POSTGRES_HOST", "127.0.0.1"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 60,
            "CONN_HEALTH_CHECKS": True,
        }
    }
else:
    # Local-only convenience database. Do not use SQLite for production PHI.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

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
TIME_ZONE = "America/New_York"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
FRONTEND_DIST_DIR = BASE_DIR / "frontend" / "dist"
STATICFILES_DIRS = [BASE_DIR / "static"]
if FRONTEND_DIST_DIR.exists():
    # Vite emits /static/react/assets/... URLs in production builds.
    STATICFILES_DIRS.append(("react", FRONTEND_DIST_DIR))
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Patient-uploaded documents are PHI and must never be reachable through the
# public MEDIA_URL static-serving route (config/urls.py only serves MEDIA_ROOT
# under DEBUG). They live in a separate root with no URL mapping at all and
# are only ever read by care.api.documents' authenticated, permission-checked
# download view.
PRIVATE_MEDIA_ROOT = BASE_DIR / "private_media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "care.User"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# Security headers and cookie policy. HTTPS is controlled by the deployment
# variable to keep local development usable.
SECURE_SSL_REDIRECT = os.getenv("DJANGO_SECURE_COOKIES", "False").lower() == "true"
SESSION_COOKIE_SECURE = SECURE_SSL_REDIRECT
CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_HSTS_SECONDS = 31_536_000 if SECURE_SSL_REDIRECT else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_SSL_REDIRECT
SECURE_HSTS_PRELOAD = SECURE_SSL_REDIRECT
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Login/session security policy. All values are configurable via environment
# variables rather than hard-coded, per the app's account-security design —
# defaults match the app's documented policy.
FAILED_LOGIN_LOCKOUT_THRESHOLD = int(os.getenv("FAILED_LOGIN_LOCKOUT_THRESHOLD", "5"))
LOCKOUT_DURATION_MINUTES = int(os.getenv("LOCKOUT_DURATION_MINUTES", "15"))
IDLE_WARNING_MINUTES = int(os.getenv("IDLE_WARNING_MINUTES", "13"))
IDLE_TIMEOUT_MINUTES = int(os.getenv("IDLE_TIMEOUT_MINUTES", "15"))
ABSOLUTE_SESSION_HOURS = int(os.getenv("ABSOLUTE_SESSION_HOURS", "12"))

# PT/PTA license expiration: escalating day-count thresholds the onboarding
# alert warns an admin at (90/60/30 = informational-to-high-priority, 14/7 =
# critical). Expiration itself (days remaining < 0), not any of these
# windows, is what auto-suspends the account.
LICENSE_WARNING_DAYS = [
    int(days) for days in os.getenv("LICENSE_WARNING_DAYS", "90,60,30,14,7").split(",") if days.strip()
]

# Plan-of-care expiration: escalating day-count thresholds a patient's active
# plan of care (the most recently documented plan_of_care_end date) warns at.
# Expiration itself (days remaining < 0) surfaces as a high-severity, blocking
# dashboard/workspace finding via services.patient_compliance_findings.
PLAN_OF_CARE_WARNING_DAYS = [
    int(days) for days in os.getenv("PLAN_OF_CARE_WARNING_DAYS", "30,14,7").split(",") if days.strip()
]

# Insurance authorization expiration: same day-count-threshold pattern as
# PLAN_OF_CARE_WARNING_DAYS, for Authorization.date_alert_tier. Separate from
# the visit-count thresholds (5/3/1 remaining), which are fixed in code —
# see Authorization.visit_alert_tier in care/models.py.
AUTHORIZATION_WARNING_DAYS = [
    int(days) for days in os.getenv("AUTHORIZATION_WARNING_DAYS", "30,14,7").split(",") if days.strip()
]

# Maximum concurrent active sessions per role. A role not listed here (e.g. a
# future role) is unlimited by omission rather than silently blocked.
SESSION_LIMITS_BY_ROLE = {
    "super_admin": int(os.getenv("SESSION_LIMIT_SUPER_ADMIN", "1")),
    "admin": int(os.getenv("SESSION_LIMIT_ADMIN", "1")),
    "biller": int(os.getenv("SESSION_LIMIT_BILLER", "1")),
    "scheduler": int(os.getenv("SESSION_LIMIT_FRONT_DESK", "1")),
    "therapist": int(os.getenv("SESSION_LIMIT_THERAPIST", "2")),
    "assistant": int(os.getenv("SESSION_LIMIT_ASSISTANT", "2")),
    "patient": int(os.getenv("SESSION_LIMIT_PATIENT", "3")),
}
DEFAULT_SESSION_LIMIT = int(os.getenv("SESSION_LIMIT_DEFAULT", "2"))

# A real AI connector is deliberately off until a HIPAA-eligible provider,
# business associate agreement, and data-use assessment are in place.
AI_DRAFTING_ENABLED = os.getenv("AI_DRAFTING_ENABLED", "False").lower() == "true"

# Outbound transactional email (client-admin invitations, etc.). Defaults to
# Django's console backend so email "sends" print to the server log with no
# external account required in development. Point EMAIL_BACKEND/EMAIL_HOST/...
# at a real HIPAA-eligible provider (SES, Postmark, SMTP relay with a BAA)
# before production use — these messages never carry PHI, only account setup
# links, but still need to go through a provider covered by the org's BAA.
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True").lower() == "true"
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "no-reply@physiotrac360.local")
