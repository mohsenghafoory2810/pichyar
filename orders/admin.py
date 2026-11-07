"""Orders (list, detail page with the state-change buttons, packing slip, Excel export),
discount codes and the gift pool."""

import re

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from jalali_date.admin import ModelAdminJalaliMixin

from catalog import stock
from core.admin_mixins import PersianDigitsSearchMixin
from core.persian import fa_digits, fa_number, latin_digits, toman
from core.utils import get_site_settings
from notifications.services import resend_admin_sms

from . import export, reports
from .models import TRANSITIONS, DiscountCode, GiftPoolItem, InvalidTransition, Order, OrderStatus

S = OrderStatus
TRACKING_CODE_RE = re.compile(r"^[0-9A-Za-z-]{6,40}$")


class OrderDateFilter(admin.SimpleListFilter):
    """Registration date in Iranian-calendar periods (week from Saturday, Jalali months)."""

    title = "تاریخ ثبت"
    parameter_name = "created"
    CHOICES = [
        ("today", "امروز"),
        ("week", "این هفته"),
        ("month", "این ماه"),
        ("last_month", "ماه گذشته"),
        ("30d", "۳۰ روز اخیر"),
    ]

    def lookups(self, request, model_admin):
        return self.CHOICES

    def queryset(self, request, queryset):
        if self.value() in dict(self.CHOICES):
            start, end = reports.period_bounds(self.value())
            return queryset.filter(created_at__gte=start, created_at__lt=end)
        return queryset


@admin.register(Order)
class OrderAdmin(PersianDigitsSearchMixin, ModelAdminJalaliMixin, admin.ModelAdmin):
    list_display = (
        "number",
        "created_at",
        "recipient_name",
        "mobile",
        "total_display",
        "payment_method",
        "status_badge",
        "post_tracking_code",
    )
    list_filter = ("status", "payment_method", OrderDateFilter)
    search_fields = ("number", "mobile", "recipient_name", "recipient_mobile", "user__name", "post_tracking_code")
    search_help_text = "شمارهٔ سفارش، موبایل، نام گیرنده یا کد رهگیری"
    list_select_related = ("user",)
    list_per_page = 50
    actions = ["export_selected", "print_selected"]
    change_form_template = "admin/orders/order/change_form.html"
    change_list_template = "admin/orders/order/change_list.html"

    def has_add_permission(self, request):
        return False  # orders come from the checkout

    def has_delete_permission(self, request, obj=None):
        return False  # cancel instead: that gives stock, gift stock and the discount use back

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in Order._meta.fields]

    @admin.display(description="مبلغ کل", ordering="total")
    def total_display(self, obj):
        return toman(obj.total)

    @admin.display(description="وضعیت", ordering="status")
    def status_badge(self, obj):
        return format_html('<span class="order-status status-{}">{}</span>', obj.status, obj.get_status_display())

    # --- detail page --------------------------------------------------------------

    def change_view(self, request, object_id, form_url="", extra_context=None):
        if request.method == "POST":
            return HttpResponseNotAllowed(["GET"])  # nothing is edited here; the buttons have their own URLs
        order = (
            Order.objects.select_related("user", "discount_code")
            .prefetch_related("items", "payments", "status_logs__changed_by")
            .filter(pk=object_id if str(object_id).isdigit() else None)
            .first()
        )
        if order is None:
            return super().change_view(request, object_id, form_url, extra_context)
        items = list(order.items.all())
        context = {
            "order": order,
            "paid_items": [i for i in items if not i.is_gift],
            "gift_items": [i for i in items if i.is_gift],
            "payments": order.payments.all(),
            "logs": order.status_logs.all(),
            "can_approve": order.status == S.AWAITING_APPROVAL,
            "can_ship": order.status == S.PAID_PROCESSING,
            "can_deliver": order.status == S.SHIPPED,
            "can_cancel": S.CANCELED in TRANSITIONS[order.status],
            "can_resend_admin_sms": order.is_confirmed,
            "has_admin_numbers": bool(get_site_settings(request).admin_mobiles),
            "print_url": reverse("admin:orders_order_print") + f"?ids={order.pk}",
            **(extra_context or {}),
        }
        return super().change_view(request, object_id, form_url, context)

    def get_urls(self):
        view = self.admin_site.admin_view
        custom = [
            path("export/", view(self.export_view), name="orders_order_export"),
            path("print/", view(self.print_view), name="orders_order_print"),
            path("<int:object_id>/do/<str:action>/", view(self.action_view), name="orders_order_action"),
        ]
        return custom + super().get_urls()

    ACTION_LABELS = {
        "approve": "تأیید پرداخت کارت به کارت",
        "reject": "رد پرداخت کارت به کارت",
        "ship": "ثبت ارسال",
        "deliver": "ثبت تحویل",
        "cancel": "لغو سفارش",
        "resend_admin_sms": "ارسال مجدد پیامک ادمین",
    }

    @staticmethod
    def _note(request, name="note"):
        return (request.POST.get(name) or "").strip()[:200]

    def _do(self, request, order, action):
        """Run one state change and return the success message (raises InvalidTransition or
        stock.InsufficientStock when it is refused; then nothing changed)."""
        user = request.user
        if action == "approve":
            order.approve(by=user)
            return "پرداخت تأیید شد. سفارش «پرداخت‌شده، در حال آماده‌سازی» است و موجودی کسر شد."
        if action == "reject":
            order.reject(by=user, reason=self._note(request, "reason"))
            return "پرداخت رد و سفارش لغو شد."
        if action == "ship":
            code = latin_digits(request.POST.get("tracking_code", "")).replace(" ", "").strip()
            if not TRACKING_CODE_RE.match(code):
                raise InvalidTransition("کد رهگیری پست را درست وارد کنید (عدد و حروف انگلیسی، دست‌کم ۶ نویسه).")
            order.mark_shipped(code, by=user)
            return "سفارش «ارسال‌شده» شد و پیامک کد رهگیری برای مشتری فرستاده شد."
        if action == "deliver":
            order.mark_delivered(by=user)
            return "سفارش «تحویل‌شده» شد."
        if action == "cancel":
            was_confirmed = order.is_confirmed
            order.cancel(by=user, note=self._note(request))
            if was_confirmed:
                return "سفارش لغو شد؛ موجودی کالاها، موجودی هدیه‌ها و استفادهٔ کد تخفیف برگشت."
            return "سفارش لغو شد."
        if action == "resend_admin_sms":
            logs = resend_admin_sms(order)
            if not logs:
                raise InvalidTransition("هیچ شمارهٔ مدیری در «تنظیمات سایت ← پیامک سفارش جدید به مدیر» ثبت نشده است.")
            return f"پیامک سفارش برای {fa_number(len(logs))} شمارهٔ مدیر در صف ارسال قرار گرفت."
        raise Http404

    def action_view(self, request, object_id, action):
        if action not in self.ACTION_LABELS:
            raise Http404
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        order = get_object_or_404(Order, pk=object_id)
        if not self.has_change_permission(request, order):
            raise PermissionDenied
        try:
            message = self._do(request, order, action)
        except InvalidTransition as e:
            self.message_user(request, str(e), messages.ERROR)
        except stock.InsufficientStock as e:
            self.message_user(request, "موجودی کافی نیست: " + " ".join(e.messages), messages.ERROR)
        else:
            self.log_change(request, order, self.ACTION_LABELS[action])
            self.message_user(request, message, messages.SUCCESS)
        return redirect(reverse("admin:orders_order_change", args=[order.pk]))

    # --- packing slip and export ----------------------------------------------------

    def print_view(self, request):
        if not self.has_view_permission(request):
            raise PermissionDenied
        ids = [x for x in request.GET.get("ids", "").split(",") if x.isdigit()]
        orders = Order.objects.filter(pk__in=ids).prefetch_related("items").order_by("created_at", "id")
        context = {"orders": orders, "site_settings": get_site_settings(request), "title": "برگهٔ بسته‌بندی"}
        return TemplateResponse(request, "admin/orders/order/print.html", context)

    def export_view(self, request):
        """The orders of the list as it is filtered/searched right now."""
        if not self.has_view_permission(request):
            raise PermissionDenied
        changelist = self.get_changelist_instance(request)
        return export.xlsx_response(changelist.get_queryset(request))

    @admin.action(description="خروجی اکسل سفارش‌های انتخاب‌شده", permissions=["view"])
    def export_selected(self, request, queryset):
        return export.xlsx_response(queryset)

    @admin.action(description="چاپ برگهٔ بسته‌بندی سفارش‌های انتخاب‌شده", permissions=["view"])
    def print_selected(self, request, queryset):
        ids = ",".join(str(pk) for pk in queryset.values_list("pk", flat=True))
        return redirect(reverse("admin:orders_order_print") + f"?ids={ids}")


@admin.register(DiscountCode)
class DiscountCodeAdmin(PersianDigitsSearchMixin, ModelAdminJalaliMixin, admin.ModelAdmin):
    list_display = ("code", "kind", "value_display", "min_order_amount", "usage", "per_user_limit", "starts_at", "ends_at", "is_active")
    list_filter = ("is_active", "kind")
    list_editable = ("is_active",)
    search_fields = ("code",)
    readonly_fields = ("used_count", "created_at")
    fieldsets = (
        (None, {"fields": ("code", "is_active")}),
        (
            "مقدار تخفیف",
            {
                "fields": ("kind", "value", "max_discount", "min_order_amount"),
                "description": "تخفیف فقط روی جمع کالاها حساب می‌شود، نه هزینهٔ ارسال.",
            },
        ),
        (
            "محدودیت‌ها",
            {
                "fields": ("usage_limit", "per_user_limit", "starts_at", "ends_at", "used_count", "created_at"),
                "description": "هر استفاده وقتی شمرده می‌شود که پرداخت سفارش تأیید شود و با لغو سفارش برمی‌گردد.",
            },
        ),
    )

    @admin.display(description="مقدار")
    def value_display(self, obj):
        return obj.value_display

    @admin.display(description="استفاده‌شده", ordering="used_count")
    def usage(self, obj):
        if obj.usage_limit is None:
            return fa_digits(obj.used_count)
        return f"{fa_digits(obj.used_count)} از {fa_digits(obj.usage_limit)}"


@admin.register(GiftPoolItem)
class GiftPoolItemAdmin(admin.ModelAdmin):
    list_display = ("product", "gift_stock", "product_stock", "is_active", "order")
    list_editable = ("gift_stock", "is_active", "order")
    list_filter = ("is_active", "product__category")
    search_fields = ("product__name", "product__short_name")
    autocomplete_fields = ("product",)
    list_select_related = ("product",)

    @admin.display(description="موجودی انبار محصول", ordering="product__stock")
    def product_stock(self, obj):
        return fa_digits(obj.product.stock)
