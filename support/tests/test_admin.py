from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from support.models import Ticket

from .utils import capture_sms, make_customer, make_ticket

S = Ticket.Status


class TicketAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("09120000001", password="pass", name="مدیر")

    def setUp(self):
        self.client.force_login(self.admin)
        self.customer = make_customer("09121111111", name="سارا")
        self.t1 = make_ticket(self.customer, subject="موضوع اول", text="متن اول <b>پررنگ</b>\nخط دوم")
        self.t2 = make_ticket(make_customer("09122222222"), subject="موضوع دوم", text="متن دوم")
        self.changelist = reverse("admin:support_ticket_changelist")
        self.change = reverse("admin:support_ticket_change", args=[self.t1.pk])

    def test_changelist_search_and_filter(self):
        self.assertContains(self.client.get(self.changelist), "موضوع اول")
        response = self.client.get(self.changelist, {"status__exact": "waiting", "q": "۰۹۱۲۱۱۱"})
        self.assertContains(response, "موضوع اول")
        self.assertNotContains(response, "موضوع دوم")
        response = self.client.get(self.changelist, {"q": "پررنگ"})  # message text
        self.assertContains(response, "موضوع اول")
        self.assertNotContains(response, "موضوع دوم")

    def test_waiting_first(self):
        Ticket.objects.filter(pk=self.t2.pk).update(status=S.ANSWERED)
        t3 = make_ticket(self.customer, subject="موضوع سوم")
        Ticket.objects.filter(pk=t3.pk).update(status=S.CLOSED)
        response = self.client.get(self.changelist)
        self.assertEqual(response.context["cl"].result_list[0].pk, self.t1.pk)

    def test_no_add(self):
        self.assertEqual(self.client.get(reverse("admin:support_ticket_add")).status_code, 403)

    def test_change_page_shows_escaped_conversation(self):
        response = self.client.get(self.change)
        self.assertContains(response, "پاسخ پشتیبانی")
        self.assertContains(response, "متن اول &lt;b&gt;پررنگ&lt;/b&gt;<br>خط دوم")
        self.assertNotContains(response, "<b>پررنگ</b>")

    def test_reply(self):
        with capture_sms() as sent, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.change, {"status": S.WAITING, "reply": "  سفارش شما ارسال شد.  "})
        self.assertEqual(response.status_code, 302)
        self.t1.refresh_from_db()
        self.assertEqual((self.t1.status, self.t1.customer_unread), (S.ANSWERED, True))
        reply = self.t1.messages.last()
        self.assertEqual((reply.text, reply.is_staff_reply, reply.author), ("سفارش شما ارسال شد.", True, self.admin))
        self.assertEqual(sent, [("09121111111", "support_reply", {"ticket_subject": "موضوع اول"})])
        self.assertContains(self.client.get(self.change), "پشتیبانی (مدیر)")

    def test_reply_and_close(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.change, {"status": S.CLOSED, "reply": "پایان گفتگو"})
        self.t1.refresh_from_db()
        self.assertEqual((self.t1.status, self.t1.messages.count()), (S.CLOSED, 2))

    def test_status_change_without_reply(self):
        with capture_sms() as sent, self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.change, {"status": S.CLOSED, "reply": ""})
        self.t1.refresh_from_db()
        self.assertEqual((self.t1.status, self.t1.messages.count(), self.t1.customer_unread), (S.CLOSED, 1, False))
        self.assertEqual(sent, [])

    def test_bulk_close(self):
        response = self.client.post(
            self.changelist, {"action": "close_selected", "_selected_action": [self.t1.pk, self.t2.pk]}, follow=True
        )
        self.assertContains(response, "۲ گفتگو بسته شد")
        self.assertEqual(set(Ticket.objects.values_list("status", flat=True)), {S.CLOSED})

    def test_dashboard_waiting_count(self):
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.context["waiting_tickets_count"], 2)
        self.assertContains(response, "پیام‌های پشتیبانی بی‌پاسخ")
        self.assertContains(response, f"{self.changelist}?status__exact=waiting")

    def test_sidebar_group(self):
        groups = [g["name"] for g in self.client.get(reverse("admin:index")).context["app_list"]]
        self.assertEqual(groups[:2], ["فروش", "پشتیبانی"])
