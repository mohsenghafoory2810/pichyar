from contextlib import ExitStack, contextmanager
from unittest import mock

from cart.cart import CartLine
from core.models import BankCard, SiteSettings
from orders.models import PaymentMethod
from orders.services import create_order

ADDRESS = {
    "recipient_name": "علی رضایی",
    "recipient_mobile": "09121111111",
    "province": "تهران",
    "city": "تهران",
    "address": "خیابان آزادی، پلاک ۱",
    "postal_code": "1234567890",
}

SMS_SENDERS = ("accounts.otp.send_sms", "orders.models.send_sms", "orders.services.send_sms")


@contextmanager
def capture_sms():
    """Collects (mobile, template_key, context) of every send_sms call."""
    sent = []

    def fake(mobile, key, context):
        sent.append((mobile, key, context))
        return True

    with ExitStack() as stack:
        for target in SMS_SENDERS:
            stack.enter_context(mock.patch(target, side_effect=fake))
        yield sent


class FakeCart:
    """Stands in for cart.Cart in service-level tests."""

    def __init__(self, *pairs):
        self._lines = [CartLine(product, qty) for product, qty in pairs]

    def lines(self):
        return self._lines

    def __iter__(self):
        return iter(self._lines)


def configure_payments(merchant_id="00000000-0000-0000-0000-000000000000", card=True):
    s = SiteSettings.load()
    s.gateway_merchant_id = merchant_id
    s.online_payment_enabled = True
    s.card_to_card_enabled = True
    s.save()
    if card and not s.cards.exists():
        BankCard.objects.create(settings=s, card_number="6037991234567890", holder_name="فروشگاه")
    return s


def make_order(*pairs, method=PaymentMethod.CARD, mobile="09121111111", user=None, **kwargs):
    return create_order(
        FakeCart(*pairs), user=user, mobile=mobile, address=ADDRESS, payment_method=method, **kwargs
    )
