"""Storefront password login (when SiteSettings.password_login_enabled is on).

    check_password_login(mobile, password, ip)  returns the user; raises LoginError

A password exists only after an SMS-code login (accounts.views.password_view), so the
first sign-in of every number is always by SMS code. Errors never tell whether the number
has an account or a password. Wrong passwords are stored (PasswordLoginFailure, in the
database so all workers see them): settings.PASSWORD_LOGIN_* of them lock the password
login of that mobile for a while and of that IP for an hour. The SMS-code login stays open,
so a locked-out customer (or a stranger trying to lock someone out) never blocks a sign-in.
This is separate from django-axes, so customers' typos never lock the admin login.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.persian import fa_digits

from .models import PasswordLoginFailure, User

INVALID_MESSAGE = (
    "شمارهٔ موبایل یا رمز عبور درست نیست. اگر هنوز رمز عبور نساخته‌اید یا آن را فراموش کرده‌اید، با کد پیامکی وارد شوید."
)


class LoginError(Exception):
    def __init__(self, message, code):
        self.message = message
        self.code = code
        super().__init__(message)


def _conf(name, default):
    return getattr(settings, name, default)


def lock_minutes():
    return _conf("PASSWORD_LOGIN_LOCK_MINUTES", 15)


def is_locked(mobile, ip, now=None):
    now = now or timezone.now()
    since = now - timedelta(minutes=lock_minutes())
    if PasswordLoginFailure.objects.filter(mobile=mobile, created_at__gte=since).count() >= _conf(
        "PASSWORD_LOGIN_MAX_FAILS_PER_MOBILE", 5
    ):
        return True
    hour_ago = now - timedelta(hours=1)
    return bool(ip) and PasswordLoginFailure.objects.filter(ip=ip, created_at__gte=hour_ago).count() >= _conf(
        "PASSWORD_LOGIN_MAX_FAILS_PER_IP_PER_HOUR", 20
    )


def check_password_login(mobile, password, ip=None):
    """The active user with this mobile and password; otherwise LoginError
    ("locked", "invalid" or "inactive")."""
    now = timezone.now()
    if is_locked(mobile, ip, now):
        raise LoginError(
            f"به دلیل چند رمز اشتباه، ورود با رمز تا {fa_digits(lock_minutes())} دقیقه بسته شد. "
            "می‌توانید همین حالا با کد پیامکی وارد شوید.",
            "locked",
        )
    user = User.objects.filter(mobile=mobile).first()
    if user is None:
        User().set_password(password)  # same hashing time as a real check: no account enumeration
        ok = False
    else:
        # False for an unusable password (never set). A number never confirmed by an SMS code
        # (e.g. a password typed in by an admin) can't use it: the first sign-in is by SMS code.
        ok = user.check_password(password) and user.mobile_verified_at is not None
    if not ok:
        with transaction.atomic():
            PasswordLoginFailure.objects.create(mobile=mobile, ip=ip, created_at=now)
            # Old rows are no longer needed for any lock window.
            PasswordLoginFailure.objects.filter(created_at__lt=now - timedelta(days=1)).delete()
        raise LoginError(INVALID_MESSAGE, "invalid")
    if not user.is_active:
        raise LoginError("این حساب غیرفعال شده است. با پشتیبانی تماس بگیرید.", "inactive")
    PasswordLoginFailure.objects.filter(mobile=mobile).delete()
    return user
