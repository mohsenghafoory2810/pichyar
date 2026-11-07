"""«ورود دومرحله‌ای»: each admin turns TOTP (Google Authenticator, Microsoft Authenticator, ...)
on or off for their own account."""

from base64 import b32encode

import qrcode
import qrcode.image.svg
from django.contrib import admin, messages
from django.db import transaction
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.safestring import mark_safe
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from core.persian import latin_digits

DEVICE_NAME = "برنامهٔ احراز هویت"


def _qr_svg(text):
    image = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    return mark_safe(image.to_string(encoding="unicode"))


def _token(request):
    return latin_digits(request.POST.get("token", "")).replace(" ", "").strip()


def two_factor_view(request):
    user = request.user
    confirmed = TOTPDevice.objects.filter(user=user, confirmed=True).first()
    error = None

    if request.method == "POST" and request.POST.get("action") == "disable" and confirmed:
        if confirmed.verify_token(_token(request)):
            TOTPDevice.objects.filter(user=user).delete()
            messages.success(request, "ورود دومرحله‌ای خاموش شد. از این پس فقط با رمز وارد می‌شوید.")
            return redirect("admin:two_factor")
        error = "کد درست نیست. برای خاموش کردن، کد فعلی برنامه را وارد کنید."

    pending = None
    if not confirmed:
        pending = TOTPDevice.objects.filter(user=user, confirmed=False).first()
        if pending is None or request.GET.get("new"):
            with transaction.atomic():
                TOTPDevice.objects.filter(user=user, confirmed=False).delete()
                pending = TOTPDevice.objects.create(user=user, name=DEVICE_NAME, confirmed=False)
        if request.method == "POST" and request.POST.get("action") == "enable":
            if pending.verify_token(_token(request)):
                pending.confirmed = True
                pending.save(update_fields=["confirmed"])
                otp_login(request, pending)  # the current session stays usable: verified with this device
                messages.success(request, "ورود دومرحله‌ای روشن شد. از این پس هنگام ورود، کد برنامه را هم وارد کنید.")
                return redirect("admin:two_factor")
            error = "کد درست نیست. ساعت گوشی را بررسی کنید و کد تازه را وارد کنید."

    context = {
        **admin.site.each_context(request),
        "title": "ورود دومرحله‌ای",
        "confirmed": confirmed,
        "error": error,
    }
    if pending is not None:
        context.update({"qr_svg": _qr_svg(pending.config_url), "secret": _b32(pending.bin_key)})
    return TemplateResponse(request, "admin/two_factor.html", context)


def _b32(raw):
    text = b32encode(raw).decode().rstrip("=")
    return " ".join(text[i : i + 4] for i in range(0, len(text), 4))
