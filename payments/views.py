from django.contrib import admin, messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from PIL import Image, UnidentifiedImageError

from orders.models import Order
from orders.services import can_view

from . import services
from .forms import CardTransferForm
from .models import Payment


def _order_for(request, number):
    order = get_object_or_404(Order, number=number)
    if not can_view(request, order):
        raise Http404
    return order


@require_POST
def start(request, number):
    """Pay (again) online for an existing order."""
    order = _order_for(request, number)
    try:
        url, _ = services.start_online_payment(order, request)
    except services.PaymentError as e:
        messages.error(request, e.message)
        return redirect(order.get_absolute_url())
    return redirect(url)


@never_cache
def callback(request, payment_id):
    """The gateway sends the customer back here (GET)."""
    try:
        payment = services.process_callback(request, payment_id)
    except Payment.DoesNotExist:
        raise Http404
    return redirect("payments:result", payment_id=payment.pk)


@never_cache
def result(request, payment_id):
    payment = get_object_or_404(Payment.objects.select_related("order"), pk=payment_id)
    order = payment.order
    return render(
        request,
        "payments/result.html",
        {"payment": payment, "order": order, "can_view_order": can_view(request, order)},
    )


def card_to_card(request, number):
    order = _order_for(request, number)
    if not order.can_submit_card_transfer:
        return redirect(order.get_absolute_url())
    form = CardTransferForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.submit_card_transfer(order, form.cleaned_data["tracking_number"], form.cleaned_data.get("receipt"))
        except services.PaymentError as e:
            messages.error(request, e.message)
        else:
            messages.success(request, "اطلاعات پرداخت ثبت شد. پس از بررسی و تأیید، سفارش شما آماده و ارسال می‌شود.")
        return redirect(order.get_absolute_url())
    return render(
        request,
        "payments/card_to_card.html",
        {"order": order, "form": form},
    )


RECEIPT_CONTENT_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


@never_cache
def receipt(request, payment_id):
    """A card-to-card receipt image, for staff who may see orders. The session must be a real
    admin session (admin login, with the 2FA code when it is on): the same rule as the admin
    pages, so a storefront (SMS-code) session of a staff member opens nothing here."""
    if not admin.site.has_permission(request):
        return redirect_to_login(request.get_full_path(), reverse("admin:login"))
    if not request.user.has_perm("orders.view_order"):
        raise PermissionDenied
    payment = get_object_or_404(Payment, pk=payment_id)
    if not payment.receipt:
        raise Http404
    try:
        with payment.receipt.open("rb") as fh, Image.open(fh) as img:
            content_type = RECEIPT_CONTENT_TYPES.get(img.format)
    except (OSError, UnidentifiedImageError, ValueError):
        content_type = None
    if content_type is None:  # not an image we accept: never sent to the browser
        raise Http404
    # The type comes from the file's real format, never from its name, and the browser may not guess.
    response = FileResponse(payment.receipt.open("rb"), content_type=content_type)
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response["Content-Disposition"] = "inline"
    return response
