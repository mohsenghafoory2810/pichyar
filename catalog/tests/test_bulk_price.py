from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from catalog import pricing
from catalog.models import Category, PriceChangeLog, Product

from .utils import make_product


class RoundingTests(SimpleTestCase):
    def test_round_to(self):
        cases = [
            (Decimal("412500"), 1000, 413_000),  # half goes up
            (Decimal("412499"), 1000, 412_000),
            (Decimal("412500"), 5000, 415_000),
            (Decimal("412499"), 5000, 410_000),
            (Decimal("415000"), 10000, 420_000),
            (Decimal("414999"), 10000, 410_000),
            (Decimal("412499.5"), 0, 412_500),
            (Decimal("412499.4"), 0, 412_499),
        ]
        for value, step, expected in cases:
            with self.subTest(value=value, step=step):
                self.assertEqual(pricing.round_to(value, step), expected)

    def test_new_price(self):
        P, F, UP, DOWN = pricing.PERCENT, pricing.FIXED, pricing.INCREASE, pricing.DECREASE
        self.assertEqual(pricing.new_price(375_000, P, UP, 10), 412_500)
        self.assertEqual(pricing.new_price(375_000, P, UP, 10, 1000), 413_000)
        self.assertEqual(pricing.new_price(375_000, P, UP, 10, 5000), 415_000)
        self.assertEqual(pricing.new_price(375_000, P, UP, 10, 10000), 410_000)
        self.assertEqual(pricing.new_price(592_500, P, DOWN, 5), 562_875)
        self.assertEqual(pricing.new_price(592_500, P, DOWN, 5, 10000), 560_000)
        self.assertEqual(pricing.new_price(45_000, P, UP, Decimal("12.5"), 1000), 51_000)  # 50,625 -> 51,000
        self.assertEqual(pricing.new_price(300_000, F, UP, 25_000), 325_000)
        self.assertEqual(pricing.new_price(300_000, F, DOWN, 2_500, 5000), 300_000)  # 297,500 -> 300,000

    def test_price_cannot_drop_to_zero(self):
        class P:
            name = "پیپر لبنانی"
            price = 45_000

        with self.assertRaisesMessage(pricing.PriceAdjustmentError, "پیپر لبنانی"):
            pricing.preview([P()], pricing.FIXED, pricing.DECREASE, 45_000)


class BulkPriceAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("09120000001", email="boss@example.com", password="pass")

    def setUp(self):
        self.client.force_login(self.admin)
        self.url = reverse("admin:catalog_product_bulk_price")
        accessories = Category.objects.get(slug="accessories")
        self.filters = Category.objects.get(slug="filters")
        self.f1 = make_product("فیلتر زغالی", price=135_000, category=self.filters)
        self.top = make_product("لوازم دیگر", price=100_000, category=accessories)
        self.tobacco = make_product("کلمبیایی", price=375_000)

    def prices(self):
        return dict(Product.objects.values_list("name", "price"))

    def test_action_redirects_with_selected_ids(self):
        response = self.client.post(
            reverse("admin:catalog_product_changelist"),
            {"action": "bulk_change_price", "_selected_action": [self.f1.pk, self.tobacco.pk]},
        )
        self.assertRedirects(response, f"{self.url}?ids={self.f1.pk},{self.tobacco.pk}", fetch_redirect_response=False)
        page = self.client.get(response["Location"])
        self.assertContains(page, "۲ محصول انتخاب شده است.")

    def test_preview_does_not_save(self):
        data = {"ids": f"{self.tobacco.pk}", "direction": "increase", "mode": "percent", "amount": "۱۰", "rounding": 5000, "preview": "1"}
        response = self.client.post(self.url, data)
        self.assertContains(response, "۴۱۵٬۰۰۰ تومان")
        self.assertContains(response, 'name="apply"')
        self.assertEqual(self.prices()["کلمبیایی"], 375_000)

    def test_apply_to_selection(self):
        data = {"ids": f"{self.tobacco.pk}", "direction": "increase", "mode": "percent", "amount": "10", "rounding": 10000, "apply": "1"}
        response = self.client.post(self.url, data)
        self.assertRedirects(response, reverse("admin:catalog_product_changelist"), fetch_redirect_response=False)
        self.assertEqual(self.prices(), {"فیلتر زغالی": 135_000, "لوازم دیگر": 100_000, "کلمبیایی": 410_000})
        log = PriceChangeLog.objects.get()
        self.assertEqual((log.product, log.new_price, log.changed_by), (self.tobacco, 410_000, self.admin))

    def test_apply_to_whole_category_includes_subcategories(self):
        accessories = Category.objects.get(slug="accessories")
        data = {"category": accessories.pk, "direction": "decrease", "mode": "fixed", "amount": "۲٬۵۰۰", "rounding": 1000, "apply": "1"}
        self.client.post(self.url, data)
        # 132,500 -> 133,000 (half up); 97,500 -> 98,000; tobacco untouched.
        self.assertEqual(self.prices(), {"فیلتر زغالی": 133_000, "لوازم دیگر": 98_000, "کلمبیایی": 375_000})
        self.assertEqual(PriceChangeLog.objects.count(), 2)

    def test_needs_category_or_selection(self):
        data = {"direction": "increase", "mode": "percent", "amount": "10", "rounding": 0, "preview": "1"}
        response = self.client.post(self.url, data)
        self.assertContains(response, "یک دسته‌بندی انتخاب کنید")

    def test_rejects_change_that_makes_price_zero(self):
        data = {"ids": f"{self.f1.pk}", "direction": "decrease", "mode": "fixed", "amount": "200000", "rounding": 0, "apply": "1"}
        response = self.client.post(self.url, data)
        self.assertContains(response, "صفر یا منفی")
        self.assertEqual(self.prices()["فیلتر زغالی"], 135_000)

    def test_requires_change_permission(self):
        staff = get_user_model().objects.create_user("09120000002", password="pass", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)
