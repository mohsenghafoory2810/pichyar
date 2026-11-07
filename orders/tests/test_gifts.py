from io import StringIO
from types import SimpleNamespace

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from catalog import stock
from catalog.models import Product
from catalog.tests.utils import make_product
from core.models import SiteSettings
from orders.gifts import GiftError, gift_hint, gift_options, slot_count, validate_selection
from orders.models import DiscountCode, DiscountType, GiftPoolItem, GiftStockShortage, Order, OrderStatus
from orders.pricing import calculate, gifts_earned
from orders.services import CheckoutError
from payments.services import submit_card_transfer

from .test_checkout import CheckoutTestCase
from .utils import FakeCart, capture_sms, configure_payments, make_order

T = 3_000_000  # default gift threshold


def lines(*totals):
    return [SimpleNamespace(line_total=t) for t in totals]


class GiftsEarnedFormulaTests(SimpleTestCase):
    def test_edge_cases(self):
        cases = {0: 0, 1: 0, T - 1: 0, T: 1, T + 1: 1, 2 * T - 1: 1, 2 * T: 2, 7_000_000: 2, 9_000_000: 3, 31_000_000: 10}
        for amount, gifts in cases.items():
            self.assertEqual(gifts_earned(amount, T), gifts, amount)

    def test_disabled_or_bad_threshold(self):
        self.assertEqual(gifts_earned(9_000_000, T, enabled=False), 0)
        self.assertEqual(gifts_earned(9_000_000, 0), 0)
        self.assertEqual(gifts_earned(-5, T), 0)


class CalculateGiftsTests(TestCase):
    def setUp(self):
        self.s = SiteSettings.load()

    def test_defaults(self):
        self.assertEqual((self.s.gift_enabled, self.s.gift_threshold), (True, T))

    def test_example_seven_million_is_two_gifts(self):
        self.assertEqual(calculate(lines(7_000_000), site_settings=self.s).gifts_earned, 2)

    def test_just_under_and_exactly(self):
        self.assertEqual(calculate(lines(T - 1), site_settings=self.s).gifts_earned, 0)
        self.assertEqual(calculate(lines(T), site_settings=self.s).gifts_earned, 1)

    def test_shipping_not_counted(self):
        b = calculate(lines(T - 1), site_settings=self.s)
        self.assertGreater(b.total, T)  # total with shipping passes the threshold ...
        self.assertEqual(b.gifts_earned, 0)  # ... but gifts only count the items

    def test_discount_lowers_gift_count_and_shipping(self):
        code = DiscountCode(code="X", kind=DiscountType.FIXED, value=100_000)
        b = calculate(lines(6_000_000), discount=code, site_settings=self.s)
        self.assertEqual(b.subtotal_after_discount, 5_900_000)
        self.assertEqual(b.gifts_earned, 1)  # 2 without the discount
        self.assertEqual(b.shipping_fee, 2 * 200_000)  # from 5,900,000 (ceil), not 6,000,000
        self.assertEqual(calculate(lines(6_000_000), site_settings=self.s).gifts_earned, 2)

    def test_shipping_computed_after_discount(self):
        code = DiscountCode(code="X", kind=DiscountType.PERCENT, value=10)
        b = calculate(lines(3_300_000), discount=code, site_settings=self.s)
        self.assertEqual(b.subtotal_after_discount, 2_970_000)
        self.assertEqual(b.shipping_fee, 200_000)  # 3,300,000 alone would be 2 steps
        self.assertEqual(b.total, 2_970_000 + 200_000)
        self.assertEqual(b.gifts_earned, 0)

    def test_disabled_in_settings(self):
        self.s.gift_enabled = False
        self.assertEqual(calculate(lines(9_000_000), site_settings=self.s).gifts_earned, 0)

    def test_custom_threshold(self):
        self.s.gift_threshold = 1_000_000
        self.assertEqual(calculate(lines(3_500_000), site_settings=self.s).gifts_earned, 3)


class GiftPoolTestCase(TestCase):
    def setUp(self):
        configure_payments()
        self.paid = make_product("کالای پولی", price=1_000_000, stock=20)
        self.machine = make_product("دستگاه خشابی", price=675_000, stock=5, short_name="خشابی")
        self.tobacco = make_product("آریزونا", price=300_000, stock=3)
        self.machine_gift = GiftPoolItem.objects.create(product=self.machine, gift_stock=2)
        self.tobacco_gift = GiftPoolItem.objects.create(product=self.tobacco, gift_stock=10)

    def stock_of(self, product):
        return Product.objects.get(pk=product.pk).stock

    def gift_stock_of(self, item):
        return GiftPoolItem.objects.get(pk=item.pk).gift_stock


class GiftOptionsTests(GiftPoolTestCase):
    def test_capacity_is_min_of_gift_stock_and_product_stock(self):
        options = {o.pk: o.max_quantity for o in gift_options(FakeCart((self.paid, 3)))}
        self.assertEqual(options, {self.machine.pk: 2, self.tobacco.pk: 3})

    def test_paid_quantity_of_same_product_reduces_capacity(self):
        options = {o.pk: o.max_quantity for o in gift_options(FakeCart((self.tobacco, 2)))}
        self.assertEqual(options[self.tobacco.pk], 1)

    def test_inactive_out_of_stock_and_exhausted_are_hidden(self):
        GiftPoolItem.objects.filter(pk=self.machine_gift.pk).update(is_active=False)
        Product.objects.filter(pk=self.tobacco.pk).update(stock=0)
        self.assertEqual(gift_options([]), [])
        GiftPoolItem.objects.filter(pk=self.machine_gift.pk).update(is_active=True, gift_stock=0)
        self.assertEqual(gift_options([]), [])

    def test_slot_count_is_limited_by_pool(self):
        options = gift_options([])  # 2 + 3
        self.assertEqual(slot_count(3, options), 3)
        self.assertEqual(slot_count(9, options), 5)
        self.assertEqual(slot_count(0, options), 0)

    def test_validate_selection(self):
        self.assertEqual(validate_selection({self.tobacco.pk: 2}, 2, []), [(self.tobacco, 2)])
        self.assertEqual(validate_selection({}, 2, []), [])
        with self.assertRaisesMessage(GiftError, "فقط ۲ هدیه"):
            validate_selection({self.tobacco.pk: 3}, 2, [])
        with self.assertRaisesMessage(GiftError, "هدیه‌ای ندارد"):
            validate_selection({self.tobacco.pk: 1}, 0, [])
        with self.assertRaisesMessage(GiftError, "فقط ۲ عدد"):
            validate_selection({self.machine.pk: 3}, 5, [])
        with self.assertRaisesMessage(GiftError, "دیگر موجود نیست"):
            validate_selection({self.paid.pk: 1}, 5, [])  # not in the pool


class GiftOrderTests(GiftPoolTestCase):
    def order(self, gifts, paid_qty=7, **kwargs):
        return make_order((self.paid, paid_qty), gifts=gifts, **kwargs)

    def test_gifts_become_free_order_items(self):
        order = self.order({self.machine.pk: 1, self.tobacco.pk: 1})
        self.assertEqual(order.items_subtotal, 7_000_000)
        gifts = list(order.items.filter(is_gift=True))
        self.assertEqual([(g.product, g.unit_price, g.quantity) for g in gifts], [(self.machine, 0, 1), (self.tobacco, 0, 1)])
        self.assertEqual(order.total, 7_000_000 + 3 * 200_000)  # gifts cost nothing
        self.assertEqual(gifts[0].short_name, "خشابی")

    def test_same_gift_more_than_once(self):
        order = self.order({self.tobacco.pk: 2})
        self.assertEqual(order.items.get(is_gift=True).quantity, 2)

    def test_more_gifts_than_earned_is_rejected(self):
        with self.assertRaises(CheckoutError) as cm:
            self.order({self.tobacco.pk: 3})  # 7,000,000 earns 2
        self.assertIn("فقط ۲ هدیه", cm.exception.messages[0])

    def test_discount_lowering_count_is_enforced(self):
        DiscountCode.objects.create(code="OFF", kind=DiscountType.FIXED, value=1_000_001, per_user_limit=None)
        with self.assertRaises(CheckoutError):
            self.order({self.tobacco.pk: 2}, discount_code="OFF")  # 5,999,999 -> 1 gift
        order = self.order({self.tobacco.pk: 1}, discount_code="OFF")
        self.assertEqual(order.items.filter(is_gift=True).count(), 1)

    def test_confirm_reduces_product_and_gift_stock_and_cancel_restores(self):
        order = self.order({self.tobacco.pk: 2})
        with capture_sms():
            order.confirm_payment()
        self.assertEqual((self.stock_of(self.tobacco), self.gift_stock_of(self.tobacco_gift)), (1, 8))
        self.assertEqual(self.stock_of(self.paid), 13)
        order.cancel()
        self.assertEqual((self.stock_of(self.tobacco), self.gift_stock_of(self.tobacco_gift)), (3, 10))
        self.assertEqual(self.stock_of(self.paid), 20)

    def test_gift_stock_exhausted_before_confirmation_changes_nothing(self):
        first = self.order({self.machine.pk: 2})
        second = self.order({self.machine.pk: 1}, mobile="09120000009")
        with capture_sms():
            first.confirm_payment()
        self.assertEqual(self.gift_stock_of(self.machine_gift), 0)
        with self.assertRaises(GiftStockShortage) as cm:
            second.confirm_payment()
        self.assertIsInstance(cm.exception, stock.InsufficientStock)  # payment code treats it as out of stock
        self.assertIn("هدیهٔ «دستگاه خشابی» تمام شده است.", cm.exception.messages)
        second.refresh_from_db()
        self.assertEqual(second.status, OrderStatus.PENDING_PAYMENT)
        self.assertFalse(second.stock_reserved)
        self.assertEqual(self.stock_of(self.paid), 13)  # the paid items of `second` were not taken either
        self.assertEqual(self.stock_of(self.machine), 3)

    def test_gift_exhausted_before_checkout(self):
        GiftPoolItem.objects.filter(pk=self.machine_gift.pk).update(gift_stock=0)
        with self.assertRaises(CheckoutError) as cm:
            self.order({self.machine.pk: 1})
        self.assertIn("«دستگاه خشابی» دیگر موجود نیست", cm.exception.messages[0])

    def test_product_stock_shared_between_paid_items_and_gifts(self):
        with self.assertRaises(CheckoutError):
            make_order((self.tobacco, 3), (self.paid, 6), gifts={self.tobacco.pk: 1})  # tobacco stock 3, all paid

    def test_card_approval_and_reject(self):
        order = self.order({self.tobacco.pk: 1})
        submit_card_transfer(order, "1")
        with capture_sms():
            order.approve()
        self.assertEqual(self.gift_stock_of(self.tobacco_gift), 9)
        order.cancel()
        self.assertEqual(self.gift_stock_of(self.tobacco_gift), 10)
        rejected = self.order({self.tobacco.pk: 1})
        submit_card_transfer(rejected, "2")
        rejected.reject()
        self.assertEqual(self.gift_stock_of(self.tobacco_gift), 10)

    def test_deleted_pool_item_is_skipped_on_release(self):
        order = self.order({self.tobacco.pk: 1})
        with capture_sms():
            order.confirm_payment()
        self.tobacco_gift.delete()
        order.cancel()
        self.assertEqual(self.stock_of(self.tobacco), 3)


class GiftHintTests(GiftPoolTestCase):
    def hint(self, amount):
        s = SiteSettings.load()
        return gift_hint(calculate(lines(amount), site_settings=s), s)

    def test_texts(self):
        self.assertEqual(self.hint(2_500_000)["text"], "با ۵۰۰٬۰۰۰ تومان خرید بیشتر یک هدیه می‌گیرید.")
        hint = self.hint(7_000_000)
        self.assertEqual((hint["earned"], hint["remaining"]), (2, 2_000_000))
        self.assertIn("۲ هدیه دارد", hint["text"])
        self.assertEqual(self.hint(T)["remaining"], T)

    def test_hidden_without_pool_or_when_disabled(self):
        GiftPoolItem.objects.update(is_active=False)
        self.assertIsNone(self.hint(2_500_000))
        GiftPoolItem.objects.update(is_active=True)
        SiteSettings.objects.update(gift_enabled=False)
        self.assertIsNone(self.hint(2_500_000))

    def test_cart_page_shows_hint(self):
        self.client.post(reverse("cart:add", args=[self.paid.pk]), {"quantity": 2})
        response = self.client.get(reverse("cart:detail"))
        self.assertContains(response, "با ۱٬۰۰۰٬۰۰۰ تومان خرید بیشتر یک هدیه می‌گیرید.")


class GiftCheckoutViewTests(CheckoutTestCase):
    """Cart: 2 × 1,000,000 of «دیویدوف» (stock 5) from CheckoutTestCase; one more makes 3,000,000 = 1 gift."""

    def setUp(self):
        super().setUp()
        Product.objects.filter(pk=self.p.pk).update(stock=10)
        self.gift = make_product("آریزونا", price=300_000, stock=4)
        GiftPoolItem.objects.create(product=self.gift, gift_stock=5)
        self.client.post(reverse("cart:add", args=[self.p.pk]), {"quantity": 4})  # 6,000,000: 2 gifts
        self.verify_guest_mobile()

    def test_page_shows_one_select_per_gift(self):
        response = self.client.get(reverse("orders:checkout"))
        self.assertContains(response, "این سفارش ۲ هدیه دارد")
        self.assertContains(response, 'name="gift_1"')
        self.assertContains(response, 'name="gift_2"')
        self.assertNotContains(response, 'name="gift_3"')

    def test_all_gifts_must_be_chosen(self):
        response, _ = self.submit(gift_1=self.gift.pk)
        self.assertContains(response, "هدیهٔ ۲ را انتخاب کنید.")

    def test_order_with_gifts(self):
        response, _ = self.submit(gift_1=self.gift.pk, gift_2=self.gift.pk)
        order = Order.objects.get()
        self.assertRedirects(response, reverse("payments:card", args=[order.number]))
        self.assertEqual(order.items.get(is_gift=True).quantity, 2)
        self.assertEqual(Product.objects.get(pk=self.gift.pk).stock, 4)  # taken only when the payment is confirmed

    def test_tampered_choice_is_rejected(self):
        response, _ = self.submit(gift_1=self.gift.pk, gift_2=self.p.pk)
        self.assertContains(response, "هدیهٔ انتخاب‌شده دیگر موجود نیست")


class SeedGiftPoolTests(TestCase):
    def test_initial_pool_is_machine_and_all_tobacco(self):
        call_command("seed_products", "--no-images", stdout=StringIO())
        pool = GiftPoolItem.objects.select_related("product__category")
        names = {g.product.name for g in pool}
        self.assertIn("دستگاه خشابی", names)
        tobacco = set(Product.objects.filter(category__slug="tobacco").values_list("name", flat=True))
        self.assertTrue(tobacco)
        self.assertEqual(names, tobacco | {"دستگاه خشابی"})
        self.assertTrue(all(g.gift_stock == 0 and g.is_active for g in pool))

    def test_pool_not_recreated_after_admin_changes(self):
        call_command("seed_products", "--no-images", stdout=StringIO())
        GiftPoolItem.objects.exclude(product__name="دستگاه خشابی").delete()
        call_command("seed_products", "--no-images", stdout=StringIO())
        self.assertEqual(GiftPoolItem.objects.count(), 1)
