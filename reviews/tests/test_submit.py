from django.test import override_settings
from django.urls import reverse

from catalog.tests.utils import make_product
from orders.models import OrderStatus
from orders.tests.utils import capture_sms, configure_payments, make_order
from reviews.models import Review
from reviews.services import has_purchased

from .utils import ReviewTestCase, make_customer, make_review


class SubmitAccessTests(ReviewTestCase):
    def test_anonymous_cannot_submit(self):
        response = self.post_review()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("accounts:login"))
        self.assertFalse(Review.objects.exists())

    def test_anonymous_without_htmx_goes_to_login(self):
        response = self.post_review(htmx=False)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse("accounts:login") + "?next="))
        self.assertFalse(Review.objects.exists())

    def test_anonymous_sees_login_prompt_on_product_page(self):
        response = self.client.get(self.product.get_absolute_url())
        self.assertContains(response, "نظر خریداران")
        self.assertContains(response, f"{reverse('accounts:login')}?next=")
        self.assertNotContains(response, self.submit_url())

    def test_get_not_allowed(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(self.submit_url()).status_code, 405)

    def test_inactive_product_404(self):
        hidden = make_product("مخفی", is_active=False)
        self.client.force_login(self.customer)
        self.assertEqual(self.post_review(product=hidden).status_code, 404)
        self.assertEqual(self.client.get(self.list_url(hidden), HTTP_HX_REQUEST="true").status_code, 404)
        self.assertFalse(Review.objects.exists())


class SubmitTests(ReviewTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.customer)

    def test_logged_in_sees_form(self):
        response = self.client.get(self.product.get_absolute_url())
        self.assertContains(response, f'hx-post="{self.submit_url()}"')
        self.assertContains(response, 'tabindex="-1"')  # honeypot

    def test_htmx_submit_creates_pending_review(self):
        response = self.post_review({"title": "خوب", "rating": "4"}, REMOTE_ADDR="10.0.0.5")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "پس از بررسی نمایش داده می‌شود")
        review = Review.objects.get()
        self.assertEqual(
            (review.status, review.rating, review.title, review.user, review.ip_address),
            (Review.Status.PENDING, 4, "خوب", self.customer, "10.0.0.5"),
        )
        self.assertFalse(review.verified_purchase)
        # Pending: not on the page for others, but shown to its author.
        page = self.client.get(self.product.get_absolute_url())
        self.assertContains(page, "در انتظار بررسی")
        self.assertContains(page, "هنوز نظری برای این محصول منتشر نشده است")

    def test_non_htmx_submit_redirects_with_message(self):
        response = self.post_review(htmx=False, follow=True)
        self.assertRedirects(response, self.product.get_absolute_url() + "#reviews", fetch_redirect_response=False)
        self.assertEqual(Review.objects.count(), 1)
        self.assertContains(response, "نظر شما ثبت شد")

    def test_one_review_per_product(self):
        self.post_review()
        response = self.post_review({"text": "یک نظر دیگر برای همین محصول."})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "قبلاً برای این محصول نظر ثبت کرده‌اید")
        self.assertEqual(Review.objects.count(), 1)
        response = self.post_review({"text": "یک نظر دیگر برای همین محصول."}, htmx=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Review.objects.count(), 1)
        self.assertNotContains(self.client.get(self.product.get_absolute_url()), f'hx-post="{self.submit_url()}"')

    def test_honeypot_pretends_success(self):
        response = self.post_review({"website": "http://spam.example"})
        self.assertContains(response, "نظر شما ثبت شد")
        self.assertFalse(Review.objects.exists())

    def test_validation_errors(self):
        cases = [
            ({"rating": ""}, "امتیاز"),
            ({"rating": "6"}, "امتیاز"),
            ({"text": "   کوتاه   "}, "دست‌کم ۱۰ نویسه"),
            ({"text": "عالی بود، سایت ما را ببینید: https://shop.test/x"}, "لینک"),
            ({"text": "برای خرید عمده به www.something مراجعه کنید"}, "لینک"),
            ({"text": "قیمت بهتر در example.com و فروشگاه دیگر"}, "لینک"),
            ({"text": "کانال ما t.me/channel را دنبال کنید"}, "لینک"),
            ({"title": "mysite.ir", "text": "متن معمولی و بی‌خطر برای آزمون"}, "لینک"),
            ({"text": "برای سفارش با 09121234567 تماس بگیرید"}, "تلفن"),
            ({"text": "برای سفارش با ۰۹۱۲ ۱۲۳ ۴۵۶۷ تماس بگیرید"}, "تلفن"),
            ({"text": "برای سفارش با ٠٩١٢-١٢٣-٤٥٦٧ تماس بگیرید"}, "تلفن"),
            ({"text": "شماره: +98 912 123 4567 واتساپ"}, "تلفن"),
            ({"text": "تلفن ثابت ۰۲۱۸۸۷۷۶۶۵۵ هم داریم"}, "تلفن"),
        ]
        for data, message in cases:
            with self.subTest(data=data):
                response = self.post_review(data)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, message)
                self.assertContains(response, f'hx-post="{self.submit_url()}"')  # the form again
        self.assertFalse(Review.objects.exists())

    def test_allowed_text(self):
        # Prices with thousands separators and short numbers are fine; so is a sentence-ending dot.
        self.post_review({"text": "با قیمت ۱٬۲۵۰٬۰۰۰ تومان خریدم. بعد از ۳ روز رسید. Good."})
        self.assertEqual(Review.objects.count(), 1)

    @override_settings(REVIEWS_USER_HOURLY_LIMIT=2)
    def test_user_rate_limit(self):
        for i in range(2):
            self.post_review(product=make_product(f"محصول {i}"))
        response = self.post_review()
        self.assertContains(response, "کمی بعد دوباره تلاش کنید")
        self.assertEqual(Review.objects.count(), 2)

    @override_settings(REVIEWS_IP_HOURLY_LIMIT=2)
    def test_ip_rate_limit(self):
        for i in range(2):
            make_review(make_product(f"محصول {i}"), make_customer(f"0912000000{i}"), ip_address="10.1.1.1")
        response = self.post_review(REMOTE_ADDR="10.1.1.1")
        self.assertContains(response, "کمی بعد دوباره تلاش کنید")
        self.assertFalse(Review.objects.filter(user=self.customer).exists())
        self.post_review(REMOTE_ADDR="10.1.1.2")
        self.assertTrue(Review.objects.filter(user=self.customer).exists())


class VerifiedPurchaseTests(ReviewTestCase):
    def setUp(self):
        super().setUp()
        configure_payments()
        self.client.force_login(self.customer)

    def order(self, product, status=None):
        with capture_sms():
            order = make_order((product, 1), user=self.customer, mobile=self.customer.mobile)
            if status:
                order.confirm_payment()
                if status == OrderStatus.SHIPPED:
                    order.mark_shipped("123456789")
        return order

    def test_only_confirmed_orders_with_the_product(self):
        other = make_product("دیگری")
        self.order(self.product)  # pending payment
        self.order(other, OrderStatus.PAID_PROCESSING)  # confirmed, other product
        self.assertFalse(has_purchased(self.customer, self.product))
        self.post_review()
        self.assertFalse(Review.objects.get().verified_purchase)

        self.order(self.product, OrderStatus.SHIPPED)
        self.assertTrue(has_purchased(self.customer, self.product))
        self.post_review(product=other)
        self.assertTrue(Review.objects.get(product=other).verified_purchase)

    def test_canceled_order_does_not_count(self):
        order = self.order(self.product, OrderStatus.PAID_PROCESSING)
        with capture_sms():
            order.cancel()
        self.assertFalse(has_purchased(self.customer, self.product))
