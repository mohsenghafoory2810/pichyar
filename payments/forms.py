import re

from django import forms
from django.conf import settings

from catalog.images import validate_image_file
from core.persian import latin_digits

TRACKING_RE = re.compile(r"^[0-9A-Za-z\-]{4,50}$")


class CardTransferForm(forms.Form):
    tracking_number = forms.CharField(
        label="کد پیگیری یا شمارهٔ ارجاع تراکنش",
        max_length=60,
        widget=forms.TextInput(attrs={"class": "input", "dir": "ltr", "inputmode": "numeric", "autocomplete": "off"}),
    )
    receipt = forms.ImageField(
        label="تصویر رسید (اختیاری)",
        required=False,
        help_text="JPG، PNG یا WebP",
        widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp", "class": "input"}),
    )

    def clean_tracking_number(self):
        value = latin_digits(self.cleaned_data["tracking_number"]).replace(" ", "").strip()
        if not TRACKING_RE.match(value):
            raise forms.ValidationError("کد پیگیری معتبر نیست (فقط عدد و حروف انگلیسی، دست‌کم ۴ نویسه).")
        return value

    def clean_receipt(self):
        receipt = self.cleaned_data.get("receipt")
        if receipt:
            validate_image_file(receipt, settings.RECEIPT_MAX_MB * 1024 * 1024)
        return receipt
