from django.test import TestCase
from django.urls import reverse

from cart.cart import SESSION_KEY
from catalog.tests.utils import make_product

HTMX = {"HX-Request": "true"}


class CartTestCase(TestCase):
    def setUp(self):
        self.p = make_product("دیویدوف", price=1_000_000, stock=3)

    def cart(self):
        return self.client.session.get(SESSION_KEY, {})

    def add(self, product, qty, **kwargs):
        return self.client.post(reverse("cart:add", args=[product.pk]), {"quantity": qty}, **kwargs)

    def update(self, product, htmx=False, **data):
        return self.client.post(reverse("cart:update", args=[product.pk]), data, headers=HTMX if htmx else {})


class AddToCartTests(CartTestCase):
    def test_add_within_stock(self):
        response = self.add(self.p, 2)
        self.assertRedirects(response, reverse("cart:detail"))
        self.assertEqual(self.cart(), {str(self.p.pk): 2})

    def test_add_accumulates_up_to_stock(self):
        self.add(self.p, 2)
        response = self.add(self.p, 2, follow=True)
        self.assertContains(response, "حداکثر ۳ عدد")
        self.assertEqual(self.cart(), {str(self.p.pk): 2})
        self.add(self.p, 1)
        self.assertEqual(self.cart(), {str(self.p.pk): 3})

    def test_above_stock_is_refused(self):
        self.add(self.p, 4)
        self.assertEqual(self.cart(), {})

    def test_out_of_stock_is_refused(self):
        p = make_product("تمام‌شده", stock=0)
        response = self.add(p, 1, headers=HTMX)
        self.assertContains(response, "ناموجود است")
        self.assertEqual(self.cart(), {})

    def test_inactive_product_is_refused(self):
        p = make_product("مخفی", stock=5, is_active=False)
        response = self.add(p, 1, headers=HTMX)
        self.assertContains(response, "دیگر فروخته نمی‌شود")
        self.assertEqual(self.cart(), {})

    def test_zero_and_garbage_quantities(self):
        self.add(self.p, 0)
        self.add(self.p, -2)
        self.assertEqual(self.cart(), {})
        self.add(self.p, "abc")  # falls back to 1
        self.assertEqual(self.cart(), {str(self.p.pk): 1})

    def test_persian_digit_quantity(self):
        self.add(self.p, "۲")
        self.assertEqual(self.cart(), {str(self.p.pk): 2})

    def test_htmx_add_updates_header_and_bottom_bar(self):
        response = self.add(self.p, 2, headers=HTMX)
        body = response.content.decode()
        self.assertIn('id="cart-feedback"', body)
        self.assertIn("به سبد خرید اضافه شد", body)
        self.assertRegex(body, r'id="header-cart"[^>]*hx-swap-oob="true"')
        self.assertRegex(body, r'id="bottom-bar"[^>]*hx-swap-oob="true"')
        self.assertIn('<span id="cart-count"', body)
        self.assertIn("۲٬۲۰۰٬۰۰۰ تومان", body)  # bottom bar total: 2,000,000 + 200,000 shipping
        self.assertIn(reverse("orders:checkout"), body)


class UpdateCartTests(CartTestCase):
    def setUp(self):
        super().setUp()
        self.add(self.p, 1)

    def test_delta_buttons(self):
        self.update(self.p, quantity=1, delta=1)
        self.assertEqual(self.cart(), {str(self.p.pk): 2})
        self.update(self.p, quantity=2, delta=-1)
        self.assertEqual(self.cart(), {str(self.p.pk): 1})

    def test_typed_quantity_above_stock_is_refused(self):
        response = self.update(self.p, quantity=5, htmx=True)
        self.assertContains(response, "حداکثر ۳ عدد")
        self.assertEqual(self.cart(), {str(self.p.pk): 1})

    def test_zero_removes(self):
        self.update(self.p, quantity=1, delta=-1)
        self.assertEqual(self.cart(), {})

    def test_remove(self):
        self.client.post(reverse("cart:remove", args=[self.p.pk]))
        self.assertEqual(self.cart(), {})

    def test_htmx_update_returns_live_totals(self):
        response = self.update(self.p, quantity=3, htmx=True)
        body = response.content.decode()
        self.assertIn('id="cart-body"', body)
        self.assertIn("۳٬۰۰۰٬۰۰۰ تومان", body)  # subtotal
        self.assertIn("۳٬۲۰۰٬۰۰۰ تومان", body)  # total with shipping
        self.assertRegex(body, r'id="bottom-bar"[^>]*hx-swap-oob="true"')

    def test_cart_page_shows_shipping_fee(self):
        response = self.client.get(reverse("cart:detail"))
        self.assertContains(response, "هزینهٔ ارسال (پست)")
        self.assertContains(response, "۲۰۰٬۰۰۰ تومان")
        self.assertContains(response, "۱٬۲۰۰٬۰۰۰ تومان")


class CartRevalidationTests(CartTestCase):
    def test_price_is_always_current(self):
        self.add(self.p, 1)
        self.p.price = 1_500_000
        self.p.save()
        self.assertContains(self.client.get(reverse("cart:detail")), "۱٬۵۰۰٬۰۰۰ تومان")

    def test_stock_drop_flags_the_line_and_blocks_checkout(self):
        self.add(self.p, 3)
        self.p.stock = 1
        self.p.save()
        response = self.client.get(reverse("cart:detail"))
        self.assertContains(response, "فقط ۱ عدد موجود است")
        self.assertRegex(response.content.decode(), r'<button type="button" class="btn-cta w-full" disabled>تسویه حساب')

    def test_deleted_product_leaves_the_cart(self):
        self.add(self.p, 1)
        self.p.delete()
        self.assertContains(self.client.get(reverse("cart:detail")), "سبد خرید شما خالی است")
        self.assertEqual(self.cart(), {})

    def test_product_page_shows_quantity_in_cart(self):
        self.add(self.p, 2)
        self.assertContains(self.client.get(self.p.get_absolute_url()), "۲ عدد از این کالا")
