from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalog.models import Category
from catalog.tests.utils import make_product


class SEOAdminTests(TestCase):
    def setUp(self):
        admin = get_user_model().objects.create_superuser("09120000000", "pass-12345")
        self.client.force_login(admin)

    def test_product_change_form(self):
        p = make_product("دیویدوف", price=120_000)
        response = self.client.get(reverse("admin:catalog_product_change", args=[p.pk]))
        self.assertEqual(response.status_code, 200)
        for name in ("sku", "brand", "meta_title", "meta_description", "canonical_url", "noindex"):
            self.assertContains(response, f'name="{name}"')
        self.assertContains(response, "specs-TOTAL_FORMS")
        self.assertContains(response, "images-__prefix__-alt_text")
        self.assertContains(response, "js/admin-seo.js")
        self.assertContains(response, "data-seo-counter")
        self.assertContains(response, 'placeholder="خودکار: دیویدوف |')

    def test_category_change_form(self):
        cat = Category.objects.get(slug="pipes")
        response = self.client.get(reverse("admin:catalog_category_change", args=[cat.pk]))
        for name in ("intro", "image_alt", "meta_title", "faqs-TOTAL_FORMS"):
            self.assertContains(response, f'name="{name}"')

    def test_static_page_banner_and_settings(self):
        response = self.client.get(reverse("admin:core_staticpage_change", args=[1]))
        self.assertContains(response, 'name="meta_description"')
        self.assertContains(self.client.get(reverse("admin:core_banner_add")), 'name="alt_text"')
        response = self.client.get(reverse("admin:core_sitesettings_change", args=[1]))
        self.assertContains(response, "۹. سئو و شبکه‌های اجتماعی")
        for name in ("site_description", "social_links", "default_og_image", "health_warning",
                     "google_site_verification", "bing_site_verification", "analytics_snippet", "allow_ai_crawlers"):
            self.assertContains(response, f'name="{name}"')
