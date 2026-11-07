"""Gifts: one per full SiteSettings.gift_threshold of the items subtotal after discount
(orders.pricing.calculate -> gifts_earned). At checkout the customer picks each gift from
the pool; the same item may be picked several times while its gift stock and product stock
(minus the paid quantity of that product in the cart) allow it.
"""

from dataclasses import dataclass

from core.persian import fa_digits, toman

from .models import GiftPoolItem


class GiftError(Exception):
    def __init__(self, messages):
        self.messages = messages
        super().__init__(" ".join(messages))


@dataclass
class GiftOption:
    product: object
    max_quantity: int  # how many of this gift one order can take

    @property
    def pk(self):
        return self.product.pk


def _paid_quantities(paid_lines):
    paid = {}
    for line in paid_lines:
        paid[line.product.pk] = paid.get(line.product.pk, 0) + line.quantity
    return paid


def gift_options(paid_lines):
    """The gifts this cart can choose from, with the most of each it can take."""
    paid = _paid_quantities(paid_lines)
    options = []
    for item in GiftPoolItem.objects.available():
        cap = min(item.gift_stock, item.product.stock - paid.get(item.product_id, 0))
        if cap > 0:
            options.append(GiftOption(item.product, cap))
    return options


def slot_count(earned, options):
    """How many gifts the customer picks: what they earned, unless the pool has fewer left."""
    return min(earned, sum(o.max_quantity for o in options))


def validate_selection(selection, earned, paid_lines):
    """selection {product_id: quantity} -> [(product, quantity)], read fresh from the database.
    Raises GiftError (Persian messages)."""
    selection = {int(pk): int(qty) for pk, qty in (selection or {}).items() if int(qty) > 0}
    total = sum(selection.values())
    if not total:
        return []
    if total > earned:
        if earned == 0:
            raise GiftError(["این سفارش هدیه‌ای ندارد."])
        raise GiftError([f"این سفارش فقط {fa_digits(earned)} هدیه دارد؛ تعداد هدیه‌های انتخاب‌شده بیشتر است."])
    options = {o.pk: o for o in gift_options(paid_lines)}
    problems = []
    for pk, qty in selection.items():
        option = options.get(pk)
        if option is None:
            item = GiftPoolItem.objects.filter(product_id=pk).select_related("product").first()
            name = f"«{item.product.name}» " if item else ""
            problems.append(f"هدیهٔ {name}دیگر موجود نیست؛ هدیهٔ دیگری انتخاب کنید.")
        elif qty > option.max_quantity:
            problems.append(
                f"از هدیهٔ «{option.product.name}» فقط {fa_digits(option.max_quantity)} عدد قابل انتخاب است."
            )
    if problems:
        raise GiftError(problems)
    return [(options[pk].product, qty) for pk, qty in selection.items()]


def gift_hint(breakdown, site_settings):
    """The cart message about gifts, or None (gifts off, or nothing left in the pool)."""
    threshold = site_settings.gift_threshold
    if not site_settings.gift_enabled or threshold <= 0 or breakdown.items_subtotal <= 0:
        return None
    if not GiftPoolItem.objects.available().exists():
        return None
    earned = breakdown.gifts_earned
    remaining = threshold - breakdown.subtotal_after_discount % threshold
    if earned:
        text = (
            f"این خرید {fa_digits(earned)} هدیه دارد که در تسویه حساب انتخاب می‌کنید. "
            f"با {toman(remaining)} خرید بیشتر یک هدیهٔ دیگر می‌گیرید."
        )
    else:
        text = f"با {toman(remaining)} خرید بیشتر یک هدیه می‌گیرید."
    return {"earned": earned, "remaining": remaining, "text": text}
