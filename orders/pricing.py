"""Order totals.

    calculate(cart, discount=None)
        -> PriceBreakdown(items_subtotal, discount_amount, shipping_fee, total, gifts_earned)

`cart` is anything iterable whose items have `.line_total` (a cart.Cart, a list of
CartLine or OrderItem; gifts are 0). `discount` is None or an object with
`amount(items_subtotal, lines) -> int` (an orders.models.DiscountCode), clamped to
0..items_subtotal here.

Order of calculation: items subtotal -> discount -> shipping and gifts, both from the
subtotal after discount (settings in SiteSettings):
    steps        = ceil|floor(subtotal_after_discount / shipping_step_amount)
    fee          = steps * shipping_step_fee            (0 when the subtotal is 0)
    gifts_earned = floor(subtotal_after_discount / gift_threshold)   (0 if gifts are off)
"""

from dataclasses import dataclass

CEIL = "ceil"  # values of SiteSettings.shipping_rounding
FLOOR = "floor"


@dataclass(frozen=True)
class PriceBreakdown:
    items_subtotal: int
    discount_amount: int
    shipping_fee: int
    total: int
    gifts_earned: int = 0

    @property
    def subtotal_after_discount(self):
        return self.items_subtotal - self.discount_amount


def shipping_fee(amount, step_amount, step_fee, rounding=CEIL):
    amount, step_amount, step_fee = int(amount), int(step_amount), int(step_fee)
    if amount <= 0 or step_amount <= 0:
        return 0
    steps = -(-amount // step_amount) if rounding == CEIL else amount // step_amount
    return steps * step_fee


def gifts_earned(amount, threshold, enabled=True):
    amount, threshold = int(amount), int(threshold)
    if not enabled or amount <= 0 or threshold <= 0:
        return 0
    return amount // threshold


def calculate(cart, discount=None, site_settings=None):
    from core.models import SiteSettings

    s = site_settings or SiteSettings.load()
    lines = list(cart)
    items_subtotal = sum(int(line.line_total) for line in lines)
    discount_amount = 0
    if discount is not None:
        discount_amount = max(0, min(int(discount.amount(items_subtotal, lines)), items_subtotal))
    after_discount = items_subtotal - discount_amount
    fee = shipping_fee(after_discount, s.shipping_step_amount, s.shipping_step_fee, s.shipping_rounding)
    gifts = gifts_earned(after_discount, s.gift_threshold, s.gift_enabled)
    return PriceBreakdown(items_subtotal, discount_amount, fee, after_discount + fee, gifts)
