from django.test import override_settings
from django.urls import reverse

from catalog.tests.utils import make_product
from orders.tests.utils import configure_payments, make_order
from support import services
from support.models import Ticket, TicketMessage

from .utils import SupportTestCase, make_customer, make_ticket, update_settings

S = Ticket.Status
LIST = reverse("support:list")
NEW = reverse("support:new")


class AccessTests(SupportTestCase):
    def test_login_required(self):
        ticket = make_ticket(self.customer)
        for url in (LIST, NEW, ticket.get_absolute_url()):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response["Location"].startswith(reverse("accounts:login")))

    def test_other_users_ticket_is_404(self):
        ticket = make_ticket(make_customer("09122222222"), subject="پیام دیگری")
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(ticket.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.post(ticket.get_absolute_url(), {"text": "سلام"}).status_code, 404)
        self.assertNotContains(self.client.get(LIST), "پیام دیگری")
        self.assertEqual(ticket.messages.count(), 1)


class CustomerFlowTests(SupportTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.customer)

    def post_new(self, **data):
        payload = {"subject": "پرسش دربارهٔ ارسال", "text": "سفارش من کی می‌رسد؟", "order": ""}
        payload.update(data)
        return self.client.post(NEW, payload)

    def test_panel_tab_and_empty_list(self):
        response = self.client.get(reverse("accounts:orders"))
        self.assertContains(response, f'href="{LIST}"')
        self.assertContains(response, "پیام به پشتیبانی")
        response = self.client.get(LIST)
        self.assertContains(response, "هنوز پیامی برای پشتیبانی نفرستاده‌اید")
        self.assertContains(response, NEW)

    def test_new_form_shows_intro_and_own_orders(self):
        update_settings(support_intro="پاسخگویی: شنبه تا چهارشنبه")
        configure_payments()
        product = make_product("آریزونا")
        mine = make_order((product, 1), user=self.customer, mobile=self.customer.mobile)
        other = make_order((product, 1), user=make_customer("09122222222"), mobile="09122222222")
        response = self.client.get(NEW)
        self.assertContains(response, "پاسخگویی: شنبه تا چهارشنبه")
        self.assertContains(response, f'value="{mine.pk}"')
        self.assertNotContains(response, f'value="{other.pk}"')
        self.assertContains(response, 'tabindex="-1"')  # honeypot
        # Someone else's order is refused.
        response = self.post_new(order=other.pk)
        self.assertContains(response, "سفارش انتخاب‌شده معتبر نیست")
        self.assertFalse(Ticket.objects.exists())
        self.post_new(order=mine.pk)
        self.assertEqual(Ticket.objects.get().order, mine)

    def test_create_ticket(self):
        response = self.post_new(subject="  پرسش   دربارهٔ ارسال ", text="  سفارش من کی می‌رسد؟\nسپاس  ")
        ticket = Ticket.objects.get()
        self.assertRedirects(response, ticket.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual((ticket.user, ticket.subject, ticket.status), (self.customer, "پرسش دربارهٔ ارسال", S.WAITING))
        self.assertEqual(ticket.messages.get().text, "سفارش من کی می‌رسد؟\nسپاس")
        page = self.client.get(ticket.get_absolute_url())
        self.assertContains(page, "پیام شما برای پشتیبانی فرستاده شد")
        self.assertContains(page, "سفارش من کی می‌رسد؟<br>سپاس")

    def test_validation(self):
        response = self.post_new(subject="", text="   ")
        self.assertContains(response, "موضوع پیام را بنویسید")
        self.assertContains(response, "متن پیام را بنویسید")
        response = self.post_new(text="ب" * 3001)
        self.assertContains(response, "حداکثر ۳۰۰۰ نویسه")
        self.assertFalse(Ticket.objects.exists())

    def test_links_and_phone_numbers_are_allowed(self):
        self.post_new(text="با شمارهٔ 09121234567 تماس بگیرید یا https://example.com را ببینید")
        self.assertEqual(Ticket.objects.count(), 1)

    def test_honeypot(self):
        response = self.post_new(website="http://spam.example")
        self.assertRedirects(response, LIST)
        self.assertFalse(Ticket.objects.exists())

    @override_settings(SUPPORT_TICKETS_HOURLY_LIMIT=1)
    def test_rate_limit_new_ticket(self):
        self.post_new()
        response = self.post_new(subject="دومی")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "تعداد پیام‌های ارسال‌شده در یک ساعت گذشته زیاد است")
        self.assertEqual(Ticket.objects.count(), 1)

    @override_settings(SUPPORT_MESSAGES_HOURLY_LIMIT=2)
    def test_rate_limit_reply(self):
        ticket = make_ticket(self.customer)
        url = ticket.get_absolute_url()
        self.assertRedirects(self.client.post(url, {"text": "دوم"}), url + "#reply", fetch_redirect_response=False)
        response = self.client.post(url, {"text": "سوم"})
        self.assertContains(response, "زیاد است")
        self.assertEqual(ticket.messages.count(), 2)

    def test_conversation_and_unread(self):
        ticket = make_ticket(self.customer)
        services.add_staff_reply(ticket, None, "سفارش شما فردا ارسال می‌شود.")
        listing = self.client.get(LIST)
        self.assertContains(listing, "پاسخ جدید")
        self.assertContains(listing, "پاسخ داده شد")
        self.assertContains(listing, "پاسخ خوانده‌نشده")  # tab badge
        page = self.client.get(ticket.get_absolute_url())
        self.assertContains(page, "سفارش شما فردا ارسال می‌شود.")
        ticket.refresh_from_db()
        self.assertFalse(ticket.customer_unread)
        self.assertNotContains(self.client.get(LIST), "پاسخ خوانده‌نشده")

    def test_reply_sets_waiting(self):
        ticket = make_ticket(self.customer)
        services.add_staff_reply(ticket, None, "پاسخ")
        self.client.post(ticket.get_absolute_url(), {"text": "یک پرسش دیگر"})
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, S.WAITING)
        last = ticket.messages.last()
        self.assertEqual((last.text, last.is_staff_reply, last.author), ("یک پرسش دیگر", False, self.customer))

    def test_reply_honeypot(self):
        ticket = make_ticket(self.customer)
        self.client.post(ticket.get_absolute_url(), {"text": "اسپم", "website": "x"})
        self.assertEqual(ticket.messages.count(), 1)

    def test_closed_ticket_is_read_only(self):
        ticket = make_ticket(self.customer)
        Ticket.objects.filter(pk=ticket.pk).update(status=S.CLOSED)
        page = self.client.get(ticket.get_absolute_url())
        self.assertContains(page, "این گفتگو بسته شده است")
        self.assertNotContains(page, 'name="text"')
        self.client.post(ticket.get_absolute_url(), {"text": "باز کن"})
        ticket.refresh_from_db()
        self.assertEqual((ticket.status, ticket.messages.count()), (S.CLOSED, 1))

    def test_html_is_escaped(self):
        ticket = make_ticket(self.customer, text="<script>alert(1)</script>")
        page = self.client.get(ticket.get_absolute_url())
        self.assertNotContains(page, "<script>alert(1)</script>")
        self.assertContains(page, "&lt;script&gt;")


class DisabledTests(SupportTestCase):
    def setUp(self):
        super().setUp()
        update_settings(support_tickets_enabled=False)
        self.client.force_login(self.customer)

    def test_tab_hidden_without_tickets(self):
        self.assertNotContains(self.client.get(reverse("accounts:orders")), f'href="{LIST}"')

    def test_new_is_refused(self):
        response = self.client.get(NEW, follow=True)
        self.assertRedirects(response, LIST)
        self.assertContains(response, "در حال حاضر فعال نیست")
        self.client.post(NEW, {"subject": "س", "text": "متن"})
        self.assertFalse(Ticket.objects.exists())

    def test_old_tickets_stay_readable_but_no_reply(self):
        ticket = make_ticket(self.customer, subject="گفتگوی قدیمی")
        self.assertContains(self.client.get(reverse("accounts:orders")), f'href="{LIST}"')
        listing = self.client.get(LIST)
        self.assertContains(listing, "گفتگوی قدیمی")
        self.assertNotContains(listing, NEW)
        page = self.client.get(ticket.get_absolute_url())
        self.assertNotContains(page, 'name="text"')
        self.client.post(ticket.get_absolute_url(), {"text": "سلام"})
        self.assertEqual(TicketMessage.objects.count(), 1)
