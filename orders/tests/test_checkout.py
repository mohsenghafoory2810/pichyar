from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Address
from catalog.models import Product
from catalog.tests.utils import make_product
from orders.models import Order, OrderStatus, PaymentMethod
from orders.services import CheckoutError
from payments.gateways import GatewayRedirect

from .utils import ADDRESS, capture_sms, configure_payments, make_order

GUEST_MOBILE = "09123334444"


def checkout_data(**overrides):
    data = {**ADDRESS, "payment_method": "card", "age_confirmed": "on", "note": ""}
    data.pop("recipient_mobile")
    data.update(overrides)
    return data


class CheckoutTestCase(TestCase):
    def setUp(self):
        configure_payments()
        self.p = make_product("دیویدوف", price=1_000_000, stock=5, short_name="دیو")
        self.client.post(reverse("cart:add", args=[self.p.pk]), {"quantity": 2})

    def verify_guest_mobile(self, mobile=GUEST_MOBILE):
        url = reverse("orders:checkout_mobile")
        with capture_sms() as sent:
            self.client.post(url, {"action": "send", "mobile": mobile}, headers={"HX-Request": "true"})
        response = self.client.post(url, {"action": "verify", "code": sent[0][2]["code"]}, headers={"HX-Request": "true"})
        self.assertContains(response, "تأیید شد")

    def expected_total(self):
        return self.client.get(reverse("orders:checkout")).context["breakdown"].total

    def submit(self, **overrides):
        data = checkout_data(expected_total=self.expected_total(), **overrides)
        with capture_sms() as sent, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("orders:checkout"), data)
        return response, sent


class GuestCheckoutTests(CheckoutTestCase):
    def test_page_shows_fee_total_and_age_checkbox(self):
        response = self.client.get(reverse("orders:checkout"))
        self.assertContains(response, "هزینهٔ ارسال (پست)")
        self.assertContains(response, "۲٬۲۰۰٬۰۰۰ تومان")
        self.assertContains(response, "تأیید می‌کنم که بالای ۱۸ سال سن دارم.")
        self.assertContains(response, "دریافت کد تأیید")

    def test_empty_cart_redirects(self):
        self.client.post(reverse("cart:remove", args=[self.p.pk]))
        self.assertRedirects(self.client.get(reverse("orders:checkout")), reverse("cart:detail"))

    def test_guest_must_verify_mobile(self):
        response, _ = self.submit()
        self.assertContains(response, "ابتدا شمارهٔ موبایل خود را با کد پیامکی تأیید کنید")
        self.assertFalse(Order.objects.exists())

    def test_card_to_card_order(self):
        self.verify_guest_mobile()
        response, sent = self.submit(note="زنگ نزنید")
        order = Order.objects.get()
        self.assertRedirects(response, reverse("payments:card", args=[order.number]))
        self.assertIsNone(order.user)
        self.assertEqual((order.mobile, order.recipient_mobile), (GUEST_MOBILE, GUEST_MOBILE))
        self.assertEqual((order.items_subtotal, order.shipping_fee, order.total), (2_000_000, 200_000, 2_200_000))
        self.assertEqual(order.status, OrderStatus.PENDING_PAYMENT)
        self.assertTrue(order.age_confirmed)
        self.assertIsNotNone(order.age_confirmed_at)
        self.assertEqual(order.note, "زنگ نزنید")
        self.assertRegex(order.number, r"^\d{7}$")
        item = order.items.get()
        self.assertEqual((item.name, item.short_name, item.unit_price, item.quantity, item.is_gift), ("دیویدوف", "دیو", 1_000_000, 2, False))
        self.assertEqual(order.status_logs.get().to_status, OrderStatus.PENDING_PAYMENT)
        self.assertEqual(sent, [(GUEST_MOBILE, "order_registered", {"order_number": order.number, "total": 2_200_000, "tracking_code": ""})])
        self.p.refresh_from_db()
        self.assertEqual(self.p.stock, 5)  # reserved only when the payment is confirmed
        self.assertEqual(self.client.session.get("cart"), {})
        # the guest can open their own order and the card page
        self.assertContains(self.client.get(reverse("payments:card", args=[order.number])), "۶۰۳۷-۹۹۱۲-۳۴۵۶-۷۸۹۰")
        self.assertContains(self.client.get(order.get_absolute_url()), order.number.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")))

    def test_age_confirmation_is_required(self):
        self.verify_guest_mobile()
        response, _ = self.submit(age_confirmed="")
        self.assertContains(response, "باید تأیید کنید که بالای ۱۸ سال سن دارید")
        self.assertFalse(Order.objects.exists())

    def test_postal_code_must_have_ten_digits(self):
        self.verify_guest_mobile()
        response, _ = self.submit(postal_code="12345")
        self.assertContains(response, "کد پستی باید ۱۰ رقم باشد")
        self.assertFalse(Order.objects.exists())

    def test_persian_postal_code_is_normalised(self):
        self.verify_guest_mobile()
        self.submit(postal_code="۱۲۳۴۵۶۷۸۹۰")
        self.assertEqual(Order.objects.get().postal_code, "1234567890")

    def test_price_change_before_submit_is_caught(self):
        self.verify_guest_mobile()
        total = self.expected_total()
        self.p.price = 1_100_000
        self.p.save()
        data = checkout_data(expected_total=total)
        response = self.client.post(reverse("orders:checkout"), data)
        self.assertContains(response, "قیمت برخی کالاها یا هزینهٔ ارسال تغییر کرده است")
        self.assertContains(response, "۲٬۴۰۰٬۰۰۰ تومان")  # the new total is shown
        self.assertFalse(Order.objects.exists())
        self.assertEqual(response.context["form"]["expected_total"].value(), 2_400_000)

    def test_stock_is_rechecked_at_checkout(self):
        self.verify_guest_mobile()
        total = self.expected_total()
        Product.objects.filter(pk=self.p.pk).update(stock=1)
        response = self.client.post(reverse("orders:checkout"), checkout_data(expected_total=total))
        self.assertContains(response, "فقط ۱ عدد موجود است")
        self.assertFalse(Order.objects.exists())

    def test_disabled_method_is_refused(self):
        self.verify_guest_mobile()
        response, _ = self.submit(payment_method="bitcoin")
        self.assertContains(response, "روش پرداخت")
        self.assertFalse(Order.objects.exists())

    def test_online_payment_redirects_to_gateway(self):
        self.verify_guest_mobile()
        redirect = GatewayRedirect(url="https://sandbox.zarinpal.com/pg/StartPay/A123", authority="A123")
        with mock.patch("payments.gateways.zarinpal.ZarinpalGateway.request", return_value=redirect) as req:
            response, _ = self.submit(payment_method="online")
        self.assertRedirects(response, redirect.url, fetch_redirect_response=False)
        order = Order.objects.get()
        self.assertEqual(order.payment_method, PaymentMethod.ONLINE)
        payment = order.payments.get()
        self.assertEqual((payment.authority, payment.amount, payment.status), ("A123", order.total, "pending"))
        self.assertTrue(req.call_args.args[1].endswith(f"/payments/callback/{payment.pk}/"))

    def test_other_browsers_cannot_open_the_order(self):
        self.verify_guest_mobile()
        self.submit()
        order = Order.objects.get()
        self.client.logout()
        self.client.cookies.clear()
        self.assertRedirects(self.client.get(order.get_absolute_url()), reverse("orders:track"))
        self.assertEqual(self.client.get(reverse("payments:card", args=[order.number])).status_code, 404)


class UserCheckoutTests(CheckoutTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("09125556666", name="سارا")
        self.client.force_login(self.user)
        super().setUp()

    def test_no_otp_needed_and_address_saved(self):
        response, _ = self.submit(recipient_mobile="09127778888", save_address="on")
        order = Order.objects.get()
        self.assertEqual((order.user, order.mobile, order.recipient_mobile), (self.user, "09125556666", "09127778888"))
        self.assertEqual(self.user.addresses.get().postal_code, "1234567890")
        # same address again is not duplicated
        self.client.post(reverse("cart:add", args=[self.p.pk]), {"quantity": 1})
        self.submit(recipient_mobile="09127778888", save_address="on")
        self.assertEqual(self.user.addresses.count(), 1)

    def test_saved_address_prefills_and_htmx_fill(self):
        a = Address.objects.create(user=self.user, **{**ADDRESS, "city": "کرج", "province": "البرز"})
        response = self.client.get(reverse("orders:checkout"))
        self.assertContains(response, 'value="کرج"')
        other = get_user_model().objects.create_user("09120001111")
        b = Address.objects.create(user=other, **ADDRESS)
        self.assertContains(self.client.get(reverse("orders:checkout_address", args=[a.pk])), 'value="کرج"')
        self.assertEqual(self.client.get(reverse("orders:checkout_address", args=[b.pk])).status_code, 404)


class OrderSnapshotTests(TestCase):
    def test_later_product_changes_never_alter_the_order(self):
        p = make_product("دیویدوف", price=500_000, stock=10)
        order = make_order((p, 2))
        p.name, p.price = "دیویدوف جدید", 900_000
        p.save()
        order.refresh_from_db()
        item = order.items.get()
        self.assertEqual((item.name, item.unit_price, item.line_total), ("دیویدوف", 500_000, 1_000_000))
        self.assertEqual(order.total, 1_000_000 + 200_000)
        p.delete()
        item.refresh_from_db()
        self.assertIsNone(item.product)
        self.assertEqual(item.name, "دیویدوف")

    def test_settings_change_does_not_alter_saved_shipping(self):
        from core.models import SiteSettings

        p = make_product(price=1_000_000, stock=10)
        order = make_order((p, 1))
        s = SiteSettings.load()
        s.shipping_step_fee = 999_000
        s.save()
        order.refresh_from_db()
        self.assertEqual(order.shipping_fee, 200_000)

    def test_inactive_product_cannot_be_ordered(self):
        p = make_product(stock=10, is_active=False)
        with self.assertRaisesMessage(CheckoutError, "ناموجود"):
            make_order((p, 1))
