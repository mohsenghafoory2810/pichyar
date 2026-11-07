from django import forms
from django.contrib import admin, messages
from django.db import models
from django.db.models import Count
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from jalali_date.admin import ModelAdminJalaliMixin

from core.persian import fa_digits
from seo.admin import SEOAdminMixin, seo_fieldset

from .checklist import missing_items
from .models import Article, ArticleCategory, ArticleFAQ, Tag


class ArticleFAQInline(admin.StackedInline):
    model = ArticleFAQ
    extra = 0
    fields = (("question", "order"), "answer")
    verbose_name_plural = "پرسش‌های متداول (در انتهای مقاله و در نتایج گوگل نمایش داده می‌شوند)"
    formfield_overrides = {
        # The answer is plain text: a compact textarea instead of the default large one.
        models.TextField: {"widget": forms.Textarea(attrs={"rows": 3, "cols": 80})},
    }


@admin.register(Article)
class ArticleAdmin(SEOAdminMixin, ModelAdminJalaliMixin, admin.ModelAdmin):
    list_display = ("title", "status", "category", "published_at", "updated_at", "checklist_summary", "preview_link")
    list_filter = ("status", "category", "tags")
    list_select_related = ("category",)
    search_fields = ("title", "slug", "short_answer", "body")
    autocomplete_fields = ("tags", "related_products", "related_articles")
    readonly_fields = ("content_checklist", "preview_link", "reading_minutes", "created_at", "updated_at")
    inlines = [ArticleFAQInline]
    actions = ["publish", "unpublish"]
    fieldsets = (
        (
            "فهرست بررسی محتوا",
            {
                "fields": ("content_checklist",),
                "description": "فقط یادآوری است؛ ذخیره و انتشار مقاله را متوقف نمی‌کند.",
            },
        ),
        (
            "۱. مقاله",
            {
                "fields": ("title", "slug", "short_answer", "body"),
                "description": "نشانی (slug) خالی بماند، خودکار از عنوان ساخته می‌شود. با تغییر نشانی، ریدایرکت ۳۰۱ خودکار ثبت می‌شود.",
            },
        ),
        ("۲. تصویر شاخص", {"fields": ("cover", "cover_alt")}),
        ("۳. انتشار", {"fields": ("status", "published_at", "author_name", "preview_link")}),
        ("۴. دسته و برچسب", {"fields": ("category", "tags")}),
        ("۵. پیوندهای داخلی", {"fields": ("related_products", "related_articles")}),
        seo_fieldset(),
        ("اطلاعات", {"fields": ("reading_minutes", "created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(faq_count=Count("faqs", distinct=True))

    # --- read-only panels -------------------------------------------------------

    @admin.display(description="وضعیت محتوا")
    def checklist_summary(self, obj):
        missing = missing_items(obj, faq_count=getattr(obj, "faq_count", None))
        if not missing:
            return format_html('<span style="color:#15803d">✓ کامل</span>')
        return format_html(
            '<span style="color:#b45309" title="{}">⚠ {} مورد ناقص</span>',
            " ".join(missing),
            fa_digits(len(missing)),
        )

    @admin.display(description="بررسی محتوا")
    def content_checklist(self, obj):
        missing = missing_items(obj, faq_count=getattr(obj, "faq_count", None)) if obj and obj.pk else None
        if missing is None:
            return "پس از اولین ذخیره، موارد ناقص مقاله اینجا نمایش داده می‌شوند."
        if not missing:
            return format_html('<strong style="color:#15803d">✓ همهٔ موارد کامل است.</strong>')
        return format_html(
            '<ul class="blog-checklist" style="margin:0;padding-inline-start:1.2em;color:#b45309">{}</ul>',
            format_html_join("", "<li>⚠ {}</li>", ((m,) for m in missing)),
        )

    @admin.display(description="پیش‌نمایش")
    def preview_link(self, obj):
        if not obj or not obj.pk:
            return "-"
        label = "دیدن در سایت" if obj.is_published else "پیش‌نمایش"
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', obj.get_absolute_url(), label)

    # --- save: warn about what is missing (never blocks) -------------------------

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        missing = missing_items(form.instance)
        if missing:
            messages.warning(request, "این مقاله ذخیره شد، اما این موارد هنوز کامل نیستند: " + " ".join(missing))

    # --- bulk actions ----------------------------------------------------------

    @admin.action(description="انتشار مقاله‌های انتخاب‌شده")
    def publish(self, request, queryset):
        count = 0
        for article in queryset.exclude(status=Article.Status.PUBLISHED):
            article.status = Article.Status.PUBLISHED
            article.save()  # sets published_at when empty
            count += 1
        scheduled = queryset.filter(status=Article.Status.PUBLISHED, published_at__gt=timezone.now()).count()
        message = f"{fa_digits(count)} مقاله منتشر شد."
        if scheduled:
            message += f" {fa_digits(scheduled)} مقاله تاریخ انتشار آینده دارد و از همان تاریخ در سایت دیده می‌شود."
        self.message_user(request, message, messages.SUCCESS)

    @admin.action(description="برگرداندن به پیش‌نویس")
    def unpublish(self, request, queryset):
        count = 0
        for article in queryset.filter(status=Article.Status.PUBLISHED):
            article.status = Article.Status.DRAFT
            article.save()
            count += 1
        self.message_user(request, f"{fa_digits(count)} مقاله به پیش‌نویس برگشت.", messages.SUCCESS)


@admin.register(ArticleCategory)
class ArticleCategoryAdmin(SEOAdminMixin, admin.ModelAdmin):
    list_display = ("name", "slug", "order", "article_count")
    list_editable = ("order",)
    search_fields = ("name", "slug")
    fieldsets = (
        (None, {"fields": ("name", "slug", "description", "order")}),
        seo_fieldset(),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n_articles=Count("articles"))

    @admin.display(description="تعداد مقاله", ordering="n_articles")
    def article_count(self, obj):
        return fa_digits(obj.n_articles)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "article_count")
    search_fields = ("name", "slug")
    fields = ("name", "slug")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n_articles=Count("articles"))

    @admin.display(description="تعداد مقاله", ordering="n_articles")
    def article_count(self, obj):
        return fa_digits(obj.n_articles)
