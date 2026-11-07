import math

from django.db import models
from django.urls import reverse
from django.utils import timezone
from tinymce.models import HTMLField

from catalog.images import image_size, process_product_image, validate_image_upload
from catalog.text import unique_slug
from core.html import sanitize_html
from seo.meta import plain_text
from seo.models import SEOFields

WORDS_PER_MINUTE = 200


class ArticleCategory(SEOFields, models.Model):
    name = models.CharField("نام", max_length=100)
    slug = models.SlugField("نشانی (slug)", max_length=120, unique=True, allow_unicode=True, blank=True)
    description = models.TextField("توضیح", blank=True)
    order = models.PositiveIntegerField("ترتیب", default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "دستهٔ مقاله"
        verbose_name_plural = "دسته‌های مقاله"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(ArticleCategory, self.name, self.pk)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("blog:category", kwargs={"slug": self.slug})


class Tag(models.Model):
    name = models.CharField("نام", max_length=60, unique=True)
    slug = models.SlugField("نشانی (slug)", max_length=80, unique=True, allow_unicode=True, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "برچسب"
        verbose_name_plural = "برچسب‌ها"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Tag, self.name, self.pk)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("blog:tag", kwargs={"slug": self.slug})


class ArticleQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=Article.Status.PUBLISHED, published_at__lte=timezone.now())


class Article(SEOFields, models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "پیش‌نویس"
        PUBLISHED = "published", "منتشرشده"

    title = models.CharField("عنوان", max_length=200)
    slug = models.SlugField("نشانی (slug)", max_length=220, unique=True, allow_unicode=True, blank=True)
    short_answer = models.TextField(
        "پاسخ کوتاه",
        blank=True,
        help_text="۲ تا ۳ جملهٔ مستقیم که به پرسش اصلی مقاله پاسخ می‌دهد. در کادر برجسته بالای مقاله نمایش داده می‌شود.",
    )
    body = HTMLField("متن مقاله", blank=True, help_text="برای فهرست مطالب خودکار، از «عنوان ۲» و «عنوان ۳» استفاده کنید.")
    cover = models.ImageField(
        "تصویر شاخص",
        upload_to="articles/",
        blank=True,
        validators=[validate_image_upload],
        help_text="JPG، PNG یا WebP؛ خودکار کوچک و به WebP تبدیل می‌شود. پیشنهاد: ۱۲۰۰×۶۳۰ پیکسل.",
    )
    cover_width = models.PositiveIntegerField(null=True, blank=True, editable=False)
    cover_height = models.PositiveIntegerField(null=True, blank=True, editable=False)
    cover_alt = models.CharField("متن جایگزین تصویر (alt)", max_length=200, blank=True)
    category = models.ForeignKey(
        ArticleCategory, verbose_name="دسته", on_delete=models.PROTECT, null=True, blank=True, related_name="articles"
    )
    tags = models.ManyToManyField(Tag, verbose_name="برچسب‌ها", blank=True, related_name="articles")
    author_name = models.CharField("نام نویسنده", max_length=100, blank=True)
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    published_at = models.DateTimeField(
        "تاریخ انتشار", null=True, blank=True, help_text="خالی بماند، هنگام انتشار زمان همان لحظه ثبت می‌شود."
    )
    created_at = models.DateTimeField("تاریخ ایجاد", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین به‌روزرسانی", auto_now=True)
    reading_minutes = models.PositiveSmallIntegerField("زمان مطالعه (دقیقه)", default=1, editable=False)
    related_products = models.ManyToManyField(
        "catalog.Product", verbose_name="محصولات مرتبط", blank=True, related_name="articles"
    )
    related_articles = models.ManyToManyField(
        "self", verbose_name="مقاله‌های مرتبط", blank=True, symmetrical=False, related_name="+"
    )

    objects = ArticleQuerySet.as_manager()

    class Meta:
        ordering = ["-published_at", "-id"]
        verbose_name = "مقاله"
        verbose_name_plural = "مقاله‌ها"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Article, self.title, self.pk)
        self.body = sanitize_html(self.body)
        if self.cover and not self.cover._committed:
            self.cover = process_product_image(self.cover)
            self.cover_width, self.cover_height = image_size(self.cover)
        if self.status == self.Status.PUBLISHED and not self.published_at:
            self.published_at = timezone.now()
        words = len(plain_text(self.body).split())
        self.reading_minutes = max(1, math.ceil(words / WORDS_PER_MINUTE))
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("blog:article", kwargs={"slug": self.slug})

    @property
    def is_published(self):
        return (
            self.status == self.Status.PUBLISHED and self.published_at is not None and self.published_at <= timezone.now()
        )

    @property
    def cover_alt_text(self):
        return self.cover_alt or self.title


class ArticleFAQ(models.Model):
    article = models.ForeignKey(Article, verbose_name="مقاله", on_delete=models.CASCADE, related_name="faqs")
    question = models.CharField("پرسش", max_length=250)
    answer = models.TextField("پاسخ")
    order = models.PositiveIntegerField("ترتیب", default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "پرسش متداول"
        verbose_name_plural = "پرسش‌های متداول"

    def __str__(self):
        return self.question
