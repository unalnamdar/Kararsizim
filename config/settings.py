"""Django settings for the Kararsızım project."""

import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


DEBUG = env_bool("DEBUG", default=False)

SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "django-insecure-local-development-only-key"
    else:
        raise ImproperlyConfigured("SECRET_KEY ortam değişkeni tanımlı olmalı (DEBUG=False).")

ALLOWED_HOSTS = [".vercel.app", "localhost", "127.0.0.1"]
CSRF_TRUSTED_ORIGINS = ["https://*.vercel.app"]


# Applications

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "accounts",
    "polls",
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

CSRF_FAILURE_VIEW = "config.views.csrf_failure"

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


# Database
# DATABASE_URL yoksa yerelde SQLite kullanılır. Supabase için Vercel'de
# transaction pooler (6543) kullanılır; bu mod prepared statement desteklemez.

# Boş bir "DATABASE_URL=" satırı da SQLite'a düşmeli; bu yüzden config() yerine parse().
_database_url = os.environ.get("DATABASE_URL", "").strip()
DATABASES = {
    "default": dj_database_url.parse(
        _database_url or "sqlite:///" + str(BASE_DIR / "db.sqlite3"),
        conn_max_age=0,
        ssl_require=_database_url.startswith(("postgres://", "postgresql://")) and not DEBUG,
    )
}
if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    # Take the write lock when a transaction starts, so "count, then save" blocks (e.g. the per-network vote
    # cap) run one after another locally the way row locks make them on PostgreSQL.
    DATABASES["default"].setdefault("OPTIONS", {})["transaction_mode"] = "IMMEDIATE"
if DATABASES["default"]["ENGINE"].endswith("postgresql"):
    DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
    DATABASES["default"].setdefault("OPTIONS", {})["prepare_threshold"] = None


# Authentication

AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "polls:feed"
LOGOUT_REDIRECT_URL = "polls:feed"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Email (used for password reset only).
# Production needs EMAIL_HOST (+ credentials) as environment variables; without EMAIL_HOST the password
# reset feature is switched off: its pages answer 404 and the login page shows no link, so nothing is
# promised that cannot be delivered. Locally (DEBUG) emails are printed to the terminal instead.

EMAIL_HOST = os.environ.get("EMAIL_HOST", "").strip()
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587") or 587)
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "").strip()
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_SSL = EMAIL_PORT == 465
EMAIL_USE_TLS = not EMAIL_USE_SSL  # STARTTLS (port 587); 465 uses implicit TLS instead
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "").strip() or (
    f"Kararsızım <{EMAIL_HOST_USER}>" if "@" in EMAIL_HOST_USER else "Kararsızım <noreply@localhost>"
)

if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
elif DEBUG:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"  # never reached: the feature is off

PASSWORD_RESET_ENABLED = bool(EMAIL_HOST) or DEBUG
PASSWORD_RESET_TIMEOUT = 60 * 60  # reset links stay valid for one hour (Django's default is three days)


# Internationalization

LANGUAGE_CODE = "tr"
TIME_ZONE = "Europe/Istanbul"
USE_I18N = True
USE_TZ = True


# Static files (Vercel runs collectstatic during build and serves STATIC_ROOT)

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Logging: Django's default setup only prints to the console when DEBUG is on, so on Vercel
# tracebacks of failed requests would never reach the function logs without this.

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {"django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False}},
}


# Production security

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
