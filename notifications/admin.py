from django.contrib import admin
from django.utils.html import format_html_join
from jalali_date.admin import ModelAdminJalaliMixin

from .defaults import TEMPLATES
from .models import SMSLog, SMSTemplate


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
    list_display = ("created_at", "mobile", "template_key", "status", "attempts", "parts", "provider", "sent_at")
    list_filter = ("status", "template_key", "provider")
    search_fields = ("mobile", "text")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in SMSLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
