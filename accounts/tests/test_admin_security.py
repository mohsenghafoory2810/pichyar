"""Admin login: password + optional TOTP, django-axes lockout, SMS sessions kept out of the admin."""

from io import StringIO

from axes.models import AccessAttempt
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice

from catalog.tests.utils import make_product
from orders.tests.utils import capture_sms, make_order

MOBILE = "09121234567"
PASSWORD = "secret-pass-1"


def current_token(device):
    totp = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
    return f"{totp.token():0{device.digits}d}"


class AdminLoginTestCase(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(MOBILE, password=PASSWORD)
        self.login_url = reverse("admin:login")
        self.index_url = reverse("admin:index")

    def login(self, password=PASSWORD, token="", **extra):
        data = {"username": MOBILE, "password": password, "otp_token": token, "next": self.index_url}
        return self.client.post(self.login_url, data, **extra)


class PasswordLoginTests(AdminLoginTestCase):
    def test_login_page_is_persian_and_has_the_code_field(self):
        response = self.client.get(self.login_url)
        self.assertContains(response, "کد ورود دومرحله‌ای")
        self.assertContains(response, "ورود به پنل مدیریت")

    def test_password_login(self):
        self.assertRedirects(self.login(), self.index_url)
        self.assertEqual(self.client.get(self.index_url).status_code, 200)

    def test_admin_url_is_not_admin(self):
        self.assertEqual(self.client.get("/admin/").status_code, 404)

    def test_sms_code_session_cannot_open_the_admin(self):
        """A staff member who signs in on the storefront with an SMS code is only a customer there."""
        with capture_sms() as sent:
            self.client.post(reverse("accounts:login"), {"action": "send", "mobile": MOBILE})
        self.client.post(reverse("accounts:login"), {"action": "verify", "code": sent[0][2]["code"]})
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.admin.pk)
        response = self.client.get(self.index_url)
        self.assertRedirects(response, f"{self.login_url}?next={self.index_url}")
        # ... and the password login still works from that browser.
        self.assertRedirects(self.login(), self.index_url)
        self.assertEqual(self.client.get(self.index_url).status_code, 200)


class LockoutTests(AdminLoginTestCase):
    def test_locked_after_five_wrong_passwords(self):
        for _ in range(4):
            self.assertEqual(self.login("wrong").status_code, 200)
        response = self.login("wrong")
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "موقتاً بسته شد", status_code=429)
        # Even the right password is refused while locked.
        self.assertEqual(self.login().status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_lockout_is_per_ip_and_can_be_reset(self):
        for _ in range(5):
            self.login("wrong")
        self.assertEqual(self.login(REMOTE_ADDR="10.0.0.9").status_code, 302)
        self.client.logout()
        call_command("axes_reset", stdout=StringIO())
        self.assertEqual(self.login().status_code, 302)

    def test_unlock_from_admin(self):
        for _ in range(5):
            self.login("wrong", REMOTE_ADDR="10.0.0.5")
        self.client.force_login(self.admin)
        url = reverse("admin:axes_accessattempt_changelist")
        self.assertContains(self.client.get(url), "10.0.0.5")
        attempt = AccessAttempt.objects.get()
        self.client.post(url, {"action": "unlock", "_selected_action": [attempt.pk]})
        self.assertFalse(AccessAttempt.objects.exists())

    def test_success_resets_the_counter(self):
        for _ in range(3):
            self.login("wrong")
        self.login()
        self.client.logout()
        for _ in range(4):
            self.assertEqual(self.login("wrong").status_code, 200)


@override_settings(OTP_TOTP_THROTTLE_FACTOR=0)  # django-otp waits 1s, 2s, 4s… after a wrong code; not in tests
class TwoFactorTests(AdminLoginTestCase):
    def make_device(self):
        return TOTPDevice.objects.create(user=self.admin, name="phone", confirmed=True)

    def test_device_requires_the_code(self):
        device = self.make_device()
        response = self.login()
        self.assertContains(response, "کد ۶ رقمی برنامهٔ احراز هویت را هم وارد کنید")
        self.assertNotIn("_auth_user_id", self.client.session)
        response = self.login(token="000000" if current_token(device) != "000000" else "111111")
        self.assertContains(response, "کد ورود دومرحله‌ای درست نیست")
        self.assertRedirects(self.login(token=current_token(device)), self.index_url)
        self.assertEqual(self.client.get(self.index_url).status_code, 200)

    def test_wrong_codes_count_towards_the_lockout(self):
        self.make_device()
        for _ in range(5):
            self.login(token="12")
        self.assertEqual(AccessAttempt.objects.get().failures_since_start, 5)
        self.assertEqual(self.login(token="12").status_code, 429)

    def test_session_without_otp_is_refused_once_a_device_exists(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.index_url).status_code, 200)
        self.make_device()
        self.assertEqual(self.client.get(self.index_url).status_code, 302)

    def test_turn_on_and_off(self):
        self.client.force_login(self.admin)
        url = reverse("admin:two_factor")
        response = self.client.get(url)
        self.assertContains(response, "<svg")
        self.assertContains(response, "روشن کردن")
        pending = TOTPDevice.objects.get(user=self.admin, confirmed=False)
        self.assertContains(self.client.post(url, {"action": "enable", "token": "1"}), "کد درست نیست")
        response = self.client.post(url, {"action": "enable", "token": current_token(pending)})
        self.assertRedirects(response, url)
        pending.refresh_from_db()
        self.assertTrue(pending.confirmed)
        # The current session stays usable (it is verified with the new device).
        self.assertContains(self.client.get(url), "ورود دومرحله‌ای روشن است")
        self.assertEqual(self.client.get(self.index_url).status_code, 200)
        self.assertContains(self.client.post(url, {"action": "disable", "token": "1"}), "کد درست نیست")
        self.assertTrue(TOTPDevice.objects.filter(user=self.admin).exists())

    def test_disable_command(self):
        self.make_device()
        call_command("disable_2fa", "۰۹۱۲۱۲۳۴۵۶۷", stdout=StringIO())
        self.assertFalse(TOTPDevice.objects.exists())
        self.assertRedirects(self.login(), self.index_url)

    def test_device_list_page(self):
        self.make_device()
        self.client.force_login(self.admin)
        # The forced session is not OTP-verified: turn the device off through the model to look at the page.
        TOTPDevice.objects.update(confirmed=False)
        response = self.client.get(reverse("admin:otp_totp_totpdevice_changelist"))
        self.assertContains(response, "ورود دومرحله‌ای مدیران")
        self.assertNotContains(response, "key")


class CustomerAdminTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("09120000001", password="pass"))
        self.customer = get_user_model().objects.create_user("09121111111", name="علی رضایی")
        p = make_product(price=1_000_000, stock=10)
        with capture_sms():
            self.guest_order = make_order((p, 1))  # earlier guest order with the same mobile
            self.order = make_order((p, 2), user=self.customer, method="online")
            self.order.confirm_payment()

    def test_list_shows_totals_and_excludes_staff(self):
        response = self.client.get(reverse("admin:accounts_customer_changelist"))
        self.assertContains(response, "علی رضایی")
        self.assertContains(response, "09121111111")
        self.assertContains(response, 'class="field-mobile"', count=1)  # the admin itself is not a customer
        self.assertContains(response, "۲٬")  # total spent of the paid order (~2.2M with shipping)

    def test_search_with_persian_digits(self):
        response = self.client.get(reverse("admin:accounts_customer_changelist"), {"q": "۰۹۱۲۱۱۱"})
        self.assertContains(response, "علی رضایی")

    def test_change_page_has_order_history_including_guest_orders(self):
        response = self.client.get(reverse("admin:accounts_customer_change", args=[self.customer.pk]))
        self.assertEqual(response.status_code, 200)
        fa = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
        self.assertContains(response, self.order.number.translate(fa))
        self.assertContains(response, self.guest_order.number.translate(fa))
        self.assertContains(response, "(مهمان)")
        self.assertContains(response, reverse("admin:orders_order_change", args=[self.order.pk]))
