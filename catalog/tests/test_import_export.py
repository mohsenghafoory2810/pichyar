from io import BytesIO

import tablib
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from catalog.models import PriceChangeLog, Product
from catalog.resources import ProductResource

from .utils import make_product

HEADERS = ["شناسه", "نام", "دسته", "واحد", "قیمت (تومان)", "موجودی"]


def xlsx_bytes(rows):
    return tablib.Dataset(*rows, headers=HEADERS).export("xlsx")


class ProductResourceTests(TestCase):
    def setUp(self):
        self.a = make_product("الف", price=300_000, stock=0)
        self.b = make_product("ب", price=525_000, stock=4)

    def row(self, product, price, stock):
        return [product.pk, product.name, product.category.name, product.unit, price, stock]

    def import_rows(self, rows, dry_run=False):
        dataset = tablib.Dataset(*rows, headers=HEADERS)
        return ProductResource().import_data(dataset, dry_run=dry_run, raise_errors=False)

    def test_export_has_all_products_with_persian_headers(self):
        dataset = ProductResource().export()
        self.assertEqual(dataset.headers, HEADERS)
        self.assertEqual(len(dataset), Product.objects.count())
        self.assertIn([self.b.pk, "ب", "توتون", "عدد", 525_000, 4], [list(r) for r in dataset])

    def test_valid_import_updates_price_and_stock(self):
        result = self.import_rows([self.row(self.a, 330_000, 12), self.row(self.b, "۵۵۰٬۰۰۰", "۳")])
        self.assertFalse(result.has_errors() or result.has_validation_errors())
        self.a.refresh_from_db()
        self.b.refresh_from_db()
        self.assertEqual((self.a.price, self.a.stock, self.b.price, self.b.stock), (330_000, 12, 550_000, 3))
        self.assertEqual(PriceChangeLog.objects.count(), 2)

    def test_excel_float_cells_are_accepted(self):
        result = self.import_rows([self.row(self.a, 310000.0, 2.0)])
        self.assertFalse(result.has_validation_errors())
        self.a.refresh_from_db()
        self.assertEqual(self.a.price, 310_000)

    def test_name_column_is_ignored(self):
        row = self.row(self.a, 300_000, 0)
        row[1] = "نام عوض‌شده"
        self.import_rows([row])
        self.a.refresh_from_db()
        self.assertEqual(self.a.name, "الف")

    def test_unchanged_rows_are_skipped(self):
        result = self.import_rows([self.row(self.a, 300_000, 0)])
        self.assertEqual(result.totals["skip"], 1)
        self.assertEqual(PriceChangeLog.objects.count(), 0)

    def test_validation_errors_block_the_whole_import(self):
        bad_rows = [
            self.row(self.a, "سیصد", 1),  # text price
            self.row(self.b, -5, 1),  # negative
            [self.a.pk, "", "", "", 1000.5, 1],  # fraction
            [self.b.pk, "", "", "", 1000, ""],  # blank stock
            [999_999, "?", "", "", 1000, 1],  # unknown product
            ["", "جدید", "", "", 1000, 1],  # new row
        ]
        for row in bad_rows:
            with self.subTest(row=row):
                # The admin preview is a dry run; with errors it offers no confirm button.
                result = self.import_rows([self.row(self.a, 999_000, 9), row], dry_run=True)
                self.assertTrue(result.has_validation_errors())
        for p in (self.a, self.b):
            p.refresh_from_db()
        self.assertEqual((self.a.price, self.b.price), (300_000, 525_000))

    def test_error_messages_are_persian(self):
        result = self.import_rows([self.row(self.a, "سیصد", 1), [999_999, "", "", "", 1, 1]])
        messages = [str(e) for row in result.invalid_rows for e in row.error.messages]
        self.assertTrue(any("عدد صحیح نیست" in m for m in messages), messages)
        self.assertTrue(any("پیدا نشد" in m for m in messages), messages)


class AdminImportExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("09120000001", email="boss@example.com", password="pass")

    def setUp(self):
        self.client.force_login(self.admin)
        self.p = make_product("چاپمن آلمانی", price=750_000, stock=0)

    def upload(self, rows):
        return self.client.post(
            reverse("admin:catalog_product_import"),
            {
                "resource": "0",
                "format": "0",
                "import_file": SimpleUploadedFile("products.xlsx", xlsx_bytes(rows)),
            },
        )

    def test_export_downloads_xlsx(self):
        response = self.client.post(
            reverse("admin:catalog_product_export"),
            {"format": "0", "resource": "0", **{f"productresource_{f}": "on" for f in ProductResource._meta.fields}},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml", response["Content-Type"])
        sheet = load_workbook(BytesIO(response.content)).active
        values = [[c.value for c in row] for row in sheet.iter_rows()]
        self.assertEqual(values[0], HEADERS)
        self.assertIn(self.p.pk, [r[0] for r in values[1:]])

    def test_preview_shows_errors_and_changes_nothing(self):
        response = self.upload([[self.p.pk, "", "", "", "abc", 1]])
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("confirm_form", response.context)
        self.assertTrue(response.context["result"].has_validation_errors())
        self.assertContains(response, "عدد صحیح نیست")
        self.p.refresh_from_db()
        self.assertEqual(self.p.price, 750_000)

    def test_preview_then_confirm(self):
        response = self.upload([[self.p.pk, "", "", "", 800_000, 6]])
        self.assertIn("confirm_form", response.context)
        self.p.refresh_from_db()
        self.assertEqual(self.p.price, 750_000, "the preview must not save anything")
        self.assertFalse(PriceChangeLog.objects.exists(), "the preview's log rows must be rolled back")

        confirm = response.context["confirm_form"].initial
        response = self.client.post(reverse("admin:catalog_product_process_import"), confirm)
        self.assertEqual(response.status_code, 302)
        self.p.refresh_from_db()
        self.assertEqual((self.p.price, self.p.stock), (800_000, 6))
        log = PriceChangeLog.objects.get()
        self.assertEqual((log.old_price, log.new_price, log.changed_by), (750_000, 800_000, self.admin))
