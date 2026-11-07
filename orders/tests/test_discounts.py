from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from catalog.tests.utils import make_product
from orders.models import DiscountCode, DiscountError, DiscountType, OrderStatus, find_usable_code
from orders.pricing import calculate
from orders.services import CheckoutError

from .test_checkout import CheckoutTestCase, GUEST_MOBILE
from .utils import FakeCart, capture_sms, configure_payments, make_order


def make_code(code="SALE10", kind=DiscountType.PERCENT, value=10, **kwargs):
    kwargs.setdefault("per_user_limit", None)
    return DiscountCode.objects.create(code=code, kind=kind, value=value, **kwargs)


class DiscountCodeModelTests(TestCase):
    def test_code_is_normalised_and_case_insensitive_unique(self):
        code = make_code(" sale-۱۰ ")
        self.assertEqual(code.code, "SALE-10")
        self.assertEqual(DiscountCode.objects.find("Sale-10"), code)
        duplicate = DiscountCode(code="SALE-10", kind=DiscountType.FIXED, value=1000)
        with self.assertRaises(ValidationError) as cm:
            duplicate.full_clean()
        self.assertIn("قبلاً ساخته شده", str(cm.exception))

    def test_validation_messages(self):
        cases = [
            (dict(code="ab", value=10), "code", "۳ تا ۳۰"),
            (dict(code="کدفارسی", value=10), "code", "حروف انگلیسی"),
            (dict(value=0), "value", "بین ۱ تا ۱۰۰"),
            (dict(value=150), "value", "بین ۱ تا ۱۰۰"),
            (dict(kind=DiscountType.FIXED, value=0), "value", "بیشتر از صفر"),
            (dict(kind=DiscountType.FIXED, value=50_000, max_discount=10_000), "max_discount", "فقط برای کد درصدی"),
            (dict(starts_at=timezone.now(), ends_at=timezone.now() - timedelta(days=1)), "ends_at", "بعد از شروع"),
            (dict(usage_limit=0), "usage_limit", "دست‌کم ۱"),
            (dict(per_user_limit=0), "per_user_limit", "دست‌کم ۱"),
        ]
        for kwargs, field, text in cases:
            data = {"code": "GOOD1", "kind": DiscountType.PERCENT, "value": 10, **kwargs}
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError) as cm:
                DiscountCode(**data).full_clean()
            self.assertIn(field, cm.exception.message_dict)
            self.assertIn(text, " ".join(cm.exception.message_dict[field]))

    def test_percent_amount_and_max_discount(self):
        code = make_code(value=10)
        self.assertEqual(code.amount(2_000_000), 200_000)
        self.assertEqual(code.amount(1_999), 199)  # rounded down to whole Toman
        code.max_discount = 150_000
        self.assertEqual(code.amount(2_000_000), 150_000)
        self.assertEqual(code.amount(1_000_000), 100_000)
        code.value = 100
        code.max_discount = None
        self.assertEqual(code.amount(500_000), 500_000)

    def test_fixed_amount_never_exceeds_subtotal(self):
        code = make_code(kind=DiscountType.FIXED, value=300_000)
        self.assertEqual(code.amount(1_000_000), 300_000)
        self.assertEqual(code.amount(200_000), 200_000)

    def test_applies_to_items_not_shipping(self):
        code = make_code(kind=DiscountType.FIXED, value=500_000)
        lines = FakeCart((make_product(price=1_000_000, stock=5), 4))  # 4,000,000
        b = calculate(lines, discount=code)
        self.assertEqual((b.items_subtotal, b.discount_amount), (4_000_000, 500_000))
        self.assertEqual(b.shipping_fee, 400_000)  # 3,500,000 after discount: 2 steps
        self.assertEqual(b.total, 3_500_000 + 400_000)


class DiscountRuleTests(TestCase):
    def setUp(self):
        configure_payments()
        self.p = make_product(price=1_000_000, stock=20)
        self.user = get_user_model().objects.create_user(mobile="09125556666")

    def check(self, code, subtotal=2_000_000, **kwargs):
        return find_usable_code(code.code, subtotal, **kwargs)

    def assertRejected(self, code, text, subtotal=2_000_000, **kwargs):
        with self.assertRaises(DiscountError) as cm:
            self.check(code, subtotal, **kwargs)
        self.assertIn(text, cm.exception.message)

    def confirmed_order(self, code, mobile="09121111111", user=None):
        order = make_order((self.p, 1), mobile=mobile, user=user, discount_code=code.code)
        order.confirm_payment()
        return order

    def test_unknown_empty_and_inactive(self):
        with self.assertRaisesMessage(DiscountError, "کد تخفیف را وارد کنید."):
            find_usable_code("  ", 1)
        with self.assertRaisesMessage(DiscountError, "کد تخفیف معتبر نیست."):
            find_usable_code("NOPE", 1)
        code = make_code(is_active=False)
        self.assertRejected(code, "کد تخفیف معتبر نیست.")

    def test_dates(self):
        now = timezone.now()
        future = make_code("LATER", starts_at=now + timedelta(days=1))
        self.assertRejected(future, "قابل استفاده است")
        expired = make_code("OLD", ends_at=now - timedelta(seconds=1))
        self.assertRejected(expired, "مهلت استفاده از این کد تخفیف تمام شده است.")
        current = make_code("NOW", starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=1))
        self.assertEqual(self.check(current), current)

    def test_minimum_order_amount_uses_items_subtotal(self):
        code = make_code(min_order_amount=2_000_000)
        self.assertRejected(code, "۱٬۰۰۰ تومان دیگر", subtotal=1_999_000)
        self.assertEqual(self.check(code, 2_000_000), code)

    def test_total_usage_limit_counts_confirmed_orders_only(self):
        code = make_code(usage_limit=1)
        pending = make_order((self.p, 1), discount_code=code.code)
        code.refresh_from_db()
        self.assertEqual(code.used_count, 0)  # not confirmed yet
        pending.confirm_payment()
        code.refresh_from_db()
        self.assertEqual(code.used_count, 1)
        self.assertRejected(code, "ظرفیت استفاده از این کد تخفیف تمام شده است.")

    def test_usage_restored_on_cancel(self):
        code = make_code(usage_limit=1)
        order = self.confirmed_order(code)
        order.cancel()
        code.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(code.used_count, 0)
        self.assertFalse(order.discount_counted)
        self.assertEqual(self.check(code), code)

    def test_cancel_of_unconfirmed_order_does_not_change_count(self):
        code = make_code()
        self.confirmed_order(code, mobile="09120000001")
        make_order((self.p, 1), discount_code=code.code).cancel()
        code.refresh_from_db()
        self.assertEqual(code.used_count, 1)

    def test_confirmation_is_counted_once(self):
        code = make_code()
        order = self.confirmed_order(code)
        order.confirm_payment()
        code.refresh_from_db()
        self.assertEqual(code.used_count, 1)

    def test_per_user_limit_by_mobile(self):
        code = make_code(per_user_limit=1)
        self.confirmed_order(code, mobile=GUEST_MOBILE)
        self.assertRejected(code, "قبلاً از این کد تخفیف استفاده کرده‌اید", mobile=GUEST_MOBILE)
        self.assertEqual(self.check(code, mobile="09129999999"), code)
        self.assertEqual(self.check(code), code)  # customer not known yet: checked again at checkout

    def test_per_user_limit_by_account_and_its_mobile(self):
        code = make_code(per_user_limit=2)
        self.confirmed_order(code, mobile=self.user.mobile, user=self.user)
        self.assertEqual(self.check(code, user=self.user), code)
        self.confirmed_order(code, mobile="09120000002", user=self.user)  # same account, other mobile
        self.assertRejected(code, "۲ بار", user=self.user)
        # A guest order with the account's mobile also counts for that account.
        other = make_code("OTHER", per_user_limit=1)
        self.confirmed_order(other, mobile=self.user.mobile)
        self.assertRejected(other, "قبلاً", user=self.user)

    def test_per_user_limit_ignores_canceled_orders(self):
        code = make_code(per_user_limit=1)
        self.confirmed_order(code, mobile=GUEST_MOBILE).cancel()
        self.assertEqual(self.check(code, mobile=GUEST_MOBILE), code)

    def test_create_order_snapshots_and_rechecks(self):
        code = make_code(value=10)
        order = make_order((self.p, 2), discount_code="sale10")
        self.assertEqual((order.discount_code, order.discount_code_text), (code, "SALE10"))
        self.assertEqual((order.items_subtotal, order.discount_amount), (2_000_000, 200_000))
        self.assertEqual(order.total, 1_800_000 + 200_000)
        code.is_active = False
        code.save()
        with self.assertRaises(CheckoutError) as cm:
            make_order((self.p, 2), discount_code="SALE10")
        self.assertIn("کد تخفیف معتبر نیست.", cm.exception.messages)

    def test_create_order_checks_per_user_limit_with_verified_mobile(self):
        code = make_code(per_user_limit=1)
        self.confirmed_order(code, mobile=GUEST_MOBILE)
        with self.assertRaises(CheckoutError):
            make_order((self.p, 1), mobile=GUEST_MOBILE, discount_code=code.code)


class DiscountViewTests(CheckoutTestCase):
    """The HTMX discount box on the cart page and on checkout (cart: 2 × 1,000,000)."""

    def apply(self, code, where="cart", htmx=True):
        headers = {"HX-Request": "true"} if htmx else {}
        return self.client.post(
            reverse("orders:discount"), {"code": code, "discount_action": "apply", "where": where}, headers=headers
        )

    def test_apply_on_cart_page(self):
        make_code(value=10)
        response = self.apply("sale10")
        self.assertContains(response, "اعمال شد")
        self.assertContains(response, "۲۰۰٬۰۰۰ تومان")  # discount
        self.assertContains(response, "۲٬۰۰۰٬۰۰۰ تومان")  # 1,800,000 + 200,000 shipping
        self.assertContains(response, 'id="bottom-bar"')  # out-of-band totals
        self.assertEqual(self.client.session["discount_code"], "SALE10")

    def test_invalid_code_shows_error_and_is_not_kept(self):
        response = self.apply("WRONG")
        self.assertContains(response, "کد تخفیف معتبر نیست.")
        self.assertNotIn("discount_code", self.client.session)

    def test_minimum_not_met_message(self):
        make_code(min_order_amount=5_000_000)
        response = self.apply("SALE10")
        self.assertContains(response, "۳٬۰۰۰٬۰۰۰ تومان دیگر کالا")

    def test_remove(self):
        make_code()
        self.apply("SALE10")
        response = self.client.post(
            reverse("orders:discount"), {"discount_action": "remove", "where": "cart"}, headers={"HX-Request": "true"}
        )
        self.assertNotIn("discount_code", self.client.session)
        self.assertContains(response, 'name="code"')

    def test_code_that_became_invalid_shows_reason_and_gives_no_discount(self):
        code = make_code(min_order_amount=2_000_000)
        self.apply("SALE10")
        self.client.post(reverse("cart:update", args=[self.p.pk]), {"quantity": 1})
        response = self.client.get(reverse("cart:detail"))
        self.assertContains(response, "اعمال نشد")
        self.assertEqual(response.context["breakdown"].discount_amount, 0)
        code.min_order_amount = 0
        code.save()
        self.assertEqual(self.client.get(reverse("cart:detail")).context["breakdown"].discount_amount, 100_000)

    def test_checkout_apply_returns_page_parts(self):
        make_code(value=10)
        response = self.apply("SALE10", where="checkout")
        self.assertContains(response, 'id="checkout-summary"')
        self.assertContains(response, 'id="gift-section"')
        self.assertEqual(response.context["breakdown"].total, 2_000_000)

    def test_no_js_fallback_redirects(self):
        make_code()
        self.assertRedirects(self.apply("SALE10", where="checkout", htmx=False), reverse("orders:checkout"))

    def test_checkout_with_discount(self):
        code = make_code(value=10)
        self.verify_guest_mobile()
        self.apply("SALE10")
        response, sent = self.submit()
        order = code.orders.get()
        self.assertRedirects(response, reverse("payments:card", args=[order.number]))
        self.assertEqual((order.discount_amount, order.total), (200_000, 2_000_000))
        self.assertNotIn("discount_code", self.client.session)

    def test_checkout_blocks_invalid_session_code(self):
        code = make_code()
        self.verify_guest_mobile()
        self.apply("SALE10")
        code.is_active = False
        code.save()
        response, _ = self.submit()
        self.assertContains(response, "کد تخفیف را حذف کنید")
        self.assertFalse(code.orders.exists())

    def test_checkout_rechecks_per_user_limit_after_mobile_verification(self):
        code = make_code(per_user_limit=1)
        earlier = make_order((self.p, 1), mobile=GUEST_MOBILE, discount_code=code.code)
        earlier.confirm_payment()
        self.apply("SALE10")  # not verified yet: accepted
        self.verify_guest_mobile()
        response, _ = self.submit()
        self.assertContains(response, "قبلاً از این کد تخفیف استفاده کرده‌اید")
        self.assertEqual(code.orders.count(), 1)


class DiscountStatusTests(TestCase):
    def setUp(self):
        configure_payments()
        self.p = make_product(price=1_000_000, stock=5)

    def test_rejected_card_payment_restores_nothing_it_did_not_count(self):
        from payments.services import submit_card_transfer

        code = make_code()
        order = make_order((self.p, 1), discount_code=code.code)
        submit_card_transfer(order, "123")
        order.reject(reason="واریز نشده")
        code.refresh_from_db()
        self.assertEqual(code.used_count, 0)
        self.assertEqual(order.status, OrderStatus.CANCELED)

    def test_approve_counts_use(self):
        from payments.services import submit_card_transfer

        code = make_code()
        order = make_order((self.p, 1), discount_code=code.code)
        submit_card_transfer(order, "123")
        with capture_sms():
            order.approve()
        code.refresh_from_db()
        self.assertEqual(code.used_count, 1)
