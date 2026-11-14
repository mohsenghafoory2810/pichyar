"""Support conversations: read the whole thread, answer it and close it.

Conversations are started by customers in their account panel, so there is no «add» here.
A reply typed in «پاسخ پشتیبانی» becomes a message of the thread (support.services.add_staff_reply):
the conversation turns «پاسخ داده شد» (or stays «بسته‌شده» if that status was chosen) and the
customer gets an SMS. Conversations waiting for an answer come first in the list.
"""

from django import forms
from django.contrib import admin
from django.db.models import Case, IntegerField, Value, When
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join, linebreaks
from django.utils.safestring import mark_safe
from jalali_date.admin import ModelAdminJalaliMixin

from core.admin_mixins import PersianDigitsSearchMixin
from core.persian import fa_digits, fa_number, jalali_format

from . import services
from .models import TEXT_MAX_LENGTH, Ticket

S = Ticket.Status
DATE_FORMAT = "%Y/%m/%d - %H:%M"


class TicketAdminForm(forms.ModelForm):
    reply = forms.CharField(
        label="پاسخ پشتیبانی",
        required=False,
        max_length=TEXT_MAX_LENGTH,
        widget=forms.Textarea(attrs={"rows": 6, "cols": 80}),
        help_text="با ذخیره، پاسخ به گفتگو افزوده می‌شود، وضعیت «پاسخ داده شد» می‌شود و مشتری با پیامک خبردار می‌شود.",
        error_messages={"max_length": "پاسخ حداکثر ۳۰۰۰ نویسه باشد."},
    )

    class Meta:
        model = Ticket
        fields = ("status",)

    def clean_reply(self):
        return self.cleaned_data.get("reply", "").strip()


@admin.register(Ticket)
class TicketAdmin(PersianDigitsSearchMixin, ModelAdminJalaliMixin, admin.ModelAdmin):
    form = TicketAdminForm
    list_display = ("number", "subject", "customer", "status_badge", "order_number", "last_message")
    list_display_links = ("number", "subject")
    list_filter = ("status",)
    search_fields = ("subject", "messages__text", "user__mobile", "user__name")
    search_help_text = "موضوع یا متن پیام، موبایل یا نام مشتری"
    list_select_related = ("user", "order")
    list_per_page = 50
    actions = ["close_selected"]
    readonly_fields = ("number", "customer", "subject", "order_link", "created", "last_message", "conversation")
    fieldsets = (
        ("گفتگو", {"fields": ("number", "customer", "subject", "order_link", "created", "last_message", "conversation")}),
        ("پاسخ و وضعیت", {
            "fields": ("reply", "status"),
            "description": "برای بستن گفتگو وضعیت را «بسته‌شده» کنید؛ مشتری در گفتگوی بسته نمی‌تواند پیام بفرستد.",
        }),
    )

    def has_add_permission(self, request):
        return False  # conversations are started by customers in their account panel

    def get_ordering(self, request):
        waiting_first = Case(When(status=S.WAITING, then=Value(0)), default=Value(1), output_field=IntegerField())
        return [waiting_first.asc(), "-last_message_at", "-id"]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        reply = form.cleaned_data.get("reply")
        if reply:
            services.add_staff_reply(obj, request.user, reply, close=obj.status == S.CLOSED)

    # --- columns and read-only fields ------------------------------------------------

    @admin.display(description="شماره", ordering="pk")
    def number(self, obj):
        return fa_digits(obj.pk)

    @admin.display(description="مشتری", ordering="user__name")
    def customer(self, obj):
        user = obj.user
        label = fa_digits(services.customer_label(user))
        if user.is_staff:  # not in «مشتریان»
            return label
        return format_html('<a href="{}">{}</a>', reverse("admin:accounts_customer_change", args=[user.pk]), label)

    @admin.display(description="وضعیت", ordering="status")
    def status_badge(self, obj):
        if obj.status == S.WAITING:
            return format_html('<strong style="color:#b45309">● {}</strong>', obj.get_status_display())
        return obj.get_status_display()

    @admin.display(description="سفارش مرتبط", ordering="order__number")
    def order_number(self, obj):
        return fa_digits(obj.order.number) if obj.order_id else "-"

    @admin.display(description="سفارش مرتبط")
    def order_link(self, obj):
        if not obj.order_id:
            return "-"
        url = reverse("admin:orders_order_change", args=[obj.order_id])
        return format_html('<a href="{}">{}</a>', url, fa_digits(obj.order.number))

    @admin.display(description="تاریخ ثبت", ordering="created_at")
    def created(self, obj):
        return jalali_format(obj.created_at, DATE_FORMAT)

    @admin.display(description="آخرین پیام", ordering="last_message_at")
    def last_message(self, obj):
        return jalali_format(obj.last_message_at, DATE_FORMAT)

    @admin.display(description="گفتگو")
    def conversation(self, obj):
        if not obj.pk:
            return "-"
        rows = []
        for message in obj.messages.select_related("author"):
            if message.is_staff_reply:
                who = "پشتیبانی"
                if message.author:
                    who += f" ({message.author.name or fa_digits(message.author.mobile)})"
                style = "background:var(--selected-bg,#fef3c7);margin-inline-start:15%"
            else:
                who = "مشتری"
                style = "background:var(--darkened-bg,#f5f5f5);margin-inline-end:15%"
            text = mark_safe(linebreaks(message.text, autoescape=True))  # the customer's text is escaped here
            rows.append((style, who, jalali_format(message.created_at, DATE_FORMAT), text))
        if not rows:
            return "-"
        return format_html(
            '<div style="max-width:48rem">{}</div>',
            format_html_join(
                "",
                '<div style="{};border:1px solid var(--hairline-color,#ddd);border-radius:8px;padding:8px 12px;margin-bottom:8px">'
                '<div style="font-weight:bold;margin-bottom:4px">{} <span style="font-weight:normal;color:var(--body-quiet-color,#666)">· {}</span></div>'
                '<div style="overflow-wrap:anywhere">{}</div></div>',
                rows,
            ),
        )

    # --- actions -----------------------------------------------------------------------

    @admin.action(description="بستن گفتگوهای انتخاب‌شده", permissions=["change"])
    def close_selected(self, request, queryset):
        count = queryset.exclude(status=S.CLOSED).update(status=S.CLOSED, updated_at=timezone.now())
        self.message_user(request, f"{fa_number(count) or '۰'} گفتگو بسته شد.")
