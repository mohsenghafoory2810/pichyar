import io
import json
import urllib.error
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from catalog.tests.utils import make_product
from core.models import SiteSettings
from notifications import services
from notifications.defaults import TEMPLATES
from notifications.models import SMSLog, SMSTemplate, sms_parts
from notifications.providers import BaseSMSProvider, ConsoleProvider, SMSError, SMSResult, get_provider, registry
from notifications.providers.kavenegar import KavenegarProvider
from orders.models import GiftPoolItem, Order
from orders.tests.utils import ADDRESS, configure_payments, make_order

S = SMSLog.Status
KAVENEGAR_SEND = "notifications.providers.kavenegar.KavenegarProvider.send"


def use_kavenegar(api_key="test-key", sender="10004346"):
    s = SiteSettings.load()
    s.sms_provider, s.sms_api_key, s.sms_sender = "kavenegar", api_key, sender
    s.save()
    return s


class TemplateTests(TestCase):
    def test_defaults_exist_for_every_key(self):
        self.assertEqual(set(SMSTemplate.objects.values_list("key", flat=True)), set(TEMPLATES))
        for key in TEMPLATES:
            SMSTemplate.objects.get(key=key).full_clean()

    def test_render_fills_placeholders(self):
        text = services.render("order_registered", {"order_number": "1234567", "total": 2_200_000})
        self.assertEqual(text, "سفارش 1234567 در پیچ‌یار ثبت شد.\nمبلغ قابل پرداخت: 2,200,000 تومان")
        shipped = services.render("shipped", {"order_number": "1234567", "tracking_code": "ABC123"})
        self.assertIn("کد رهگیری پست: ABC123", shipped)

    def test_edited_template_is_used_and_unknown_values_are_blank(self):
        SMSTemplate.objects.filter(key="otp").update(text="کد: {code} {missing}")
        self.assertEqual(services.render("otp", {"code": "12345"}), "کد: 12345")

    def test_broken_template_falls_back_to_default(self):
        SMSTemplate.objects.filter(key="otp").update(text="کد {code")
        self.assertIn("12345", services.render("otp", {"code": "12345"}))

    def test_admin_validation_of_placeholders(self):
        template = SMSTemplate.objects.get(key="otp")
        template.text = "کد {code} برای سفارش {order_number}"
        with self.assertRaises(ValidationError) as cm:
            template.full_clean()
        self.assertIn("{order_number}", cm.exception.message_dict["text"][0])
        self.assertIn("{code}", cm.exception.message_dict["text"][0])
        template.text = "کد {code"
        with self.assertRaisesMessage(ValidationError, "آکولاد"):
            template.full_clean()


class SmsPartsTests(SimpleTestCase):
    def test_parts(self):
        self.assertEqual(sms_parts("a" * 160), 1)
        self.assertEqual(sms_parts("a" * 161), 2)
        self.assertEqual(sms_parts("س" * 70), 1)
        self.assertEqual(sms_parts("س" * 71), 2)
        self.assertEqual(sms_parts("س" * 135), 3)


class ProviderRegistryTests(TestCase):
    def test_console_mode_without_api_key(self):
        s = SiteSettings.load()
        self.assertEqual(s.sms_provider, "kavenegar")
        self.assertIsInstance(get_provider(s), ConsoleProvider)
        self.assertIsInstance(get_provider(use_kavenegar()), KavenegarProvider)

    def test_unknown_provider_falls_back_to_console(self):
        s = use_kavenegar()
        s.sms_provider = "gone"
        self.assertIsInstance(get_provider(s), ConsoleProvider)

    def test_new_provider_needs_only_one_class(self):
        @registry.register
        class DummyProvider(BaseSMSProvider):
            key = "dummy"
            label = "آزمایشی"

            def send(self, mobile, text):
                return SMSResult(message_id="d1", response="ok")

        try:
            self.assertIn(("dummy", "آزمایشی"), registry.choices())
            s = use_kavenegar()
            s.sms_provider = "dummy"
            provider = get_provider(s)
            self.assertIsInstance(provider, DummyProvider)
            self.assertEqual((provider.api_key, provider.sender), ("test-key", "10004346"))
        finally:
            registry._providers.pop("dummy")


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class KavenegarTests(SimpleTestCase):
    def provider(self):
        return KavenegarProvider(api_key="KEY/1", sender="2000")

    def test_success(self):
        body = {"return": {"status": 200, "message": "تایید شد"}, "entries": [{"messageid": 8792343, "status": 1}]}
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse(json.dumps(body).encode())) as urlopen:
            result = self.provider().send("09121111111", "سلام")
        req = urlopen.call_args.args[0]
        self.assertEqual(req.full_url, "https://api.kavenegar.com/v1/KEY%2F1/sms/send.json")
        self.assertIn("receptor=09121111111", req.data.decode())
        self.assertIn("sender=2000", req.data.decode())
        self.assertEqual(result.message_id, "8792343")

    def http_error(self, status):
        body = json.dumps({"return": {"status": status, "message": "x"}, "entries": None}).encode()
        return urllib.error.HTTPError("url", status, "err", {}, io.BytesIO(body))

    def test_permanent_error(self):
        with mock.patch("urllib.request.urlopen", side_effect=self.http_error(403)):
            with self.assertRaises(SMSError) as cm:
                self.provider().send("09121111111", "سلام")
        self.assertFalse(cm.exception.retryable)
        self.assertIn("کلید API", cm.exception.message)

    def test_credit_error_is_retried(self):
        with mock.patch("urllib.request.urlopen", side_effect=self.http_error(418)):
            with self.assertRaises(SMSError) as cm:
                self.provider().send("09121111111", "سلام")
        self.assertTrue(cm.exception.retryable)

    def test_network_error_is_retried(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            with self.assertRaises(SMSError) as cm:
                self.provider().send("09121111111", "سلام")
        self.assertTrue(cm.exception.retryable)

    def test_bad_body(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse(b"<html>")):
            with self.assertRaisesMessage(SMSError, "پاسخ نامعتبر"):
                self.provider().send("09121111111", "سلام")


class ConsoleModeTests(TestCase):
    def test_logged_and_marked_sent_without_queue(self):
        with mock.patch("django_q.tasks.async_task") as async_task:
            log = services.send_sms("09121111111", "order_registered", {"order_number": "1", "total": 10})
        async_task.assert_not_called()
        log.refresh_from_db()
        self.assertEqual((log.status, log.provider, log.attempts, log.template_key), (S.SENT, "console", 1, "order_registered"))
        self.assertIn("ثبت شد", log.text)
        self.assertIsNotNone(log.sent_at)

    def test_login_code_is_not_kept_in_the_log(self):
        log = services.send_sms("09121111111", "otp", {"code": "48213"})
        log.refresh_from_db()
        self.assertNotIn("48213", log.text)
        self.assertIn("•••••", log.text)


class QueueAndRetryTests(TestCase):
    def setUp(self):
        use_kavenegar()

    def queue(self):
        with mock.patch("django_q.tasks.async_task") as async_task, self.captureOnCommitCallbacks(execute=True):
            log = services.send_sms("09121111111", "payment_confirmed", {"order_number": "7654321"})
        async_task.assert_called_once_with("notifications.tasks.deliver_sms", log.pk)
        return log

    def test_queued_then_delivered_by_the_job(self):
        log = self.queue()
        self.assertEqual(SMSLog.objects.get(pk=log.pk).status, S.QUEUED)
        with mock.patch(KAVENEGAR_SEND, return_value=SMSResult("m-1", '{"return":{"status":200}}')) as send:
            from notifications.tasks import deliver_sms

            self.assertEqual(deliver_sms(log.pk), S.SENT)
        send.assert_called_once_with("09121111111", log.text)
        log.refresh_from_db()
        self.assertEqual((log.status, log.message_id, log.attempts), (S.SENT, "m-1", 1))
        self.assertIn("status", log.provider_response)

    def test_retry_with_backoff_then_success(self):
        log = self.queue()
        with mock.patch(KAVENEGAR_SEND, side_effect=SMSError("قطع است", response="timeout")):
            before = timezone.now()
            self.assertEqual(services.deliver(log.pk), S.RETRYING)
        log.refresh_from_db()
        self.assertEqual((log.attempts, log.error, log.provider_response), (1, "قطع است", "timeout"))
        self.assertAlmostEqual((log.next_attempt_at - before).total_seconds(), 60, delta=5)

        with mock.patch(KAVENEGAR_SEND) as send:  # not due yet
            self.assertIsNone(services.deliver(log.pk))
            self.assertEqual(services.deliver_due(), 0)
        send.assert_not_called()

        SMSLog.objects.filter(pk=log.pk).update(next_attempt_at=timezone.now() - timedelta(seconds=1))
        with mock.patch(KAVENEGAR_SEND, side_effect=SMSError("باز هم")):
            self.assertEqual(services.deliver_due(), 1)
        log.refresh_from_db()
        self.assertEqual((log.status, log.attempts), (S.RETRYING, 2))
        self.assertAlmostEqual((log.next_attempt_at - timezone.now()).total_seconds(), 300, delta=5)

        SMSLog.objects.filter(pk=log.pk).update(next_attempt_at=timezone.now())
        with mock.patch(KAVENEGAR_SEND, return_value=SMSResult("m-2", "ok")):
            self.assertEqual(services.deliver(log.pk), S.SENT)
        log.refresh_from_db()
        self.assertEqual((log.status, log.attempts, log.error, log.next_attempt_at), (S.SENT, 3, "", None))

    def test_gives_up_after_max_attempts(self):
        log = self.queue()
        with mock.patch(KAVENEGAR_SEND, side_effect=SMSError("خطا")):
            for _ in range(services.MAX_ATTEMPTS):
                SMSLog.objects.filter(pk=log.pk).update(next_attempt_at=timezone.now())
                status = services.deliver(log.pk)
        log.refresh_from_db()
        self.assertEqual((status, log.status, log.attempts, log.next_attempt_at), (S.FAILED, S.FAILED, 5, None))
        self.assertIsNone(services.deliver(log.pk))

    def test_permanent_error_is_not_retried(self):
        log = self.queue()
        with mock.patch(KAVENEGAR_SEND, side_effect=SMSError("شماره نامعتبر", retryable=False)):
            self.assertEqual(services.deliver(log.pk), S.FAILED)

    def test_unexpected_exception_is_retried(self):
        log = self.queue()
        with mock.patch(KAVENEGAR_SEND, side_effect=RuntimeError("bug")):
            self.assertEqual(services.deliver(log.pk), S.RETRYING)
        self.assertEqual(SMSLog.objects.get(pk=log.pk).error, "bug")

    def test_never_sent_twice(self):
        log = self.queue()
        with mock.patch(KAVENEGAR_SEND, return_value=SMSResult()) as send:
            services.deliver(log.pk)
            self.assertIsNone(services.deliver(log.pk))
            services.deliver_due()
        self.assertEqual(send.call_count, 1)

    def test_lost_job_and_stuck_send_are_picked_up(self):
        lost = self.queue()
        fresh = self.queue()
        stuck = self.queue()
        old = timezone.now() - timedelta(minutes=11)
        SMSLog.objects.filter(pk=lost.pk).update(created_at=old)
        SMSLog.objects.filter(pk=stuck.pk).update(status=S.SENDING, updated_at=old)
        with mock.patch(KAVENEGAR_SEND, return_value=SMSResult()):
            self.assertEqual(services.deliver_due(), 2)
        statuses = {log.pk: log.status for log in SMSLog.objects.all()}
        self.assertEqual(statuses, {lost.pk: S.SENT, fresh.pk: S.QUEUED, stuck.pk: S.SENT})

    def test_queue_failure_never_raises(self):
        with mock.patch("notifications.services.SMSLog.objects.create", side_effect=RuntimeError("db")):
            self.assertIsNone(services.send_sms("09121111111", "otp", {"code": "1"}))
        with mock.patch("notifications.services.render", side_effect=RuntimeError("x")):
            self.assertIsNone(services.send_sms("09121111111", "otp", {"code": "1"}))
        with mock.patch("django_q.tasks.async_task", side_effect=RuntimeError("broker")), self.captureOnCommitCallbacks(
            execute=True
        ):
            log = services.send_text("09121111111", "متن")
        self.assertEqual(SMSLog.objects.get(pk=log.pk).status, S.QUEUED)  # the retry job sends it later


class AdminSettingsTests(TestCase):
    def test_numbers_are_normalised_and_validated(self):
        s = SiteSettings.load()
        s.admin_sms_numbers = "۰۹۱۲۱۱۱۲۲۲۲\n+989123334444, 09121112222"
        s.full_clean()
        self.assertEqual(s.admin_sms_numbers, "09121112222\n09123334444")
        self.assertEqual(s.admin_mobiles, ["09121112222", "09123334444"])
        s.admin_sms_numbers = "09121112222\n12345"
        with self.assertRaises(ValidationError) as cm:
            s.full_clean()
        self.assertIn("12345", cm.exception.message_dict["admin_sms_numbers"][0])


class AdminOrderSmsTests(TestCase):
    ADMINS = ["09350000001", "09350000002"]

    def setUp(self):
        s = configure_payments()
        s.admin_sms_numbers = "\n".join(self.ADMINS)
        s.save()
        self.tubes = make_product("پوکه ۲۰۰ نخی پرستون", price=1_000_000, stock=50, short_name="پوکه پرستون")
        self.arizona = make_product("آریزونا", price=300_000, stock=10)
        self.shamzin = make_product("شمزین", price=300_000, stock=10)
        GiftPoolItem.objects.create(product=self.shamzin, gift_stock=5)

    def order(self):
        return make_order((self.tubes, 16), (self.arizona, 3), gifts={self.shamzin.pk: 2})

    def admin_logs(self):
        return SMSLog.objects.filter(template_key="admin_new_order")

    def test_text_format(self):
        expected = "\n".join(
            [
                "پوکه پرستون 16",
                "آریزونا 3",
                "شمزین 2 (هدیه)",
                ADDRESS["recipient_name"],
                ADDRESS["recipient_mobile"],
                ADDRESS["postal_code"],
                f"{ADDRESS['province']}، {ADDRESS['city']}، {ADDRESS['address']}",
            ]
        )
        self.assertEqual(services.build_admin_order_text(self.order()), expected)

    def test_sent_once_when_paid(self):
        order = self.order()
        self.assertFalse(self.admin_logs().exists())  # not on registration
        with self.captureOnCommitCallbacks(execute=True):
            order.confirm_payment()
        with self.captureOnCommitCallbacks(execute=True):
            order.confirm_payment()  # idempotent: no second message
            order.mark_shipped("TRACK1")
        logs = self.admin_logs()
        self.assertEqual(sorted(logs.values_list("mobile", flat=True)), self.ADMINS)
        self.assertEqual(logs[0].text, services.build_admin_order_text(order))
        order.refresh_from_db()
        self.assertIsNotNone(order.admin_sms_queued_at)

    def test_card_approval_sends_it(self):
        from payments.services import submit_card_transfer

        order = self.order()
        submit_card_transfer(order, "1")
        with self.captureOnCommitCallbacks(execute=True):
            order.approve()
        self.assertEqual(self.admin_logs().count(), 2)

    def test_toggle_off(self):
        SiteSettings.objects.update(admin_sms_enabled=False)
        with self.captureOnCommitCallbacks(execute=True):
            self.order().confirm_payment()
        self.assertFalse(self.admin_logs().exists())

    def test_resend(self):
        order = self.order()
        logs = services.resend_admin_sms(order)
        self.assertEqual(len(logs), 2)
        SiteSettings.objects.update(admin_sms_enabled=False)
        self.assertEqual(len(services.resend_admin_sms(order)), 2)  # explicit resend ignores the toggle

    def test_long_message_is_never_truncated(self):
        many = [make_product(f"کالای شمارهٔ {i}", price=100_000, stock=5, short_name=f"کالای {i}") for i in range(30)]
        order = make_order(*[(p, 1) for p in many])
        text = services.build_admin_order_text(order)
        log = services.resend_admin_sms(order)[0]
        self.assertEqual(log.text, text)
        self.assertGreater(log.parts, 3)
        self.assertIn("کالای 29 1", log.text)

    def test_failure_does_not_block_confirmation(self):
        order = self.order()
        with mock.patch("notifications.services.build_admin_order_text", side_effect=RuntimeError("x")):
            with self.captureOnCommitCallbacks(execute=True):
                order.confirm_payment()
        order.refresh_from_db()
        self.assertEqual(order.status, "paid_processing")


class CheckoutSurvivesSmsFailureTests(TestCase):
    def setUp(self):
        configure_payments()
        use_kavenegar()
        self.p = make_product("دیویدوف", price=1_000_000, stock=5)
        self.user = get_user_model().objects.create_user(mobile="09125556666")
        self.client.force_login(self.user)
        self.client.post(reverse("cart:add", args=[self.p.pk]), {"quantity": 2})

    def checkout(self):
        total = self.client.get(reverse("orders:checkout")).context["breakdown"].total
        data = {**ADDRESS, "payment_method": "card", "age_confirmed": "on", "note": "", "expected_total": total}
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse("orders:checkout"), data)

    def test_broker_down(self):
        with mock.patch("django_q.tasks.async_task", side_effect=RuntimeError("broker down")):
            response = self.checkout()
        order = Order.objects.get()
        self.assertRedirects(response, reverse("payments:card", args=[order.number]))
        self.assertEqual(SMSLog.objects.get().status, S.QUEUED)

    def test_database_error_while_logging(self):
        with mock.patch("notifications.services.SMSLog.objects.create", side_effect=RuntimeError("db")):
            response = self.checkout()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Order.objects.exists())

    def test_provider_failure_in_console_mode(self):
        SiteSettings.objects.update(sms_api_key="")
        with mock.patch.object(ConsoleProvider, "send", side_effect=RuntimeError("boom")):
            response = self.checkout()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SMSLog.objects.get().status, S.RETRYING)
