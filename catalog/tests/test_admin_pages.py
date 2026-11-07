from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalog.models import ProductImage

from .utils import TempMediaMixin, image_upload, make_product


class AdminPagesTests(TempMediaMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("09120000001", email="boss@example.com", password="pass")

    def setUp(self):
        self.client.force_login(self.admin)
        self.low = make_product("کم‌موجود", stock=2, low_stock_threshold=5)
        self.out = make_product("تمام‌شده", stock=0)
        self.ok = make_product("فراوان", stock=50)
        ProductImage.objects.create(product=self.ok, image=image_upload())

    def test_pages_render(self):
        urls = [
            reverse("admin:catalog_product_changelist"),
            reverse("admin:catalog_product_add"),
            reverse("admin:catalog_product_change", args=[self.ok.pk]),
            reverse("admin:catalog_product_import"),
            reverse("admin:catalog_product_export"),
            reverse("admin:catalog_product_bulk_price"),
            reverse("admin:catalog_category_changelist"),
            reverse("admin:catalog_category_add"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_changelist_flags_low_stock_and_has_tools(self):
        response = self.client.get(reverse("admin:catalog_product_changelist"))
        self.assertContains(response, 'class="stock-flag stock-low"')
        self.assertContains(response, 'class="stock-flag stock-out"')
        self.assertContains(response, 'name="form-0-price"')
        self.assertContains(response, reverse("admin:catalog_product_import"))
        self.assertContains(response, reverse("admin:catalog_product_bulk_price"))

    def test_low_stock_filter(self):
        response = self.client.get(reverse("admin:catalog_product_changelist"), {"stock_state": "low"})
        names = {p.name for p in response.context["cl"].result_list}
        self.assertEqual(names, {"کم‌موجود", "تمام‌شده"})

    def test_category_filter_includes_subcategories(self):
        from catalog.models import Category

        accessories = Category.objects.get(slug="accessories")
        make_product("فیلتر زغالی", category=Category.objects.get(slug="filters"))
        response = self.client.get(reverse("admin:catalog_product_changelist"), {"cat": accessories.pk})
        self.assertEqual([p.name for p in response.context["cl"].result_list], ["فیلتر زغالی"])

    def test_image_inline_upload_and_reorder(self):
        first = self.ok.images.get()
        url = reverse("admin:catalog_product_change", args=[self.ok.pk])
        data = {
            "name": self.ok.name, "short_name": self.ok.short_name, "slug": self.ok.slug,
            "category": self.ok.category_id, "description": "", "price": self.ok.price, "unit": self.ok.unit,
            "stock": self.ok.stock, "low_stock_threshold": 5, "is_active": "on", "sort_order": 0,
            "images-TOTAL_FORMS": 2, "images-INITIAL_FORMS": 1,
            "images-0-id": first.pk, "images-0-product": self.ok.pk, "images-0-order": 1,
            "images-1-image": image_upload("new.png", "PNG"), "images-1-order": 0,
            "price_logs-TOTAL_FORMS": 0, "price_logs-INITIAL_FORMS": 0,
            "specs-TOTAL_FORMS": 0, "specs-INITIAL_FORMS": 0,
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.ok.refresh_from_db()
        main = self.ok.main_image
        self.assertNotEqual(main.pk, first.pk)
        self.assertTrue(main.image.name.endswith(".webp"))

    def test_image_inline_rejects_bad_file(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        url = reverse("admin:catalog_product_change", args=[self.low.pk])
        data = {
            "name": self.low.name, "short_name": self.low.short_name, "slug": self.low.slug,
            "category": self.low.category_id, "description": "", "price": self.low.price, "unit": self.low.unit,
            "stock": 2, "low_stock_threshold": 5, "is_active": "on", "sort_order": 0,
            "images-TOTAL_FORMS": 1, "images-INITIAL_FORMS": 0,
            "images-0-image": SimpleUploadedFile("evil.jpg", b"<?php echo 1; ?>"), "images-0-order": 0,
            "price_logs-TOTAL_FORMS": 0, "price_logs-INITIAL_FORMS": 0,
            "specs-TOTAL_FORMS": 0, "specs-INITIAL_FORMS": 0,
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.low.images.exists())
