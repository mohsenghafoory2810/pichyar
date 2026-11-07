from django.contrib import admin
from django.utils.html import format_html_join
from jalali_date.admin import ModelAdminJalaliMixin

from .defaults import TEMPLATES
from .models import SMSLog, SMSTemplate


@admin.register(SMSTemplate)
class SMSTemplateAdmin(ModelAdminJalaliMixin, admin.ModelAdmin):
    list_display = ("__str__", "text", "updated_at")
    fields = ("key", "text", "variables")
    readonly_fields = ("key", "variables")

    @admin.display(description="متغیرهای مجاز")
    def variables(self, obj):
        return format_html_join("، ", "<code dir='ltr'>{{{}}}</code>", ((v,) for v in obj.allowed_vars))

    def has_add_permission(self, request):
        return SMSTemplate.objects.count() < len(TEMPLATES)

    def get_readonly_fields(self, request, obj=None):
        return ("variables",) if obj is None else self.readonly_fields

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SMSLog)
class SMSLogAdmin(ModelAdminJalaliMixin, admin.ModelAdmin):
    list_display = ("created_at", "mobile", "template_key", "status", "attempts", "parts", "provider", "sent_at")
    list_filter = ("status", "template_key", "provider")
    search_fields = ("mobile", "text")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in SMSLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
