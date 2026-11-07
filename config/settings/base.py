"""Settings shared by every environment. Values come from the environment / .env."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
if (BASE_DIR / ".env").exists():
    environ.Env.read_env(BASE_DIR / ".env")

# All writable data (database, media, backups, logs) lives under DATA_DIR.
DATA_DIR = Path(env("DATA_DIR", default=str(BASE_DIR / "var")))
LOG_DIR = DATA_DIR / "logs"
BACKUP_DIR = Path(env("BACKUP_DIR", default=str(DATA_DIR / "backups")))
PRIVATE_MEDIA_ROOT = DATA_DIR / "private"  # card-to-card receipts; never served publicly
for _d in (DATA_DIR / "db", DATA_DIR / "media", PRIVATE_MEDIA_ROOT, LOG_DIR, BACKUP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

SECRET_KEY = env("SECRET_KEY", default=None)
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

# Admin lives at a secret-ish path instead of /admin/.
ADMIN_URL = env("ADMIN_URL", default="manage/").strip("/") + "/"

INSTALLED_APPS = [
    "core.admin_config.ShopAdminConfig",  # django.contrib.admin with our AdminSite (core.admin_site)
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    "jalali_date",
    "tinymce",
    "django_q",
    "import_export",
    "axes",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "core",
    "accounts",
    "catalog",
    "cart",
    "orders",
    "payments",
    "notifications",
    "seo",
    "blog",
    "reviews",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "seo.middleware.RedirectMiddleware",  # 404 → seo.Redirect (301)
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "catalog.audit.ActingUserMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.MaintenanceModeMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
    "axes.middleware.AxesMiddleware",  # last, as django-axes requires
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

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
                "core.context_processors.site",
                "cart.context_processors.cart",
            ],
            # Persian filters (fa_digits, toman, jdate, ...) available in every template.
            "builtins": ["core.templatetags.persian", "django.templatetags.static"],
        },
    },
]

# --- Database -------------------------------------------------------------
# SQLite by default. Set DATABASE_URL (e.g. postgres://user:pass@host/db) to switch.
if env("DATABASE_URL", default=""):
    DATABASES = {"default": env.db("DATABASE_URL")}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": DATA_DIR / "db" / "db.sqlite3",
        }
    }
if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    # IMMEDIATE avoids "database is locked" on write upgrades; WAL/busy_timeout are
    # set per-connection in core.signals.
    DATABASES["default"].setdefault("OPTIONS", {}).update(
        {"transaction_mode": "IMMEDIATE", "timeout": 20}
    )
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"
# Axes must come first: it blocks locked-out admin logins before the password is checked.
# Customers sign in with an SMS code through accounts.backends.SMSCodeBackend, which the
# admin site does not accept (core.admin_site): the admin always needs the password.
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
    "accounts.backends.SMSCodeBackend",
]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:orders"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Locale ---------------------------------------------------------------
LANGUAGE_CODE = "fa"
LANGUAGES = [("fa", "فارسی")]
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True

# --- Static & media -------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = DATA_DIR / "media"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
FILE_UPLOAD_PERMISSIONS = 0o644

# --- Site behaviour -------------------------------------------------------
AGE_GATE_COOKIE = "age_ok"
AGE_GATE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
AGE_GATE_EXIT_URL = env("AGE_GATE_EXIT_URL", default="https://www.google.com/")
BACKUP_KEEP = env.int("BACKUP_KEEP", default=14)
PRODUCT_IMAGE_MAX_MB = env.int("PRODUCT_IMAGE_MAX_MB", default=5)
RECEIPT_MAX_MB = env.int("RECEIPT_MAX_MB", default=5)
# Behind Caddy the visitor IP comes from X-Forwarded-For (turned on in prod.py).
USE_X_FORWARDED_FOR = env.bool("USE_X_FORWARDED_FOR", default=False)

# --- SMS codes (accounts.otp) and payments ------------------------------------
OTP_TTL_SECONDS = 120
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN = 60
OTP_MAX_PER_MOBILE_PER_HOUR = env.int("OTP_MAX_PER_MOBILE_PER_HOUR", default=5)
OTP_MAX_PER_IP_PER_HOUR = env.int("OTP_MAX_PER_IP_PER_HOUR", default=15)
PAYMENT_GATEWAY_TIMEOUT = 15  # seconds
SMS_PROVIDER_TIMEOUT = 10  # seconds

# --- Admin login protection -------------------------------------------------
# django-axes: after AXES_FAILURE_LIMIT wrong passwords (or 2FA codes) from one IP the
# admin login is blocked for AXES_COOLOFF_HOURS. Unlock early: «امنیت ← قفل‌های ورود» or
# `python manage.py axes_reset`.
AXES_FAILURE_LIMIT = env.int("AXES_FAILURE_LIMIT", default=5)
AXES_COOLOFF_TIME = env.float("AXES_COOLOFF_HOURS", default=1.0)  # hours
AXES_LOCKOUT_PARAMETERS = ["ip_address"]
AXES_USERNAME_FORM_FIELD = "username"  # the admin login form's field (holds the mobile)
AXES_CLIENT_IP_CALLABLE = "core.utils.client_ip"
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "admin/locked_out.html"
AXES_ENABLE_ADMIN = False  # replaced by a Persian admin in accounts.admin
# django-otp: optional TOTP (Google Authenticator, ...) per admin account.
OTP_TOTP_ISSUER = env("OTP_TOTP_ISSUER", default="Pichyar")

# --- Content-Security-Policy (core.middleware.SecurityHeadersMiddleware) ------
# Everything is self-hosted; inline styles/scripts are still used by the Django admin
# and TinyMCE, hence 'unsafe-inline'.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline'; font-src 'self' data:; connect-src 'self'; "
    "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
)
PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=()"
# Bigger request bodies than this are refused (images are limited separately).
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# --- Excel import/export of products (django-import-export) -----------------
IMPORT_EXPORT_USE_TRANSACTIONS = True  # the preview (dry run) is rolled back
IMPORT_EXPORT_IMPORT_PERMISSION_CODE = "change"
IMPORT_EXPORT_EXPORT_PERMISSION_CODE = "view"

# --- Background worker (django-q2, database broker) ------------------------
Q_CLUSTER = {
    "name": "pichyar",
    "orm": "default",
    "workers": 1,
    "timeout": 300,
    "retry": 600,
    "max_attempts": 1,
    "poll": 5,
    "catch_up": False,
    "save_limit": 200,
    "label": "صف کارها",
}

# --- Admin widgets --------------------------------------------------------
JALALI_DATE_DEFAULTS = {
    "LIST_DISPLAY_AUTO_CONVERT": True,
    "Strftime": {"date": "%Y/%m/%d", "datetime": "%Y/%m/%d - %H:%M"},
}
TINYMCE_DEFAULT_CONFIG = {
    "height": 420,
    "menubar": False,
    "directionality": "rtl",
    "plugins": "link lists autoresize",
    "toolbar": "undo redo | blocks | bold italic | bullist numlist | link | removeformat",
    "content_style": "body { font-family: Tahoma, sans-serif; direction: rtl; }",
}

# --- Logging --------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
        "error_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "errors.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
            "level": "ERROR",
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console", "error_file"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console", "error_file"], "level": "INFO", "propagate": False},
        # SMS texts are printed here in console mode (no SMS API key yet), login codes included.
        "notifications": {"handlers": ["console"], "level": "INFO", "propagate": False},
        # Lockouts are WARNING; the per-request INFO lines are noise.
        "axes": {"handlers": ["console", "error_file"], "level": "WARNING", "propagate": False},
    },
}
