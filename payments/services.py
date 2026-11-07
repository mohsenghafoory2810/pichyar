"""Online payment and card-to-card flows.

Online callback (process_callback) is idempotent and safe against repeated or
parallel callbacks:
  1. claim   (short transaction, payment row locked): if it is already final, return
             it unchanged; otherwise reserve the order's stock and mark it VERIFYING.
  2. verify  with the gateway, outside any transaction (a network call must not hold
             the SQLite write lock).
  3. finish  (short transaction): SUCCEEDED -> order.confirm_payment(); otherwise the
             stock is released and the order becomes failed.
Stock is reserved *before* the gateway verify call, so money is never captured for
items that are no longer in stock (an unverified Zarinpal payment is refunded
automatically). A payment stuck in VERIFYING (e.g. a crash) is verified again by a
callback that arrives more than VERIFY_RETRY_SECONDS later; the gateway answers
"already verified" in that case.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from catalog import stock
from core.models import SiteSettings
from orders.models import Order, OrderStatus, PaymentMethod

from .gateways import GatewayError, get_gateway
from .models import Payment

logger = logging.getLogger("payments")

VERIFY_RETRY_SECONDS = 60
OUT_OF_STOCK_MESSAGE = (
    "متأسفانه پیش از تکمیل پرداخت، موجودی برخی کالاها تمام شد و سفارش ثبت نشد. "
    "اگر مبلغی از حساب شما کم شده باشد، حداکثر تا ۷۲ ساعت خودکار برمی‌گردد."
)


class PaymentError(Exception):
    def __init__(self, message, payment=None):
        self.message = message
        self.payment = payment
        super().__init__(message)


def start_online_payment(order, request):
    """Create a Payment and ask the gateway for a payment page. -> (redirect_url, payment)."""
    site_settings = SiteSettings.load()
    if not site_settings.online_payment_available:
        raise PaymentError("پرداخت اینترنتی فعلاً در دسترس نیست.")
    gateway = get_gateway(site_settings)
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if not order.can_pay_online:
            raise PaymentError("این سفارش قابل پرداخت نیست.")
        if order.payments.filter(status=Payment.Status.VERIFYING).exists():
            raise PaymentError("پرداخت قبلی این سفارش در حال بررسی است. چند لحظه بعد صفحه را تازه کنید.")
        if order.status == OrderStatus.FAILED:
            order._apply(OrderStatus.PENDING_PAYMENT, "تلاش دوباره برای پرداخت")
        payment = Payment.objects.create(
            order=order, method=PaymentMethod.ONLINE, gateway=gateway.key, amount=order.total
        )
    callback_url = request.build_absolute_uri(reverse("payments:callback", args=[payment.pk]))
    try:
        redirect = gateway.request(order, callback_url)
    except GatewayError as e:
        Payment.objects.filter(pk=payment.pk).update(status=Payment.Status.FAILED, message=str(e)[:255])
        raise PaymentError(str(e), payment=payment) from e
    payment.authority = redirect.authority
    payment.raw = {"request": redirect.raw}
    payment.save(update_fields=["authority", "raw", "updated_at"])
    return redirect.url, payment


def _fail(payment, order, status, message):
    """Inside a transaction with both rows locked."""
    payment.status = status
    payment.message = message[:255]
    payment.save(update_fields=["status", "message", "updated_at"])
    others_verifying = order.payments.filter(status=Payment.Status.VERIFYING).exclude(pk=payment.pk).exists()
    if order.status == OrderStatus.PENDING_PAYMENT and not others_verifying:
        order.mark_failed(message)


def process_callback(request, payment_id):
    """Handle the gateway's return to the site. Safe to call any number of times. -> Payment."""
    site_settings = SiteSettings.load()

    # 1. claim
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment_id, method=PaymentMethod.ONLINE)
        if payment.is_final:
            return payment
        if payment.status == Payment.Status.VERIFYING and timezone.now() - payment.updated_at < timedelta(
            seconds=VERIFY_RETRY_SECONDS
        ):
            return payment  # another request is verifying it right now
        gateway = get_gateway(site_settings, key=payment.gateway)
        if not payment.authority or gateway.callback_authority(request) != payment.authority:
            logger.warning("Payment %s: callback authority mismatch", payment.pk)
            return payment
        order = Order.objects.select_for_update().get(pk=payment.order_id)
        if not gateway.is_success_callback(request):
            _fail(payment, order, Payment.Status.CANCELED, "پرداخت انجام نشد یا از آن انصراف دادید.")
            return payment
        if order.status != OrderStatus.PENDING_PAYMENT:
            _fail(payment, order, Payment.Status.FAILED, "این سفارش دیگر قابل پرداخت نیست؛ اگر مبلغی کم شده باشد، خودکار برمی‌گردد.")
            return payment
        if order.payments.filter(status=Payment.Status.VERIFYING).exclude(pk=payment.pk).exists():
            _fail(payment, order, Payment.Status.FAILED, "پرداخت دیگری برای این سفارش در حال بررسی است.")
            return payment
        try:
            order._reserve_stock()
        except stock.InsufficientStock:
            _fail(payment, order, Payment.Status.FAILED, OUT_OF_STOCK_MESSAGE)
            return payment
        payment.status = Payment.Status.VERIFYING
        payment.save(update_fields=["status", "updated_at"])

    # 2. verify (no transaction open)
    try:
        result = gateway.verify(request, payment)
    except GatewayError as e:
        Payment.objects.filter(pk=payment.pk).update(message=str(e)[:255])
        payment.refresh_from_db()
        return payment

    # 3. finish
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        if payment.status != Payment.Status.VERIFYING:
            return payment
        order = Order.objects.select_for_update().get(pk=payment.order_id)
        payment.raw = {**payment.raw, "verify": result.raw}
        if not result.success:
            payment.save(update_fields=["raw"])
            status = Payment.Status.CANCELED if result.canceled else Payment.Status.FAILED
            _fail(payment, order, status, result.message or "پرداخت تأیید نشد.")
            return payment
        payment.status = Payment.Status.SUCCEEDED
        payment.ref_id = result.ref_id
        payment.card_pan = result.card_pan
        payment.verified_at = timezone.now()
        payment.save()
        if order.status == OrderStatus.PENDING_PAYMENT:
            order.confirm_payment(note=f"پرداخت اینترنتی موفق؛ کد پیگیری {result.ref_id}")
        else:  # e.g. canceled by an admin while the customer was paying
            logger.error("Payment %s succeeded but order %s is %s: refund needed", payment.pk, order.number, order.status)
            payment.message = "پرداخت انجام شد ولی سفارش در این فاصله لغو شده بود؛ مبلغ بازگردانده می‌شود."
            payment.save(update_fields=["message", "updated_at"])
    return payment


def submit_card_transfer(order, tracking_number, receipt=None):
    """The customer reports a card-to-card payment; the order waits for the admin (Order.approve/reject)."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if not order.can_submit_card_transfer:
            raise PaymentError("برای این سفارش امکان ثبت کارت به کارت وجود ندارد.")
        payment = Payment.objects.create(
            order=order,
            method=PaymentMethod.CARD,
            amount=order.total,
            tracking_number=tracking_number,
            receipt=receipt or "",
        )
        order._apply(OrderStatus.AWAITING_APPROVAL, f"کد پیگیری کارت به کارت: {tracking_number}")
    return payment
