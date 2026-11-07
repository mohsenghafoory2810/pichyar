from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Address
from catalog.tests.utils import make_product
from orders.tests.utils import ADDRESS, configure_payments, make_order

User = get_user_model()


class PanelTests(TestCase):
    def setUp(self):
        configure_payments()
        self.user = User.objects.create_user("09125556666", name="سارا")
        self.other = User.objects.create_user("09127770000")
        self.client.force_login(self.user)
        p = make_product(stock=10)
        self.mine = make_order((p, 1), user=self.user, mobile=self.user.mobile)
        self.guest_mine = make_order((p, 2), mobile=self.user.mobile)  # placed as a guest with the same mobile
        self.theirs = make_order((p, 3), user=self.other, mobile=self.other.mobile)

    def test_login_required(self):
        self.client.logout()
        response = self.client.get(reverse("accounts:orders"))
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={reverse('accounts:orders')}")

    def test_order_list(self):
        response = self.client.get(reverse("accounts:orders"))
        numbers = [o.number for o in response.context["orders"]]
        self.assertCountEqual(numbers, [self.mine.number, self.guest_mine.number])

    def test_order_detail(self):
        response = self.client.get(reverse("accounts:order_detail", args=[self.mine.number]))
        self.assertContains(response, "علی رضایی")
        self.assertContains(response, "در انتظار پرداخت")
        self.assertEqual(self.client.get(reverse("accounts:order_detail", args=[self.theirs.number])).status_code, 404)
        # the public order URL sends the owner to the panel
        self.assertRedirects(self.client.get(self.mine.get_absolute_url()), reverse("accounts:order_detail", args=[self.mine.number]))

    def test_address_crud(self):
        data = {**ADDRESS, "recipient_mobile": "۰۹۱۲۱۱۱۱۱۱۱", "postal_code": "۱۲۳۴۵۶۷۸۹۰"}
        self.assertRedirects(self.client.post(reverse("accounts:address_add"), data), reverse("accounts:addresses"))
        a = self.user.addresses.get()
        self.assertEqual((a.recipient_mobile, a.postal_code), ("09121111111", "1234567890"))
        self.client.post(reverse("accounts:address_edit", args=[a.pk]), {**data, "city": "شیراز", "province": "فارس"})
        a.refresh_from_db()
        self.assertEqual(a.city, "شیراز")
        self.assertContains(self.client.get(reverse("accounts:addresses")), "شیراز")
        self.client.post(reverse("accounts:address_delete", args=[a.pk]))
        self.assertFalse(self.user.addresses.exists())

    def test_address_validation(self):
        response = self.client.post(reverse("accounts:address_add"), {**ADDRESS, "postal_code": "123"})
        self.assertContains(response, "کد پستی باید ۱۰ رقم باشد")
        self.assertFalse(Address.objects.exists())

    def test_cannot_touch_other_users_addresses(self):
        theirs = Address.objects.create(user=self.other, **ADDRESS)
        self.assertEqual(self.client.get(reverse("accounts:address_edit", args=[theirs.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("accounts:address_delete", args=[theirs.pk])).status_code, 404)
        self.assertTrue(Address.objects.filter(pk=theirs.pk).exists())

    def test_address_limit(self):
        for _ in range(Address.MAX_PER_USER):
            Address.objects.create(user=self.user, **ADDRESS)
        self.client.post(reverse("accounts:address_add"), ADDRESS)
        self.assertEqual(self.user.addresses.count(), Address.MAX_PER_USER)

    def test_profile(self):
        self.assertContains(self.client.get(reverse("accounts:profile")), "۰۹۱۲۵۵۵۶۶۶۶")
        response = self.client.post(reverse("accounts:profile") + "?next=/checkout/", {"name": "سارا احمدی", "next": "/checkout/"})
        self.assertRedirects(response, "/checkout/", fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.name, "سارا احمدی")
        self.assertContains(self.client.post(reverse("accounts:profile"), {"name": ""}), "این فیلد لازم است")

    def test_logout(self):
        self.client.post(reverse("accounts:logout"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_header_shows_account_link(self):
        self.assertContains(self.client.get("/"), "حساب من")


class TrackingTests(TestCase):
    def setUp(self):
        configure_payments()
        self.order = make_order((make_product(stock=10), 1), mobile="09123334444")
        self.url = reverse("orders:track")

    def test_page(self):
        self.assertContains(self.client.get(self.url), "پیگیری سفارش")

    def test_found_with_persian_digits(self):
        fa = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
        response = self.client.post(self.url, {"mobile": "09123334444".translate(fa), "number": self.order.number.translate(fa)})
        self.assertContains(response, "در انتظار پرداخت")
        self.assertContains(response, "علی رضایی")
        self.assertNotContains(response, "ثبت اطلاعات پرداخت")  # no payment actions on the tracking page

    def test_wrong_mobile(self):
        response = self.client.post(self.url, {"mobile": "09120000000", "number": self.order.number}, headers={"HX-Request": "true"})
        self.assertContains(response, "سفارشی با این شمارهٔ موبایل و شمارهٔ سفارش پیدا نشد")
        self.assertNotContains(response, "علی رضایی")

    def test_shows_post_tracking_code(self):
        from payments.services import submit_card_transfer

        submit_card_transfer(self.order, "123456")
        self.order.approve()
        self.order.mark_shipped("PT-998877")
        response = self.client.post(self.url, {"mobile": "09123334444", "number": self.order.number})
        self.assertContains(response, "کد رهگیری پست")
        self.assertContains(response, "ارسال‌شده")
