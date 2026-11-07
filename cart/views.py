from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from catalog.models import Product
from core.persian import latin_digits
from core.utils import is_htmx
from orders.discounts import price_cart

from .cart import Cart, CartError


def _int(value, default):
    try:
        return int(latin_digits(value).strip())
    except (TypeError, ValueError):
        return default


def _cart_context(request, cart, error=""):
    pricing = price_cart(request, cart)
    return {
        "cart": cart,
        "lines": cart.lines(),
        "breakdown": pricing.breakdown,
        "pricing": pricing,
        "where": "cart",
        "cart_error": error,
    }


def detail(request):
    cart = Cart(request)
    return render(request, "cart/detail.html", _cart_context(request, cart))


@require_POST
def add(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    cart = Cart(request)
    quantity = _int(request.POST.get("quantity"), 1)
    ok, message = True, f"«{product.name}» به سبد خرید اضافه شد."
    if quantity < 1:
        ok, message = False, "تعداد باید دست‌کم ۱ باشد."
    else:
        try:
            cart.add(product, quantity)
        except CartError as e:
            ok, message = False, str(e)
    if is_htmx(request):
        return render(request, "cart/_add_result.html", {"ok": ok, "message": message, "product": product})
    if ok:
        messages.success(request, message)
        return redirect("cart:detail")
    messages.error(request, message)
    return redirect(product.get_absolute_url())


@require_POST
def update(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    cart = Cart(request)
    current = cart.quantity_of(product)
    quantity = _int(request.POST.get("quantity"), current) + _int(request.POST.get("delta"), 0)
    error = ""
    try:
        cart.set(product, quantity)
    except CartError as e:
        error = str(e)
    return _respond(request, cart, error)


@require_POST
def remove(request, product_id):
    cart = Cart(request)
    product = get_object_or_404(Product, pk=product_id)
    cart.remove(product)
    return _respond(request, cart)


def _respond(request, cart, error=""):
    if is_htmx(request):
        return render(request, "cart/_cart_body.html", {**_cart_context(request, cart, error), "oob": True})
    if error:
        messages.error(request, error)
    return redirect("cart:detail")
