"""Customer reviews: moderation (approve / reject, also in bulk) and the shop's public reply.

Reviews come only from customers on the storefront, so there is no «add» here, and the
customer's own words (rating, title, text) are read-only.
"""

from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from django.utils.text import Truncator
from jalali_date.admin import ModelAdminJalaliMixin

from core.admin_mixins import PersianDigitsSearchMixin
from core.persian import fa_digits, fa_number, jalali_format

from .models import Review

S = Review.Status


@admin.register(Review)
class ReviewAdmin(PersianDigitsSearchMixin, ModelAdminJalaliMixin, admin.ModelAdmin):
    list_display = ("product", "user", "rating_display", "status", "verified_purchase", "created", "short_text")
    list_display_links = ("product",)
    list_editable = ("status",)
    list_filter = ("status", "rating", "verified_purchase", "product")
    search_fields = ("text", "title", "product__name", "user__mobile", "user__name")
    search_help_text = "متن یا عنوان نظر، نام محصول، موبایل یا نام مشتری"
    list_select_related = ("product", "user")
    list_per_page = 50
    actions = ["approve_selected", "reject_selected"]
    readonly_fields = (
        "product",
        "user",
        "rating_display",
        "title",
        "text",
        "verified_purchase",
        "ip_address",
        "created",
        "updated",
    )
    fieldsets = (
        ("نظر مشتری", {"fields": ("product", "user", "rating_display", "title", "text")}),
        ("بررسی و پاسخ", {
            "fields": ("status", "admin_reply"),
            "description": "فقط نظرهای «تأییدشده» در سایت نمایش داده می‌شوند. پاسخ فروشگاه زیر همان نظر نمایش داده می‌شود.",
        }),
        ("اطلاعات ثبت", {"fields": ("verified_purchase", "ip_address", "created", "updated")}),
    )

    def has_add_permission(self, request):
        return False  # reviews are written by customers on the storefront

    @admin.display(description="امتیاز", ordering="rating")
    def rating_display(self, obj):
        return format_html(
            '<span title="{} از ۵">{}<span style="color:#ccc">{}</span></span>',
            fa_digits(obj.rating),
            "★" * obj.rating,
            "★" * (5 - obj.rating),
        )

    @admin.display(description="تاریخ ثبت", ordering="created_at")
    def created(self, obj):
        return jalali_format(obj.created_at, "%Y/%m/%d - %H:%M")

    @admin.display(description="آخرین ویرایش", ordering="updated_at")
    def updated(self, obj):
        return jalali_format(obj.updated_at, "%Y/%m/%d - %H:%M")

    @admin.display(description="متن")
    def short_text(self, obj):
        return Truncator(obj.text).chars(60)

    def _set_status(self, request, queryset, status, label):
        count = queryset.exclude(status=status).update(status=status, updated_at=timezone.now())
        self.message_user(request, f"{fa_number(count) or '۰'} نظر {label} شد.")

    @admin.action(description="تأیید نظرهای انتخاب‌شده", permissions=["change"])
    def approve_selected(self, request, queryset):
        self._set_status(request, queryset, S.APPROVED, "تأیید")

    @admin.action(description="رد نظرهای انتخاب‌شده", permissions=["change"])
    def reject_selected(self, request, queryset):
        self._set_status(request, queryset, S.REJECTED, "رد")
