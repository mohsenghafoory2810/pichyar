from django import forms
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm

from core.persian import latin_digits

from .models import Address, User
from .otp import CODE_LENGTH
from .validators import MobileField, PostalCodeField


class MobileForm(forms.Form):
    mobile = MobileField()


class CodeForm(forms.Form):
    code = forms.CharField(
        label="کد تأیید",
        max_length=10,
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
                "dir": "ltr",
                "class": "input text-center tracking-[0.5em]",
                "autofocus": True,
            }
        ),
    )

    def clean_code(self):
        code = latin_digits(self.cleaned_data["code"]).strip()
        if not (code.isdigit() and len(code) == CODE_LENGTH):
            raise forms.ValidationError("کد ۵ رقمی پیامک‌شده را وارد کنید.")
        return code


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("name",)
        widgets = {"name": forms.TextInput(attrs={"class": "input", "autocomplete": "name"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].required = True


class AddressForm(forms.ModelForm):
    recipient_mobile = MobileField(label="موبایل گیرنده")
    postal_code = PostalCodeField()

    class Meta:
        model = Address
        fields = ("recipient_name", "recipient_mobile", "province", "city", "address", "postal_code")
        widgets = {
            "recipient_name": forms.TextInput(attrs={"class": "input", "autocomplete": "name"}),
            "province": forms.Select(attrs={"class": "input"}),
            "city": forms.TextInput(attrs={"class": "input"}),
            "address": forms.Textarea(attrs={"class": "input", "rows": 3}),
        }


# --- admin -------------------------------------------------------------------


class UserAdminCreationForm(AdminUserCreationForm):
    mobile = MobileField()

    class Meta(AdminUserCreationForm.Meta):
        model = User
        fields = ("mobile", "name")
        field_classes = {}


class UserAdminChangeForm(UserChangeForm):
    mobile = MobileField()

    class Meta(UserChangeForm.Meta):
        model = User
        field_classes = {}
