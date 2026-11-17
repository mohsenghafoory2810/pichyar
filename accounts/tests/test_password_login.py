import time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import PasswordLoginFailure
from core.models import SiteSettings
from orders.tests.utils import capture_sms

MOBILE = "09121234567"
PASSWORD = "Kh0b-ramz-1403"
LOGIN_URL = reverse("accounts:login")
PASSWORD_URL = reverse("accounts:password")


def enable_password_login(on=True):
    s = SiteSettings.load()
    s.password_login_enabled = on
    s.save()


class PasswordLoginBase(TestCase):
    def setUp(self):
        enable_password_login()

    def make_user(self, password=PASSWORD, **extra):
        extra.setdefault("mobile_verified_at", timezone.now())  # signed in by SMS code before
        return get_user_model().objects.create_user(MOBILE, password=password, name="مریم", **extra)

    def post_password(self, mobile=MOBILE, password=PASSWORD, headers=None, **extra):
        data = {"method": "password", "mobile": mobile, "password": password, **extra}
        return self.client.post(LOGIN_URL, data, headers=headers)

    def sms_login(self):
        with capture_sms() as sent:
            self.client.post(LOGIN_URL, {"action": "send", "mobile": MOBILE})
        return self.client.post(LOGIN_URL, {"action": "verify", "code": sent[0][2]["code"]})


class LoginPageTests(PasswordLoginBase):
    def test_tabs_only_when_enabled(self):
        tab = 'aria-label="روش ورود"'
        self.assertContains(self.client.get(LOGIN_URL), tab)
        enable_password_login(False)
        response = self.client.get(LOGIN_URL + "?method=password")
        self.assertNotContains(response, tab)
        self.assertContains(response, "دریافت کد تأیید")  # falls back to the SMS code

    def test_password_tab_shows_form(self):
        response = self.client.get(LOGIN_URL + "?method=password")
        self.assertContains(response, 'name="password"')
        self.assertContains(response, 'autocomplete="current-password"')

    def test_disabled_refuses_password_post(self):
        self.make_user()
        enable_password_login(False)
        self.post_password()
        self.assertNotIn("_auth_user_id", self.client.session)


class PasswordLoginTests(PasswordLoginBase):
    def test_login_with_password(self):
        user = self.make_user()
        response = self.post_password(mobile="۰۹۱۲۱۲۳۴۵۶۷", next="/checkout/")
        self.assertRedirects(response, "/checkout/", fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        self.assertEqual(self.client.session["_auth_user_backend"], "accounts.backends.StorefrontPasswordBackend")

    def test_htmx_uses_hx_redirect(self):
        self.make_user()
        response = self.post_password(headers={"HX-Request": "true"})
        self.assertEqual(response["HX-Redirect"], reverse("accounts:orders"))

    def test_first_time_needs_sms_code(self):
        """A number without an account (or without a password) can't sign in with a password."""
        response = self.post_password()
        self.assertContains(response, "با کد پیامکی وارد شوید")
        self.assertFalse(get_user_model().objects.exists())
        get_user_model().objects.create_user(MOBILE)  # registered by SMS code, no password yet
        self.post_password(password="")
        self.post_password()
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_password_set_by_admin_needs_one_sms_login_first(self):
        user = self.make_user(mobile_verified_at=None)
        self.assertContains(self.post_password(), "شمارهٔ موبایل یا رمز عبور درست نیست")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.sms_login()
        user.refresh_from_db()
        self.assertIsNotNone(user.mobile_verified_at)
        self.client.post(reverse("accounts:logout"))
        self.post_password()
        self.assertIn("_auth_user_id", self.client.session)

    def test_same_error_for_unknown_number_and_wrong_password(self):
        self.make_user()
        wrong = self.post_password(password="wrong-pass-1").content.decode()
        unknown = self.post_password(mobile="09351112233").content.decode()
        self.assertIn("شمارهٔ موبایل یا رمز عبور درست نیست", wrong)
        self.assertEqual(wrong.count("alert-error"), unknown.count("alert-error"))

    def test_password_is_not_echoed_back(self):
        self.make_user()
        self.assertNotContains(self.post_password(password="wrong-pass-1"), "wrong-pass-1")

    def test_inactive_user(self):
        self.make_user(is_active=False)
        self.assertContains(self.post_password(), "غیرفعال")
        self.assertNotIn("_auth_user_id", self.client.session)

    @override_settings(PASSWORD_LOGIN_MAX_FAILS_PER_MOBILE=3)
    def test_lockout_per_mobile_but_sms_code_still_works(self):
        self.make_user()
        for _ in range(3):
            self.post_password(password="wrong-pass-1")
        response = self.post_password()  # right password, but locked
        self.assertContains(response, "ورود با رمز تا")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.sms_login()
        self.assertIn("_auth_user_id", self.client.session)

    @override_settings(PASSWORD_LOGIN_MAX_FAILS_PER_MOBILE=3)
    def test_lock_expires(self):
        self.make_user()
        for _ in range(3):
            self.post_password(password="wrong-pass-1")
        from datetime import timedelta

        for f in PasswordLoginFailure.objects.all():
            PasswordLoginFailure.objects.filter(pk=f.pk).update(created_at=f.created_at - timedelta(minutes=16))
        self.post_password()
        self.assertIn("_auth_user_id", self.client.session)

    @override_settings(PASSWORD_LOGIN_MAX_FAILS_PER_IP_PER_HOUR=4, PASSWORD_LOGIN_MAX_FAILS_PER_MOBILE=100)
    def test_lockout_per_ip(self):
        self.make_user()
        for i in range(4):
            self.post_password(mobile=f"0935111223{i}")
        self.assertContains(self.post_password(), "ورود با رمز تا")

    def test_success_clears_failures(self):
        self.make_user()
        self.post_password(password="wrong-pass-1")
        self.post_password()
        self.assertFalse(PasswordLoginFailure.objects.filter(mobile=MOBILE).exists())

    def test_customer_lockout_does_not_lock_admin_login(self):
        get_user_model().objects.create_superuser(MOBILE, password=PASSWORD)
        for _ in range(settings.AXES_FAILURE_LIMIT + 1):
            self.post_password(password="wrong-pass-1")
        admin_login = f"/{settings.ADMIN_URL}login/"
        response = self.client.post(admin_login, {"username": MOBILE, "password": PASSWORD})
        self.assertEqual(response.status_code, 302)

    def test_storefront_password_session_is_refused_by_admin(self):
        get_user_model().objects.create_superuser(MOBILE, password=PASSWORD, mobile_verified_at=timezone.now())
        self.post_password()
        self.assertIn("_auth_user_id", self.client.session)
        response = self.client.get(f"/{settings.ADMIN_URL}")
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])


class PasswordPageTests(PasswordLoginBase):
    def test_hidden_and_404_when_disabled(self):
        self.sms_login()
        self.assertContains(self.client.get(reverse("accounts:profile")), PASSWORD_URL)
        enable_password_login(False)
        self.assertNotContains(self.client.get(reverse("accounts:profile")), PASSWORD_URL)
        self.assertEqual(self.client.get(PASSWORD_URL).status_code, 404)

    def test_requires_login(self):
        self.assertEqual(self.client.get(PASSWORD_URL).status_code, 302)

    def test_set_password_after_sms_login_then_login_with_it(self):
        self.sms_login()
        response = self.client.get(PASSWORD_URL)
        self.assertNotContains(response, "current_password")
        response = self.client.post(PASSWORD_URL, {"new_password1": PASSWORD, "new_password2": PASSWORD})
        self.assertRedirects(response, PASSWORD_URL, fetch_redirect_response=False)
        self.assertIn("_auth_user_id", self.client.session)  # still signed in
        self.client.post(reverse("accounts:logout"))
        self.post_password()
        self.assertIn("_auth_user_id", self.client.session)

    def test_weak_and_mismatched_passwords(self):
        self.sms_login()
        response = self.client.post(PASSWORD_URL, {"new_password1": "12345678", "new_password2": "12345678"})
        self.assertContains(response, "text-error")
        response = self.client.post(PASSWORD_URL, {"new_password1": PASSWORD, "new_password2": PASSWORD + "x"})
        self.assertContains(response, "تکرار رمز عبور با رمز جدید یکی نیست")
        self.assertFalse(get_user_model().objects.get().has_usable_password())

    def test_change_needs_current_password_without_recent_sms_login(self):
        self.make_user()
        self.post_password()  # signed in with the password, not with an SMS code
        response = self.client.post(PASSWORD_URL, {"new_password1": "Taze-ramz-99", "new_password2": "Taze-ramz-99"})
        self.assertContains(response, "رمز عبور فعلی")
        self.assertTrue(get_user_model().objects.get().check_password(PASSWORD))
        response = self.client.post(
            PASSWORD_URL, {"current_password": "bad", "new_password1": "Taze-ramz-99", "new_password2": "Taze-ramz-99"}
        )
        self.assertContains(response, "رمز عبور فعلی درست نیست")
        self.client.post(
            PASSWORD_URL, {"current_password": PASSWORD, "new_password1": "Taze-ramz-99", "new_password2": "Taze-ramz-99"}
        )
        self.assertTrue(get_user_model().objects.get().check_password("Taze-ramz-99"))

    def test_forgotten_password_reset_by_sms_login(self):
        self.make_user()
        self.sms_login()
        self.client.post(PASSWORD_URL, {"new_password1": "Taze-ramz-99", "new_password2": "Taze-ramz-99"})
        self.assertTrue(get_user_model().objects.get().check_password("Taze-ramz-99"))

    def test_sms_login_grace_period_expires(self):
        self.make_user()
        self.sms_login()
        session = self.client.session
        session["sms_login_at"] = int(time.time()) - 11 * 60
        session.save()
        self.assertContains(self.client.get(PASSWORD_URL), "current_password")

    def test_change_signs_out_other_sessions(self):
        self.make_user()
        other = self.client_class()
        other.post(LOGIN_URL, {"method": "password", "mobile": MOBILE, "password": PASSWORD})
        self.sms_login()
        self.client.post(PASSWORD_URL, {"new_password1": "Taze-ramz-99", "new_password2": "Taze-ramz-99"})
        self.assertEqual(other.get(reverse("accounts:orders")).status_code, 302)
        self.assertEqual(self.client.get(reverse("accounts:orders")).status_code, 200)

    def test_staff_cannot_change_admin_password_here(self):
        get_user_model().objects.create_superuser(MOBILE, password=PASSWORD, name="مدیر")
        self.sms_login()
        self.assertNotContains(self.client.get(reverse("accounts:profile")), PASSWORD_URL)
        response = self.client.post(PASSWORD_URL, {"new_password1": "Taze-ramz-99", "new_password2": "Taze-ramz-99"})
        self.assertRedirects(response, reverse("accounts:profile"), fetch_redirect_response=False)
        self.assertTrue(get_user_model().objects.get().check_password(PASSWORD))
