import shutil
import tempfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image

from catalog.models import Category, Product


class TempMediaMixin:
    """Uploaded files go to a throw-away MEDIA_ROOT."""

    @classmethod
    def setUpClass(cls):
        cls._media_dir = tempfile.mkdtemp(prefix="pichyar-media-")
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_dir)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_dir, ignore_errors=True)


def image_upload(name="photo.jpg", fmt="JPEG", size=(2400, 1600), color=(120, 80, 40)):
    out = BytesIO()
    Image.new("RGB", size, color).save(out, fmt)
    return SimpleUploadedFile(name, out.getvalue(), content_type=f"image/{fmt.lower()}")


def make_product(name="محصول آزمایشی", price=100_000, stock=10, category=None, **kwargs):
    category = category or Category.objects.get(slug="tobacco")
    return Product.objects.create(name=name, price=price, stock=stock, category=category, **kwargs)
