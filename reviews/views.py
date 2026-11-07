"""Product reviews on the storefront: the paginated list (HTMX partial) and the submit form."""

from urllib.parse import urlencode

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from catalog.models import Product
from core.utils import client_ip, is_htmx

from . import services
from .forms import ReviewForm
from .templatetags.reviews_tags import PAGE_PARAM, approved_page


def _product(product_id):
    return get_object_or_404(Product.objects.active(), pk=product_id)


def _reviews_url(product, page=None):
    query = f"?{urlencode({PAGE_PARAM: page})}" if page and page > 1 else ""
    return f"{product.get_absolute_url()}{query}#reviews"


@require_GET
def review_list(request, product_id):
    """One page of approved reviews: the <li> items plus the next «more» item (HTMX).
    Without HTMX, the same page of the product page itself."""
    product = _product(product_id)
    page = approved_page(product, request.GET.get("page"))
    if not is_htmx(request):
        return redirect(_reviews_url(product, page.number))
    response = render(request, "reviews/_review_items.html", {"product": product, "page": page})
    response["X-Robots-Tag"] = "noindex"
    return response


@require_POST
def submit_review(request, product_id):
    product = _product(product_id)
    htmx = is_htmx(request)
    user = request.user

    def area(**context):
        return render(request, "reviews/_form_area.html", {"product": product, "user": user, **context})

    if not user.is_authenticated:
        if htmx:
            return area()
        login = reverse("accounts:login")
        return redirect(f"{login}?{urlencode({'next': _reviews_url(product)})}")

    existing = services.user_review(user, product)
    if existing:
        if htmx:
            return area(own_review=existing, notice=services.ALREADY_REVIEWED)
        messages.info(request, services.ALREADY_REVIEWED)
        return redirect(_reviews_url(product))

    form = ReviewForm(request.POST)
    if form.is_bot:
        # Honeypot filled: look like a success, save nothing.
        return _thanks(request, product, htmx, area)

    ip = client_ip(request)
    limit_error = services.rate_limit_error(user, ip)
    if limit_error:
        form.is_valid()
        form.add_error(None, limit_error)
    if form.is_valid():
        review = services.create_review(form, product, user, ip)
        if review is None:  # a parallel submit won
            if htmx:
                return area(own_review=services.user_review(user, product), notice=services.ALREADY_REVIEWED)
            messages.info(request, services.ALREADY_REVIEWED)
            return redirect(_reviews_url(product))
        return _thanks(request, product, htmx, area)

    if htmx:
        return area(form=form)
    for errors in form.errors.values():
        for error in errors:
            messages.error(request, error)
    return redirect(_reviews_url(product))


THANKS = "نظر شما ثبت شد و پس از بررسی نمایش داده می‌شود. از شما سپاسگزاریم."


def _thanks(request, product, htmx, area):
    if htmx:
        return area(thanks=THANKS)
    messages.success(request, THANKS)
    return redirect(_reviews_url(product))
