from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from catalog.tests.utils import make_product
from orders import reports
from orders.models import Order

from .utils import capture_sms, configure_payments, make_order


def tehran(*args):
    return timezone.make_aware(datetime(*args))


class PeriodTests(TestCase):
    def test_week_starts_on_saturday_and_month_is_jalali(self):
        now = tehran(2026, 11, 11, 15, 0)  # Wednesday 20 Aban 1405
        start, end = reports.period_bounds("today", now)
        self.assertEqual((start, end), (tehran(2026, 11, 11), tehran(2026, 11, 12)))
        start, _ = reports.period_bounds("week", now)
        self.assertEqual(start, tehran(2026, 11, 7))  # Saturday
        self.assertEqual(start.weekday(), 5)
        start, _ = reports.period_bounds("month", now)
        self.assertEqual(start, tehran(2026, 10, 23))  # 1 Aban 1405
        start, end = reports.period_bounds("last_month", now)
        self.assertEqual((start, end), (tehran(2026, 9, 23), tehran(2026, 10, 23)))  # Mehr 1405

    def test_saturday_is_its_own_week_start(self):
        start, _ = reports.period_bounds("week", tehran(2026, 11, 7, 0, 30))
        self.assertEqual(start, tehran(2026, 11, 7))


class SalesTests(TestCase):
    def setUp(self):
        configure_payments()
        self.p = make_product(price=1_000_000, stock=50)

    def paid_order(self, qty=1, paid_at=None):
        with capture_sms():
            order = make_order((self.p, qty), method="online")
            order.confirm_payment()
        if paid_at:
            Order.objects.filter(pk=order.pk).update(paid_at=paid_at)
        return order

    def test_summary_counts_confirmed_orders_only(self):
        a = self.paid_order(1)
        b = self.paid_order(2)
        with capture_sms():
            make_order((self.p, 5))  # unpaid: not a sale
        self.paid_order(3, paid_at=timezone.now() - timedelta(days=60))
        summary = {p.key: p for p in reports.sales_summary()}
        self.assertEqual(summary["today"].count, 2)
        self.assertEqual(summary["today"].amount, a.total + b.total)
        self.assertEqual(summary["month"].count, 2)
        with capture_sms():
            a.cancel()
        self.assertEqual({p.key: p for p in reports.sales_summary()}["today"].count, 1)

    def test_chart_has_one_bar_per_day(self):
        order = self.paid_order(2)
        self.paid_order(1, paid_at=timezone.now() - timedelta(days=3))
        chart = reports.sales_chart()
        self.assertEqual(len(chart["bars"]), reports.CHART_DAYS)
        today = chart["bars"][-1]
        self.assertEqual(today["amount"], order.total)
        self.assertEqual(chart["max"], order.total)
        self.assertGreater(today["h"], chart["bars"][-4]["h"])
        self.assertTrue(all(b["h"] == 0 for b in chart["bars"][:-4]))
        self.assertLess(today["x"], chart["bars"][0]["x"])  # right-to-left: today on the left


class DashboardPageTests(TestCase):
    def setUp(self):
        configure_payments()
        self.client.force_login(get_user_model().objects.create_superuser("09120000001", password="pass"))

    def test_empty_dashboard(self):
        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, "فروش امروز")
        self.assertContains(response, "سفارش پرداخت‌شده‌ای نبوده است")

    def test_dashboard_lists_actions_low_stock_and_chart(self):
        p = make_product("آریزونا", price=1_000_000, stock=50)
        low = make_product("کم‌موجود", stock=1, low_stock_threshold=3)
        make_product("ناموجود", stock=0)
        make_product("غیرفعال", stock=0, is_active=False)
        with capture_sms():
            waiting = make_order((p, 1))
            from payments.services import submit_card_transfer

            submit_card_transfer(waiting, "123456")
            to_ship = make_order((p, 2), method="online")
            to_ship.confirm_payment()
        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, waiting.number.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")))
        self.assertContains(response, to_ship.number.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")))
        self.assertContains(response, "?status__exact=awaiting_approval")
        self.assertContains(response, low.name)
        self.assertContains(response, "ناموجود")
        self.assertNotContains(response, "غیرفعال</a>")
        self.assertContains(response, '<svg viewBox="0 0 720 200"')
        self.assertContains(response, 'class="bar"')
        self.assertNotContains(response, "cdn")

    def test_sidebar_groups(self):
        response = self.client.get(reverse("admin:orders_order_changelist"))
        content = response.content.decode()
        groups = ["فروش", "محصولات", "محتوای سایت", "پیامک", "تنظیمات", "کاربران و امنیت"]
        positions = [content.find(f">{g}</a>") for g in groups]
        self.assertTrue(all(p > 0 for p in positions), positions)
        self.assertEqual(positions, sorted(positions))
        for label in ["مشتریان", "ورود دومرحله‌ای مدیران", "قفل‌های ورود به پنل"]:
            self.assertContains(response, label)
        self.assertNotContains(response, "Successful tasks")
