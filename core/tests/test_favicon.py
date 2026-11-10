from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from catalog.images import FAVICON_SIZE, validate_favicon_upload
from catalog.tests.utils import TempMediaMixin, image_upload
from core.models import SiteSettings


def ico_upload(sizes=((16, 16), (48, 48))):
    out = BytesIO()
    Image.new("RGBA", (64, 64), (200, 160, 40, 255)).save(out, "ICO", sizes=list(sizes))
    return SimpleUploadedFile("favicon.ico", out.getvalue(), content_type="image/x-icon")


class FaviconValidationTests(TestCase):
    def test_accepts_square_png_jpg_webp_and_ico(self):
        for upload in (
            image_upload("a.png", "PNG", size=(512, 512)),
            image_upload("a.jpg", "JPEG", size=(64, 64)),
            image_upload("a.webp", "WEBP", size=(200, 198)),
            ico_upload(),
        ):
            validate_favicon_upload(upload)

    def test_rejects_non_square_tiny_and_svg(self):
        with self.assertRaisesMessage(ValidationError, "مربع"):
            validate_favicon_upload(image_upload("wide.png", "PNG", size=(400, 100)))
        with self.assertRaisesMessage(ValidationError, "۳۲×۳۲"):
            validate_favicon_upload(image_upload("tiny.png", "PNG", size=(16, 16)))
        svg = SimpleUploadedFile("x.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
        with self.assertRaisesMessage(ValidationError, "معتبر"):
            validate_favicon_upload(svg)

    def test_rejects_large_files(self):
        big = SimpleUploadedFile("big.png", b"0" * (1024 * 1024 + 1))
        with self.assertRaisesMessage(ValidationError, "مگابایت"):
            validate_favicon_upload(big)


class FaviconTests(TempMediaMixin, TestCase):
    def test_default_icon_when_none_uploaded(self):
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, 'href="/static/img/favicon.svg"')
        self.assertContains(response, 'rel="apple-touch-icon" href="/static/img/apple-touch-icon.png"')
        response = self.client.get("/favicon.ico")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/static/img/favicon.svg")

    def test_uploaded_icon_is_stored_as_square_png_and_used(self):
        s = SiteSettings.load()
        s.favicon = ico_upload()
        s.save()
        s.refresh_from_db()
        self.assertTrue(s.favicon.name.endswith(".png"), s.favicon.name)
        with s.favicon.open() as fh, Image.open(fh) as img:
            self.assertEqual((img.format, img.size), ("PNG", (FAVICON_SIZE, FAVICON_SIZE)))

        response = self.client.get(reverse("core:home"))
        self.assertContains(response, f'rel="icon" href="{s.favicon.url}"')
        self.assertNotContains(response, "/static/img/favicon.svg")
        self.assertEqual(self.client.get("/favicon.ico")["Location"], s.favicon.url)

        name = s.favicon.name
        s.site_name = "فروشگاه"
        s.save()  # saving other settings keeps the stored icon as is
        s.refresh_from_db()
        self.assertEqual(s.favicon.name, name)

    def test_favicon_and_maintenance_page(self):
        s = SiteSettings.load()
        s.maintenance_mode = True
        s.save()
        self.assertEqual(self.client.get("/favicon.ico").status_code, 302)
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "/static/img/favicon.svg", status_code=503)
