"""Stock reservation used by checkout (later parts).

    reserve({product_id: qty, ...})   or   reserve([(product, qty), ...])
    release(...)                      same shapes; puts stock back

Rows are locked with select_for_update (PostgreSQL). On SQLite the project opens
transactions with BEGIN IMMEDIATE, which serialises writers the same way. The
decrement is also conditional (stock >= qty), so stock can never go negative.
"""

from collections import OrderedDict
from collections.abc import Mapping

from django.db import transaction
from django.db.models import F

from core.persian import fa_digits

from .models import Product


class InsufficientStock(Exception):
    """Raised when at least one product does not have enough stock. Nothing is reserved."""

    def __init__(self, shortages):
        self.shortages = shortages  # [(product, requested, available)]
        super().__init__(" ".join(self.messages))

    @property
    def messages(self):
        out = []
        for product, requested, available in self.shortages:
            if available <= 0:
                out.append(f"«{product.name}» ناموجود است.")
            else:
                out.append(
                    f"موجودی «{product.name}» کافی نیست (درخواست: {fa_digits(requested)}، موجود: {fa_digits(available)})."
                )
        return out


def _normalise(items):
    """-> OrderedDict {product_id: qty} sorted by id (a fixed lock order avoids deadlocks)."""
    pairs = items.items() if isinstance(items, Mapping) else items
    totals = {}
    for product, qty in pairs:
        pk = product.pk if isinstance(product, Product) else int(product)
        qty = int(qty)
        if qty <= 0:
            raise ValueError("تعداد باید بزرگ‌تر از صفر باشد.")
        totals[pk] = totals.get(pk, 0) + qty
    return OrderedDict(sorted(totals.items()))


def reserve(items):
    """Decrease stock for all items, or for none of them (raises InsufficientStock)."""
    wanted = _normalise(items)
    if not wanted:
        return
    with transaction.atomic():
        products = {p.pk: p for p in Product.objects.select_for_update().filter(pk__in=wanted).order_by("pk")}
        missing = [pk for pk in wanted if pk not in products]
        if missing:
            raise Product.DoesNotExist(f"محصول با شناسهٔ {missing} پیدا نشد.")
        shortages = [(products[pk], qty, products[pk].stock) for pk, qty in wanted.items() if products[pk].stock < qty]
        if shortages:
            raise InsufficientStock(shortages)
        for pk, qty in wanted.items():
            updated = Product.objects.filter(pk=pk, stock__gte=qty).update(stock=F("stock") - qty)
            if not updated:  # only possible if a writer slipped past the lock; roll everything back
                product = Product.objects.get(pk=pk)
                raise InsufficientStock([(product, qty, product.stock)])


def release(items):
    """Return stock for all items (e.g. a cancelled or expired order)."""
    wanted = _normalise(items)
    if not wanted:
        return
    with transaction.atomic():
        found = set(Product.objects.select_for_update().filter(pk__in=wanted).order_by("pk").values_list("pk", flat=True))
        missing = [pk for pk in wanted if pk not in found]
        if missing:
            raise Product.DoesNotExist(f"محصول با شناسهٔ {missing} پیدا نشد.")
        for pk, qty in wanted.items():
            Product.objects.filter(pk=pk).update(stock=F("stock") + qty)


def can_add_to_cart(product, quantity=1):
    """Out-of-stock or inactive products cannot be added to a cart."""
    return product.is_active and 0 < quantity <= product.stock
