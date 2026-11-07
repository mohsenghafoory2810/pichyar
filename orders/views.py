from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.flows import otp_step
from accounts.models import Address, OTPCode
from cart.cart import Cart
from core.utils import get_site_settings, htmx_redirect, is_htmx
from payments.services import PaymentError, start_online_payment

from .discounts import forget_code, price_cart, remember_code
from .forms import CheckoutForm, TrackForm
from .gifts import gift_options, slot_count
from .models import DiscountError, Order, PaymentMethod, find_usable_code
from .services import CHECKOUT_MOBILE_KEY, CheckoutError, can_view, create_order, remember_order, verified_mobile

CHECKOUT_PENDING_KEY = "checkout_pending_mobile"  # waiting for its SMS code


def available_methods(site_settings):
    methods = []
    if site_settings.online_payment_available:
        methods.append(PaymentMethod.ONLINE)
    if site_settings.card_to_card_available:
        methods.append(PaymentMethod.CARD)
    return methods


def _initial(request):
    user = request.user
    if not user.is_authenticated:
        return {}
    last = user.addresses.first()
    if last:
        return last.as_dict()
    return {"recipient_name": user.name, "recipient_mobile": user.mobile}


def _mobile_context(request, otp_context=None):
    if otp_context is None:
        _, otp_context = otp_step(request, OTPCode.Purpose.CHECKOUT, CHECKOUT_PENDING_KEY)
    return {
        **otp_context,
        "verified_mobile": request.session.get(CHECKOUT_MOBILE_KEY),
        "otp_url": reverse("orders:checkout_mobile"),
        "box_id": "checkout-mobile",
    }


def checkout(request):
    cart = Cart(request)
    if not cart:
        messages.info(request, "سبد خرید شما خالی است.")
        return redirect("cart:detail")
    site_settings = get_site_settings(request)
    methods = available_methods(site_settings)
    is_guest = not request.user.is_authenticated
    pricing = price_cart(request, cart, site_settings)
    form = _checkout_form(request, cart, pricing, methods, request.POST or None)
    mobile = verified_mobile(request)

    if request.method == "POST":
        if not methods:
            form.add_error(None, "در حال حاضر امکان پرداخت وجود ندارد. لطفاً بعداً تلاش کنید یا با پشتیبانی تماس بگیرید.")
        if not mobile:
            form.add_error(None, "ابتدا شمارهٔ موبایل خود را با کد پیامکی تأیید کنید.")
        if form.is_valid():
            data = form.cleaned_data
            address = {f: data.get(f) for f in CheckoutForm.ADDRESS_FIELDS}
            if is_guest:
                address["recipient_mobile"] = mobile
            try:
                order = create_order(
                    cart,
                    user=request.user,
                    mobile=mobile,
                    address=address,
                    note=data["note"],
                    payment_method=data["payment_method"],
                    expected_total=data["expected_total"],
                    site_settings=site_settings,
                    discount_code=pricing.code_text,
                    gifts=form.gift_selection(),
                )
            except CheckoutError as e:
                for message in e.messages:
                    form.add_error(None, message)
            else:
                if not is_guest and data.get("save_address"):
                    _save_address(request.user, address)
                cart.clear()
                forget_code(request)
                remember_order(request, order)
                if order.payment_method == PaymentMethod.CARD:
                    return redirect("payments:card", number=order.number)
                try:
                    url, _ = start_online_payment(order, request)
                except PaymentError as e:
                    messages.error(request, f"سفارش ثبت شد ولی اتصال به درگاه انجام نشد: {e.message}")
                    return redirect(order.get_absolute_url())
                return redirect(url)

    return render(request, "orders/checkout.html", _checkout_context(request, cart, form, pricing, methods))


def _checkout_form(request, cart, pricing, methods, data=None):
    earned = pricing.breakdown.gifts_earned
    options = gift_options(cart.lines()) if earned else []
    return CheckoutForm(
        data,
        methods=methods,
        is_guest=not request.user.is_authenticated,
        initial=_initial(request),
        gift_slots=slot_count(earned, options),
        gift_options=options,
    )


def _checkout_context(request, cart, form, pricing, methods, **extra):
    is_guest = not request.user.is_authenticated
    site_settings = pricing.site_settings
    breakdown = pricing.breakdown
    context = {
        "form": form,
        "lines": cart.lines(),
        "problems": cart.problems,
        "breakdown": breakdown,
        "pricing": pricing,
        "where": "checkout",
        "is_guest": is_guest,
        "methods": methods,
        "cards": site_settings.active_cards() if PaymentMethod.CARD in methods else [],
        "addresses": request.user.addresses.all() if not is_guest else [],
        "verified": bool(verified_mobile(request)),
        **extra,
    }
    if is_guest:
        context["mobile_box"] = _mobile_context(request)
    if form.is_bound:  # the total the customer saw on this render is the one they agree to
        form.data = form.data.copy()
        form.data["expected_total"] = breakdown.total
    else:
        form.initial["expected_total"] = breakdown.total
    return context


@require_POST
def discount(request):
    """Apply or remove the discount code (cart page and checkout; HTMX or a plain POST)."""
    cart = Cart(request)
    where = "checkout" if request.POST.get("where") == "checkout" else "cart"
    error = ""
    if request.POST.get("discount_action") == "remove":
        forget_code(request)
    else:
        subtotal = sum(line.line_total for line in cart.lines())
        try:
            code = find_usable_code(
                request.POST.get("code", ""), subtotal, user=request.user, mobile=verified_mobile(request)
            )
        except DiscountError as e:
            error = e.message
        else:
            remember_code(request, code)

    if not is_htmx(request):
        if error:
            messages.error(request, error)
        return redirect("orders:checkout" if where == "checkout" else "cart:detail")
    box = {"discount_input_error": error, "discount_input_value": request.POST.get("code", "") if error else ""}
    if where == "cart":
        from cart.views import _cart_context

        return render(request, "cart/_cart_body.html", {**_cart_context(request, cart), **box, "oob": True})
    if not cart:
        return htmx_redirect(request, reverse("cart:detail"))
    # Checkout: the whole page is rendered and the client swaps the summary, gift choices and totals.
    methods = available_methods(get_site_settings(request))
    pricing = price_cart(request, cart)
    form = _checkout_form(request, cart, pricing, methods)
    return render(request, "orders/checkout.html", _checkout_context(request, cart, form, pricing, methods, **box))


def _save_address(user, address):
    if user.addresses.count() >= Address.MAX_PER_USER:
        return
    if not user.addresses.filter(**address).exists():
        Address.objects.create(user=user, **address)


@require_POST
def checkout_mobile(request):
    """The guest's mobile verification box on the checkout page."""
    if request.POST.get("action") == "change":
        request.session.pop(CHECKOUT_MOBILE_KEY, None)
    verified, otp_context = otp_step(request, OTPCode.Purpose.CHECKOUT, CHECKOUT_PENDING_KEY)
    if verified:
        request.session[CHECKOUT_MOBILE_KEY] = verified
    if is_htmx(request):
        return render(request, "orders/_checkout_mobile.html", {"mobile_box": _mobile_context(request, otp_context)})
    if otp_context["error"]:
        messages.error(request, otp_context["error"])
    return redirect("orders:checkout")


@login_required
def address_fields(request, pk):
    """HTMX: fill the checkout address fields from a saved address."""
    address = get_object_or_404(Address, pk=pk, user=request.user)
    form = CheckoutForm(
        methods=available_methods(get_site_settings(request)), is_guest=False, initial=address.as_dict()
    )
    return render(request, "orders/_address_fields.html", {"form": form})


def detail(request, number):
    order = get_object_or_404(Order.objects.prefetch_related("items", "payments"), number=number)
    if not can_view(request, order):
        messages.info(request, "برای دیدن سفارش، شمارهٔ موبایل و شمارهٔ سفارش را وارد کنید.")
        return redirect("orders:track")
    if request.user.is_authenticated and Order.objects.for_user(request.user).filter(pk=order.pk).exists():
        return redirect("accounts:order_detail", number=order.number)
    return render(request, "orders/detail.html", {"order": order})


def track(request):
    form = TrackForm(request.POST or None)
    order = None
    not_found = False
    if request.method == "POST" and form.is_valid():
        order = (
            Order.objects.prefetch_related("items")
            .filter(number=form.cleaned_data["number"], mobile=form.cleaned_data["mobile"])
            .first()
        )
        not_found = order is None
    context = {"form": form, "order": order, "not_found": not_found, "tracking": True}
    if is_htmx(request):
        return render(request, "orders/_track_result.html", context)
    return render(request, "orders/track.html", context)
