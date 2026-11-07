from django import template
from django.core.paginator import Paginator

from core.persian import fa_digits

from .. import services
from ..forms import ReviewForm
from ..models import Review
from ..stats import rating_summary

register = template.Library()

PAGE_PARAM = "reviews_page"


def approved_page(product, number):
    reviews = Review.objects.approved().filter(product=product).select_related("user")
    return Paginator(reviews, services.page_size()).get_page(number)


@register.simple_tag(takes_context=True)
def reviews_context(context, product):
    """Everything the product page's reviews section needs:
    {% reviews_context product as rv %}"""
    request = context.get("request")
    user = getattr(request, "user", None)
    number = request.GET.get(PAGE_PARAM) if request else None
    return {
        "summary": rating_summary(product),
        "page": approved_page(product, number),
        "own_review": services.user_review(user, product),
        "form": ReviewForm(),
    }


@register.filter
def fa_rating(value):
    """4.5 -> '۴٫۵' (one decimal, Persian decimal separator)."""
    if value in (None, ""):
        return ""
    try:
        return fa_digits(f"{float(value):.1f}").replace(".", "٫")
    except (TypeError, ValueError):
        return ""


@register.filter
def review_author(user):
    return services.author_name(user)

