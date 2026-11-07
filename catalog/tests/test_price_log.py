"""A PriceChangeLog row is written on every path that changes a price."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalog import pricing
from catalog.audit import acting_as
from catalog.models import PriceChangeLog, Product

from .utils import make_product


class PriceChangeLogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("09120000001", email="boss@example.com", password="pass")

    def setUp(self):
        self.product = make_product(price=100_000)

    def logs(self):
        return list(
            PriceChangeLog.objects.filter(product=self.product).values_list("old_price", "new_price", "changed_by")
        )

    def test_creating_a_product_is_not_a_change(self):
        self.assertEqual(self.logs(), [])

    def test_model_save(self):
        self.product.price = 120_000
        self.product.save()
        self.assertEqual(self.logs(), [(100_000, 120_000, None)])

    def test_saving_without_price_change_writes_nothing(self):
        self.product.stock = 3
        self.product.save()
        self.assertEqual(self.logs(), [])

    def test_acting_user_is_recorded(self):
        with acting_as(self.admin):
            self.product.price = 90_000
            self.product.save()
        self.assertEqual(self.logs(), [(100_000, 90_000, self.admin.pk)])

    def test_queryset_update(self):
        Product.objects.filter(pk=self.product.pk).update(price=130_000)
        self.assertEqual(self.logs(), [(100_000, 130_000, None)])

    def test_queryset_update_with_filter_on_price(self):
        # The filter no longer matches after the update; the log must still be written.
        Product.objects.filter(price=100_000).update(price=110_000)
        self.assertEqual(self.logs(), [(100_000, 110_000, None)])

    def test_bulk_update(self):
        self.product.price = 140_000
        Product.objects.bulk_update([self.product], ["price"])
        self.assertEqual(self.logs(), [(100_000, 140_000, None)])

    def test_bulk_price_service(self):
        with acting_as(self.admin):
            pricing.apply([self.product], pricing.PERCENT, pricing.INCREASE, 10)
        self.assertEqual(self.logs(), [(100_000, 110_000, self.admin.pk)])

    def test_admin_change_form(self):
        self.client.force_login(self.admin)
        url = reverse("admin:catalog_product_change", args=[self.product.pk])
        data = {
            "name": self.product.name,
            "short_name": self.product.short_name,
            "slug": self.product.slug,
            "category": self.product.category_id,
            "description": "",
            "price": 155_000,
            "unit": self.product.unit,
            "stock": 10,
            "low_stock_threshold": 5,
            "is_active": "on",
            "sort_order": 0,
            "images-TOTAL_FORMS": 0,
            "images-INITIAL_FORMS": 0,
            "price_logs-TOTAL_FORMS": 0,
            "price_logs-INITIAL_FORMS": 0,
            "specs-TOTAL_FORMS": 0,
            "specs-INITIAL_FORMS": 0,
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.logs(), [(100_000, 155_000, self.admin.pk)])

    def test_admin_list_inline_edit(self):
        self.client.force_login(self.admin)
        data = {
            "form-TOTAL_FORMS": 1,
            "form-INITIAL_FORMS": 1,
            "form-0-id": self.product.pk,
            "form-0-price": 99_000,
            "form-0-stock": 7,
            "_save": "ذخیره",
        }
        response = self.client.post(reverse("admin:catalog_product_changelist"), data)
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual((self.product.price, self.product.stock), (99_000, 7))
        self.assertEqual(self.logs(), [(100_000, 99_000, self.admin.pk)])

    def test_admin_page_shows_history(self):
        with acting_as(self.admin):
            self.product.price = 120_000
            self.product.save()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin:catalog_product_change", args=[self.product.pk]))
        self.assertContains(response, "تاریخچهٔ تغییر قیمت")
        self.assertContains(response, "۱۰۰٬۰۰۰ تومان")
        self.assertContains(response, "۱۲۰٬۰۰۰ تومان")
