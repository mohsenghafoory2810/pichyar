from django.test import TestCase

from catalog.models import Category, Product
from core.models import SiteSettings


class HomeSEOTests(TestCase):
    def get(self, **params):
        self.client.cookies["age_ok"] = "1"
        return self.client.get("/", data=params)

    def test_defaults_to_site_name(self):
        response = self.get()
        site = SiteSettings.load()
        self.assertContains(response, f"<title>{site.site_name}</title>", html=True)
        self.assertContains(response, f'<h1 class="sr-only">{site.site_name}</h1>', html=True)

    def test_home_fields_are_used_and_intro_is_sanitized(self):
        site = SiteSettings.load()
        site.home_meta_title = "خرید لوازم سیگار پیچ"
        site.home_meta_description = "توضیح صفحهٔ اصلی"
        site.home_heading = "فروشگاه لوازم سیگار پیچ"
        site.home_intro = '<h2>معرفی</h2><script>alert(1)</script><p>متن معرفی</p>'
        site.save()
        response = self.get()
        self.assertContains(response, "<title>خرید لوازم سیگار پیچ</title>", html=True)
        self.assertContains(response, 'content="توضیح صفحهٔ اصلی"')
        self.assertContains(response, "فروشگاه لوازم سیگار پیچ</h1>")
        self.assertContains(response, "<h2>معرفی</h2>")
        self.assertNotContains(response, "alert(1)</script>")

    def test_html_is_not_cacheable_by_shared_caches(self):
        response = self.get()
        self.assertEqual(response["Cache-Control"], "private, no-cache")

    def test_tracking_parameter_keeps_home_indexable(self):
        self.assertNotContains(self.get(utm_source="x"), "noindex")
        self.assertContains(self.get(foo="x"), "noindex")


class RelatedProductsTests(TestCase):
    def test_related_products_follow_the_current_one_and_wrap(self):
        from catalog.views import related_products

        category = Category.objects.create(name="دستهٔ آزمون", slug="test-related")
        products = [
            Product.objects.create(name=f"کالا {i}", slug=f"kala-{i}", category=category, price=1000, sort_order=i)
            for i in range(12)
        ]
        names = [p.name for p in related_products(products[9])]
        self.assertEqual(names, [f"کالا {i}" for i in (10, 11, 0, 1, 2, 3, 4, 5)])
        self.assertNotIn(products[9].name, names)


class RichTextTests(TestCase):
    def test_plain_text_becomes_paragraphs_and_html_is_sanitized(self):
        from core.html import rich_text

        self.assertEqual(rich_text("خط یک\nخط دو\n\nبند ۲ < ۳"), "<p>خط یک<br>خط دو</p>\n\n<p>بند ۲ &lt; ۳</p>")
        self.assertEqual(rich_text("متن <b>مهم</b>\n\nبند دوم"), "<p>متن <b>مهم</b></p>\n\n<p>بند دوم</p>")
        self.assertEqual(rich_text("<h2>تیتر</h2><script>x()</script><p>متن</p>"), "<h2>تیتر</h2><p>متن</p>")
        self.assertEqual(rich_text(""), "")

    def test_product_description_is_stored_as_html_and_shown(self):
        category = Category.objects.create(name="دستهٔ متن", slug="test-rich")
        product = Product.objects.create(name="کالای متن", slug="kala-rich", category=category, price=1000, description="بند اول\n\nبند دوم")
        self.assertEqual(product.description, "<p>بند اول</p>\n\n<p>بند دوم</p>")
        self.client.cookies["age_ok"] = "1"
        response = self.client.get(product.get_absolute_url())
        self.assertContains(response, "<p>بند اول</p>")
        self.assertContains(response, 'content="بند اول بند دوم"')
