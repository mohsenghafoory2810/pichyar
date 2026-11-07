"""Review submission rules: verified purchase, rate limits and the public author name."""

from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.persian import fa_digits

from .models import Review

# Overridable in Django settings.
USER_HOURLY_LIMIT = 5
IP_HOURLY_LIMIT = 10
PAGE_SIZE = 10

RATE_LIMIT_ERROR = "تعداد نظرهای ثبت‌شده در یک ساعت گذشته زیاد است. لطفاً کمی بعد دوباره تلاش کنید."
ALREADY_REVIEWED = "شما قبلاً برای این محصول نظر ثبت کرده‌اید."


def setting(name, default):
    return getattr(settings, name, default)


def user_limit():
    return setting("REVIEWS_USER_HOURLY_LIMIT", USER_HOURLY_LIMIT)


def ip_limit():
    return setting("REVIEWS_IP_HOURLY_LIMIT", IP_HOURLY_LIMIT)


def page_size():
    return setting("REVIEWS_PAGE_SIZE", PAGE_SIZE)


def has_purchased(user, product):
    """True when the user has a confirmed (paid, shipped or delivered) order containing the
    product — their own orders and guest orders placed with their verified mobile."""
    from orders.models import CONFIRMED_STATUSES, Order, OrderItem

    if not getattr(user, "is_authenticated", False):
        return False
    return OrderItem.objects.filter(
        product=product,
        order__in=Order.objects.for_user(user).filter(status__in=CONFIRMED_STATUSES),
    ).exists()


def user_review(user, product):
    """The user's own review of the product (any status), or None."""
    if not getattr(user, "is_authenticated", False):
        return None
    return Review.objects.filter(product=product, user=user).first()


def rate_limit_error(user, ip):
    """RATE_LIMIT_ERROR when the user or the IP posted too many reviews in the last hour."""
    since = timezone.now() - timedelta(hours=1)
    recent = Review.objects.filter(created_at__gte=since)
    if recent.filter(user=user).count() >= user_limit():
        return RATE_LIMIT_ERROR
    if ip and recent.filter(ip_address=ip).count() >= ip_limit():
        return RATE_LIMIT_ERROR
    return None


def create_review(form, product, user, ip):
    """Saves the form's review as pending. Returns the Review, or None if the user already
    reviewed the product (also when two submissions race)."""
    review = form.save(commit=False)
    review.product = product
    review.user = user
    review.ip_address = ip
    review.status = Review.Status.PENDING
    review.verified_purchase = has_purchased(user, product)
    try:
        with transaction.atomic():
            review.save()
    except IntegrityError:
        return None
    return review


def author_name(user):
    """Public name: the first word of the customer's name, else «کاربر» and the last 4 digits
    of the mobile (the full number is never shown)."""
    name = (getattr(user, "name", "") or "").split()
    if name:
        return name[0][:30]
    mobile = getattr(user, "mobile", "") or ""
    return f"کاربر …{fa_digits(mobile[-4:])}" if len(mobile) >= 4 else "کاربر"
