import logging

from .base import *  # noqa: F401,F403
from .base import DATA_DIR, env

DEBUG = False
SECRET_KEY = "test-secret-key"
ALLOWED_HOSTS = ["testserver", "localhost"]
# A file (not :memory:) so the stock concurrency tests can use several real connections.
# TEST_DB_NAME lets several test runs work side by side.
_TEST_DB = DATA_DIR / "db" / env("TEST_DB_NAME", default="test.sqlite3")
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": _TEST_DB,
        "OPTIONS": {"transaction_mode": "IMMEDIATE", "timeout": 20},
        "TEST": {"NAME": _TEST_DB},
    }
}
MEDIA_ROOT = DATA_DIR / "media-test"
PRIVATE_MEDIA_ROOT = DATA_DIR / "private-test"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
STATIC_ROOT = DATA_DIR / "staticfiles-test"
STATIC_ROOT.mkdir(parents=True, exist_ok=True)

logging.disable(logging.CRITICAL)
