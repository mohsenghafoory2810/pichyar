"""Security hardening: request throttle, guessable lookups, receipt access, spreadsheet
formulas, admin privilege escalation and unused public URLs."""

import shutil
import tempfile
import time
from io import BytesIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice
from openpyxl import load_workbook

from accounts import otp
from catalog.tests.utils import image_upload, make_product
from core import ratelimit
from orders import export
from orders.models import DiscountCode, PaymentMethod
from orders.services import SESSION_ORDERS_KEY
from orders.tests.utils import capture_sms, configure_payments, make_order
from payments.models import Payment

User = get_user_model()
LIMITS_ON = override_settings(RATE_LIMITS_ENABLED=True)


def staff(mobile, *perms, superuser=False):
    user = User.objects.create_user(mobile, password="secret-pass-1", is_staff=True, is_superuser=superuser)
    for perm in perms:
        app_label, codename = perm.split(".")
        user.user_permissions.add(Permission.objects.get(content_type__app_label=app_label, codename=codename))
    return user


class RateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.request = RequestFactory().get("/", REMOTE_ADDR="10.0.0.1")

    @LIMITS_ON
    def test_over_the_limit_is_refused_per_ip(self):
        results = [ratelimit.hit(self.request, "t", limit=3, window=60) for _ in range(5)]
        self.assertEqual(results, [False, False, False, True, True])
        other = RequestFactory().get("/", REMOTE_ADDR="10.0.0.2")
        self.assertFalse(ratelimit.hit(other, "t", limit=3, window=60))
        self.assertFalse(ratelimit.hit(self.request, "other-scope", limit=3, window=60))

    @LIMITS_ON
    def test_window_ends(self):
        ratelimit.hit(self.request, "t", limit=1, window=60)
        self.assertTrue(ratelimit.hit(self.request, "t", limit=1, window=60))
        with mock.patch("core.ratelimit.time.time", return_value=time.time() + 61):
            self.assertFalse(ratelimit.hit(self.request, "t", limit=1, window=60))

    def test_switched_off_in_the_test_settings(self):
        self.assertFalse(any(ratelimit.hit(self.request, "t", limit=1, window=60) for _ in range(5)))


class GuessingTests(TestCase):
    def setUp(self):
        cache.clear()
        configure_payments()
        self.product = make_product(price=150_000, stock=10)
        self.order = make_order((self.product, 1), mobile="09121111111")

    def track(self, number):
        return self.client.post(reverse("orders:track"), {"mobile": "09121111111", "number": number})

    @LIMITS_ON
    @override_settings(TRACK_MAX_PER_IP=3)
    def test_order_tracking_cannot_be_brute_forced(self):
        for _ in range(3):
            self.assertContains(self.track("1"), "پیدا نشد")
        # Over the limit even the right number shows nothing.
        response = self.track(self.order.number)
        self.assertContains(response, ratelimit.TOO_MANY_MESSAGE)
        self.assertNotContains(response, self.order.recipient_name)

    def test_tracking_still_works(self):
        self.assertContains(self.track(self.order.number), self.order.recipient_name)

    @LIMITS_ON
    @override_settings(DISCOUNT_MAX_TRIES_PER_IP=3)
    def test_discount_codes_cannot_be_brute_forced(self):
        DiscountCode.objects.create(code="REAL10", value=10)
        self.client.post(reverse("cart:add", args=[self.product.pk]), {"quantity": 1})
        apply = lambda code: self.client.post(  # noqa: E731
            reverse("orders:discount"), {"code": code, "discount_action": "apply", "where": "cart"}, follow=True
        )
        for i in range(3):
            self.assertContains(apply(f"GUESS{i}"), "معتبر نیست")
        self.assertContains(apply("REAL10"), ratelimit.TOO_MANY_MESSAGE)
        self.assertNotIn("discount_code", self.client.session)

    @override_settings(OTP_MAX_PER_MOBILE_PER_DAY=2, OTP_RESEND_COOLDOWN=0, OTP_MAX_PER_MOBILE_PER_HOUR=100)
    def test_sms_codes_per_mobile_per_day(self):
        with capture_sms():
            otp.send_code("09123334455", "login")
            otp.send_code("09123334455", "login")
            with self.assertRaises(otp.OTPError) as ctx:
                otp.send_code("09123334455", "login")
        self.assertEqual(ctx.exception.code, "rate_mobile")


class PaymentPrivacyTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls._private = tempfile.mkdtemp(prefix="pichyar-private-")
        cls._override = override_settings(PRIVATE_MEDIA_ROOT=cls._private)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._private, ignore_errors=True)

    def setUp(self):
        configure_payments()
        self.product = make_product(price=150_000, stock=10)
        self.order = make_order((self.product, 1), method=PaymentMethod.ONLINE)

    def test_result_page_shows_the_order_only_to_its_owner(self):
        payment = Payment.objects.create(
            order=self.order, method=PaymentMethod.ONLINE, amount=self.order.total, status="succeeded", ref_id="778899"
        )
        url = reverse("payments:result", args=[payment.pk])
        stranger = self.client.get(url)
        self.assertContains(stranger, "پرداخت موفق")
        self.assertNotContains(stranger, "شمارهٔ سفارش")
        self.assertNotContains(stranger, "۷۷۸۸۹۹")
        session = self.client.session
        session[SESSION_ORDERS_KEY] = [self.order.number]
        session.save()
        self.assertContains(self.client.get(url), "۷۷۸۸۹۹")

    def _receipt(self, name="r.png", data=None):
        payment = Payment(order=self.order, method=PaymentMethod.CARD, amount=self.order.total)
        payment.receipt.save(name, ContentFile(data if data is not None else image_upload(name, "PNG", (20, 20)).read()))
        payment.save()
        return payment

    def test_receipt_needs_an_admin_session_with_the_order_permission(self):
        url = reverse("payments:receipt", args=[self._receipt().pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(staff("09120000001"))
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(staff("09120000002", "orders.view_order"))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn("sandbox", response["Content-Security-Policy"])
        b"".join(response.streaming_content)  # read to the end (closes the file)

    def test_receipt_is_closed_to_a_storefront_session_of_a_staff_member(self):
        url = reverse("payments:receipt", args=[self._receipt().pk])
        user = staff("09120000003", "orders.view_order")
        self.client.force_login(user, backend="accounts.backends.SMSCodeBackend")
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_receipt_needs_the_2fa_code_when_it_is_on(self):
        url = reverse("payments:receipt", args=[self._receipt().pk])
        user = staff("09120000004", "orders.view_order")
        TOTPDevice.objects.create(user=user, name="x", confirmed=True)
        self.client.force_login(user)  # password only, no code
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_receipt_name_and_type_never_come_from_the_client(self):
        payment = self._receipt("evil.html")
        self.assertTrue(payment.receipt.name.endswith(".jpg"))
        self.client.force_login(staff("09120000005", superuser=True))
        response = self.client.get(reverse("payments:receipt", args=[payment.pk]))
        self.assertEqual(response["Content-Type"], "image/png")  # the real format, not the name
        b"".join(response.streaming_content)  # read to the end (closes the file)
        html = self._receipt("page.png", b"<html><script>alert(1)</script></html>")
        self.assertEqual(self.client.get(reverse("payments:receipt", args=[html.pk])).status_code, 404)


class ExportFormulaTests(TestCase):
    def test_customer_text_is_never_a_formula(self):
        self.assertEqual(export.safe_cell("=HYPERLINK(\"http://x\")"), "'=HYPERLINK(\"http://x\")")
        for value in ("+1", "-1", "@SUM(A1)", "\t=1"):
            self.assertTrue(export.safe_cell(value).startswith("'"))
        self.assertEqual(export.safe_cell("علی رضایی"), "علی رضایی")
        self.assertEqual(export.safe_cell(1500), 1500)

    def test_workbook_cells(self):
        order = make_order((make_product(), 1))
        order.recipient_name = "=1+1"
        order.note = "@cmd"
        order.save(update_fields=["recipient_name", "note"])
        out = BytesIO()
        export.orders_workbook([order]).save(out)
        sheet = load_workbook(BytesIO(out.getvalue())).active
        for cell in sheet[2]:
            self.assertNotEqual(cell.data_type, "f")
        self.assertEqual(sheet.cell(row=2, column=7).value, "'=1+1")
        self.assertEqual(sheet.cell(row=2, column=18).value, order.total)


class AdminPrivilegeTests(TestCase):
    def setUp(self):
        self.boss = staff("09120000010", superuser=True)
        self.clerk = staff("09120000011", "accounts.change_user", "accounts.view_user", "accounts.delete_user")
        self.customer = User.objects.create_user("09120000012")
        self.client.force_login(self.clerk)

    def url(self, user, name="change"):
        return reverse(f"admin:accounts_user_{name}", args=[user.pk])

    def test_clerk_cannot_make_anyone_superuser(self):
        data = {
            "mobile": self.customer.mobile,
            "name": "مشتری",
            "is_active": "on",
            "is_staff": "on",
            "is_superuser": "on",
            "date_joined_0": "2025-01-01",
            "date_joined_1": "00:00:00",
            "addresses-TOTAL_FORMS": 0,
            "addresses-INITIAL_FORMS": 0,
        }
        self.client.post(self.url(self.customer), data)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_staff)
        self.assertFalse(self.customer.is_superuser)

    def test_clerk_cannot_change_staff_accounts_or_their_passwords(self):
        for target in (self.boss, self.clerk):
            self.assertEqual(self.client.post(self.url(target), {"name": "x"}).status_code, 403)
            response = self.client.post(
                reverse("admin:auth_user_password_change", args=[target.pk]),
                {"password1": "New-pass-12345", "password2": "New-pass-12345"},
            )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(self.client.post(self.url(target, "delete"), {"post": "yes"}).status_code, 403)
        self.boss.refresh_from_db()
        self.assertTrue(self.boss.check_password("secret-pass-1"))
        self.assertTrue(User.objects.filter(pk=self.boss.pk).exists())

    def test_groups_are_for_superusers_only(self):
        group = Group.objects.create(name="فروش")
        clerk = staff("09120000013", "auth.change_group", "auth.view_group", "auth.add_group")
        self.client.force_login(clerk)
        self.assertEqual(self.client.get(reverse("admin:auth_group_change", args=[group.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:auth_group_add")).status_code, 403)
        self.client.force_login(self.boss)
        self.assertEqual(self.client.get(reverse("admin:auth_group_change", args=[group.pk])).status_code, 200)

    def test_only_a_superuser_turns_off_someone_elses_two_step_login(self):
        device = TOTPDevice.objects.create(user=self.boss, name="x", confirmed=True)
        clerk = staff("09120000014", "otp_totp.delete_totpdevice", "otp_totp.view_totpdevice")
        self.client.force_login(clerk)
        url = reverse("admin:otp_totp_totpdevice_delete", args=[device.pk])
        self.assertEqual(self.client.post(url, {"post": "yes"}).status_code, 403)
        self.assertTrue(TOTPDevice.objects.filter(pk=device.pk).exists())


class PublicSurfaceTests(TestCase):
    def test_tinymce_views_are_not_public(self):
        for path in ("/tinymce/compressor/", "/tinymce/filebrowser/", "/tinymce/flatpages_link_list/"):
            self.assertEqual(self.client.get(path).status_code, 404)
