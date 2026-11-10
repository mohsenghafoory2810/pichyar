"""Persian overrides in locale/ and core.i18n: no English left in the admin or the storefront."""

import importlib.util
import re
import tempfile
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import Permission
from django.test import SimpleTestCase, TestCase
from django.utils import translation

ROOT = Path(settings.BASE_DIR)


class LocaleOverridesTests(SimpleTestCase):
    def test_compiled_catalog_is_up_to_date(self):
        spec = importlib.util.spec_from_file_location("compile_po", ROOT / "scripts" / "compile_po.py")
        compile_po = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(compile_po)
        pos = list((ROOT / "locale").glob("*/LC_MESSAGES/*.po"))
        self.assertTrue(pos)
        with tempfile.TemporaryDirectory() as tmp:
            for po in pos:
                fresh = Path(tmp) / po.with_suffix(".mo").name
                compile_po.write_mo(compile_po.parse_po(po), fresh)
                mo = po.with_suffix(".mo")
                self.assertTrue(
                    mo.exists() and mo.read_bytes() == fresh.read_bytes(),
                    f"{mo.relative_to(ROOT)} is out of date: run python scripts/compile_po.py",
                )

    def test_third_party_strings_are_persian(self):
        with translation.override("fa"):
            self.assertEqual(translation.gettext("Failed tasks"), "کارهای ناموفق")  # django-q2
            self.assertEqual(translation.gettext("access attempts"), "قفل‌های ورود به پنل")  # django-axes
            self.assertEqual(translation.gettext("Password-based authentication"), "ورود با گذرواژه")  # Django 5.1+
            self.assertEqual(translation.gettext("Select all"), "انتخاب همه")  # import-export

    def test_untranslatable_names_are_persian(self):
        self.assertEqual(apps.get_app_config("axes").verbose_name, "قفل‌های ورود")
        self.assertEqual(apps.get_app_config("otp_totp").verbose_name, "ورود دومرحله‌ای")
        self.assertEqual(apps.get_model("otp_totp", "totpdevice")._meta.verbose_name, "دستگاه ورود دومرحله‌ای")

    def test_no_multiline_hash_comments_in_templates(self):
        # {# … #} only works on one line; a multi-line one is printed on the page as text.
        for template in (ROOT / "templates").rglob("*.html"):
            for number, line in enumerate(template.read_text(encoding="utf-8").splitlines(), 1):
                opened = len(re.findall(r"\{#", line))
                self.assertEqual(
                    opened, len(re.findall(r"#\}", line)), f"{template.relative_to(ROOT)}:{number} use {{% comment %}}"
                )


class PermissionNamesTests(TestCase):
    def test_default_permissions_are_persian(self):
        self.assertFalse(Permission.objects.filter(name__startswith="Can ").exists())
        self.assertEqual(Permission.objects.get(codename="add_order").name, "افزودن سفارش")
        self.assertEqual(Permission.objects.get(codename="view_failure").name, "مشاهده کار ناموفق")
