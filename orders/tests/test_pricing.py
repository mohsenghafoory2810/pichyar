from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from core.models import SiteSettings
from orders.pricing import CEIL, FLOOR, calculate, shipping_fee

STEP, FEE = 3_000_000, 200_000


def lines(*totals):
    return [SimpleNamespace(line_total=t) for t in totals]


class ShippingFeeFormulaTests(SimpleTestCase):
    def test_ceil(self):
        cases = {
            0: 0,
            1: FEE,
            2_999_999: FEE,
            3_000_000: FEE,
            3_000_001: 2 * FEE,
            6_000_000: 2 * FEE,
            9_000_001: 4 * FEE,
        }
        for amount, fee in cases.items():
            self.assertEqual(shipping_fee(amount, STEP, FEE, CEIL), fee, amount)

    def test_floor(self):
        cases = {
            0: 0,
            1: 0,
            2_999_999: 0,
            3_000_000: FEE,
            3_000_001: FEE,
            6_000_000: 2 * FEE,
            8_999_999: 2 * FEE,
        }
        for amount, fee in cases.items():
            self.assertEqual(shipping_fee(amount, STEP, FEE, FLOOR), fee, amount)

    def test_free_shipping_and_bad_step(self):
        self.assertEqual(shipping_fee(5_000_000, STEP, 0), 0)
        self.assertEqual(shipping_fee(5_000_000, 0, FEE), 0)
        self.assertEqual(shipping_fee(-10, STEP, FEE), 0)


class CalculateTests(TestCase):
    def setUp(self):
        self.s = SiteSettings.load()

    def test_defaults(self):
        self.assertEqual((self.s.shipping_step_amount, self.s.shipping_step_fee, self.s.shipping_rounding), (STEP, FEE, CEIL))

    def test_empty_cart_is_zero(self):
        b = calculate([], site_settings=self.s)
        self.assertEqual((b.items_subtotal, b.discount_amount, b.shipping_fee, b.total), (0, 0, 0, 0))

    def test_exactly_one_step(self):
        b = calculate(lines(1_000_000, 2_000_000), site_settings=self.s)
        self.assertEqual((b.items_subtotal, b.shipping_fee, b.total), (3_000_000, 200_000, 3_200_000))

    def test_one_toman_over_a_step(self):
        b = calculate(lines(3_000_001), site_settings=self.s)
        self.assertEqual((b.shipping_fee, b.total), (400_000, 3_400_001))
        self.s.shipping_rounding = FLOOR
        b = calculate(lines(3_000_001), site_settings=self.s)
        self.assertEqual((b.shipping_fee, b.total), (200_000, 3_200_001))

    def test_settings_are_editable(self):
        self.s.shipping_step_amount = 1_000_000
        self.s.shipping_step_fee = 50_000
        self.s.save()
        b = calculate(lines(2_500_000))  # loads SiteSettings itself
        self.assertEqual(b.shipping_fee, 150_000)

    def test_discount_reduces_the_fee_base_and_is_clamped(self):
        class Discount:
            def __init__(self, amount):
                self.value = amount

            def amount(self, items_subtotal, lines):
                return self.value

        b = calculate(lines(3_500_000), discount=Discount(600_000), site_settings=self.s)
        self.assertEqual((b.discount_amount, b.subtotal_after_discount, b.shipping_fee, b.total), (600_000, 2_900_000, FEE, 3_100_000))
        b = calculate(lines(100_000), discount=Discount(999_999), site_settings=self.s)
        self.assertEqual((b.discount_amount, b.shipping_fee, b.total), (100_000, 0, 0))
        b = calculate(lines(100_000), discount=Discount(-5), site_settings=self.s)
        self.assertEqual(b.discount_amount, 0)
