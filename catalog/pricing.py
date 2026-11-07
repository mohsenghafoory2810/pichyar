"""Bulk price changes (admin action and 'whole category' page)."""

from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from .models import Product

PERCENT, FIXED = "percent", "fixed"
INCREASE, DECREASE = "increase", "decrease"
ROUNDING_CHOICES = [
    (0, "بدون گرد کردن"),
    (1000, "نزدیک‌ترین ۱٬۰۰۰ تومان"),
    (5000, "نزدیک‌ترین ۵٬۰۰۰ تومان"),
    (10000, "نزدیک‌ترین ۱۰٬۰۰۰ تومان"),
]


class PriceAdjustmentError(ValueError):
    pass


def round_to(value: Decimal, step: int) -> int:
    """Round half up to a multiple of `step` (or to a whole Toman when step is 0)."""
    step = Decimal(step or 1)
    return int((Decimal(value) / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step)


def new_price(old: int, mode: str, direction: str, amount, rounding: int = 0) -> int:
    amount = Decimal(str(amount))
    if amount < 0:
        raise PriceAdjustmentError("مقدار تغییر نمی‌تواند منفی باشد.")
    sign = 1 if direction == INCREASE else -1
    if mode == PERCENT:
        value = Decimal(old) * (1 + sign * amount / 100)
    elif mode == FIXED:
        value = Decimal(old) + sign * amount
    else:
        raise PriceAdjustmentError(f"نوع تغییر نامعتبر است: {mode}")
    return round_to(value, rounding)


def preview(products, mode, direction, amount, rounding=0):
    """[(product, old, new)]; raises PriceAdjustmentError if any price would drop to zero or below."""
    rows = [(p, p.price, new_price(p.price, mode, direction, amount, rounding)) for p in products]
    bad = [p.name for p, _, new in rows if new <= 0]
    if bad:
        raise PriceAdjustmentError("قیمت این محصولات صفر یا منفی می‌شود: " + "، ".join(bad))
    return rows


def apply(products, mode, direction, amount, rounding=0):
    """Apply the change; returns the number of products whose price changed. Logged via bulk_update."""
    with transaction.atomic():
        locked = list(Product.objects.select_for_update().filter(pk__in=[p.pk for p in products]).order_by("pk"))
        changed, now = [], timezone.now()
        for product, old, new in preview(locked, mode, direction, amount, rounding):
            if new != old:
                product.price, product.updated_at = new, now
                changed.append(product)
        Product.objects.bulk_update(changed, ["price", "updated_at"])
    return len(changed)
