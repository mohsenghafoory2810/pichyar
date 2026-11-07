from decimal import Decimal, InvalidOperation

from django import forms

from core.persian import THOUSANDS_SEPARATOR, latin_digits

from . import pricing
from .models import Category


class BulkPriceForm(forms.Form):
    ids = forms.CharField(widget=forms.HiddenInput, required=False)
    category = forms.ModelChoiceField(
        Category.objects.all(),
        label="دسته‌بندی",
        required=False,
        help_text="همهٔ محصولات این دسته (و زیردسته‌هایش) تغییر می‌کنند.",
    )
    direction = forms.ChoiceField(
        label="جهت تغییر",
        choices=[(pricing.INCREASE, "افزایش"), (pricing.DECREASE, "کاهش")],
        widget=forms.RadioSelect,
        initial=pricing.INCREASE,
    )
    mode = forms.ChoiceField(
        label="نوع تغییر",
        choices=[(pricing.PERCENT, "درصدی"), (pricing.FIXED, "مبلغ ثابت (تومان)")],
        widget=forms.RadioSelect,
        initial=pricing.PERCENT,
    )
    amount = forms.CharField(label="مقدار", help_text="مثلاً ۱۰ برای ۱۰٪ یا ۵۰۰۰۰ برای ۵۰٬۰۰۰ تومان")
    rounding = forms.TypedChoiceField(
        label="گرد کردن قیمت جدید", choices=pricing.ROUNDING_CHOICES, coerce=int, initial=1000
    )

    def clean_ids(self):
        raw = latin_digits(self.cleaned_data.get("ids") or "")
        try:
            return [int(x) for x in raw.split(",") if x.strip()]
        except ValueError:
            raise forms.ValidationError("فهرست محصولات نامعتبر است.")

    def clean_amount(self):
        raw = latin_digits(self.cleaned_data["amount"]).replace(",", "").replace(THOUSANDS_SEPARATOR, "").strip()
        try:
            value = Decimal(raw)
        except InvalidOperation:
            raise forms.ValidationError("یک عدد وارد کنید.")
        if value <= 0:
            raise forms.ValidationError("مقدار باید بزرگ‌تر از صفر باشد.")
        return value

    def clean(self):
        data = super().clean()
        if not data.get("ids") and not data.get("category"):
            raise forms.ValidationError("یک دسته‌بندی انتخاب کنید یا از فهرست محصولات، محصولاتی را برگزینید.")
        if data.get("mode") == pricing.PERCENT and data.get("direction") == pricing.DECREASE and data.get("amount", 0) >= 100:
            self.add_error("amount", "کاهش درصدی باید کمتر از ۱۰۰ باشد.")
        return data
