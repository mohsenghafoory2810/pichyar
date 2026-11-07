from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from catalog.models import Product
from catalog.tests.utils import TempMediaMixin, image_upload, make_product
from core.models import SiteSettings
from notifications.models import SMSLog
from orders.models import DiscountCode, DiscountType, GiftPoolItem, Order, OrderStatus
from payments.services import submit_card_transfer

from .utils import capture_sms, configure_payments, make_order

S = OrderStatus


class OrderAdminTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("09120000001", password="pass")

    def setUp(self):
        configure_payments()
        self.client.force_login(self.admin)
        self.paid = make_product("آریزونا", price=1_000_000, stock=10, short_name="آریزونا")
        self.gift = make_product("شمزین", price=50_000, stock=5)
        GiftPoolItem.objects.create(product=self.gift, gift_stock=3)
        self.code = DiscountCode.objects.create(code="OFF", kind=DiscountType.FIXED, value=10_000)
        with capture_sms():
            self.order = make_order((self.paid, 4), gifts={self.gift.pk: 1}, discount_code="OFF")

    def change_url(self, order=None):
        return reverse("admin:orders_order_change", args=[(order or self.order).pk])

    def act(self, action, data=None, order=None):
        with capture_sms() as sent:
            response = self.client.post(
                reverse("admin:orders_order_action", args=[(order or self.order).pk, action]), data or {}
            )
        self.sent = sent
        self.order.refresh_from_db()
        return response

    def approved(self):
        submit_card_transfer(self.order, "123456")
        self.act("approve")
        self.assertEqual(self.order.status, S.PAID_PROCESSING)


class OrderListTests(OrderAdminTestCase):
    def test_list_filters_and_search(self):
        url = reverse("admin:orders_order_changelist")
        for params in ["", "?status__exact=pending_payment", "?payment_method__exact=card", "?created=today",
                       "?created=week", "?created=month", "?created=last_month", "?created=30d"]:
            with self.subTest(params=params):
                self.assertEqual(self.client.get(url + params).status_code, 200)
        self.assertContains(self.client.get(url + "?created=today"), self.order.number)
        self.assertNotContains(self.client.get(url + "?created=last_month"), self.order.number)
        self.assertNotContains(self.client.get(url + "?status__exact=shipped"), self.order.number)

    def test_search_by_mobile_number_and_name_with_persian_digits(self):
        url = reverse("admin:orders_order_changelist")
        persian_number = self.order.number.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
        for q in ["۰۹۱۲۱۱۱۱۱۱۱", persian_number, "رضایی"]:
            with self.subTest(q=q):
                self.assertContains(self.client.get(url, {"q": q}), self.order.number)
        self.assertNotContains(self.client.get(url, {"q": "09359999999"}), self.order.number)

    def test_no_add_or_delete(self):
        self.assertEqual(self.client.get(reverse("admin:orders_order_add")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:orders_order_delete", args=[self.order.pk])).status_code, 403)

    def test_customers_cannot_see_admin(self):
        customer = get_user_model().objects.create_user("09125555555")
        self.client.force_login(customer)
        response = self.client.get(reverse("admin:orders_order_changelist"))
        self.assertEqual(response.status_code, 302)


class OrderDetailTests(TempMediaMixin, OrderAdminTestCase):
    def test_detail_shows_items_gift_address_payment_and_history(self):
        submit_card_transfer(self.order, "987654", receipt=image_upload("r.jpg", size=(50, 50)))
        response = self.client.get(self.change_url())
        self.assertEqual(response.status_code, 200)
        payment = self.order.payments.get()
        for text in ["آریزونا", "شمزین", "هدیه", "خیابان آزادی", "1234567890", "987654",
                     reverse("payments:receipt", args=[payment.pk]), "در انتظار تأیید پرداخت",
                     "تأیید پرداخت کارت به کارت", "رد پرداخت", "لغو سفارش", "تاریخچهٔ وضعیت", "OFF"]:
            self.assertContains(response, text)
        self.assertNotContains(response, "ثبت ارسال")
        self.assertEqual(self.client.get(reverse("payments:receipt", args=[payment.pk])).status_code, 200)

    def test_post_to_change_view_is_refused(self):
        self.assertEqual(self.client.post(self.change_url(), {"status": "delivered"}).status_code, 405)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, S.PENDING_PAYMENT)


class OrderActionTests(OrderAdminTestCase):
    def test_approve_reserves_stock_and_counts_discount(self):
        self.approved()
        self.assertEqual(Product.objects.get(pk=self.paid.pk).stock, 6)
        self.assertEqual(Product.objects.get(pk=self.gift.pk).stock, 4)
        self.assertEqual(GiftPoolItem.objects.get(product=self.gift).gift_stock, 2)
        self.assertEqual(DiscountCode.objects.get(pk=self.code.pk).used_count, 1)
        log = self.order.status_logs.last()
        self.assertEqual(log.changed_by, self.admin)

    def test_approve_without_enough_stock_shows_persian_error(self):
        submit_card_transfer(self.order, "123456")
        Product.objects.filter(pk=self.paid.pk).update(stock=1)
        response = self.act("approve")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.order.status, S.AWAITING_APPROVAL)
        page = self.client.get(self.change_url())
        self.assertContains(page, "موجودی کافی نیست")

    def test_reject_cancels_with_reason(self):
        submit_card_transfer(self.order, "123456")
        self.act("reject", {"reason": "مبلغ واریز نشده"})
        self.assertEqual(self.order.status, S.CANCELED)
        self.assertEqual(self.order.payments.get().status, "rejected")
        self.assertEqual(self.order.status_logs.last().note, "مبلغ واریز نشده")

    def test_ship_requires_tracking_code_and_sends_sms(self):
        self.approved()
        self.act("ship", {"tracking_code": ""})
        self.assertEqual(self.order.status, S.PAID_PROCESSING)
        self.act("ship", {"tracking_code": "۱۲۳۴ ۵۶۷۸ ۹۰۱۲"})
        self.assertEqual(self.order.status, S.SHIPPED)
        self.assertEqual(self.order.post_tracking_code, "123456789012")

    def test_ship_sms_goes_out_on_commit(self):
        self.approved()
        with self.captureOnCommitCallbacks(execute=True):
            self.act("ship", {"tracking_code": "123456789012"})
        log = SMSLog.objects.filter(template_key="shipped").get()
        self.assertIn("123456789012", log.text)
        self.assertEqual(log.mobile, self.order.mobile)

    def test_deliver(self):
        self.approved()
        self.act("ship", {"tracking_code": "123456789012"})
        self.act("deliver")
        self.assertEqual(self.order.status, S.DELIVERED)

    def test_cancel_confirmed_restores_stock_discount_and_gift_stock(self):
        self.approved()
        self.act("cancel", {"note": "درخواست مشتری"})
        self.assertEqual(self.order.status, S.CANCELED)
        self.assertEqual(Product.objects.get(pk=self.paid.pk).stock, 10)
        self.assertEqual(Product.objects.get(pk=self.gift.pk).stock, 5)
        self.assertEqual(GiftPoolItem.objects.get(product=self.gift).gift_stock, 3)
        self.assertEqual(DiscountCode.objects.get(pk=self.code.pk).used_count, 0)

    def test_invalid_transition_is_a_message_not_a_crash(self):
        response = self.act("deliver")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.order.status, S.PENDING_PAYMENT)
        self.assertContains(self.client.get(self.change_url()), "مجاز نیست")

    def test_actions_need_post(self):
        url = reverse("admin:orders_order_action", args=[self.order.pk, "cancel"])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(reverse("admin:orders_order_action", args=[self.order.pk, "x"])).status_code, 404)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, S.PENDING_PAYMENT)

    def test_resend_admin_sms(self):
        self.approved()
        self.act("resend_admin_sms")
        self.assertContains(self.client.get(self.change_url()), "هیچ شمارهٔ مدیری")
        s = SiteSettings.load()
        s.admin_sms_numbers = "09121234567\n09127654321"
        s.save()
        self.act("resend_admin_sms")
        logs = SMSLog.objects.filter(template_key="admin_new_order")
        self.assertEqual(sorted(logs.values_list("mobile", flat=True)), ["09121234567", "09127654321"])
        self.assertIn("شمزین 1 (هدیه)", logs.first().text)

    def test_resend_button_only_for_confirmed_orders(self):
        self.assertNotContains(self.client.get(self.change_url()), "ارسال مجدد پیامک ادمین")
        self.approved()
        self.assertContains(self.client.get(self.change_url()), "ارسال مجدد پیامک ادمین")


class PrintAndExportTests(OrderAdminTestCase):
    def test_packing_slip_lists_items_gifts_and_address(self):
        with capture_sms():
            other = make_order((self.paid, 1))
        response = self.client.get(reverse("admin:orders_order_print"), {"ids": f"{self.order.pk},{other.pk}"})
        self.assertEqual(response.status_code, 200)
        for text in ["علی رضایی", "1234567890", "09121111111", "[هدیه]", "شمزین", "آریزونا"]:
            self.assertContains(response, text)
        self.assertEqual(response.content.decode().count('class="slip"'), 2)

    def test_print_selected_action_redirects_to_slip(self):
        response = self.client.post(
            reverse("admin:orders_order_changelist"),
            {"action": "print_selected", "_selected_action": [self.order.pk]},
        )
        self.assertRedirects(response, reverse("admin:orders_order_print") + f"?ids={self.order.pk}")

    def read_xlsx(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml", response["Content-Type"])
        ws = load_workbook(BytesIO(response.content)).active
        return [list(row) for row in ws.iter_rows(values_only=True)]

    def test_export_filtered_list(self):
        rows = self.read_xlsx(self.client.get(reverse("admin:orders_order_export")))
        self.assertEqual(rows[0][0], "شمارهٔ سفارش")
        self.assertEqual(len(rows), 2)
        row = dict(zip(rows[0], rows[1]))
        self.assertEqual(row["شمارهٔ سفارش"], self.order.number)
        self.assertEqual(row["موبایل سفارش‌دهنده"], "09121111111")
        self.assertEqual(row["مبلغ کل (تومان)"], self.order.total)
        self.assertIn("شمزین × 1 (هدیه)", row["اقلام"])
        empty = self.read_xlsx(self.client.get(reverse("admin:orders_order_export"), {"status__exact": "shipped"}))
        self.assertEqual(len(empty), 1)

    def test_export_selected_action(self):
        response = self.client.post(
            reverse("admin:orders_order_changelist"),
            {"action": "export_selected", "_selected_action": [self.order.pk]},
        )
        self.assertEqual(len(self.read_xlsx(response)), 2)

    def test_changelist_has_export_button(self):
        response = self.client.get(reverse("admin:orders_order_changelist"), {"status__exact": "pending_payment"})
        self.assertContains(response, reverse("admin:orders_order_export") + "?status__exact=pending_payment")
