from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from accounts import otp
from accounts.models import OTPCode
from accounts.validators import normalize_mobile, normalize_postal_code
from core.utils import client_ip
from orders.tests.utils import capture_sms

MOBILE = "09121234567"
LOGIN = OTPCode.Purpose.LOGIN


def age_back(seconds, **filters):
    """Pretend the codes were sent `seconds` ago."""
    for o in OTPCode.objects.filter(**filters):
        OTPCode.objects.filter(pk=o.pk).update(
            created_at=o.created_at - timedelta(seconds=seconds), expires_at=o.expires_at - timedelta(seconds=seconds)
        )


class MobileValidationTests(TestCase):
    def test_normalises_persian_arabic_digits_and_prefixes(self):
        for value in ("09121234567", "۰۹۱۲۱۲۳۴۵۶۷", "٠٩١٢١٢٣٤٥٦٧", "+989121234567", "00989121234567",
                      "989121234567", "9121234567", "0912 123 4567", "0912-123-4567"):
            self.assertEqual(normalize_mobile(value), MOBILE, value)

    def test_rejects_invalid(self):
        for value in ("", "0912123456", "091212345678", "02112345678", "08121234567", "abc", "+18005551234"):
            with self.assertRaises(ValidationError, msg=value):
                normalize_mobile(value)

    def test_postal_code(self):
        self.assertEqual(normalize_postal_code("۱۲۳۴۵-۶۷۸۹۰"), "1234567890")
        for value in ("123456789", "12345678901", "12345abcde"):
            with self.assertRaises(ValidationError):
                normalize_postal_code(value)


class OTPServiceTests(TestCase):
    def send(self, mobile=MOBILE, purpose=LOGIN, ip="1.2.3.4"):
        with capture_sms() as sent:
            otp.send_code(mobile, purpose, ip)
        self.assertEqual(sent[-1][:2], (mobile, "otp"))
        return sent[-1][2]["code"]

    def test_send_and_verify(self):
        code = self.send()
        self.assertRegex(code, r"^\d{5}$")
        otp.verify_code(MOBILE, LOGIN, code)
        self.assertIsNotNone(OTPCode.objects.get().consumed_at)

    def test_code_is_stored_hashed(self):
        code = self.send()
        row = OTPCode.objects.get()
        self.assertNotIn(code, row.code_hash)
        self.assertEqual(len(row.code_hash), 64)
        self.assertEqual(row.expires_at - row.created_at, timedelta(seconds=120))

    def test_persian_digits_accepted(self):
        code = self.send()
        otp.verify_code(MOBILE, LOGIN, code.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")))

    def test_code_works_once(self):
        code = self.send()
        otp.verify_code(MOBILE, LOGIN, code)
        with self.assertRaises(otp.OTPError) as ctx:
            otp.verify_code(MOBILE, LOGIN, code)
        self.assertEqual(ctx.exception.code, "missing")

    def test_expired_after_two_minutes(self):
        code = self.send()
        age_back(119)
        otp.verify_code(MOBILE, LOGIN, code)  # still valid at 1:59

        age_back(61)
        code = self.send()
        age_back(121)
        with self.assertRaises(otp.OTPError) as ctx:
            otp.verify_code(MOBILE, LOGIN, code)
        self.assertEqual(ctx.exception.code, "expired")

    def test_five_wrong_attempts_lock_the_code(self):
        code = self.send()
        wrong = "00000" if code != "00000" else "11111"
        for left in (4, 3, 2, 1):
            with self.assertRaises(otp.OTPError) as ctx:
                otp.verify_code(MOBILE, LOGIN, wrong)
            self.assertEqual(ctx.exception.code, "wrong")
            self.assertIn(f"{'۰۱۲۳۴'[left]} بار دیگر", ctx.exception.message)
        with self.assertRaises(otp.OTPError):
            otp.verify_code(MOBILE, LOGIN, wrong)  # 5th wrong try
        self.assertEqual(OTPCode.objects.get().attempts, 5)  # counter is committed despite the error
        with self.assertRaises(otp.OTPError) as ctx:
            otp.verify_code(MOBILE, LOGIN, code)  # even the right code is refused now
        self.assertEqual(ctx.exception.code, "too_many_attempts")

    def test_resend_cooldown(self):
        self.send()
        with self.assertRaises(otp.OTPError) as ctx:
            otp.send_code(MOBILE, LOGIN, "1.2.3.4")
        self.assertEqual(ctx.exception.code, "cooldown")
        self.assertEqual(ctx.exception.retry_after, 60)
        self.assertEqual(otp.seconds_until_resend(MOBILE), 60)
        age_back(30)
        self.assertEqual(otp.seconds_until_resend(MOBILE), 30)
        age_back(31)
        self.assertEqual(otp.seconds_until_resend(MOBILE), 0)
        self.send()
        self.assertEqual(OTPCode.objects.count(), 2)

    def test_cooldown_is_per_mobile(self):
        self.send()
        self.send(mobile="09129999999")

    def test_new_code_invalidates_the_old_one(self):
        old = self.send()
        age_back(61)
        new = self.send()
        if old != new:
            with self.assertRaises(otp.OTPError):
                otp.verify_code(MOBILE, LOGIN, old)
        otp.verify_code(MOBILE, LOGIN, new)

    def test_purposes_are_separate(self):
        code = self.send(purpose=LOGIN)
        with self.assertRaises(otp.OTPError):
            otp.verify_code(MOBILE, OTPCode.Purpose.CHECKOUT, code)

    def test_rate_limit_per_mobile(self):
        for _ in range(5):
            self.send()
            age_back(61)
        with self.assertRaises(otp.OTPError) as ctx:
            otp.send_code(MOBILE, LOGIN, "1.2.3.4")
        self.assertEqual(ctx.exception.code, "rate_mobile")
        age_back(3600)  # an hour later it works again
        self.send()

    @override_settings(OTP_MAX_PER_IP_PER_HOUR=3)
    def test_rate_limit_per_ip(self):
        for i in range(3):
            self.send(mobile=f"0912000000{i}", ip="5.6.7.8")
        with self.assertRaises(otp.OTPError) as ctx:
            otp.send_code("09120000009", LOGIN, "5.6.7.8")
        self.assertEqual(ctx.exception.code, "rate_ip")
        self.send(mobile="09120000009", ip="5.6.7.9")  # another IP is fine

    def test_wrong_format_code_never_matches(self):
        self.send()
        with self.assertRaises(otp.OTPError):
            otp.verify_code(MOBILE, LOGIN, "")


class ClientIPTests(TestCase):
    def test_remote_addr_by_default(self):
        request = RequestFactory().get("/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="6.6.6.6")
        self.assertEqual(client_ip(request), "10.0.0.1")

    @override_settings(USE_X_FORWARDED_FOR=True)
    def test_last_forwarded_entry_behind_proxy(self):
        request = RequestFactory().get("/", REMOTE_ADDR="172.18.0.3", HTTP_X_FORWARDED_FOR="6.6.6.6, 2.2.2.2")
        self.assertEqual(client_ip(request), "2.2.2.2")


class LoginViewTests(TestCase):
    url = reverse("accounts:login")

    def login_flow(self, mobile="۰۹۱۲۱۲۳۴۵۶۷", next_url=None, **headers):
        data = {"action": "send", "mobile": mobile}
        if next_url:
            data["next"] = next_url
        with capture_sms() as sent:
            response = self.client.post(self.url, data, **headers)
        self.assertContains(response, "کد ۵ رقمی")
        code = sent[0][2]["code"]
        verify = {"action": "verify", "code": code, **({"next": next_url} if next_url else {})}
        return self.client.post(self.url, verify, **headers)

    def test_registration_creates_user_and_asks_for_name(self):
        response = self.login_flow()
        user = get_user_model().objects.get()
        self.assertEqual(user.mobile, MOBILE)
        self.assertFalse(user.has_usable_password())
        self.assertRedirects(response, f"{reverse('accounts:profile')}?next=%2Faccounts%2F&welcome=1", fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_existing_user_goes_to_next(self):
        get_user_model().objects.create_user(MOBILE, name="مریم")
        response = self.login_flow(next_url="/checkout/")
        self.assertRedirects(response, "/checkout/", fetch_redirect_response=False)

    def test_unsafe_next_is_ignored(self):
        get_user_model().objects.create_user(MOBILE, name="مریم")
        response = self.login_flow(next_url="https://evil.example/")
        self.assertRedirects(response, reverse("accounts:orders"), fetch_redirect_response=False)

    def test_htmx_uses_hx_redirect(self):
        get_user_model().objects.create_user(MOBILE, name="مریم")
        response = self.login_flow(headers={"HX-Request": "true"})
        self.assertEqual(response["HX-Redirect"], reverse("accounts:orders"))

    def test_inactive_user_cannot_log_in(self):
        get_user_model().objects.create_user(MOBILE, is_active=False)
        response = self.login_flow()
        self.assertContains(response, "غیرفعال")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_wrong_code_shows_error(self):
        with capture_sms():
            self.client.post(self.url, {"action": "send", "mobile": MOBILE})
        response = self.client.post(self.url, {"action": "verify", "code": "abcde"})
        self.assertContains(response, "کد ۵ رقمی پیامک‌شده را وارد کنید")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_invalid_mobile(self):
        response = self.client.post(self.url, {"action": "send", "mobile": "12345"})
        self.assertContains(response, "شمارهٔ موبایل معتبر نیست")
        self.assertFalse(OTPCode.objects.exists())

    def test_resend_is_refused_during_cooldown(self):
        with capture_sms() as sent:
            self.client.post(self.url, {"action": "send", "mobile": MOBILE})
            response = self.client.post(self.url, {"action": "resend"})
        self.assertEqual(len(sent), 1)
        self.assertContains(response, "ثانیه صبر کنید")
        self.assertContains(response, 'data-countdown="60"')

    def test_change_number_goes_back(self):
        with capture_sms():
            self.client.post(self.url, {"action": "send", "mobile": MOBILE})
        response = self.client.post(self.url, {"action": "change"})
        self.assertContains(response, "دریافت کد تأیید")
        self.assertNotIn("login_mobile", self.client.session)

    def test_staff_admin_login_with_mobile_and_password(self):
        get_user_model().objects.create_superuser(MOBILE, password="secret-pass-1")
        login_url = f"/{settings.ADMIN_URL}login/"
        response = self.client.post(login_url, {"username": MOBILE, "password": "secret-pass-1"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get(f"/{settings.ADMIN_URL}").status_code, 200)
