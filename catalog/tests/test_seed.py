from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from catalog.models import Category, PriceChangeLog, Product, ProductImage
from catalog.seed_data import ACCESSORIES, TOBACCO

from .utils import TempMediaMixin


def seed(*args):
    call_command("seed_products", *args, stdout=StringIO())


class SeedProductsTests(TempMediaMixin, TestCase):
    def test_loads_every_product_once(self):
        seed()
        seed()
        self.assertEqual(Product.objects.count(), len(TOBACCO) + len(ACCESSORIES))
        self.assertEqual(ProductImage.objects.count(), Product.objects.count())
        self.assertEqual(Category.objects.count(), 10)
        self.assertFalse(Product.objects.exclude(stock=0).exists())

    def test_data_lands_in_the_right_place(self):
        seed("--no-images")
        chapman = Product.objects.get(name="چاپمن آلمانی")
        self.assertEqual((chapman.price, chapman.unit, chapman.category.slug), (750_000, "۵۰ گرم", "tobacco"))
        machine = Product.objects.get(name="دستگاه رومیزی سایز کینگ و اسلیم")
        self.assertEqual((machine.price, machine.unit, machine.category.slug), (8_925_000, "عدد", "machines"))
        self.assertEqual(machine.short_name, "دستگاه رومیزی")
        self.assertEqual(Product.objects.get(name="دیویدوف").short_name, "دیویدوف")
        self.assertEqual(Product.objects.get(name="پیپ شیشه‌ای").category.parent.slug, "accessories")
        self.assertEqual(Product.objects.filter(category__slug="tobacco").count(), 32)

    def test_rerun_keeps_admin_edits(self):
        seed("--no-images")
        p = Product.objects.get(name="کلمبیایی")
        p.price, p.stock = 400_000, 9
        p.save()
        seed("--no-images")
        p.refresh_from_db()
        self.assertEqual((p.price, p.stock), (400_000, 9))
        self.assertEqual(PriceChangeLog.objects.count(), 1)

    def test_placeholder_images_are_webp(self):
        seed()
        image = ProductImage.objects.first()
        self.assertTrue(image.image.name.endswith(".webp"))
