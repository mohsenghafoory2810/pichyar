from django.utils.functional import SimpleLazyObject

from .cart import Cart


def cart(request):
    current = Cart(request)

    def summary():
        from orders.discounts import price_cart

        return price_cart(request, current).breakdown

    return {
        "cart_count": current.count,
        # Only queried when a template actually shows the total (bottom bar with items).
        "cart_summary": SimpleLazyObject(summary),
    }
