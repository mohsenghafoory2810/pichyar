from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

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


@staff_member_required
def receipt(request, payment_id):
    payment = get_object_or_404(Payment, pk=payment_id)
    if not payment.receipt:
        raise Http404
    return FileResponse(payment.receipt.open("rb"))
