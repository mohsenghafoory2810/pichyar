from axes.models import AccessAttempt
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.db.models import Count, IntegerField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.template.loader import render_to_string
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice
from jalali_date.admin import ModelAdminJalaliMixin, TabularInlineJalaliMixin

from core.admin_mixins import PersianDigitsSearchMixin
from core.persian import fa_number, jalali_format, toman
from orders.models import CONFIRMED_STATUSES, Order

from .forms import UserAdminChangeForm, UserAdminCreationForm
from .models import Address, Customer, User


class AddressInline(TabularInlineJalaliMixin, admin.TabularInline):
    model = Address
    extra = 0
    fields = ("recipient_name", "recipient_mobile", "province", "city", "address", "postal_code")


@admin.register(User)
class UserAdmin(PersianDigitsSearchMixin, ModelAdminJalaliMixin, BaseUserAdmin):
    form = UserAdminChangeForm
    add_form = UserAdminCreationForm
    list_display = ("mobile", "name", "is_staff", "is_active", "two_factor", "date_joined")
    list_filter = ("is_staff", "is_superuser", "is_active", "groups")
    search_fields = ("mobile", "name", "email")
    ordering = ("-date_joined",)
    inlines = [AddressInline]
    fieldsets = (
        (None, {"fields": ("mobile", "password")}),
        ("مشخصات", {"fields": ("name", "email")}),
        ("دسترسی‌ها", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("تاریخ‌ها", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("mobile", "name", "usable_password", "password1", "password2")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _totp=Count("totpdevice", filter=Q(totpdevice__confirmed=True))
        )

    @admin.display(description="ورود دومرحله‌ای", boolean=True, ordering="_totp")
    def two_factor(self, obj):
        return bool(obj._totp) if obj.is_staff else None


# --- customers ---------------------------------------------------------------------


def _orders_of_customer():
    """The customer's orders: their account's plus earlier guest orders with the same mobile
    (same rule as Order.objects.for_user)."""
    return Order.objects.filter(Q(user=OuterRef("pk")) | Q(user__isnull=True, mobile=OuterRef("mobile")))


def _aggregate(queryset, expression):
    value = queryset.order_by().annotate(_g=Value(1)).values("_g").annotate(v=expression).values("v")
    return Coalesce(Subquery(value, output_field=IntegerField()), 0)


@admin.register(Customer)
class CustomerAdmin(PersianDigitsSearchMixin, ModelAdminJalaliMixin, admin.ModelAdmin):
    list_display = ("mobile", "name", "orders_count", "total_spent", "last_order", "date_joined", "is_active")
    list_filter = ("is_active",)
    search_fields = ("mobile", "name", "email")
    ordering = ("-date_joined",)
    list_per_page = 50
    fields = ("mobile", "name", "email", "is_active", "date_joined", "last_login", "order_history")
    readonly_fields = ("mobile", "date_joined", "last_login", "order_history")
    inlines = [AddressInline]

    def get_queryset(self, request):
        confirmed = _orders_of_customer().filter(status__in=CONFIRMED_STATUSES)
        return (
            super()
            .get_queryset(request)
            .annotate(
                _orders=_aggregate(confirmed, Count("id")),
                _spent=_aggregate(confirmed, Sum("total")),
                _last_order=Subquery(_orders_of_customer().order_by("-created_at").values("created_at")[:1]),
            )
        )

    def has_add_permission(self, request):
        return False  # customers sign up themselves with their mobile

    @admin.display(description="سفارش‌های پرداخت‌شده", ordering="_orders")
    def orders_count(self, obj):
        return fa_number(obj._orders)

    @admin.display(description="جمع خرید", ordering="_spent")
    def total_spent(self, obj):
        return toman(obj._spent)

    @admin.display(description="آخرین سفارش", ordering="_last_order")
    def last_order(self, obj):
        return jalali_format(obj._last_order, "%Y/%m/%d") if obj._last_order else "-"

    @admin.display(description="تاریخچهٔ سفارش‌ها")
    def order_history(self, obj):
        orders = Order.objects.for_user(obj).prefetch_related("items")
        all_url = reverse("admin:orders_order_changelist") + f"?q={obj.mobile}"
        return render_to_string("admin/accounts/customer/order_history.html", {"orders": orders, "all_url": all_url})


# --- security: two-step login devices and login lockouts ------------------------------

admin.site.unregister(TOTPDevice)


@admin.register(TOTPDevice)
class TOTPDeviceAdmin(admin.ModelAdmin):
    """Read-only list; deleting a row turns two-step login off for that user (e.g. lost phone)."""

    list_display = ("owner", "confirmed_display", "created", "last_used")
    list_display_links = None
    list_select_related = ("user",)
    search_fields = ("user__mobile", "user__name")

    def has_add_permission(self, request):
        return False  # each admin turns it on for themselves («ورود دومرحله‌ای» in the top bar)

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(request, {"title": "ورود دومرحله‌ای مدیران", **(extra_context or {})})

    @admin.display(description="مدیر", ordering="user__mobile")
    def owner(self, obj):
        return str(obj.user)

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="فعال", boolean=True, ordering="confirmed")
    def confirmed_display(self, obj):
        return obj.confirmed

    @admin.display(description="زمان فعال‌سازی", ordering="created_at")
    def created(self, obj):
        return jalali_format(obj.created_at, "%Y/%m/%d - %H:%M") if obj.created_at else "-"

    @admin.display(description="آخرین استفاده", ordering="last_used_at")
    def last_used(self, obj):
        return jalali_format(obj.last_used_at, "%Y/%m/%d - %H:%M") if obj.last_used_at else "-"


@admin.register(AccessAttempt)
class AccessAttemptAdmin(admin.ModelAdmin):
    """Failed admin logins counted by django-axes. Deleting a row unlocks that IP at once."""

    list_display = ("ip", "login_name", "failures", "last_attempt", "locked")
    list_display_links = None
    search_fields = ("ip_address", "username")
    actions = ["unlock"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(request, {"title": "قفل‌های ورود به پنل", **(extra_context or {})})

    @admin.display(description="آی‌پی", ordering="ip_address")
    def ip(self, obj):
        return obj.ip_address

    @admin.display(description="نام کاربری واردشده", ordering="username")
    def login_name(self, obj):
        return obj.username

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    @admin.display(description="تعداد تلاش ناموفق", ordering="failures_since_start")
    def failures(self, obj):
        return fa_number(obj.failures_since_start)

    @admin.display(description="آخرین تلاش", ordering="attempt_time")
    def last_attempt(self, obj):
        return jalali_format(obj.attempt_time, "%Y/%m/%d - %H:%M")

    @admin.display(description="قفل شده", boolean=True)
    def locked(self, obj):
        from django.conf import settings

        return obj.failures_since_start >= settings.AXES_FAILURE_LIMIT

    @admin.action(description="باز کردن قفل ردیف‌های انتخاب‌شده", permissions=["delete"])
    def unlock(self, request, queryset):
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f"قفل {fa_number(count)} ردیف باز شد.", messages.SUCCESS)

