from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from catalog.images import MAX_SIDE, validate_product_image
from catalog.models import ProductImage

from .utils import TempMediaMixin, image_upload, make_product


class ProductImageTests(TempMediaMixin, TestCase):
    def test_upload_is_resized_and_converted_to_webp(self):
        product = make_product()
        img = ProductImage.objects.create(product=product, image=image_upload("big.png", "PNG", (3000, 1500)))
        self.assertTrue(img.image.name.endswith(".webp"))
        with Image.open(img.image.path) as stored:
            self.assertEqual(stored.format, "WEBP")
            self.assertEqual(stored.size, (MAX_SIDE, MAX_SIDE // 2))

    def test_first_image_by_order_is_main(self):
        product = make_product()
        second = ProductImage.objects.create(product=product, image=image_upload(), order=1)
        first = ProductImage.objects.create(product=product, image=image_upload(), order=0)
        self.assertEqual(product.main_image, first)
        self.assertNotEqual(product.main_image, second)

    def test_deleting_removes_the_file(self):
        img = ProductImage.objects.create(product=make_product(), image=image_upload())
        storage, name = img.image.storage, img.image.name
        with self.captureOnCommitCallbacks(execute=True):
            img.delete()
        self.assertFalse(storage.exists(name))

    def test_rejects_non_images(self):
        with self.assertRaisesMessage(ValidationError, "تصویر معتبری نیست"):
            validate_product_image(SimpleUploadedFile("x.jpg", b"not an image"))

    def test_rejects_unsupported_format(self):
        with self.assertRaisesMessage(ValidationError, "فقط تصویرهای JPG، PNG یا WebP"):
            validate_product_image(image_upload("x.gif", "GIF", (10, 10)))

    @override_settings(PRODUCT_IMAGE_MAX_MB=1)
    def test_rejects_large_files(self):
        big = SimpleUploadedFile("x.jpg", b"0" * (1024 * 1024 + 1))
        with self.assertRaisesMessage(ValidationError, "بیشتر از ۱ مگابایت"):
            validate_product_image(big)


class ImageVariantTests(TempMediaMixin, TestCase):
    def test_variants_created_srcset_and_deleted(self):
        from catalog.images import srcset_for, variant_name

        img = ProductImage.objects.create(product=make_product(), image=image_upload("big.png", "PNG", (3000, 1500)))
        storage, name = img.image.storage, img.image.name
        self.assertEqual((img.width, img.height), (MAX_SIDE, MAX_SIDE // 2))
        for width in (400, 800):
            vname = variant_name(name, width)
            self.assertTrue(storage.exists(vname))
            with Image.open(storage.path(vname)) as v:
                self.assertEqual(v.format, "WEBP")
                self.assertEqual(v.width, width)
        srcset = srcset_for(img)
        self.assertIn("-400w.webp 400w", srcset)
        self.assertIn("-800w.webp 800w", srcset)
        self.assertTrue(srcset.endswith(f"{img.image.url} {MAX_SIDE}w"))
        with self.captureOnCommitCallbacks(execute=True):
            img.delete()
        self.assertFalse(storage.exists(name))
        self.assertFalse(storage.exists(variant_name(name, 400)))

    def test_small_image_has_no_variants(self):
        from catalog.images import srcset_for, variant_name

        img = ProductImage.objects.create(product=make_product(), image=image_upload(size=(300, 300)))
        self.assertFalse(img.image.storage.exists(variant_name(img.image.name, 400)))
        self.assertEqual(srcset_for(img), "")

    def test_missing_variant_files_are_skipped(self):
        from catalog.images import srcset_for, variant_name

        img = ProductImage.objects.create(product=make_product(), image=image_upload())
        img.image.storage.delete(variant_name(img.image.name, 400))
        srcset = srcset_for(img)
        self.assertNotIn("-400w.webp", srcset)
        self.assertIn("800w", srcset)

    def test_product_page_uses_srcset_and_alt(self):
        from django.conf import settings

        product = make_product("تصویردار")
        ProductImage.objects.create(product=product, image=image_upload(), alt_text="نمای روبه‌رو")
        self.client.cookies[settings.AGE_GATE_COOKIE] = "1"
        response = self.client.get(product.get_absolute_url())
        self.assertContains(response, 'alt="نمای روبه‌رو"')
        self.assertContains(response, "srcset=")
        self.assertContains(response, 'fetchpriority="high"')
        self.assertContains(response, f'width="{MAX_SIDE}"')
