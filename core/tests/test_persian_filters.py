from datetime import date, datetime, timezone as dt_timezone

from django.template import Context, Template
from django.test import SimpleTestCase

from core import persian


class PersianFilterTests(SimpleTestCase):
    def render(self, tpl, **ctx):
        return Template(tpl).render(Context(ctx))

    def test_fa_digits(self):
        self.assertEqual(persian.fa_digits("Order 1290"), "Order ۱۲۹۰")
        self.assertEqual(persian.fa_digits("٤٥"), "۴۵")  # Arabic-Indic -> Persian
        self.assertEqual(persian.fa_digits(None), "")

    def test_toman(self):
        self.assertEqual(persian.toman(1250000), "۱٬۲۵۰٬۰۰۰ تومان")
        self.assertEqual(persian.toman(0), "۰ تومان")
        self.assertEqual(persian.toman(999), "۹۹۹ تومان")
        self.assertEqual(persian.toman("45000"), "۴۵٬۰۰۰ تومان")
        self.assertEqual(persian.toman(1999.5), "۲٬۰۰۰ تومان")
        self.assertEqual(persian.toman(None), "")
        self.assertEqual(persian.toman("abc"), "")

    def test_template_filters_are_builtin(self):
        out = self.render("{{ p|toman }}|{{ n|fa_number }}|{{ s|fa_digits }}", p=89000, n=1234567, s="09121234567")
        self.assertEqual(out, "۸۹٬۰۰۰ تومان|۱٬۲۳۴٬۵۶۷|۰۹۱۲۱۲۳۴۵۶۷")

    def test_jalali_date(self):
        self.assertEqual(self.render("{{ d|jdate }}", d=date(2024, 3, 20)), "۱۴۰۳/۰۱/۰۱")
        self.assertEqual(self.render('{{ d|jdate:"%d %B %Y" }}', d=date(2024, 3, 20)), "۰۱ فروردین ۱۴۰۳")

    def test_jalali_datetime_uses_tehran_time(self):
        # 2024-03-19 21:00 UTC is 2024-03-20 00:30 in Tehran (first day of 1403).
        dt = datetime(2024, 3, 19, 21, 0, tzinfo=dt_timezone.utc)
        self.assertEqual(self.render("{{ d|jdatetime }}", d=dt), "۱۴۰۳/۰۱/۰۱ - ۰۰:۳۰")

    def test_jalali_empty(self):
        self.assertEqual(self.render("{{ d|jdate }}", d=None), "")
