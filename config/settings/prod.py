from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import ADMIN_URL, SECRET_KEY, env

DEBUG = False
if not SECRET_KEY:
    raise ImproperlyConfigured("SECRET_KEY must be set in .env")
if len(SECRET_KEY) < 50 and SECRET_KEY != "build-only":
    raise ImproperlyConfigured("SECRET_KEY is too short: use `openssl rand -hex 32`")
if ADMIN_URL.strip("/").lower() in ("admin", "panel-change-me", ""):
    raise ImproperlyConfigured("Set ADMIN_URL in .env to a hard-to-guess path (not admin/ or panel-change-me/)")

DOMAIN = env("DOMAIN", default="")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[DOMAIN] if DOMAIN else [])
# Container healthchecks call the app directly.
ALLOWED_HOSTS += ["localhost", "127.0.0.1"]
CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if h not in ("localhost", "127.0.0.1")]

# Caddy terminates TLS and forwards the original scheme.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_FOR = env.bool("USE_X_FORWARDED_FOR", default=True)
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r"^health$"]
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30)
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# HSTS for subdomains/preload is hard to undo; opt in deliberately by editing these.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]
