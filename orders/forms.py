from django import forms

from accounts.iran import PROVINCE_CHOICES
from accounts.validators import MobileField, PostalCodeField
from core.persian import fa_digits, latin_digits

from .models import PaymentMethod

PAYMENT_METHOD_LABELS = {
    PaymentMethod.ONLINE: "پرداخت اینترنتی (همهٔ کارت‌های عضو شتاب)",
    PaymentMethod.CARD: "کارت به کارت",
}
AGE_LABEL = "تأیید می‌کنم که بالای ۱۸ سال سن دارم."


class CheckoutForm(forms.Form):
    recipient_name = forms.CharField(
        label="نام و نام خانوادگی گیرنده",
        max_length=100,
        widget=forms.TextInput(attrs={"class": "input", "autocomplete": "name"}),
    )
    recipient_mobile = MobileField(label="موبایل گیرنده")
    province = forms.ChoiceField(
        label="استان", choices=[("", "انتخاب استان")] + PROVINCE_CHOICES, widget=forms.Select(attrs={"class": "input"})
    )
    city = forms.CharField(label="شهر", max_length=60, widget=forms.TextInput(attrs={"class": "input"}))
    address = forms.CharField(
        label="نشانی کامل",
        max_length=400,
        widget=forms.Textarea(attrs={"class": "input", "rows": 3, "placeholder": "خیابان، کوچه، پلاک، واحد"}),
    )
    postal_code = PostalCodeField()
    note = forms.CharField(
        label="توضیحات (اختیاری)",
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={"class": "input", "rows": 2}),
    )
    save_address = forms.BooleanField(label="این نشانی در حساب من ذخیره شود", required=False)
    payment_method = forms.ChoiceField(label="روش پرداخت", widget=forms.RadioSelect)
    age_confirmed = forms.BooleanField(
        label=AGE_LABEL,
        error_messages={"required": "برای ثبت سفارش باید تأیید کنید که بالای ۱۸ سال سن دارید."},
    )
    expected_total = forms.IntegerField(widget=forms.HiddenInput, required=False)

    ADDRESS_FIELDS = ("recipient_name", "recipient_mobile", "province", "city", "address", "postal_code")

    def __init__(self, *args, methods, is_guest, gift_slots=0, gift_options=(), **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("", "انتخاب هدیه")] + [(o.pk, o.product.name) for o in gift_options]
        for i in range(1, gift_slots + 1):
            self.fields[f"gift_{i}"] = forms.TypedChoiceField(
                label=f"هدیهٔ {fa_digits(i)}",
                coerce=int,
                choices=choices,
                widget=forms.Select(attrs={"class": "input"}),
                error_messages={
                    "required": f"هدیهٔ {fa_digits(i)} را انتخاب کنید.",
                    "invalid_choice": "هدیهٔ انتخاب‌شده دیگر موجود نیست؛ هدیهٔ دیگری انتخاب کنید.",
                },
            )
        self.gift_slots = gift_slots
        self.fields["payment_method"].choices = [(m, PAYMENT_METHOD_LABELS[m]) for m in methods]
        if len(methods) == 1:
            self.fields["payment_method"].initial = methods[0]
        if is_guest:  # a guest's recipient mobile is the OTP-verified one
            del self.fields["recipient_mobile"]
            del self.fields["save_address"]

    def address_fields(self):
        return [self[name] for name in self.ADDRESS_FIELDS if name in self.fields]

    def gift_fields(self):
        return [self[f"gift_{i}"] for i in range(1, self.gift_slots + 1)]

    def gift_selection(self):
        """{product_id: quantity} of the chosen gifts (after is_valid())."""
        selection = {}
        for i in range(1, self.gift_slots + 1):
            pk = self.cleaned_data.get(f"gift_{i}")
            if pk:
                selection[pk] = selection.get(pk, 0) + 1
        return selection


class TrackForm(forms.Form):
    mobile = MobileField(label="شمارهٔ موبایل ثبت سفارش")
    number = forms.CharField(
        label="شمارهٔ سفارش",
        max_length=20,
        widget=forms.TextInput(attrs={"class": "input", "dir": "ltr", "inputmode": "numeric"}),
    )

    def clean_number(self):
        return latin_digits(self.cleaned_data["number"]).strip()
