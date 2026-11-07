"""Excel export/import of products for bulk price and stock edits.

Only «قیمت (تومان)» and «موجودی» are imported; the other columns are there so the
sheet is readable and are ignored on import. Rows are matched by «شناسه»; the import
never creates or deletes products.
"""

import re

from django.core.exceptions import ValidationError
from import_export import fields, resources, widgets

from core.persian import THOUSANDS_SEPARATOR, latin_digits

from .models import Product


class WholeNumberWidget(widgets.Widget):
    """Accepts 750000, 750000.0, '750,000' and '۷۵۰٬۰۰۰'; rejects blanks, fractions and text."""

    def __init__(self, allow_blank=False, **kwargs):
        self.allow_blank = allow_blank
        super().__init__(**kwargs)

    def clean(self, value, row=None, **kwargs):
        if value is None or str(value).strip() == "":
            if self.allow_blank:
                return None
            raise ValueError("این خانه خالی است.")
        if isinstance(value, float):
            if not value.is_integer():
                raise ValueError(f"«{value}» عدد صحیح نیست.")
            value = int(value)
        if isinstance(value, int):
            number = value
        else:
            text = re.sub(r"[\s,٬" + THOUSANDS_SEPARATOR + "]", "", latin_digits(str(value)))
            if not re.fullmatch(r"-?\d+", text):
                raise ValueError(f"«{value}» عدد صحیح نیست.")
            number = int(text)
        if number < 0:
            raise ValueError("عدد منفی پذیرفته نیست.")
        return number

    def render(self, value, obj=None, **kwargs):
        return value


class ProductResource(resources.ModelResource):
    id = fields.Field(attribute="id", column_name="شناسه", widget=WholeNumberWidget(allow_blank=True))
    name = fields.Field(attribute="name", column_name="نام", readonly=True)
    category = fields.Field(attribute="category__name", column_name="دسته", readonly=True)
    unit = fields.Field(attribute="unit", column_name="واحد", readonly=True)
    price = fields.Field(attribute="price", column_name="قیمت (تومان)", widget=WholeNumberWidget())
    stock = fields.Field(attribute="stock", column_name="موجودی", widget=WholeNumberWidget())

    class Meta:
        model = Product
        fields = ("id", "name", "category", "unit", "price", "stock")
        import_id_fields = ("id",)
        skip_unchanged = True
        report_skipped = True
        clean_model_instances = True
        use_bulk = False  # every row goes through Product.save(), which writes the price log

    def get_queryset(self):
        return Product.objects.select_related("category").order_by("category__order", "sort_order", "id")

    def get_instance(self, instance_loader, row):
        try:
            return super().get_instance(instance_loader, row)
        except ValueError:
            raise ValidationError(f"شناسهٔ «{row.get('شناسه')}» عدد نیست.")

    def init_instance(self, row=None):
        raise ValidationError(f"محصولی با شناسهٔ «{row.get('شناسه') or '—'}» پیدا نشد. ردیف جدید از اکسل ساخته نمی‌شود.")

    def before_save_instance(self, instance, row, **kwargs):
        instance._changed_by = kwargs.get("user")
