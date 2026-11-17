from django import forms
from django.contrib import admin
from django.db.models import Count, Q
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from jalali_date.admin import ModelAdminJalaliMixin

from . import services
from .defaults import TEMPLATES
from .models import SMSCampaign, SMSLog, SMSTemplate, sms_parts


@admin.register(SMSTemplate)
class SMSTemplateAdmin(ModelAdminJalaliMixin, admin.ModelAdmin):
    list_display = ("__str__", "is_active", "text", "updated_at")
    list_display_links = ("__str__",)
    list_editable = ("is_active",)
    fields = ("key", "is_active", "text", "variables")
    readonly_fields = ("key", "variables")

    @admin.display(description="متغیرهای مجاز")
    def variables(self, obj):
        return format_html_join("، ", "<code dir='ltr'>{{{}}}</code>", ((v,) for v in obj.allowed_vars))

    def has_add_permission(self, request):
        return SMSTemplate.objects.count() < len(TEMPLATES)

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ("variables",)
        if not obj.can_disable:
            return (*self.readonly_fields, "is_active")
        return self.readonly_fields

    def get_changelist_formset(self, request, **kwargs):
        formset = super().get_changelist_formset(request, **kwargs)

        class LockedFormSet(formset):
            def add_fields(self, form, index):
                super().add_fields(form, index)
                if form.instance.pk and not form.instance.can_disable:
                    form.fields["is_active"].disabled = True

        return LockedFormSet

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SMSLog)
class SMSLogAdmin(ModelAdminJalaliMixin, admin.ModelAdmin):
    list_display = ("created_at", "mobile", "template_key", "campaign", "status", "attempts", "parts", "provider", "sent_at")
    list_filter = ("status", "template_key", "provider", ("campaign", admin.EmptyFieldListFilter))
    search_fields = ("mobile", "text")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in SMSLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class SMSCampaignForm(forms.ModelForm):
    confirm = forms.BooleanField(label="تأیید ارسال", required=True)

    class Meta:
        model = SMSCampaign
        fields = ("text",)
        widgets = {"text": forms.Textarea(attrs={"rows": 5, "dir": "auto"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        count = services.campaign_recipients().count()
        self.fields["confirm"].help_text = (
            f"با ذخیره، این پیامک برای {count:,} کاربر فعال سایت فرستاده می‌شود و قابل برگشت نیست."
        )
        self.fields["confirm"].error_messages["required"] = "برای ارسال، این گزینه را تیک بزنید."


@admin.register(SMSCampaign)
class SMSCampaignAdmin(ModelAdminJalaliMixin, admin.ModelAdmin):
    form = SMSCampaignForm
    list_display = ("__str__", "created_at", "status", "recipients_count", "sent_count", "failed_count", "created_by")
    list_filter = ("status",)
    search_fields = ("text",)
    readonly_fields = (
        "text", "status", "recipients_count", "parts", "sent_count", "pending_count", "failed_count",
        "logs_link", "created_by", "created_at",
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("created_by")
            .annotate(
                _sent=Count("logs", filter=Q(logs__status=SMSLog.Status.SENT)),
                _failed=Count("logs", filter=Q(logs__status=SMSLog.Status.FAILED)),
                _pending=Count("logs", filter=Q(logs__status__in=services.PENDING)),
            )
        )

    def get_fields(self, request, obj=None):
        return ("text", "confirm") if obj is None else self.readonly_fields

    def get_readonly_fields(self, request, obj=None):
        return () if obj is None else self.readonly_fields

    @admin.display(description="ارسال‌شده", ordering="_sent")
    def sent_count(self, obj):
        return obj._sent

    @admin.display(description="ناموفق", ordering="_failed")
    def failed_count(self, obj):
        return obj._failed

    @admin.display(description="در صف یا در حال ارسال")
    def pending_count(self, obj):
        return obj._pending

    @admin.display(description="تعداد بخش هر پیامک")
    def parts(self, obj):
        return sms_parts(services.render_campaign(obj.text))

    @admin.display(description="پیامک‌ها")
    def logs_link(self, obj):
        url = reverse("admin:notifications_smslog_changelist") + f"?campaign__id__exact={obj.pk}"
        return format_html('<a href="{}">دیدن پیامک‌های این ارسال در گزارش پیامک‌ها</a>', url)

    def save_model(self, request, obj, form, change):
        if change:
            return
        obj.created_by = request.user
        obj.recipients_count = services.campaign_recipients().count()
        super().save_model(request, obj, form, change)
        services.start_campaign(obj)

    def has_change_permission(self, request, obj=None):
        return obj is None and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return False
