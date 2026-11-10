from django import forms
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html
from django_q.models import Failure, OrmQ, Schedule, Success
from jalali_date.admin import ModelAdminJalaliMixin, TabularInlineJalaliMixin

from seo.admin import SEOAdminMixin, seo_fieldset
from seo.meta import auto_description, auto_title

from .models import BankCard, Banner, SiteSettings, StaticPage
from .persian import jalali_format
from .utils import get_site_settings

# Site header, titles and sidebar groups: core.admin_site.ShopAdminSite.


class BankCardInline(TabularInlineJalaliMixin, admin.TabularInline):
    model = BankCard
    extra = 0
    fields = ("card_number", "holder_name", "bank_name", "is_active", "order")
    verbose_name_plural = "کارت‌های بانکی برای کارت به کارت (شماره کارت + نام صاحب کارت)"


def mask_secret(value):
    """'abcd1234wxyz' -> '••••••••wxyz' (only the last 4 characters are shown)."""
    value = value or ""
    if not value:
        return ""
    visible = value[-4:] if len(value) > 8 else ""
    return "•" * max(8, len(value) - len(visible)) + visible


class SecretField(forms.CharField):
    """A credential the admin page never sends back to the browser. Left empty, the saved
    value is kept; the «پاک کردن» box next to it removes it."""

    widget = forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password", "dir": "ltr"})

    def __init__(self, *args, **kwargs):
        kwargs["required"] = False
        kwargs.pop("empty_value", None)
        super().__init__(*args, **kwargs)


class SiteSettingsForm(forms.ModelForm):
    SECRET_FIELDS = ("sms_api_key", "gateway_merchant_id")

    clear_sms_api_key = forms.BooleanField(label="پاک کردن کلید API پیامک", required=False)
    clear_gateway_merchant_id = forms.BooleanField(label="پاک کردن شناسهٔ پذیرنده", required=False)

    class Meta:
        model = SiteSettings
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.SECRET_FIELDS:
            model_field = self.fields[name]
            current = getattr(self.instance, name, "")
            hint = (
                f"مقدار فعلی: {mask_secret(current)} — برای تغییر، مقدار جدید را وارد کنید؛ خالی بماند، همان قبلی می‌ماند."
                if current
                else "هنوز وارد نشده است."
            )
            self.fields[name] = SecretField(
                label=model_field.label,
                max_length=model_field.max_length,
                help_text=f"{model_field.help_text} {hint}".strip(),
            )
            self.fields[name].widget.attrs["placeholder"] = mask_secret(current) or ""

    def clean(self):
        cleaned = super().clean()
        for name in self.SECRET_FIELDS:
            new = (cleaned.get(name) or "").strip()
            if cleaned.get(f"clear_{name}"):
                cleaned[name] = ""
            else:
                cleaned[name] = new or getattr(self.instance, name, "") or ""
        return cleaned


@admin.register(SiteSettings)
class SiteSettingsAdmin(ModelAdminJalaliMixin, admin.ModelAdmin):
    form = SiteSettingsForm
    inlines = [BankCardInline]
    fieldsets = (
        ("۱. مشخصات فروشگاه", {"fields": ("site_name", "logo", "favicon", "phone", "support_info")}),
        (
            "۲. تعمیر و نگهداری",
            {
                "fields": ("maintenance_mode", "maintenance_message"),
                "description": "وقتی روشن است، بازدیدکنندگان فقط پیام زیر را می‌بینند؛ مدیرانِ واردشده سایت را عادی می‌بینند.",
            },
        ),
        (
            "۳. هزینهٔ ارسال (پست)",
            {
                "fields": ("shipping_step_amount", "shipping_step_fee", "shipping_rounding"),
                "description": "هزینهٔ ارسال = تعداد پله‌ها × هزینهٔ هر پله. تعداد پله‌ها = مبلغ خرید ÷ مبلغ هر پله (گردشده).",
            },
        ),
        (
            "۴. هدیه",
            {
                "fields": ("gift_enabled", "gift_threshold"),
                "description": "تعداد هدیه = جمع کالاها پس از تخفیف ÷ مبلغ هر هدیه (رو به پایین). کالاهای هدیه در «فروش ← کالاهای هدیه» تعیین می‌شوند.",
            },
        ),
        (
            "۵. پرداخت اینترنتی (درگاه بانکی)",
            {
                "fields": (
                    "online_payment_enabled",
                    "payment_gateway",
                    "gateway_merchant_id",
                    "clear_gateway_merchant_id",
                    "gateway_sandbox",
                ),
                "description": "بدون شناسهٔ پذیرنده، گزینهٔ پرداخت اینترنتی به مشتری نشان داده نمی‌شود و فقط کارت به کارت کار می‌کند.",
            },
        ),
        (
            "۶. کارت به کارت",
            {
                "fields": ("card_to_card_enabled",),
                "description": "شماره کارت‌ها و نام صاحب هر کارت را پایین همین صفحه وارد کنید. کارت به کارت بدون درگاه هم کار می‌کند.",
            },
        ),
        (
            "۷. سرویس پیامک",
            {
                "fields": ("sms_provider", "sms_api_key", "clear_sms_api_key", "sms_sender"),
                "description": "تا کلید API خالی است، پیامکی فرستاده نمی‌شود (فقط در «گزارش پیامک‌ها» ثبت می‌شود). متن پیامک‌ها در «پیامک ← متن‌های پیامک».",
            },
        ),
        ("۸. پیامک سفارش جدید به مدیر", {"fields": ("admin_sms_enabled", "admin_sms_numbers")}),
        (
            "۹. سئو و شبکه‌های اجتماعی",
            {
                "fields": (
                    "site_description",
                    "organization_name",
                    "social_links",
                    "default_og_image",
                    "health_warning",
                    "google_site_verification",
                    "bing_site_verification",
                    "analytics_snippet",
                    "allow_ai_crawlers",
                ),
                "description": "نقشهٔ سایت: /sitemap.xml — قواعد خزنده‌ها: /robots.txt — معرفی سایت برای هوش مصنوعی: /llms.txt",
            },
        ),
    )

    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # There is only one row: go straight to its edit page.
        obj = SiteSettings.load()
        return redirect(reverse("admin:core_sitesettings_change", args=[obj.pk]))


@admin.register(StaticPage)
class StaticPageAdmin(SEOAdminMixin, ModelAdminJalaliMixin, admin.ModelAdmin):
    list_display = ("title", "slug", "is_active", "show_in_footer", "order", "updated_at", "view_link")
    list_editable = ("is_active", "show_in_footer", "order")
    search_fields = ("title", "body")
    fieldsets = (
        (None, {"fields": ("title", "slug", "body", "is_active", "show_in_footer", "order")}),
        seo_fieldset(),
    )

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if obj is not None:
            from catalog.admin import seo_placeholders

            site_name = get_site_settings(request).site_name
            seo_placeholders(form, auto_title(obj.title, site_name), auto_description(obj.body))
        return form

    @admin.display(description="نمایش")
    def view_link(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener">دیدن در سایت</a>', obj.get_absolute_url())


@admin.register(Banner)
class BannerAdmin(ModelAdminJalaliMixin, admin.ModelAdmin):
    list_display = ("thumbnail", "title", "link", "order", "is_active")
    list_display_links = ("thumbnail", "title")
    list_editable = ("order", "is_active")
    list_filter = ("is_active",)
    fields = ("title", "image", "preview", "alt_text", "link", "order", "is_active")
    readonly_fields = ("preview",)

    @admin.display(description="پیش‌نمایش")
    def thumbnail(self, obj):
        if not obj.image:
            return "-"
        return format_html('<img src="{}" alt="" style="height:48px;border-radius:6px">', obj.image.url)

    @admin.display(description="تصویر فعلی")
    def preview(self, obj):
        if not obj.pk or not obj.image:
            return "-"
        return format_html('<img src="{}" alt="" style="max-width:100%;max-height:200px;border-radius:8px">', obj.image.url)


# --- background jobs (django-q2) -----------------------------------------------------
# The schedules are created by `setup_schedules`, so only failed jobs are worth showing.
for _model in (Success, Schedule, OrmQ):
    if admin.site.is_registered(_model):
        admin.site.unregister(_model)
admin.site.unregister(Failure)


@admin.register(Failure)
class FailedTaskAdmin(admin.ModelAdmin):
    list_display = ("task_name", "function", "failed_at", "error")
    list_display_links = None
    search_fields = ("name", "func")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(request, {"title": "کارهای پس‌زمینهٔ ناموفق", **(extra_context or {})})

    @admin.display(description="نام کار", ordering="name")
    def task_name(self, obj):
        return obj.name

    @admin.display(description="تابع")
    def function(self, obj):
        return format_html('<code dir="ltr">{}</code>', obj.func)

    @admin.display(description="زمان", ordering="stopped")
    def failed_at(self, obj):
        return jalali_format(obj.stopped, "%Y/%m/%d - %H:%M") if obj.stopped else "-"

    @admin.display(description="خطا")
    def error(self, obj):
        return str(obj.result or "")[:200]
