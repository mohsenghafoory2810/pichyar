from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from catalog.models import Category
from catalog.views import PAGE_SIZE

from .utils import make_product


class StorefrontTestCase(TestCase):
    def setUp(self):
        self.client.cookies[settings.AGE_GATE_COOKIE] = "1"
        self.tobacco = Category.objects.get(slug="tobacco")
        self.accessories = Category.objects.get(slug="accessories")
        self.pipes = Category.objects.get(slug="pipes")


class HomeTests(StorefrontTestCase):
    def test_tobacco_and_accessories_sections(self):
        make_product("چاپمن آلمانی", price=750_000, category=self.tobacco)
        make_product("پیپ شیشه‌ای", price=1_425_000, category=self.pipes)  # sub-category of لوازم
        response = self.client.get("/")
        sections = response.context["sections"]
        self.assertEqual([s["category"].slug for s in sections], ["tobacco", "accessories"])
        self.assertContains(response, "چاپمن آلمانی")
        self.assertContains(response, "پیپ شیشه‌ای")
        self.assertContains(response, "۱٬۴۲۵٬۰۰۰ تومان")

    def test_hides_inactive_products(self):
        make_product("مخفی", is_active=False)
        self.assertNotContains(self.client.get("/"), "مخفی")


class CategoryListingTests(StorefrontTestCase):
    def test_top_level_includes_subcategories(self):
        make_product("پیپ چوبی ترکیه", category=self.pipes)
        make_product("کلمبیایی", category=self.tobacco)
        response = self.client.get(self.accessories.get_absolute_url())
        self.assertContains(response, "پیپ چوبی ترکیه")
        self.assertNotContains(response, "کلمبیایی")
        self.assertContains(response, self.pipes.get_absolute_url())  # sub-category chip

    def test_search_and_arabic_letters(self):
        make_product("کارتل آمریکایی", category=self.tobacco)
        make_product("یونانی", category=self.tobacco)
        response = self.client.get(self.tobacco.get_absolute_url(), {"q": "كارتل"})  # Arabic kaf
        self.assertEqual([p.name for p in response.context["products"]], ["کارتل آمریکایی"])

    def test_sorting(self):
        make_product("گران", price=900_000)
        make_product("ارزان", price=100_000)
        make_product("وسط", price=500_000)
        url = self.tobacco.get_absolute_url()
        names = lambda sort: [p.name for p in self.client.get(url, {"sort": sort}).context["products"]]  # noqa: E731
        self.assertEqual(names("price_asc"), ["ارزان", "وسط", "گران"])
        self.assertEqual(names("price_desc"), ["گران", "وسط", "ارزان"])
        self.assertEqual(names("newest"), ["وسط", "ارزان", "گران"])

    def test_pagination_keeps_query(self):
        for i in range(PAGE_SIZE + 1):
            make_product(f"توتون {i}", price=1000 + i)
        url = self.tobacco.get_absolute_url()
        first = self.client.get(url, {"sort": "price_asc"})
        self.assertEqual(len(first.context["products"]), PAGE_SIZE)
        self.assertContains(first, "page=2")
        self.assertContains(first, "sort=price_asc")
        second = self.client.get(url, {"sort": "price_asc", "page": 2})
        self.assertEqual([p.name for p in second.context["products"]], [f"توتون {PAGE_SIZE}"])

    def test_htmx_request_gets_results_only(self):
        make_product("یونانی")
        response = self.client.get(
            self.tobacco.get_absolute_url(), {"q": "یون"}, HTTP_HX_REQUEST="true", HTTP_HX_TARGET="product-results"
        )
        self.assertTemplateUsed(response, "catalog/_product_results.html")
        self.assertNotContains(response, "<html")

    def test_inactive_category_is_404(self):
        self.pipes.is_active = False
        self.pipes.save()
        self.assertEqual(self.client.get(self.pipes.get_absolute_url()).status_code, 404)

    def test_header_search(self):
        make_product("پیپ چوبی ترکیه", category=self.pipes)
        response = self.client.get(reverse("catalog:search"), {"q": "پیپ"})
        self.assertContains(response, "پیپ چوبی ترکیه")


class ProductDetailTests(StorefrontTestCase):
    def test_in_stock(self):
        p = make_product("دیویدوف", price=300_000, stock=3, unit="۵۰ گرم")
        response = self.client.get(p.get_absolute_url())
        self.assertContains(response, "<h1")
        self.assertContains(response, "۳۰۰٬۰۰۰ تومان")
        self.assertContains(response, "۵۰ گرم")
        self.assertContains(response, "موجود")
        self.assertContains(response, 'max="3"')
        self.assertContains(response, "افزودن به سبد خرید")
        self.assertContains(response, f'hx-post="/cart/add/{p.pk}/"')

    def test_out_of_stock(self):
        p = make_product("دیویدوف", stock=0)
        response = self.client.get(p.get_absolute_url())
        self.assertContains(response, "ناموجود")
        self.assertNotContains(response, "افزودن به سبد خرید")

    def test_inactive_product_is_404(self):
        p = make_product("مخفی", is_active=False)
        self.assertEqual(self.client.get(p.get_absolute_url()).status_code, 404)

    def test_persian_slug_url(self):
        p = make_product("دستگاه زیگ‌زاگ طلایی ترکیه‌ای")
        self.assertEqual(p.slug, "دستگاه-زیگ-زاگ-طلایی-ترکیه-ای")
        self.assertEqual(self.client.get(p.get_absolute_url()).status_code, 200)


class CategoryModelTests(TestCase):
    def test_max_two_levels(self):
        from django.core.exceptions import ValidationError

        pipes = Category.objects.get(slug="pipes")
        with self.assertRaises(ValidationError):
            Category(name="سطح سوم", parent=pipes).full_clean()
        accessories = Category.objects.get(slug="accessories")
        accessories.parent = Category.objects.get(slug="tobacco")
        with self.assertRaises(ValidationError):
            accessories.full_clean()  # has children, cannot become a child
