from django.contrib import admin

from .models import META_DESCRIPTION_MAX, META_TITLE_MAX, Redirect

SEO_FIELDS = ("meta_title", "meta_description", "canonical_url", "noindex")


def seo_fieldset(title="سئو (اختیاری)"):
    """A collapsed fieldset for SEOFields models: fieldsets = (..., seo_fieldset())."""
    return (
        title,
        {
            "fields": SEO_FIELDS,
            "classes": ("collapse",),
            "description": "خالی بمانند، عنوان و توضیح از نام و متن خود صفحه ساخته می‌شوند.",
        },
    )


class SEOAdminMixin:
    """Live length counters under meta_title / meta_description (static/js/admin-seo.js)."""

    class Media:
        js = ("js/admin-seo.js",)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        limits = {"meta_title": META_TITLE_MAX, "meta_description": META_DESCRIPTION_MAX}
        if field is not None and db_field.name in limits:
            field.widget.attrs.update({"data-seo-counter": limits[db_field.name], "style": "width: 40em"})
        return field


@admin.register(Redirect)
class RedirectAdmin(admin.ModelAdmin):
    list_display = ("old_path", "new_path", "is_active", "is_automatic", "hits", "created_at")
    list_filter = ("is_active", "is_automatic")
    list_editable = ("is_active",)
    search_fields = ("old_path", "new_path")
    readonly_fields = ("is_automatic", "hits", "created_at")
