"""Iranian mobile numbers and postal codes. Persian/Arabic digits are accepted everywhere."""

import re

from django import forms
from django.core.exceptions import ValidationError

from core.persian import latin_digits

MOBILE_RE = re.compile(r"^09\d{9}$")
POSTAL_CODE_RE = re.compile(r"^\d{10}$")
_SEPARATORS = re.compile(r"[\s\-()‌]")

MOBILE_ERROR = "شمارهٔ موبایل معتبر نیست؛ مثلاً ۰۹۱۲۳۴۵۶۷۸۹"
POSTAL_CODE_ERROR = "کد پستی باید ۱۰ رقم باشد."


def normalize_mobile(value) -> str:
    """'۰۹۱۲ ۳۴۵ ۶۷۸۹', '+989123456789', '00989123456789', '9123456789' -> '09123456789'.
    Raises ValidationError if it is not an Iranian mobile number."""
    digits = _SEPARATORS.sub("", latin_digits(value or "").strip())
    if digits.startswith("+98"):
        digits = "0" + digits[3:]
    elif digits.startswith("0098"):
        digits = "0" + digits[4:]
    elif digits.startswith("98") and len(digits) == 12:
        digits = "0" + digits[2:]
    elif digits.startswith("9") and len(digits) == 10:
        digits = "0" + digits
    if not MOBILE_RE.match(digits):
        raise ValidationError(MOBILE_ERROR, code="invalid_mobile")
    return digits


def normalize_postal_code(value) -> str:
    digits = _SEPARATORS.sub("", latin_digits(value or "").strip())
    if not POSTAL_CODE_RE.match(digits):
        raise ValidationError(POSTAL_CODE_ERROR, code="invalid_postal_code")
    return digits


def validate_mobile(value):
    """Model-level check of an already normalised number."""
    if not MOBILE_RE.match(value or ""):
        raise ValidationError(MOBILE_ERROR, code="invalid_mobile")


def validate_postal_code(value):
    if not POSTAL_CODE_RE.match(value or ""):
        raise ValidationError(POSTAL_CODE_ERROR, code="invalid_postal_code")


class MobileField(forms.CharField):
    def __init__(self, **kwargs):
        kwargs.setdefault("label", "شمارهٔ موبایل")
        kwargs.setdefault("max_length", 20)
        super().__init__(**kwargs)
        self.widget.attrs.update(
            {"inputmode": "tel", "autocomplete": "tel", "dir": "ltr", "placeholder": "۰۹۱۲۳۴۵۶۷۸۹", "class": "input"}
        )

    def clean(self, value):
        value = super().clean(value)
        return normalize_mobile(value) if value else value


class PostalCodeField(forms.CharField):
    def __init__(self, **kwargs):
        kwargs.setdefault("label", "کد پستی")
        kwargs.setdefault("max_length", 20)
        super().__init__(**kwargs)
        self.widget.attrs.update({"inputmode": "numeric", "dir": "ltr", "autocomplete": "postal-code", "class": "input"})

    def clean(self, value):
        value = super().clean(value)
        return normalize_postal_code(value) if value else value
