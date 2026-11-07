import os
import re
import subprocess
import sys

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.tests.utils import TempMediaMixin, image_upload
from core.admin import mask_secret
from core.models import Banner, SiteSettings

SECRET = "4F7A6E2B5C3D4E5F6A7B8C9D0E1F2A3B"
MERCHANT = "00000000-1111-2222-3333-444455556666"

# Every setting the earlier parts introduced must be on the settings page.
REQUIRED_FIELDS = [
    "site_name", "logo", "phone", "support_info", "maintenance_mode", "maintenance_message",
    "shipping_step_amount", "shipping_step_fee", "shipping_rounding", "gift_enabled", "gift_threshold",
    "admin_sms_enabled", "admin_sms_numbers", "sms_provider", "sms_api_key", "sms_sender",
    "online_payment_enabled", "payment_gateway", "gateway_merchant_id", "gateway_sandbox", "card_to_card_enabled",
]


class SiteSettingsAdminTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("09120000001", password="pass"))
        self.s = SiteSettings.load()
        self.s.sms_api_key = SECRET
        self.s.gateway_merchant_id = MERCHANT
        self.s.save()
        self.url = reverse("admin:core_sitesettings_change", args=[self.s.pk])

    def form_data(self, **overrides):
        s = self.s
        data = {
            "site_name": s.site_name, "phone": s.phone, "support_info": s.support_info,
            "maintenance_message": s.maintenance_message,
            "shipping_step_amount": s.shipping_step_amount, "shipping_step_fee": s.shipping_step_fee,
            "shipping_rounding": s.shipping_rounding, "gift_enabled": "on", "gift_threshold": s.gift_threshold,
            "online_payment_enabled": "on", "payment_gateway": s.payment_gateway, "card_to_card_enabled": "on",
            "sms_provider": s.sms_provider, "sms_sender": "", "admin_sms_enabled": "on", "admin_sms_numbers": "",
            "sms_api_key": "", "gateway_merchant_id": "",
            "cards-TOTAL_FORMS": "1", "cards-INITIAL_FORMS": "0", "cards-MIN_NUM_FORMS": "0", "cards-MAX_NUM_FORMS": "1000",
            "cards-0-card_number": "۶۰۳۷-۹۹۱۲-۳۴۵۶-۷۸۹۰", "cards-0-holder_name": "فروشگاه", "cards-0-bank_name": "ملی",
            "cards-0-is_active": "on", "cards-0-order": "0",
        }
        data.update(overrides)
        return data

    def test_every_setting_is_on_the_page(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        for name in REQUIRED_FIELDS:
            self.assertContains(response, f'name="{name}"', msg_prefix=name)
        for section in ["مشخصات فروشگاه", "تعمیر و نگهداری", "هزینهٔ ارسال", "هدیه", "پرداخت اینترنتی",
                        "کارت به کارت", "سرویس پیامک", "پیامک سفارش جدید به مدیر", "نام صاحب کارت"]:
            self.assertContains(response, section)

    def test_secrets_are_never_sent_to_the_browser(self):
        response = self.client.get(self.url)
        self.assertNotContains(response, SECRET)
        self.assertNotContains(response, MERCHANT)
        self.assertContains(response, mask_secret(SECRET))
        self.assertTrue(mask_secret(SECRET).endswith("2A3B"))

    def test_empty_secret_keeps_the_saved_value(self):
        response = self.client.post(self.url, self.form_data(site_name="فروشگاه تازه"))
        self.assertEqual(response.status_code, 302, getattr(response, "context_data", {}).get("errors"))
        self.s.refresh_from_db()
        self.assertEqual((self.s.site_name, self.s.sms_api_key, self.s.gateway_merchant_id), ("فروشگاه تازه", SECRET, MERCHANT))
        self.assertEqual(self.s.cards.get().card_number, "6037991234567890")

    def test_new_secret_replaces_and_clear_removes(self):
        self.client.post(self.url, self.form_data(sms_api_key=" new-key-123456789 "))
        self.s.refresh_from_db()
        self.assertEqual(self.s.sms_api_key, "new-key-123456789")
        self.client.post(self.url, self.form_data(clear_gateway_merchant_id="on"))
        self.s.refresh_from_db()
        self.assertEqual(self.s.gateway_merchant_id, "")
        self.assertEqual(self.s.sms_api_key, "new-key-123456789")

    def test_mask(self):
        self.assertEqual(mask_secret(""), "")
        self.assertEqual(mask_secret("short"), "••••••••")
        self.assertEqual(mask_secret("abcdefghijkl"), "••••••••ijkl")


class SecurityHeadersTests(TestCase):
    def test_csp_and_permissions_policy(self):
        response = self.client.get(reverse("health"))
        self.assertIn("default-src 'self'", response["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
        self.assertIn("camera=()", response["Permissions-Policy"])
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def run_prod_check(self, **env):
        """`manage.py check --deploy` with the production settings, in a fresh process."""
        environment = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.prod", "SECRET_KEY": "0123456789abcdef" * 4,
                       "ADMIN_URL": "panel-k39x/", "DOMAIN": "example.ir", **env}
        return subprocess.run(
            [sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING"],
            cwd=settings.BASE_DIR, env=environment, capture_output=True, text=True, timeout=120,
        )

    def test_production_settings_pass_the_deploy_check(self):
        result = self.run_prod_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_production_refuses_admin_url_admin_and_weak_secret(self):
        for env in ({"ADMIN_URL": "admin/"}, {"ADMIN_URL": "panel-change-me/"}, {"SECRET_KEY": "short"}, {"SECRET_KEY": ""}):
            with self.subTest(env=env):
                result = self.run_prod_check(**env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ImproperlyConfigured", result.stderr)

    def test_csrf_is_enforced(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        response = client.post(reverse("accounts:login"), {"action": "send", "mobile": "09121234567"})
        self.assertEqual(response.status_code, 403)


class UploadValidationTests(TempMediaMixin, TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("09120000001", password="pass"))

    def post_banner(self, image):
        return self.client.post(reverse("admin:core_banner_add"), {"title": "بنر", "image": image, "order": 0, "is_active": "on"})

    def test_valid_banner(self):
        self.assertEqual(self.post_banner(image_upload("b.png", "PNG", (40, 20))).status_code, 302)
        self.assertEqual(Banner.objects.count(), 1)

    def test_fake_image_rejected(self):
        fake = SimpleUploadedFile("evil.jpg", b"<script>alert(1)</script>", content_type="image/jpeg")
        response = self.post_banner(fake)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Banner.objects.exists())

    def test_gif_rejected(self):
        response = self.post_banner(image_upload("b.gif", "GIF", (10, 10)))
        self.assertContains(response, "فقط تصویرهای JPG، PNG یا WebP")

    @override_settings(PRODUCT_IMAGE_MAX_MB=0)
    def test_too_big_rejected(self):
        response = self.post_banner(image_upload("b.png", "PNG", (10, 10)))
        self.assertContains(response, "حجم تصویر نباید بیشتر از")
        self.assertFalse(Banner.objects.exists())


class EveryAdminPageTests(TestCase):
    """Smoke test: the list (and add) page of every registered model opens and is labelled in Persian."""

    def test_all_changelists_and_add_pages(self):
        from django.contrib import admin

        user = get_user_model().objects.create_superuser("09120000001", password="pass")
        self.client.force_login(user)
        for model, model_admin in admin.site._registry.items():
            opts = model._meta
            with self.subTest(model=opts.label):
                url = reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist")
                response = self.client.get(url, follow=True)
                self.assertEqual(response.status_code, 200)
                title = re.search(r"<h1>(.*?)</h1>", response.content.decode(), re.S).group(1)
                self.assertNotRegex(title, r"[A-Za-z]{3,}")  # e.g. an untranslated "Select task to change"
                if model_admin.has_add_permission(response.wsgi_request):
                    add = reverse(f"admin:{opts.app_label}_{opts.model_name}_add")
                    self.assertEqual(self.client.get(add).status_code, 200)
