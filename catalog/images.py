"""Product image validation and processing (resize + convert to WebP)."""

from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

from core.persian import fa_digits

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_SIDE = 1400
WEBP_QUALITY = 82


def max_upload_bytes():
    return getattr(settings, "PRODUCT_IMAGE_MAX_MB", 5) * 1024 * 1024


def validate_product_image(file):
    validate_image_file(file, max_upload_bytes())


def validate_image_upload(file):
    """Logo, banner and category images: same rules as product images."""
    validate_image_file(file, max_upload_bytes())


def validate_image_file(file, limit):
    """JPEG/PNG/WebP of at most `limit` bytes (also used for card-to-card receipts)."""
    if file.size > limit:
        raise ValidationError(f"حجم تصویر نباید بیشتر از {fa_digits(limit // (1024 * 1024))} مگابایت باشد.")
    try:
        file.seek(0)
        with Image.open(file) as img:
            fmt = img.format
            img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise ValidationError("این فایل تصویر معتبری نیست.")
    finally:
        file.seek(0)
    if fmt not in ALLOWED_FORMATS:
        raise ValidationError("فقط تصویرهای JPG، PNG یا WebP پذیرفته می‌شوند.")


def process_product_image(field_file):
    """Returns a ContentFile: EXIF-rotated, at most MAX_SIDE px, WebP, metadata stripped."""
    field_file.seek(0)
    with Image.open(field_file) as img:
        img = ImageOps.exif_transpose(img)
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "transparency" in img.info or img.mode in ("LA", "P") else "RGB")
        out = BytesIO()
        img.save(out, "WEBP", quality=WEBP_QUALITY, method=4)
    name = Path(field_file.name).stem + ".webp"
    return ContentFile(out.getvalue(), name=name)


def image_size(file):
    """(width, height) of an image file or ContentFile."""
    file.seek(0)
    with Image.open(file) as img:
        size = img.size
    file.seek(0)
    return size


# --- responsive variants (srcset) ---------------------------------------------------
# Smaller WebP copies stored next to the original: products/7/x.webp → products/7/x-400w.webp.
# Created after a ProductImage is saved and removed with it (catalog.signals).

VARIANT_WIDTHS = (400, 800)


def variant_name(name, width):
    path = Path(name)
    return str(path.with_name(f"{path.stem}-{width}w.webp")).replace("\\", "/")


def create_variants(field_file, widths=VARIANT_WIDTHS):
    """Writes the missing variants narrower than the original. Returns the names written."""
    storage, name = field_file.storage, field_file.name
    written = []
    try:
        with storage.open(name) as fh, Image.open(fh) as img:
            img.load()
            original_width = img.width
            for width in widths:
                target = variant_name(name, width)
                if width >= original_width or storage.exists(target):
                    continue
                copy = img.copy()
                copy.thumbnail((width, width * 10), Image.Resampling.LANCZOS)
                out = BytesIO()
                copy.save(out, "WEBP", quality=WEBP_QUALITY, method=4)
                written.append(storage.save(target, ContentFile(out.getvalue())))
    except (OSError, UnidentifiedImageError):
        pass
    return written


def delete_variants(storage, name, widths=VARIANT_WIDTHS):
    for width in widths:
        target = variant_name(name, width)
        if storage.exists(target):
            storage.delete(target)


def srcset_for(product_image, widths=VARIANT_WIDTHS):
    """'…-400w.webp 400w, …-800w.webp 800w, original.webp 1400w' from files that exist; '' when
    there is nothing to choose from (no width known)."""
    field_file = getattr(product_image, "image", None)
    if not field_file or not product_image.width:
        return ""
    storage, name = field_file.storage, field_file.name
    parts = []
    for width in widths:
        if width < product_image.width:
            target = variant_name(name, width)
            if storage.exists(target):
                parts.append(f"{storage.url(target)} {width}w")
    if not parts:
        return ""
    parts.append(f"{field_file.url} {product_image.width}w")
    return ", ".join(parts)
