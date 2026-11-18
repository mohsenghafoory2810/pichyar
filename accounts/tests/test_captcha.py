"""Picture code (core.captcha) before SMS codes while sending looks like SMS bombing."""

from io import BytesIO
from unittest import mock

from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from accounts import otp
from accounts.models import OTPCode
from core import captcha
from orders.tests.utils import capture_sms

LOGIN = OTPCode.Purpose.LOGIN
CAPTCHA_ON = override_settings(
    OTP_CAPTCHA_ENABLED=True,
    OTP_CAPTCHA_AFTER_PER_IP=100,
    OTP_CAPTCHA_AFTER_PER_MOBILE=100,
    OTP_CAPTCHA_SITE_PER_10_MIN=0,
    OTP_RESEND_COOLDOWN=0,
)


def session_request():
    request = RequestFactory().get("/")
    request.session = {}
    return request


def load_picture(client, **extra):
    """Load the picture like a browser does; returns the code drawn in it."""
    with mock.patch.object(captcha._random, "choice", return_value="7"):
        response = client.get(reverse("accounts:captcha"), **extra)
    assert response.status_code == 200
    return "7" * captcha.LENGTH


class ChallengeTests(TestCase):
    def test_right_code_works_once(self):
        request = session_request()
        text = captcha.new_challenge(request)
        self.assertRegex(text, rf"^[2-9]{{{captcha.LENGTH}}}$")
        self.assertNotIn(text, str(request.session))  # only a hash is kept
        self.assertTrue(captcha.check(request, text))
        self.assertFalse(captcha.check(request, text))

    def test_wrong_code_uses_the_challenge_up(self):
        request = session_request()
        text = captcha.new_challenge(request)
        self.assertFalse(captcha.check(request, "00000"))
        self.assertFalse(captcha.check(request, text))

    def test_persian_digits_and_empty_values(self):
        request = session_request()
        text = captcha.new_challenge(request)
        self.assertTrue(captcha.check(request, text.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))))
        self.assertFalse(captcha.check(session_request(), ""))  # no picture was ever loaded
        request = session_request()
        captcha.new_challenge(request)
        self.assertFalse(captcha.check(request, None))

    def test_code_expires(self):
        request = session_request()
        text = captcha.new_challenge(request)
        request.session[captcha.SESSION_KEY]["at"] -= captcha.CAPTCHA_TTL + 1
        self.assertFalse(captcha.check(request, text))

    def test_picture_is_a_png_and_never_cached(self):
        response = self.client.get(reverse("accounts:captcha"))
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertIn("no-store", response["Cache-Control"])
        picture = Image.open(BytesIO(response.content))
        self.assertEqual((picture.format, picture.size), ("PNG", captcha.SIZE))
        first = self.client.session[captcha.SESSION_KEY]["hash"]
        self.client.get(reverse("accounts:captcha"))
        self.assertNotEqual(self.client.session[captcha.SESSION_KEY]["hash"], first)  # a new code every load
        self.assertEqual(self.client.post(reverse("accounts:captcha")).status_code, 405)

    @override_settings(RATE_LIMITS_ENABLED=True, CAPTCHA_IMAGES_PER_IP=2)
    def test_pictures_are_throttled_per_ip(self):
        cache.clear()
        url = reverse("accounts:captcha")
        self.assertEqual([self.client.get(url).status_code for _ in range(3)], [200, 200, 429])
        cache.clear()


class CaptchaRequiredTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def send(self, mobile, ip):
        with capture_sms():
            otp.send_code(mobile, LOGIN, ip)

    def test_off_in_the_test_settings(self):
        for i in range(5):
            self.send(f"0912000000{i}", "1.1.1.1")
        self.assertFalse(otp.captcha_required("09120000000", "1.1.1.1"))

    @CAPTCHA_ON
    @override_settings(OTP_CAPTCHA_AFTER_PER_IP=2)
    def test_after_some_codes_from_one_ip(self):
        self.send("09120000001", "1.1.1.1")
        self.assertFalse(otp.captcha_required("09120000002", "1.1.1.1"))
        self.send("09120000002", "1.1.1.1")
        self.assertTrue(otp.captcha_required("09120000003", "1.1.1.1"))
        self.assertFalse(otp.captcha_required("09120000003", "2.2.2.2"))

    @CAPTCHA_ON
    @override_settings(OTP_CAPTCHA_AFTER_PER_MOBILE=2)
    def test_after_some_codes_for_one_mobile(self):
        self.send("09120000001", "1.1.1.1")
        self.assertFalse(otp.captcha_required("09120000001", "9.9.9.9"))
        self.send("09120000001", "2.2.2.2")
        self.assertTrue(otp.captcha_required("09120000001", "9.9.9.9"))
        self.assertFalse(otp.captcha_required("09120000002", "9.9.9.9"))

    @CAPTCHA_ON
    @override_settings(OTP_CAPTCHA_SITE_PER_10_MIN=3)
    def test_site_wide_when_many_ips_and_numbers_ask(self):
        for i in range(3):
            self.assertFalse(otp.captcha_required(f"0912000000{i}", f"1.1.1.{i}"))
            self.send(f"0912000000{i}", f"1.1.1.{i}")
        self.assertTrue(otp.captcha_required("09129999999", "8.8.8.8"))
        # It stays on for a while even when the codes get old (the attack is being stopped).
        OTPCode.objects.all().delete()
        self.assertTrue(otp.captcha_required("09129999999", "8.8.8.8"))
        cache.clear()
        self.assertFalse(otp.captcha_required("09129999999", "8.8.8.8"))


class LoginCaptchaTests(TestCase):
    url = reverse("accounts:login")

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def post(self, **data):
        return self.client.post(self.url, data)

    @CAPTCHA_ON
    @override_settings(OTP_CAPTCHA_AFTER_PER_IP=1)
    def test_next_number_from_the_same_ip_needs_the_picture_code(self):
        with capture_sms() as sent:
            self.assertNotContains(self.client.get(self.url), reverse("accounts:captcha"))
            self.post(action="send", mobile="09120000001")
            self.post(action="change")
            # The form now shows the picture; posting without it sends nothing.
            self.assertContains(self.client.get(self.url), reverse("accounts:captcha"))
            response = self.post(action="send", mobile="09120000002")
            self.assertContains(response, captcha.REQUIRED_MESSAGE)
            self.assertContains(response, reverse("accounts:captcha"))
            self.assertContains(response, "09120000002")  # the number stays in the form
            # A wrong code: nothing either, and that picture is used up.
            text = load_picture(self.client)
            self.assertContains(self.post(action="send", mobile="09120000002", captcha="22222"), captcha.WRONG_MESSAGE)
            self.assertContains(self.post(action="send", mobile="09120000002", captcha=text), captcha.WRONG_MESSAGE)
            self.assertEqual(len(sent), 1)
            # The right code of a new picture.
            text = load_picture(self.client)
            response = self.post(action="send", mobile="09120000002", captcha=text)
            self.assertContains(response, "کد ۶ رقمی")
            self.assertEqual([s[0] for s in sent], ["09120000001", "09120000002"])

    @CAPTCHA_ON
    @override_settings(OTP_CAPTCHA_AFTER_PER_MOBILE=1)
    def test_sending_again_needs_the_picture_code(self):
        with capture_sms() as sent:
            response = self.post(action="send", mobile="09120000001")
            self.assertContains(response, "برای ارسال دوبارهٔ کد")
            self.assertContains(self.post(action="resend"), captcha.REQUIRED_MESSAGE)
            self.assertEqual(len(sent), 1)
            text = load_picture(self.client)
            self.assertContains(self.post(action="resend", captcha=text), "کد جدید پیامک شد")
            self.assertEqual(len(sent), 2)
            # Entering the SMS code itself never needs the picture.
            code = sent[-1][2]["code"]
            self.assertEqual(self.post(action="verify", code=code).status_code, 302)

    @CAPTCHA_ON
    @override_settings(OTP_CAPTCHA_SITE_PER_10_MIN=2)
    def test_site_wide_attack_shows_it_to_a_new_visitor(self):
        with capture_sms() as sent:
            for i in range(2):
                otp.send_code(f"0912000000{i}", LOGIN, f"1.1.1.{i}")
            self.assertContains(self.client.get(self.url), reverse("accounts:captcha"))
            self.assertContains(self.post(action="send", mobile="09120000009"), captcha.REQUIRED_MESSAGE)
            self.assertEqual(len(sent), 2)

    @CAPTCHA_ON
    def test_ordinary_login_has_no_picture_code(self):
        with capture_sms() as sent:
            self.assertNotContains(self.client.get(self.url), reverse("accounts:captcha"))
            response = self.post(action="send", mobile="09120000001")
            self.assertNotContains(response, reverse("accounts:captcha"))
            self.assertEqual(self.post(action="verify", code=sent[0][2]["code"]).status_code, 302)

    @CAPTCHA_ON
    @override_settings(OTP_CAPTCHA_AFTER_PER_IP=1)
    def test_guest_checkout_uses_the_same_rule(self):
        from catalog.tests.utils import make_product
        from orders.tests.utils import configure_payments

        configure_payments()
        self.client.post(reverse("cart:add", args=[make_product(price=150_000, stock=5).pk]), {"quantity": 1})
        url = reverse("orders:checkout_mobile")
        with capture_sms() as sent:
            otp.send_code("09120000001", LOGIN, "127.0.0.1")
            response = self.client.post(url, {"action": "send", "mobile": "09120000002"}, headers={"HX-Request": "true"})
            self.assertContains(response, captcha.REQUIRED_MESSAGE)
            self.assertContains(response, reverse("accounts:captcha"))
            self.assertEqual(len(sent), 1)
            text = load_picture(self.client)
            self.client.post(url, {"action": "send", "mobile": "09120000002", "captcha": text})
            self.assertEqual(len(sent), 2)
