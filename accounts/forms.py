from django import forms
from django.contrib.auth import password_validation
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
                "data-otp-length": CODE_LENGTH,  # app.js: read from the SMS and submit when complete
            }
        ),
    )

    def clean_code(self):
        code = latin_digits(self.cleaned_data["code"]).strip()
        if not (code.isdigit() and len(code) == CODE_LENGTH):
            raise forms.ValidationError("کد ۶ رقمی پیامک‌شده را وارد کنید.")
        return code


def _password_input(autocomplete, **attrs):
    return forms.PasswordInput(attrs={"autocomplete": autocomplete, "dir": "ltr", "class": "input", **attrs})


class PasswordLoginForm(forms.Form):
    mobile = MobileField()
    password = forms.CharField(label="رمز عبور", strip=False, max_length=128, widget=_password_input("current-password"))


class SetPasswordForm(forms.Form):
    """Set or change the storefront password. With require_current (a password exists and
    there was no recent SMS-code login) the current password is asked for too."""

    current_password = forms.CharField(
        label="رمز عبور فعلی", strip=False, max_length=128, widget=_password_input("current-password")
    )
    new_password1 = forms.CharField(
        label="رمز عبور جدید",
        strip=False,
        max_length=128,
        widget=_password_input("new-password"),
        help_text="دست‌کم ۸ نویسه، فقط عدد نباشد و شبیه شمارهٔ موبایل یا رمزهای رایج هم نباشد.",
    )
    new_password2 = forms.CharField(
        label="تکرار رمز عبور جدید", strip=False, max_length=128, widget=_password_input("new-password")
    )

    def __init__(self, user, *args, require_current=False, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if not require_current:
            del self.fields["current_password"]

    def clean_current_password(self):
        value = self.cleaned_data["current_password"]
        if not self.user.check_password(value):
            raise forms.ValidationError("رمز عبور فعلی درست نیست.")
        return value

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("new_password1"), cleaned.get("new_password2")
        if p1 and p2 and p1 != p2:
            self.add_error("new_password2", "تکرار رمز عبور با رمز جدید یکی نیست.")
        elif p1:
            try:
                password_validation.validate_password(p1, self.user)
            except forms.ValidationError as e:
                self.add_error("new_password1", e)
        return cleaned

    def save(self):
        self.user.set_password(self.cleaned_data["new_password1"])
        self.user.save(update_fields=["password"])
        return self.user


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
