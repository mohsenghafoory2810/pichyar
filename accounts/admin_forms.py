"""Admin login: mobile + password, and the authenticator code when two-step login is on."""

from django import forms
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth.signals import user_login_failed
from django.contrib.auth.views import LoginView
from django_otp import devices_for_user
from django_otp import login as otp_login

from core.persian import latin_digits


class ShopAdminLoginForm(AdminAuthenticationForm):
    otp_token = forms.CharField(
        label="کد ورود دومرحله‌ای",
        required=False,
        max_length=8,
        help_text="فقط اگر ورود دومرحله‌ای را روشن کرده‌اید: کد ۶ رقمی برنامهٔ احراز هویت.",
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code", "dir": "ltr"}),
    )

    error_messages = {
        **AdminAuthenticationForm.error_messages,
        "otp_required": "این حساب ورود دومرحله‌ای دارد. کد ۶ رقمی برنامهٔ احراز هویت را هم وارد کنید.",
        "otp_invalid": "کد ورود دومرحله‌ای درست نیست یا منقضی شده است.",
    }

    otp_device = None

    def clean(self):
        cleaned = super().clean()  # authenticates (and lets django-axes count a wrong password)
        user = self.get_user()
        if user is None:
            return cleaned
        devices = list(devices_for_user(user, confirmed=True))
        if not devices:
            return cleaned
        token = latin_digits(cleaned.get("otp_token") or "").replace(" ", "")
        if not token:
            raise forms.ValidationError(self.error_messages["otp_required"], code="otp_required")
        for device in devices:
            if device.verify_token(token):
                self.otp_device = device
                return cleaned
        # A wrong code counts as a failed login for django-axes, like a wrong password.
        user_login_failed.send(
            sender=__name__, credentials={"username": cleaned.get("username")}, request=self.request
        )
        raise forms.ValidationError(self.error_messages["otp_invalid"], code="otp_invalid")


class OTPLoginView(LoginView):
    def form_valid(self, form):
        response = super().form_valid(form)
        if form.otp_device is not None:
            otp_login(self.request, form.otp_device)
        return response
