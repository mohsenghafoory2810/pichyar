from django.db import transaction
from django.utils import timezone

from accounts.models import ADDRESS_FIELDS
from cart.cart import CartLine
from catalog.models import Product
from core.persian import fa_digits
from notifications.services import send_sms

from .gifts import GiftError, validate_selection
from .models import DiscountError, Order, OrderItem, OrderStatus, OrderStatusLog, find_usable_code
from .pricing import calculate

SESSION_ORDERS_KEY = "orders"  # order numbers this browser placed (guest access)
CHECKOUT_MOBILE_KEY = "checkout_mobile"  # the guest's verified mobile


def verified_mobile(request):
    if request.user.is_authenticated:
        return request.user.mobile
    return request.session.get(CHECKOUT_MOBILE_KEY)


class CheckoutError(Exception):
    def __init__(self, messages, price_changed=False):
        self.messages = messages
        self.price_changed = price_changed
        super().__init__(" ".join(messages))


def revalidate(cart_lines):
    """Fresh products for the cart lines, read inside the current transaction.
    -> (lines with current prices, problems)"""
    ids = [line.product.pk for line in cart_lines]
    products = {p.pk: p for p in Product.objects.active().filter(pk__in=ids)}
    lines, problems = [], []
    for line in cart_lines:
        product = products.get(line.product.pk)
        if product is None or product.stock <= 0:
            problems.append(f"«{line.product.name}» ناموجود است؛ آن را از سبد حذف کنید.")
        elif line.quantity > product.stock:
            problems.append(f"از «{product.name}» فقط {fa_digits(product.stock)} عدد موجود است.")
        else:
            lines.append(CartLine(product, line.quantity))
    return lines, problems


def create_order(
    cart,
    *,
    user,
    mobile,
    address,
    payment_method,
    note="",
    expected_total=None,
    site_settings=None,
    discount_code="",
    gifts=None,
):
    """Create an order from the cart with price snapshots. Stock is checked here but only
    reserved when the payment is confirmed. Raises CheckoutError.

    discount_code: the code text the customer applied ("" for none); checked again here.
    gifts: {product_id: quantity} chosen from the gift pool; at most breakdown.gifts_earned,
    each within its gift stock and product stock. They become OrderItems with price 0."""
    cart_lines = cart.lines()
    if not cart_lines:
        raise CheckoutError(["سبد خرید شما خالی است."])
    with transaction.atomic():
        lines, problems = revalidate(cart_lines)
        if problems:
            raise CheckoutError(problems)
        code = None
        if discount_code:
            subtotal = sum(line.line_total for line in lines)
            try:
                code = find_usable_code(discount_code, subtotal, user=user, mobile=mobile)
            except DiscountError as e:
                raise CheckoutError([e.message, "کد تخفیف را حذف کنید یا کد دیگری وارد کنید."]) from e
        breakdown = calculate(lines, discount=code, site_settings=site_settings)
        if expected_total is not None and breakdown.total != expected_total:
            raise CheckoutError(
                ["قیمت برخی کالاها یا هزینهٔ ارسال تغییر کرده است. مبلغ جدید را بررسی کنید و دوباره ثبت کنید."],
                price_changed=True,
            )
        try:
            gift_lines = validate_selection(gifts, breakdown.gifts_earned, lines)
        except GiftError as e:
            raise CheckoutError(e.messages) from e
        now = timezone.now()
        order = Order.objects.create(
            user=user if user is not None and user.is_authenticated else None,
            mobile=mobile,
            note=note,
            age_confirmed=True,
            age_confirmed_at=now,
            payment_method=payment_method,
            items_subtotal=breakdown.items_subtotal,
            discount_amount=breakdown.discount_amount,
            discount_code=code,
            discount_code_text=code.code if code else "",
            shipping_fee=breakdown.shipping_fee,
            total=breakdown.total,
            **{f: address[f] for f in ADDRESS_FIELDS},
        )
        items = [_item(order, line.product, line.quantity, line.product.price) for line in lines]
        items += [_item(order, product, qty, 0, is_gift=True) for product, qty in gift_lines]
        OrderItem.objects.bulk_create(items)
        OrderStatusLog.objects.create(order=order, to_status=OrderStatus.PENDING_PAYMENT, note="ثبت سفارش")
        context = order.sms_context()
        transaction.on_commit(lambda: send_sms(mobile, "order_registered", context))
    return order


def _item(order, product, quantity, unit_price, is_gift=False):
    return OrderItem(
        order=order,
        product=product,
        name=product.name,
        short_name=product.short_name or product.name[:40],
        unit=product.unit,
        unit_price=unit_price,
        quantity=quantity,
        is_gift=is_gift,
    )


def remember_order(request, order):
    numbers = [n for n in request.session.get(SESSION_ORDERS_KEY, []) if n != order.number]
    request.session[SESSION_ORDERS_KEY] = (numbers + [order.number])[-20:]


def can_view(request, order):
    user = request.user
    if user.is_authenticated and (order.user_id == user.pk or (order.user_id is None and order.mobile == user.mobile)):
        return True
    return order.number in request.session.get(SESSION_ORDERS_KEY, [])
