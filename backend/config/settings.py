"""Fail-closed settings. Production secrets come from mounted files."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def secret(name):
    file_path = os.environ.get(f"{name}_FILE")
    value = Path(file_path).read_text().strip() if file_path else os.environ.get(name, "")
    if not value:
        raise ImproperlyConfigured(f"Missing {name} or {name}_FILE")
    return value


def csv(name, default=""):
    return [value.strip() for value in os.environ.get(name, default).split(",") if value.strip()]


ENVIRONMENT = os.environ.get("APP_ENV", "production")
if ENVIRONMENT not in {"development", "production", "test"}:
    raise ImproperlyConfigured("Invalid APP_ENV")
DEBUG = ENVIRONMENT == "development"
SECRET_KEY = secret("DJANGO_SECRET_KEY")
if len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must have at least 50 characters")
ALLOWED_HOSTS = csv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
if "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Wildcard hosts are not allowed")
CSRF_TRUSTED_ORIGINS = csv("DJANGO_CSRF_TRUSTED_ORIGINS")
if ENVIRONMENT == "production" and (
    not CSRF_TRUSTED_ORIGINS or any(not x.startswith("https://") for x in CSRF_TRUSTED_ORIGINS)
):
    raise ImproperlyConfigured("Production requires explicit HTTPS CSRF origins")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "core",
    "tickets",
    "wiki",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "pulse"),
        "USER": os.environ.get("POSTGRES_USER", "pulse"),
        "PASSWORD": secret("POSTGRES_PASSWORD"),
        "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {"connect_timeout": 5},
    }
}
# Custom identity from the first migration avoids replacing auth.User later.
AUTH_USER_MODEL = "core.User"
IDENTITY_KEY = secret("IDENTITY_KEY")
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
IDENTITY_RATE_LIMIT = 10
# Cloudflare Turnstile: ativo somente quando as duas chaves estão configuradas.
TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "").strip()
_turnstile_file = os.environ.get("TURNSTILE_SECRET_KEY_FILE")
TURNSTILE_SECRET_KEY = (
    Path(_turnstile_file).read_text().strip()
    if _turnstile_file
    else os.environ.get("TURNSTILE_SECRET_KEY", "").strip()
)
TURNSTILE_ENABLED = bool(TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY)
if ENVIRONMENT == "production" and bool(TURNSTILE_SITE_KEY) != bool(TURNSTILE_SECRET_KEY):
    raise ImproperlyConfigured("Configure TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY together")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = secret("SMTP_PASSWORD") if os.environ.get("SMTP_PASSWORD_FILE") else ""
EMAIL_USE_TLS = True
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "")
SESSION_COOKIE_AGE = 8 * 60 * 60
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
REST_FRAMEWORK = {
    "EXCEPTION_HANDLER": "core.exceptions.api_exception_handler",
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": ["core.authentication.VerifiedSessionAuthentication"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}
SPECTACULAR_SETTINGS = {
    "TITLE": "Pulse Services API",
    "VERSION": "0.3.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SERVE_PERMISSIONS": ["core.authentication.IsIdentityAdmin"],
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "CommentVisibilityEnum": "tickets.models.Comment.Visibility",
        "UserRoleEnum": "core.models.User.Role",
    },
}
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = ENVIRONMENT == "production"
CSRF_COOKIE_SECURE = ENVIRONMENT == "production"
SECURE_SSL_REDIRECT = ENVIRONMENT == "production"
SECURE_REDIRECT_EXEMPT = [r"^api/v1/health/(live|ready)/$"]
SECURE_HSTS_SECONDS = 31536000 if ENVIRONMENT == "production" else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = ENVIRONMENT == "production"
SECURE_HSTS_PRELOAD = ENVIRONMENT == "production"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
# API has no published port. Gateway replaces this header, never passes client values.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Proxies in front of the API that append to X-Forwarded-For (gateway = 1, NPM + gateway = 2).
# 0 keeps REMOTE_ADDR, the safe default until the proxy chain is homologated.
TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", "0"))
if TRUSTED_PROXY_COUNT < 0:
    raise ImproperlyConfigured("TRUSTED_PROXY_COUNT must not be negative")
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}

ATTACHMENT_ROOT = os.environ.get("ATTACHMENT_ROOT", "/var/lib/pulse/attachments")
CLAMAV_HOST = os.environ.get("CLAMAV_HOST", "antimalware")
CLAMAV_PORT = int(os.environ.get("CLAMAV_PORT", "3310"))

SMTP_ALLOWED_HOSTS = csv("SMTP_ALLOWED_HOSTS")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8086")
