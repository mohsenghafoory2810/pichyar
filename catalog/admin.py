from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import F
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from import_export.admin import ImportExportModelAdmin
from import_export.formats.base_formats import XLSX
from import_export.forms import SelectableFieldsExportForm
from jalali_date.admin import ModelAdminJalaliMixin

from core.persian import fa_number, jalali_format, toman
from core.utils import get_site_settings
from seo.admin import SEOAdminMixin, seo_fieldset
from seo.meta import auto_title

from . import pricing
from .forms import BulkPriceForm
from .models import Category, CategoryFAQ, PriceChangeLog, Product, ProductImage, ProductSpec
from .resources import ProductResource


def thumbnail_html(image, height=48):
    if not image:
        return "-"
    return format_html('<img src="{}" alt="" class="catalog-thumb" style="height:{}px">', image.url, height)


def seo_placeholders(form_class, title, description):
    """Show the automatic title/description as the placeholder of the empty SEO fields."""
    for name, value in (("meta_title", title), ("meta_description", description)):
        field = form_class.base_fields.get(name)
        if field is not None and value:
            field.widget.attrs["placeholder"] = f"خودکار: {value}"
    return form_class


class CategoryFAQInline(admin.StackedInline):
    model = CategoryFAQ
    extra = 0
    fields = ("question", "answer", "order")


@admin.register(Category)
class CategoryAdmin(SEOAdminMixin, admin.ModelAdmin):
    list_display = ("__str__", "slug", "order", "is_active")
    list_editable = ("order", "is_active")
    list_filter = ("is_active", ("parent", admin.EmptyFieldListFilter))
    search_fields = ("name", "slug")
    inlines = [CategoryFAQInline]
    fieldsets = (
        (None, {"fields": ("name", "slug", "parent", "image", "image_alt", "order", "is_active")}),
        ("متن معرفی", {"fields": ("intro",)}),
        seo_fieldset(),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("parent")

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if obj is not None:
            from .views import category_meta_description

            site_name = get_site_settings(request).site_name
            seo_placeholders(form, auto_title(obj.name, site_name), category_meta_description(obj))
        return form


class ProductSpecInline(admin.TabularInline):
    model = ProductSpec
    extra = 0
    fields = ("name", "value", "order")


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0
    fields = ("preview", "image", "alt_text", "order")
    readonly_fields = ("preview",)
    classes = ("sortable-images",)

    class Media:
        js = ("js/admin-image-sort.js",)

    @admin.display(description="پیش‌نمایش")
    def preview(self, obj):
        return thumbnail_html(obj.image if obj.pk else None, 72)


class PriceChangeLogInline(admin.TabularInline):
    model = PriceChangeLog
    verbose_name_plural = "تاریخچهٔ تغییر قیمت"
    fields = ("changed_at", "old_price_display", "new_price_display", "changed_by")
    readonly_fields = fields
    extra = 0
    max_num = 0
    can_delete = False
    classes = ("collapse",)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("changed_by")

    @admin.display(description="زمان")
    def changed_at(self, obj):
        return jalali_format(obj.created_at, "%Y/%m/%d - %H:%M")

    @admin.display(description="قیمت قبلی")
    def old_price_display(self, obj):
        return toman(obj.old_price)

    @admin.display(description="قیمت جدید")
    def new_price_display(self, obj):
        return toman(obj.new_price)


class CategoryTreeFilter(admin.SimpleListFilter):
    """Picking a top-level category also shows products of its sub-categories."""

    title = "دسته‌بندی"
    parameter_name = "cat"

    def lookups(self, request, model_admin):
        out = []
        for top in Category.objects.filter(parent__isnull=True).prefetch_related("children"):
            out.append((str(top.pk), top.name))
            out.extend((str(c.pk), f"— {c.name}") for c in top.children.all())
        return out

    def queryset(self, request, queryset):
        if not self.value():
            return queryset
        category = Category.objects.filter(pk=self.value()).first()
        return queryset.in_category(category) if category else queryset.none()


class StockFilter(admin.SimpleListFilter):
    title = "وضعیت موجودی"
    parameter_name = "stock_state"

    def lookups(self, request, model_admin):
        return [("low", "کم (به آستانه رسیده)"), ("out", "ناموجود"), ("ok", "کافی")]

    def queryset(self, request, queryset):
        if self.value() == "low":
            return queryset.filter(stock__lte=F("low_stock_threshold"))
        if self.value() == "out":
            return queryset.filter(stock=0)
        if self.value() == "ok":
            return queryset.filter(stock__gt=F("low_stock_threshold"))
        return queryset


class PersianExportForm(SelectableFieldsExportForm):
    """Export page checkboxes labelled with the Persian column name only (not «Name (نام)»)."""

    def _get_field_label(self, resource, field_name):
        field = resource.fields.get(field_name)
        return field.column_name if field and field.column_name else super()._get_field_label(resource, field_name)


@admin.register(Product)
class ProductAdmin(SEOAdminMixin, ModelAdminJalaliMixin, ImportExportModelAdmin):
    resource_classes = [ProductResource]
    formats = [XLSX]
    export_form_class = PersianExportForm
    change_list_template = "admin/catalog/product/change_list_tools.html"

    list_display = ("thumbnail", "name", "category", "price", "unit", "stock", "stock_state", "is_active")
    list_display_links = ("thumbnail", "name")
    list_editable = ("price", "stock")
    list_filter = (CategoryTreeFilter, "is_active", StockFilter)
    search_fields = ("name", "short_name", "slug", "sku")
    list_select_related = ("category", "category__parent")
    list_per_page = 50
    actions = ["bulk_change_price", "make_active", "make_inactive"]
    inlines = [ProductImageInline, ProductSpecInline, PriceChangeLogInline]
    fieldsets = (
        (None, {"fields": ("name", "short_name", "slug", "category", "description")}),
        ("شناسه و برند", {"fields": ("sku", "brand")}),
        ("قیمت و موجودی", {"fields": ("price", "unit", "stock", "low_stock_threshold")}),
        ("نمایش", {"fields": ("is_active", "sort_order")}),
        seo_fieldset(),
    )

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if obj is not None:
            from .views import product_meta_description

            site_name = get_site_settings(request).site_name
            seo_placeholders(form, auto_title(obj.name, site_name), product_meta_description(obj, site_name))
        return form

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("images")

    def save_model(self, request, obj, form, change):
        obj._changed_by = request.user
        super().save_model(request, obj, form, change)

    @admin.display(description="تصویر")
    def thumbnail(self, obj):
        image = obj.main_image
        return thumbnail_html(image.image if image else None)

    @admin.display(description="وضعیت موجودی", ordering="stock")
    def stock_state(self, obj):
        # The stock-flag class also highlights the whole row (see static/css/admin.css).
        if obj.stock == 0:
            return format_html('<span class="stock-flag stock-out">ناموجود</span>')
        if obj.is_low_stock:
            return format_html('<span class="stock-flag stock-low">کم ({})</span>', fa_number(obj.stock))
        return "کافی"

    # --- actions ----------------------------------------------------------
    @admin.action(description="تغییر گروهی قیمت محصولات انتخاب‌شده", permissions=["change"])
    def bulk_change_price(self, request, queryset):
        ids = ",".join(str(pk) for pk in queryset.values_list("pk", flat=True))
        return redirect(f"{reverse('admin:catalog_product_bulk_price')}?ids={ids}")

    @admin.action(description="فعال کردن محصولات انتخاب‌شده", permissions=["change"])
    def make_active(self, request, queryset):
        self.message_user(request, f"{fa_number(queryset.update(is_active=True))} محصول فعال شد.")

    @admin.action(description="غیرفعال کردن محصولات انتخاب‌شده", permissions=["change"])
    def make_inactive(self, request, queryset):
        self.message_user(request, f"{fa_number(queryset.update(is_active=False))} محصول غیرفعال شد.")

    # --- bulk price page --------------------------------------------------
    def get_urls(self):
        custom = [
            path("bulk-price/", self.admin_site.admin_view(self.bulk_price_view), name="catalog_product_bulk_price"),
        ]
        return custom + super().get_urls()

    def bulk_price_view(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied
        changelist_url = reverse("admin:catalog_product_changelist")
        ids_param = request.GET.get("ids", "")
        data = request.POST if request.method == "POST" else None
        form = BulkPriceForm(data, initial={"ids": ids_param})
        rows, products, error = None, None, None
        if form.is_valid():
            d = form.cleaned_data
            if d["ids"]:
                products = Product.objects.filter(pk__in=d["ids"])
            else:
                products = Product.objects.in_category(d["category"])
            products = list(products.select_related("category").order_by("category__order", "sort_order", "id"))
            args = (d["mode"], d["direction"], d["amount"], d["rounding"])
            try:
                if "apply" in request.POST:
                    changed = pricing.apply(products, *args)
                    self.message_user(request, f"قیمت {fa_number(changed)} محصول تغییر کرد.", messages.SUCCESS)
                    return redirect(changelist_url)
                rows = pricing.preview(products, *args)
            except pricing.PriceAdjustmentError as e:
                error = str(e)
        elif not form.is_bound and ids_param:
            products = Product.objects.filter(pk__in=[x for x in ids_param.split(",") if x.isdigit()])
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "تغییر گروهی قیمت",
            "form": form,
            "rows": rows,
            "error": error,
            "selected_count": len(products) if products is not None else None,
            "has_ids": bool(ids_param or request.POST.get("ids")),
            "changelist_url": changelist_url,
        }
        return TemplateResponse(request, "admin/catalog/product/bulk_price.html", context)
