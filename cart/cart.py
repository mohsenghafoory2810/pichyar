"""Session cart (works for guests): {product_id: quantity} in request.session["cart"].

Prices are never stored in the session: every read takes the current price and
stock from the database, so the cart always shows what checkout will charge.
"""

from django.db.models import Prefetch

from catalog import stock
from catalog.models import Product, ProductImage
from core.persian import fa_digits

SESSION_KEY = "cart"


class CartError(Exception):
    pass


class CartLine:
    def __init__(self, product, quantity, available=True):
        self.product = product
        self.quantity = quantity
        self.available = available  # active product in an active category

    @property
    def unit_price(self):
        return self.product.price

    @property
    def line_total(self):
        return self.product.price * self.quantity

    @property
    def max_quantity(self):
        return self.product.stock if self.available else 0

    @property
    def problem(self):
        if not self.available or self.product.stock <= 0:
            return "این کالا ناموجود است؛ آن را از سبد حذف کنید."
        if self.quantity > self.product.stock:
            return f"فقط {fa_digits(self.product.stock)} عدد موجود است؛ تعداد را کم کنید."
        return None


def limit_message(product):
    if product.stock <= 0:
        return f"«{product.name}» ناموجود است."
    return f"از «{product.name}» حداکثر {fa_digits(product.stock)} عدد می‌توانید سفارش دهید."


class Cart:
    def __init__(self, request):
        self.session = request.session
        data = self.session.get(SESSION_KEY)
        self._data = data if isinstance(data, dict) else {}
        self._lines = None

    def _save(self):
        self.session[SESSION_KEY] = self._data
        self.session.modified = True
        self._lines = None

    # --- reading -------------------------------------------------------------

    @property
    def count(self):
        """Total number of items (no database query)."""
        return sum(self._data.values())

    def __len__(self):
        return len(self._data)

    def __bool__(self):
        return bool(self._data)

    def quantity_of(self, product):
        return self._data.get(str(product.pk), 0)

    def lines(self):
        if self._lines is None:
            ids = [int(pk) for pk in self._data]
            products = Product.objects.filter(pk__in=ids).prefetch_related(
                Prefetch("images", queryset=ProductImage.objects.order_by("order", "id"))
            )
            products = {p.pk: p for p in products}
            active = set(Product.objects.active().filter(pk__in=ids).values_list("pk", flat=True))
            gone = [pk for pk in ids if pk not in products]
            if gone:  # deleted products silently leave the cart
                for pk in gone:
                    self._data.pop(str(pk), None)
                self._save()
            self._lines = [
                CartLine(products[int(pk)], qty, available=int(pk) in active) for pk, qty in self._data.items()
            ]
        return self._lines

    def __iter__(self):
        return iter(self.lines())

    @property
    def problems(self):
        return [line for line in self.lines() if line.problem]

    @property
    def items_subtotal(self):
        return sum(line.line_total for line in self.lines())

    # --- changing --------------------------------------------------------------

    def add(self, product, quantity=1):
        self.set(product, self.quantity_of(product) + quantity)

    def set(self, product, quantity):
        """Set the quantity (0 removes). Raises CartError above stock or for unavailable products."""
        if quantity <= 0:
            self.remove(product)
            return
        is_active = Product.objects.active().filter(pk=product.pk).exists()
        if not is_active or not stock.can_add_to_cart(product, quantity):
            raise CartError(limit_message(product) if is_active else f"«{product.name}» دیگر فروخته نمی‌شود.")
        self._data[str(product.pk)] = int(quantity)
        self._save()

    def remove(self, product):
        if self._data.pop(str(product.pk), None) is not None:
            self._save()

    def clear(self):
        self._data = {}
        self._save()
