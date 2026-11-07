"""SMS one-time codes.

    send_code(mobile, purpose, ip)      creates a code and sends it; raises OTPError
    verify_code(mobile, purpose, code)  raises OTPError unless the code is right

Rules (settings.OTP_*): 5 digits, valid for 2 minutes, 5 wrong tries per code,
60 seconds between two codes for the same mobile, and at most N codes per hour
per mobile and per IP. Codes are stored as an HMAC (keyed with SECRET_KEY), never
in plain text. Only the newest code of a mobile+purpose is valid.
"""

import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from core.persian import fa_digits, latin_digits
from notifications.services import send_sms

from .models import OTPCode

CODE_LENGTH = 5


def _conf(name, default):
    return getattr(settings, name, default)


def ttl_seconds():
    return _conf("OTP_TTL_SECONDS", 120)


def max_attempts():
    return _conf("OTP_MAX_ATTEMPTS", 5)


def resend_cooldown():
    return _conf("OTP_RESEND_COOLDOWN", 60)


class OTPError(Exception):
    def __init__(self, message, code, retry_after=None):
        self.message = message
        self.code = code
        self.retry_after = retry_after
        super().__init__(message)


def hash_code(mobile, purpose, code):
    return salted_hmac("accounts.otp", f"{purpose}:{mobile}:{code}", algorithm="sha256").hexdigest()


def generate_code():
    return f"{secrets.randbelow(10**CODE_LENGTH):0{CODE_LENGTH}d}"


def seconds_until_resend(mobile, now=None):
    now = now or timezone.now()
    last = OTPCode.objects.filter(mobile=mobile).order_by("-created_at").values_list("created_at", flat=True).first()
    if last is None:
        return 0
    return max(0, int(resend_cooldown() - (now - last).total_seconds() + 0.999))


def send_code(mobile, purpose, ip=None):
    """Create and send a new code (the previous one of the same purpose stops working)."""
    now = timezone.now()
    code = generate_code()
    with transaction.atomic():  # BEGIN IMMEDIATE on SQLite: the checks and the insert can't interleave
        wait = seconds_until_resend(mobile, now)
        if wait:
            raise OTPError(f"برای دریافت دوبارهٔ کد {fa_digits(wait)} ثانیه صبر کنید.", "cooldown", retry_after=wait)
        hour_ago = now - timedelta(hours=1)
        if OTPCode.objects.filter(mobile=mobile, created_at__gte=hour_ago).count() >= _conf("OTP_MAX_PER_MOBILE_PER_HOUR", 5):
            raise OTPError("برای این شماره کد زیادی درخواست شده است. لطفاً یک ساعت دیگر دوباره تلاش کنید.", "rate_mobile")
        if ip and OTPCode.objects.filter(ip=ip, created_at__gte=hour_ago).count() >= _conf("OTP_MAX_PER_IP_PER_HOUR", 15):
            raise OTPError("تعداد درخواست‌ها زیاد است. لطفاً کمی بعد دوباره تلاش کنید.", "rate_ip")
        OTPCode.objects.filter(mobile=mobile, purpose=purpose, consumed_at__isnull=True).update(consumed_at=now)
        otp = OTPCode.objects.create(
            mobile=mobile,
            purpose=purpose,
            code_hash=hash_code(mobile, purpose, code),
            ip=ip,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds()),
        )
    send_sms(mobile, "otp", {"code": code})
    return otp


def verify_code(mobile, purpose, code):
    """Consume the newest code of this mobile+purpose if `code` matches it; otherwise raise OTPError."""
    code = latin_digits(code or "").strip()
    now = timezone.now()
    error = None
    with transaction.atomic():
        otp = (
            OTPCode.objects.select_for_update()
            .filter(mobile=mobile, purpose=purpose, consumed_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
        if otp is None:
            error = OTPError("ابتدا کد تأیید را دریافت کنید.", "missing")
        elif otp.expires_at <= now:
            error = OTPError("کد تأیید منقضی شده است. کد جدید بگیرید.", "expired")
        elif otp.attempts >= max_attempts():
            error = OTPError("تعداد تلاش‌های نادرست زیاد بود. کد جدید بگیرید.", "too_many_attempts")
        elif not constant_time_compare(otp.code_hash, hash_code(mobile, purpose, code)):
            OTPCode.objects.filter(pk=otp.pk).update(attempts=F("attempts") + 1)
            left = max_attempts() - otp.attempts - 1
            if left > 0:
                error = OTPError(f"کد وارد شده درست نیست. {fa_digits(left)} بار دیگر می‌توانید تلاش کنید.", "wrong")
            else:
                error = OTPError("کد وارد شده درست نیست. کد جدید بگیرید.", "too_many_attempts")
        else:
            OTPCode.objects.filter(pk=otp.pk).update(consumed_at=now)
    # Raised after the transaction so the attempt counter is committed.
    if error:
        raise error
