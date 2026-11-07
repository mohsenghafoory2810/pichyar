"""The discount code applied to the session's cart, and the cart's prices with it.

The code is kept in the session (request.session["discount_code"]) and checked again
on every page and at checkout, so a code that stops being valid (expired, cart below the
minimum, ...) shows its reason and gives no discount instead of silently disappearing.
"""

from dataclasses import dataclass
from functools import cached_property

from core.utils import get_site_settings

from .gifts import gift_hint
from .models import DiscountError, find_usable_code
from .pricing import calculate
from .services import verified_mobile

SESSION_KEY = "discount_code"


def session_code(request):
    return request.session.get(SESSION_KEY, "")


def remember_code(request, code):
    request.session[SESSION_KEY] = code.code


def forget_code(request):
    request.session.pop(SESSION_KEY, None)


@dataclass
class CartPricing:
    breakdown: object
    site_settings: object
    code_text: str = ""
    discount_code: object = None
    discount_error: str = ""

    @cached_property
    def gift_hint(self):
        return gift_hint(self.breakdown, self.site_settings)


def price_cart(request, cart, site_settings=None, lines=None):
    """Prices of `cart` (or of `lines`) with the session's discount code -> CartPricing."""
    site_settings = site_settings or get_site_settings(request)
    lines = list(cart if lines is None else lines)
    text = session_code(request)
    code, error = None, ""
    if text:
        subtotal = sum(int(line.line_total) for line in lines)
        try:
            code = find_usable_code(text, subtotal, user=request.user, mobile=verified_mobile(request))
        except DiscountError as e:
            error = e.message
    breakdown = calculate(lines, discount=code, site_settings=site_settings)
    return CartPricing(breakdown, site_settings, text, code, error)
