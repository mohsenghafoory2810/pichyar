from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import SiteSettings, normalize_bale_id, normalize_telegram_id, normalize_whatsapp_number


class NormalizeWhatsappTests(SimpleTestCase):
    def test_accepted_forms(self):
        for raw in [
            "09123456789",
            "۰۹۱۲۳۴۵۶۷۸۹",
            "۰۹۱۲ ۳۴۵ ۶۷۸۹",
            "0912-345-6789",
            "9123456789",
            "+989123456789",
            "+98 912 345 6789",
            "00989123456789",
            "‎+98 (912) 345-6789‏",
            "wa.me/989123456789",
            "https://wa.me/989123456789",
            "https://wa.me/+989123456789?text=سلام",
            "https://api.whatsapp.com/send?phone=989123456789&text=x",
            " ٠٩١٢٣٤٥٦٧٨٩ ",
        ]:
            self.assertEqual(normalize_whatsapp_number(raw), "989123456789", raw)

    def test_foreign_number_is_kept(self):
        self.assertEqual(normalize_whatsapp_number("+1 (415) 555-0100"), "14155550100")

    def test_empty(self):
        self.assertEqual(normalize_whatsapp_number("  "), "")

    def test_invalid(self):
        for raw in ["123", "0912abc4567", "+98912345678901234", "https://example.com/989123456789", "wa.me/"]:
            with self.assertRaises(ValidationError, msg=raw):
                normalize_whatsapp_number(raw)


class NormalizeUsernameTests(SimpleTestCase):
    def test_telegram_forms(self):
        for raw in [
            "pichyar_support",
            "@pichyar_support",
            " @pichyar_support ",
            "t.me/pichyar_support",
            "https://t.me/pichyar_support",
            "http://www.t.me/pichyar_support/",
            "telegram.me/pichyar_support",
            "https://telegram.me/pichyar_support?start=1",
            "‏@pichyar_support",
        ]:
            self.assertEqual(normalize_telegram_id(raw), "pichyar_support", raw)

    def test_telegram_invalid(self):
        for raw in ["abcd", "1pichyar", "_pichyar", "pich-yar", "پیچیار", "a" * 33, "https://example.com/pichyar", "@"]:
            with self.assertRaises(ValidationError, msg=raw):
                normalize_telegram_id(raw)

    def test_bale_forms(self):
        for raw in ["pichyar", "@pichyar", "ble.ir/pichyar", "https://ble.ir/pichyar", "https://www.ble.ir/pichyar/"]:
            self.assertEqual(normalize_bale_id(raw), "pichyar", raw)
        self.assertEqual(normalize_bale_id("abc"), "abc")

    def test_bale_invalid(self):
        for raw in ["ab", "9pichyar", "pich yar", "پیچیار", "t.me/pichyar", "a" * 33]:
            with self.assertRaises(ValidationError, msg=raw):
                normalize_bale_id(raw)


class SiteSettingsCleanTests(TestCase):
    def setUp(self):
        self.s = SiteSettings.load()

    def test_full_clean_normalizes_every_field(self):
        self.s.whatsapp_number = "۰۹۱۲ ۳۴۵ ۶۷۸۹"
        self.s.telegram_id = "https://t.me/pichyar_support"
        self.s.bale_id = "@pichyar"
        self.s.admin_sms_numbers = "۰۹۱۲۰۰۰۰۰۰۱"
        self.s.full_clean()
        self.assertEqual(
            (self.s.whatsapp_number, self.s.telegram_id, self.s.bale_id, self.s.admin_sms_numbers),
            ("989123456789", "pichyar_support", "pichyar", "09120000001"),
        )

    def test_errors_are_reported_per_field(self):
        self.s.whatsapp_number = "12"
        self.s.telegram_id = "ab"
        self.s.bale_id = "پیچیار"
        self.s.admin_sms_numbers = "123"
        with self.assertRaises(ValidationError) as cm:
            self.s.full_clean()
        errors = cm.exception.message_dict
        self.assertEqual(set(errors), {"whatsapp_number", "telegram_id", "bale_id", "admin_sms_numbers"})
        self.assertIn("واتساپ", errors["whatsapp_number"][0])
        self.assertIn("تلگرام", errors["telegram_id"][0])
        self.assertIn("بله", errors["bale_id"][0])

    def test_excluded_fields_are_left_alone(self):
        self.s.admin_sms_numbers = "bad"
        self.s.whatsapp_number = "۰۹۱۲۳۴۵۶۷۸۹"
        self.s.full_clean(exclude=["admin_sms_numbers"])
        self.assertEqual(self.s.whatsapp_number, "989123456789")
        self.s.telegram_id = "x"
        self.s.full_clean(exclude=["admin_sms_numbers", "telegram_id"])  # no error: excluded
        self.assertEqual(self.s.telegram_id, "x")


class MessengerUrlTests(SimpleTestCase):
    def test_empty(self):
        s = SiteSettings()
        self.assertEqual((s.whatsapp_url, s.telegram_url, s.bale_url, s.messenger_links), ("", "", "", []))

    def test_urls_and_order(self):
        s = SiteSettings(whatsapp_number="989123456789", telegram_id="pichyar_support", bale_id="pichyar")
        self.assertEqual(s.whatsapp_url, "https://wa.me/989123456789")
        self.assertEqual(s.telegram_url, "https://t.me/pichyar_support")
        self.assertEqual(s.bale_url, "https://ble.ir/pichyar")
        self.assertEqual(
            s.messenger_links,
            [
                {"key": "bale", "name": "بله", "url": "https://ble.ir/pichyar"},
                {"key": "whatsapp", "name": "واتساپ", "url": "https://wa.me/989123456789"},
                {"key": "telegram", "name": "تلگرام", "url": "https://t.me/pichyar_support"},
            ],
        )

    def test_whatsapp_message_is_urlencoded(self):
        s = SiteSettings(whatsapp_number="989123456789", whatsapp_message=" سلام، سفارش #12 & بیشتر ")
        self.assertEqual(
            s.whatsapp_url,
            "https://wa.me/989123456789?text=%D8%B3%D9%84%D8%A7%D9%85%D8%8C%20%D8%B3%D9%81%D8%A7%D8%B1%D8%B4%20%2312%20%26%20%D8%A8%DB%8C%D8%B4%D8%AA%D8%B1",
        )

    def test_only_configured_links(self):
        s = SiteSettings(telegram_id="pichyar_support")
        self.assertEqual([link["key"] for link in s.messenger_links], ["telegram"])


class StorefrontMessengerTests(TestCase):
    def setUp(self):
        self.client.cookies[settings.AGE_GATE_COOKIE] = "1"
        self.s = SiteSettings.load()

    def configure(self, **values):
        for name, value in values.items():
            setattr(self.s, name, value)
        self.s.save()

    def test_button_with_links_and_phone(self):
        self.configure(
            whatsapp_number="989123456789", telegram_id="pichyar_support", bale_id="pichyar", phone="02112345678",
            messenger_button_label="گفتگو با ما",
        )
        response = self.client.get("/")
        self.assertContains(response, 'id="support-fab"')
        self.assertContains(response, 'aria-controls="support-fab-panel"')
        self.assertContains(response, 'aria-expanded="false"')
        self.assertContains(response, 'role="group" hidden')
        self.assertContains(response, "گفتگو با ما")
        self.assertContains(response, "support-fab--left")
        html = response.content.decode()
        start = html.index('id="support-fab-panel"')
        panel = html[start:html.index("</ul>", start)]
        self.assertLess(panel.index("https://ble.ir/pichyar"), panel.index("https://wa.me/989123456789"))
        self.assertLess(panel.index("https://wa.me/989123456789"), panel.index("https://t.me/pichyar_support"))
        self.assertIn('href="tel:02112345678"', panel)
        self.assertIn('target="_blank" rel="noopener"', panel)
        # Inside #page, so the age gate makes it inert.
        self.assertLess(html.index('id="page"'), html.index('id="support-fab"'))

    def test_position_right(self):
        self.configure(telegram_id="pichyar_support", messenger_button_position="right")
        self.assertContains(self.client.get("/"), "support-fab--right")

    def test_hidden_when_disabled(self):
        self.configure(telegram_id="pichyar_support", messenger_button_enabled=False)
        response = self.client.get("/")
        self.assertNotContains(response, 'id="support-fab"')
        self.assertContains(response, "https://t.me/pichyar_support")  # still in the footer

    def test_hidden_when_nothing_to_offer(self):
        self.configure(phone="", support_tickets_enabled=False)
        self.assertNotContains(self.client.get("/"), 'id="support-fab"')

    def test_shown_for_support_tickets_alone(self):
        self.configure(phone="", support_tickets_enabled=True)
        response = self.client.get("/")
        self.assertContains(response, 'id="support-fab"')
        self.assertContains(response, f'href="{reverse("support:new")}"')
        self.assertContains(response, "پیام به پشتیبانی در سایت")

    def test_ticket_link_hidden_when_tickets_disabled(self):
        self.configure(telegram_id="pichyar_support", support_tickets_enabled=False)
        response = self.client.get("/")
        self.assertContains(response, 'id="support-fab"')
        self.assertNotContains(response, 'data-messenger="ticket"')

    def test_guest_ticket_link_leads_to_login(self):
        response = self.client.get(reverse("support:new"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_footer_links(self):
        self.configure(phone="", whatsapp_number="989123456789", bale_id="pichyar")
        html = self.client.get("/").content.decode()
        footer = html[html.index("<footer"):html.index("</footer>")]
        self.assertIn("پیام‌رسان‌ها", footer)
        self.assertIn('href="https://wa.me/989123456789"', footer)
        self.assertIn('href="https://ble.ir/pichyar"', footer)
        self.assertNotIn("t.me", footer)

    def test_not_on_maintenance_page(self):
        self.configure(maintenance_mode=True, telegram_id="pichyar_support")
        response = self.client.get("/")
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, "support-fab", status_code=503)


class MessengerAdminTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("09120000001", password="pass"))
        self.s = SiteSettings.load()
        self.url = reverse("admin:core_sitesettings_change", args=[self.s.pk])

    def test_page_has_the_section(self):
        self.s.telegram_id = "pichyar_support"
        self.s.save()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "۱۰. پشتیبانی و پیام‌رسان‌ها")
        for name in [
            "support_tickets_enabled", "support_intro", "support_admin_sms_enabled", "support_reply_sms_enabled",
            "whatsapp_number", "whatsapp_message", "telegram_id", "bale_id",
            "messenger_button_enabled", "messenger_button_position", "messenger_button_label",
        ]:
            self.assertContains(response, f'name="{name}"', msg_prefix=name)
        self.assertContains(response, 'href="https://t.me/pichyar_support"')

    def form_data(self, **overrides):
        # Reuse the full-form helper of the settings-page tests (module import, so its tests don't run twice).
        from core.tests import test_admin_settings

        return test_admin_settings.SiteSettingsAdminTests.form_data(self, **overrides)

    def test_post_normalizes(self):
        response = self.client.post(
            self.url,
            self.form_data(whatsapp_number="۰۹۱۲ ۳۴۵ ۶۷۸۹", telegram_id="https://t.me/pichyar_support", bale_id="@pichyar"),
        )
        self.assertEqual(response.status_code, 302, getattr(response, "context_data", {}).get("errors"))
        self.s.refresh_from_db()
        self.assertEqual(
            (self.s.whatsapp_number, self.s.telegram_id, self.s.bale_id), ("989123456789", "pichyar_support", "pichyar")
        )

    def test_post_reports_errors(self):
        response = self.client.post(self.url, self.form_data(whatsapp_number="12", telegram_id="ab", bale_id="پیچیار"))
        self.assertEqual(response.status_code, 200)
        errors = response.context["adminform"].form.errors
        self.assertEqual({"whatsapp_number", "telegram_id", "bale_id"} - set(errors), set())
        self.assertContains(response, "شمارهٔ واتساپ معتبر نیست")
