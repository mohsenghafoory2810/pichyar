from django.test import override_settings

from notifications.models import SMSLog
from support import services
from support.models import Ticket, TicketMessage

from .utils import SupportTestCase, capture_sms, make_customer, make_ticket, update_settings

S = Ticket.Status


class ServiceTests(SupportTestCase):
    def test_create_ticket(self):
        ticket = make_ticket(self.customer)
        self.assertEqual((ticket.status, ticket.customer_unread), (S.WAITING, False))
        message = ticket.messages.get()
        self.assertEqual((message.author, message.is_staff_reply), (self.customer, False))
        self.assertEqual(ticket.last_message_at, message.created_at)

    def test_reply_flow(self):
        ticket = make_ticket(self.customer)
        staff = make_customer("09120000001", is_staff=True)
        services.add_staff_reply(ticket, staff, "بررسی شد.")
        ticket.refresh_from_db()
        self.assertEqual((ticket.status, ticket.customer_unread), (S.ANSWERED, True))
        services.mark_read(ticket)
        ticket.refresh_from_db()
        self.assertFalse(ticket.customer_unread)
        services.add_customer_message(ticket, self.customer, "سپاس، یک پرسش دیگر هم دارم.")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, S.WAITING)
        self.assertEqual(ticket.messages.count(), 3)
        services.add_staff_reply(ticket, staff, "پایان.", close=True)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, S.CLOSED)

    def test_tab_info(self):
        self.assertEqual(services.tab_info(self.customer), {"tickets": 0, "unread": 0})
        a = make_ticket(self.customer)
        make_ticket(self.customer)
        services.add_staff_reply(a, None, "پاسخ")
        self.assertEqual(services.tab_info(self.customer), {"tickets": 2, "unread": 1})

    @override_settings(SUPPORT_TICKETS_HOURLY_LIMIT=2, SUPPORT_MESSAGES_HOURLY_LIMIT=3)
    def test_rate_limits(self):
        ticket = make_ticket(self.customer)
        self.assertIsNone(services.rate_limit_error(self.customer, new_ticket=True))
        make_ticket(self.customer)
        self.assertEqual(services.rate_limit_error(self.customer, new_ticket=True), services.RATE_LIMIT_ERROR)
        self.assertIsNone(services.rate_limit_error(self.customer))
        services.add_staff_reply(ticket, None, "پاسخ پشتیبانی شمرده نمی‌شود")
        self.assertIsNone(services.rate_limit_error(self.customer))
        services.add_customer_message(ticket, self.customer, "پیام سوم")
        self.assertEqual(services.rate_limit_error(self.customer), services.RATE_LIMIT_ERROR)
        self.assertIsNone(services.rate_limit_error(make_customer("09122222222")))


class NotificationTests(SupportTestCase):
    def setUp(self):
        super().setUp()
        update_settings(admin_sms_numbers="09121234567\n09127654321")

    def test_admin_sms_on_new_ticket_and_message(self):
        with capture_sms() as sent, self.captureOnCommitCallbacks(execute=True):
            ticket = make_ticket(self.customer, text="متن   طولانی\nپیام")
        self.assertEqual([(m, k) for m, k, _ in sent], [("09121234567", "admin_support_message"), ("09127654321", "admin_support_message")])
        self.assertEqual(
            sent[0][2],
            {"customer": "سارا احمدی (09121111111)", "ticket_subject": "مشکل در سفارش", "text_preview": "متن طولانی پیام"},
        )
        with capture_sms() as sent, self.captureOnCommitCallbacks(execute=True):
            services.add_customer_message(ticket, self.customer, "پیگیری")
        self.assertEqual(len(sent), 2)

    def test_admin_sms_disabled(self):
        update_settings(support_admin_sms_enabled=False)
        with capture_sms() as sent, self.captureOnCommitCallbacks(execute=True):
            make_ticket(self.customer)
        self.assertEqual(sent, [])

    def test_reply_sms_to_customer(self):
        ticket = make_ticket(self.customer)
        with capture_sms() as sent, self.captureOnCommitCallbacks(execute=True):
            services.add_staff_reply(ticket, None, "پاسخ")
        self.assertEqual(sent, [("09121111111", "support_reply", {"ticket_subject": "مشکل در سفارش"})])

    def test_reply_sms_disabled(self):
        update_settings(support_reply_sms_enabled=False)
        ticket = make_ticket(self.customer)
        with capture_sms() as sent, self.captureOnCommitCallbacks(execute=True):
            services.add_staff_reply(ticket, None, "پاسخ")
        self.assertEqual(sent, [])

    def test_sms_is_logged_with_seeded_template(self):
        # Console provider (no API key): the real send_sms writes an SMSLog row.
        ticket = make_ticket(self.customer)
        with self.captureOnCommitCallbacks(execute=True):
            services.add_staff_reply(ticket, None, "پاسخ")
        log = SMSLog.objects.get(template_key="support_reply")
        self.assertEqual(log.mobile, "09121111111")
        self.assertIn("پاسخ پیام شما", log.text)

    def test_nothing_sent_before_commit(self):
        with capture_sms() as sent:
            make_ticket(self.customer)
        self.assertEqual(sent, [])
        self.assertEqual(TicketMessage.objects.count(), 1)
