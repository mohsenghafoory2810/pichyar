from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.urls import reverse
from tinymce.models import HTMLField

from core.html import sanitize_html
from seo.models import SEOFields

from .audit import get_acting_user
from .images import image_size, process_product_image, validate_image_upload, validate_product_image
from .text import unique_slug


class Category(SEOFields, models.Model):
    """Two levels at most: top-level categories (e.g. «لوازم») and their sub-categories."""

    name = models.CharField("نام", max_length=100)
    slug = models.SlugField("نشانی (slug)", max_length=120, unique=True, allow_unicode=True, blank=True)
    parent = models.ForeignKey(
        "self",
        verbose_name="دستهٔ والد",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
        limit_choices_to={"parent__isnull": True},
        help_text="برای دسته‌های اصلی خالی بگذارید.",
    )
    image = models.ImageField("تصویر", upload_to="categories/", blank=True, validators=[validate_image_upload])
    image_alt = models.CharField("متن جایگزین تصویر (alt)", max_length=150, blank=True, help_text="خالی بماند، نام دسته استفاده می‌شود.")
    intro = HTMLField("متن معرفی بالای صفحه", blank=True, help_text="اختیاری. بالای فهرست محصولات این دسته نمایش داده می‌شود.")
    order = models.PositiveIntegerField("ترتیب", default=0)
    is_active = models.BooleanField("فعال", default=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "دسته‌بندی"
        verbose_name_plural = "دسته‌بندی‌ها"

    def __str__(self):
        return f"{self.parent.name} › {self.name}" if self.parent_id else self.name

    def clean(self):
        if not self.parent_id:
            return
        if self.parent_id == self.pk:
            raise ValidationError({"parent": "یک دسته نمی‌تواند والد خودش باشد."})
        if self.parent.parent_id:
            raise ValidationError({"parent": "دسته‌بندی حداکثر دو سطح دارد؛ والد باید یک دستهٔ اصلی باشد."})
        if self.pk and self.children.exists():
            raise ValidationError({"parent": "این دسته زیردسته دارد و خودش نمی‌تواند زیردسته شود."})

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Category, self.name, self.pk)
        self.intro = sanitize_html(self.intro)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("catalog:category", kwargs={"slug": self.slug})

    def descendant_ids(self):
        """This category and its sub-categories."""
        return [self.pk, *self.children.values_list("pk", flat=True)]


class ProductQuerySet(models.QuerySet):
    """update() bypasses Model.save(), so it logs price changes itself (bulk_update() goes through update())."""

    def active(self):
        return self.filter(is_active=True, category__is_active=True).filter(
            models.Q(category__parent__isnull=True) | models.Q(category__parent__is_active=True)
        )

    def in_category(self, category):
        return self.filter(category_id__in=category.descendant_ids())

    def update(self, **kwargs):
        if "price" not in kwargs:
            return super().update(**kwargs)
        with transaction.atomic(using=self.db):
            old = dict(self.values_list("pk", "price"))
            rows = super().update(**kwargs)
            new = dict(Product.objects.using(self.db).filter(pk__in=old).values_list("pk", "price"))
            PriceChangeLog.record_many((pk, old[pk], new[pk]) for pk in old if old[pk] != new.get(pk, old[pk]))
        return rows


class Product(SEOFields, models.Model):
    name = models.CharField("نام", max_length=150)
    short_name = models.CharField(
        "نام کوتاه", max_length=40, blank=True, help_text="برای پیامک‌های مدیر. اگر خالی بماند، همان نام استفاده می‌شود."
    )
    slug = models.SlugField("نشانی (slug)", max_length=170, unique=True, allow_unicode=True, blank=True)
    category = models.ForeignKey(Category, verbose_name="دسته‌بندی", on_delete=models.PROTECT, related_name="products")
    description = models.TextField("توضیحات", blank=True)
    sku = models.CharField(
        "کد کالا (SKU)", max_length=40, blank=True, help_text="اختیاری. خالی بماند، شناسهٔ محصول استفاده می‌شود."
    )
    brand = models.CharField("برند", max_length=80, blank=True)
    price = models.PositiveIntegerField("قیمت (تومان)")
    unit = models.CharField("واحد فروش", max_length=30, default="عدد", help_text="مثلاً «۵۰ گرم» یا «عدد»")
    stock = models.PositiveIntegerField("موجودی", default=0)
    low_stock_threshold = models.PositiveIntegerField(
        "آستانهٔ کمبود موجودی", default=5, help_text="وقتی موجودی به این عدد یا کمتر برسد، در فهرست مدیریت هشدار داده می‌شود."
    )
    is_active = models.BooleanField("فعال", default=True)
    sort_order = models.PositiveIntegerField("ترتیب نمایش", default=0)
    created_at = models.DateTimeField("تاریخ ایجاد", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین ویرایش", auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "محصول"
        verbose_name_plural = "محصولات"
        constraints = [
            models.CheckConstraint(condition=models.Q(stock__gte=0), name="product_stock_not_negative"),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Product, self.name, self.pk)
        if not self.short_name:
            self.short_name = self.name[:40]
        with transaction.atomic():
            old_price = None
            if self.pk:
                old_price = Product.objects.filter(pk=self.pk).values_list("price", flat=True).first()
            super().save(*args, **kwargs)
            if old_price is not None and old_price != self.price:
                PriceChangeLog.record_many([(self.pk, old_price, self.price)], user=getattr(self, "_changed_by", None))

    def get_absolute_url(self):
        return reverse("catalog:product", kwargs={"slug": self.slug})

    @property
    def in_stock(self):
        return self.stock > 0

    @property
    def is_low_stock(self):
        return self.stock <= self.low_stock_threshold

    @property
    def sku_or_id(self):
        return self.sku or f"P{self.pk}"

    @property
    def main_image(self):
        """First image by order (uses the prefetch cache when present)."""
        images = list(self.images.all())
        return images[0] if images else None


def product_image_path(instance, filename):
    return f"products/{instance.product_id or 'new'}/{filename}"


class ProductImage(models.Model):
    product = models.ForeignKey(Product, verbose_name="محصول", on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(
        "تصویر",
        upload_to=product_image_path,
        validators=[validate_product_image],
        help_text="JPG، PNG یا WebP. خودکار کوچک و به WebP تبدیل می‌شود. اولین تصویر، تصویر اصلی است.",
    )
    width = models.PositiveIntegerField("پهنا", null=True, blank=True, editable=False)
    height = models.PositiveIntegerField("ارتفاع", null=True, blank=True, editable=False)
    alt_text = models.CharField(
        "متن جایگزین (alt)", max_length=150, blank=True, help_text="توصیف کوتاه تصویر. خالی بماند، نام محصول استفاده می‌شود."
    )
    order = models.PositiveIntegerField("ترتیب", default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "تصویر محصول"
        verbose_name_plural = "تصویرهای محصول"

    def __str__(self):
        return f"تصویر {self.product}"

    @property
    def alt(self):
        return self.alt_text or self.product.name

    def save(self, *args, **kwargs):
        # A freshly uploaded file has not been written to storage yet.
        if self.image and not self.image._committed:
            self.image = process_product_image(self.image)
            self.width, self.height = image_size(self.image)
        super().save(*args, **kwargs)


class ProductSpec(models.Model):
    """Key-value specifications (origin, type, weight, ...) shown as a table on the product page."""

    product = models.ForeignKey(Product, verbose_name="محصول", on_delete=models.CASCADE, related_name="specs")
    name = models.CharField("ویژگی", max_length=60, help_text="مثلاً «کشور سازنده»")
    value = models.CharField("مقدار", max_length=200)
    order = models.PositiveIntegerField("ترتیب", default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "مشخصه"
        verbose_name_plural = "مشخصات فنی"

    def __str__(self):
        return f"{self.name}: {self.value}"


class CategoryFAQ(models.Model):
    category = models.ForeignKey(Category, verbose_name="دسته‌بندی", on_delete=models.CASCADE, related_name="faqs")
    question = models.CharField("پرسش", max_length=250)
    answer = models.TextField("پاسخ")
    order = models.PositiveIntegerField("ترتیب", default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "پرسش متداول"
        verbose_name_plural = "پرسش‌های متداول"

    def __str__(self):
        return self.question


class PriceChangeLog(models.Model):
    product = models.ForeignKey(Product, verbose_name="محصول", on_delete=models.CASCADE, related_name="price_logs")
    old_price = models.PositiveIntegerField("قیمت قبلی")
    new_price = models.PositiveIntegerField("قیمت جدید")
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="کاربر", on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField("زمان", auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "تغییر قیمت"
        verbose_name_plural = "تاریخچهٔ تغییر قیمت‌ها"

    def __str__(self):
        return f"{self.product_id}: {self.old_price} → {self.new_price}"

    @classmethod
    def record_many(cls, changes, user=None):
        """changes: iterable of (product_id, old_price, new_price)."""
        user = user or get_acting_user()
        user_id = user.pk if user is not None and user.is_authenticated else None
        cls.objects.bulk_create(
            cls(product_id=pk, old_price=old, new_price=new, changed_by_id=user_id) for pk, old, new in changes
        )
