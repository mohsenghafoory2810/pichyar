import json
import shutil
import tempfile
import threading
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from catalog.models import Category, Product
from catalog.tests.utils import image_upload, make_product
from core.models import SiteSettings
from orders.models import Order, OrderStatus, PaymentMethod
from orders.services import SESSION_ORDERS_KEY
from orders.tests.utils import capture_sms, configure_payments, make_order
from payments import services
from payments.gateways import GatewayError, get_gateway, registry
from payments.gateways.zarinpal import ZarinpalGateway
from payments.models import Payment

POST = "payments.gateways.zarinpal.ZarinpalGateway._post"
REQUEST_OK = {"data": {"code": 100, "message": "Success", "authority": "A0000000000000000000000000000abc"}, "errors": []}
VERIFY_OK = {"data": {"code": 100, "ref_id": 201, "card_pan": "502229******5995"}, "errors": []}
VERIFY_AGAIN = {"data": {"code": 101, "ref_id": 201, "card_pan": "502229******5995"}, "errors": []}
VERIFY_FAIL = {"data": [], "errors": {"code": -51, "message": "Session is not valid"}}


class ZarinpalTests(TestCase):
    def setUp(self):
        self.s = configure_payments()
        self.p = make_product(price=150_000, stock=10)
        self.order = make_order((self.p, 2), method=PaymentMethod.ONLINE)

    def test_registered_and_selected_in_settings(self):
        self.assertIn(("zarinpal", "زرین‌پال"), registry.choices())
        gateway = get_gateway(self.s)
        self.assertIsInstance(gateway, ZarinpalGateway)
        self.assertEqual(gateway.base_url, "https://payment.zarinpal.com")
        self.s.gateway_sandbox = True
        self.assertEqual(get_gateway(self.s).base_url, "https://sandbox.zarinpal.com")

    def test_request_sends_rials_and_builds_start_pay_url(self):
        with mock.patch(POST, return_value=REQUEST_OK) as post:
            redirect = get_gateway(self.s).request(self.order, "https://shop.ir/payments/callback/1/")
        path, payload = post.call_args.args
        self.assertEqual(path, "/pg/v4/payment/request.json")
        self.assertEqual(payload["amount"], self.order.total * 10)
        self.assertEqual(payload["currency"], "IRR")
        self.assertEqual(payload["merchant_id"], self.s.gateway_merchant_id)
        self.assertEqual(redirect.url, "https://payment.zarinpal.com/pg/StartPay/A0000000000000000000000000000abc")

    def test_request_error_code(self):
        body = {"data": [], "errors": {"code": -10, "message": "merchant invalid"}}
        with mock.patch(POST, return_value=body), self.assertRaisesMessage(GatewayError, "مرچنت"):
            get_gateway(self.s).request(self.order, "https://x/")

    def test_network_error_becomes_gateway_error(self):
        gateway = get_gateway(self.s)
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            with self.assertRaisesMessage(GatewayError, "ارتباط با درگاه"):
                gateway.request(self.order, "https://x/")

    def test_http_error_body_is_parsed(self):
        err = urllib.error.HTTPError("u", 400, "bad", {}, BytesIO(json.dumps({"data": [], "errors": {"code": -9}}).encode()))
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaisesMessage(GatewayError, "اطلاعات ارسالی"):
                get_gateway(self.s).request(self.order, "https://x/")

    def test_verify_codes(self):
        gateway = get_gateway(self.s)
        payment = Payment(order=self.order, amount=self.order.total, authority="A1")
        ok = RequestFactory().get("/", {"Authority": "A1", "Status": "OK"})
        for body, success in ((VERIFY_OK, True), (VERIFY_AGAIN, True), (VERIFY_FAIL, False)):
            with mock.patch(POST, return_value=body) as post:
                result = gateway.verify(ok, payment)
            self.assertEqual(result.success, success)
            self.assertEqual(post.call_args.args[1]["amount"], self.order.total * 10)
        self.assertEqual(result.message, "پرداخت ناموفق بود.")
        with mock.patch(POST) as post:
            result = gateway.verify(RequestFactory().get("/", {"Authority": "A1", "Status": "NOK"}), payment)
        post.assert_not_called()
        self.assertTrue(result.canceled)


class CallbackTests(TestCase):
    def setUp(self):
        configure_payments()
        self.p = make_product(price=150_000, stock=3)
        self.order = make_order((self.p, 2), method=PaymentMethod.ONLINE)
        session = self.client.session
        session[SESSION_ORDERS_KEY] = [self.order.number]
        session.save()
        self.factory = RequestFactory()
        self.payment = self.start()

    def start(self):
        with mock.patch(POST, return_value=REQUEST_OK):
            _, payment = services.start_online_payment(self.order, self.factory.get("/"))
        return payment

    def callback(self, status="OK", authority=None, verify=VERIFY_OK):
        params = {"Authority": authority or self.payment.authority, "Status": status}
        with mock.patch(POST, return_value=verify) as post, capture_sms() as sent, self.captureOnCommitCallbacks(execute=True):
            response = self.client.get(reverse("payments:callback", args=[self.payment.pk]), params)
        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.p.refresh_from_db()
        return response, post, sent

    def test_success(self):
        response, post, sent = self.callback()
        self.assertRedirects(response, reverse("payments:result", args=[self.payment.pk]), fetch_redirect_response=False)
        self.assertEqual(self.payment.status, Payment.Status.SUCCEEDED)
        self.assertEqual((self.payment.ref_id, self.payment.card_pan), ("201", "502229******5995"))
        self.assertEqual(self.order.status, OrderStatus.PAID_PROCESSING)
        self.assertEqual(self.p.stock, 1)
        self.assertEqual(post.call_count, 1)
        self.assertEqual([k for _, k, _ in sent], ["payment_confirmed"])
        result = self.client.get(reverse("payments:result", args=[self.payment.pk]))
        self.assertContains(result, "پرداخت موفق")
        self.assertContains(result, "۲۰۱")

    def test_repeated_callbacks_are_idempotent(self):
        self.callback()
        for _ in range(3):
            _, post, sent = self.callback(verify=VERIFY_AGAIN)
            post.assert_not_called()  # final payments are never verified again
            self.assertEqual(sent, [])
        self.assertEqual(self.p.stock, 1)  # reserved once
        self.assertEqual(self.order.status_logs.filter(to_status=OrderStatus.PAID_PROCESSING).count(), 1)

    def test_cancel_at_gateway(self):
        _, post, _ = self.callback(status="NOK")
        post.assert_not_called()
        self.assertEqual(self.payment.status, Payment.Status.CANCELED)
        self.assertEqual(self.order.status, OrderStatus.FAILED)
        self.assertEqual(self.p.stock, 3)
        self.assertContains(self.client.get(reverse("payments:result", args=[self.payment.pk])), "پرداخت دوباره")

    def test_retry_after_failure(self):
        self.callback(status="NOK")
        self.payment = self.start()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PENDING_PAYMENT)
        self.callback()
        self.assertEqual(self.order.status, OrderStatus.PAID_PROCESSING)
        self.assertEqual(self.p.stock, 1)

    def test_retry_view(self):
        self.callback(status="NOK")
        with mock.patch(POST, return_value=REQUEST_OK):
            response = self.client.post(reverse("payments:start", args=[self.order.number]))
        self.assertTrue(response["Location"].startswith("https://payment.zarinpal.com/pg/StartPay/"))

    def test_verify_failure_releases_stock(self):
        _, post, _ = self.callback(verify=VERIFY_FAIL)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(self.payment.status, Payment.Status.FAILED)
        self.assertEqual(self.order.status, OrderStatus.FAILED)
        self.assertFalse(self.order.stock_reserved)
        self.assertEqual(self.p.stock, 3)

    def test_out_of_stock_before_verify_never_captures(self):
        Product.objects.filter(pk=self.p.pk).update(stock=1)
        _, post, _ = self.callback()
        post.assert_not_called()  # unverified Zarinpal payments are refunded automatically
        self.assertEqual(self.payment.status, Payment.Status.FAILED)
        self.assertEqual(self.order.status, OrderStatus.FAILED)
        self.assertIn("موجودی", self.payment.message)
        self.assertEqual(self.p.stock, 1)

    def test_wrong_authority_is_ignored(self):
        _, post, _ = self.callback(authority="FORGED")
        post.assert_not_called()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)
        self.assertEqual(self.p.stock, 3)

    def test_network_error_then_retry_verifies_once(self):
        with mock.patch(POST, side_effect=GatewayError("down")):
            self.client.get(reverse("payments:callback", args=[self.payment.pk]), {"Authority": self.payment.authority, "Status": "OK"})
        self.payment.refresh_from_db()
        self.p.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.VERIFYING)
        self.assertEqual(self.p.stock, 1)  # held while verifying
        _, post, _ = self.callback(verify=VERIFY_AGAIN)  # within 60 s: left alone
        post.assert_not_called()
        Payment.objects.filter(pk=self.payment.pk).update(updated_at=self.payment.updated_at.replace(year=2020))
        _, post, _ = self.callback(verify=VERIFY_AGAIN)  # stale: verified again, gateway says "already verified"
        self.assertEqual(post.call_count, 1)
        self.assertEqual(self.payment.status, Payment.Status.SUCCEEDED)
        self.assertEqual(self.order.status, OrderStatus.PAID_PROCESSING)
        self.assertEqual(self.p.stock, 1)  # still reserved only once

    def test_canceled_order_is_not_paid(self):
        self.order.cancel()
        _, post, _ = self.callback()
        post.assert_not_called()
        self.assertEqual(self.payment.status, Payment.Status.FAILED)
        self.assertEqual(self.order.status, OrderStatus.CANCELED)

    def test_result_page_hides_details_from_strangers(self):
        self.callback()
        self.client.cookies.clear()
        response = self.client.get(reverse("payments:result", args=[self.payment.pk]))
        self.assertContains(response, "پیگیری سفارش")
        self.assertNotContains(response, "مشاهدهٔ سفارش")

    def test_unknown_payment_is_404(self):
        self.assertEqual(self.client.get(reverse("payments:callback", args=[99999])).status_code, 404)

    def test_online_unavailable_without_merchant(self):
        s = SiteSettings.load()
        s.gateway_merchant_id = ""
        s.save()
        with self.assertRaisesMessage(services.PaymentError, "در دسترس نیست"):
            services.start_online_payment(self.order, self.factory.get("/"))


class ConcurrentCallbackTests(TransactionTestCase):
    def setUp(self):
        category = Category.objects.create(name="آزمایشی", slug="test-cat")
        self.product = Product.objects.create(name="پرفروش", price=1000, stock=5, category=category)
        configure_payments()
        self.order = make_order((self.product, 2), method=PaymentMethod.ONLINE)
        with mock.patch(POST, return_value=REQUEST_OK):
            _, self.payment = services.start_online_payment(self.order, RequestFactory().get("/"))

    def test_parallel_callbacks_confirm_once(self):
        n = 6
        barrier = threading.Barrier(n)
        verify_calls = []
        request = RequestFactory().get("/", {"Authority": self.payment.authority, "Status": "OK"})

        def fake_post(path, payload):
            verify_calls.append(path)
            return VERIFY_OK

        errors = []

        def worker():
            try:
                barrier.wait()
                services.process_callback(request, self.payment.pk)
            except Exception as e:
                errors.append(repr(e))
            finally:
                connection.close()

        with mock.patch(POST, side_effect=fake_post), capture_sms():
            threads = [threading.Thread(target=worker) for _ in range(n)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(verify_calls), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PAID_PROCESSING)
        self.assertEqual(self.order.status_logs.filter(to_status=OrderStatus.PAID_PROCESSING).count(), 1)


class CardToCardTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._private = tempfile.mkdtemp(prefix="pichyar-private-")
        cls._override = override_settings(PRIVATE_MEDIA_ROOT=Path(cls._private))
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._private, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        configure_payments()
        self.p = make_product(price=250_000, stock=4)
        self.order = make_order((self.p, 1))
        session = self.client.session
        session[SESSION_ORDERS_KEY] = [self.order.number]
        session.save()
        self.url = reverse("payments:card", args=[self.order.number])

    def test_page_shows_cards_holder_and_exact_total(self):
        response = self.client.get(self.url)
        self.assertContains(response, "۶۰۳۷-۹۹۱۲-۳۴۵۶-۷۸۹۰")
        self.assertContains(response, "به نام فروشگاه")
        self.assertContains(response, "۴۵۰٬۰۰۰ تومان")

    def test_submit_with_receipt(self):
        response = self.client.post(self.url, {"tracking_number": "۹۸۷۶۵۴", "receipt": image_upload("r.png", "PNG", (400, 300))})
        self.assertRedirects(response, self.order.get_absolute_url(), fetch_redirect_response=False)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.AWAITING_APPROVAL)
        payment = self.order.payments.get()
        self.assertEqual(payment.tracking_number, "987654")
        stored = Path(settings.PRIVATE_MEDIA_ROOT) / payment.receipt.name
        self.assertTrue(stored.exists())
        self.assertFalse(str(stored).startswith(str(settings.MEDIA_ROOT)))
        # customers can't fetch receipts; staff can
        self.assertEqual(self.client.get(reverse("payments:receipt", args=[payment.pk])).status_code, 302)
        from django.contrib.auth import get_user_model

        self.client.force_login(get_user_model().objects.create_user("09120000001", password="x", is_staff=True))
        self.assertEqual(self.client.get(reverse("payments:receipt", args=[payment.pk])).status_code, 200)

    def test_receipt_is_optional(self):
        self.client.post(self.url, {"tracking_number": "123456"})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.AWAITING_APPROVAL)

    def test_invalid_receipt_type(self):
        fake = SimpleUploadedFile("r.png", b"not an image", content_type="image/png")
        response = self.client.post(self.url, {"tracking_number": "123456", "receipt": fake})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Payment.objects.exists())

    def test_gif_is_refused(self):
        response = self.client.post(self.url, {"tracking_number": "123456", "receipt": image_upload("r.gif", "GIF", (50, 50))})
        self.assertContains(response, "فقط تصویرهای JPG، PNG یا WebP")
        self.assertFalse(Payment.objects.exists())

    @override_settings(RECEIPT_MAX_MB=0)
    def test_receipt_too_big(self):
        response = self.client.post(self.url, {"tracking_number": "123456", "receipt": image_upload("r.jpg")})
        self.assertContains(response, "حجم تصویر نباید بیشتر از")
        self.assertFalse(Payment.objects.exists())

    def test_tracking_number_validation(self):
        response = self.client.post(self.url, {"tracking_number": "12"})
        self.assertContains(response, "کد پیگیری معتبر نیست")

    def test_second_submission_is_not_possible(self):
        self.client.post(self.url, {"tracking_number": "123456"})
        response = self.client.get(self.url)
        self.assertRedirects(response, self.order.get_absolute_url(), fetch_redirect_response=False)
        with self.assertRaises(services.PaymentError):
            services.submit_card_transfer(Order.objects.get(pk=self.order.pk), "222222")
