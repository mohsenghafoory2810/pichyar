from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalog.tests.utils import make_product
from core.models import SiteSettings
from notifications import services
from notifications.models import SMSLog, SMSTemplate
from orders.models import DiscountCode, DiscountType, GiftPoolItem


class AdminPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("09120000001", email="boss@example.com", password="pass")

    def setUp(self):
        self.client.force_login(self.admin)
        self.code = DiscountCode.objects.create(code="SALE", kind=DiscountType.PERCENT, value=10, max_discount=50_000)
        self.gift = GiftPoolItem.objects.create(product=make_product("آریزونا"), gift_stock=3)
        services.send_sms("09121111111", "otp", {"code": "12345"})

    def test_pages_render(self):
        urls = [
            reverse("admin:orders_discountcode_changelist"),
            reverse("admin:orders_discountcode_add"),
            reverse("admin:orders_discountcode_change", args=[self.code.pk]),
            reverse("admin:orders_giftpoolitem_changelist"),
            reverse("admin:orders_giftpoolitem_add"),
            reverse("admin:notifications_smstemplate_changelist"),
            reverse("admin:notifications_smstemplate_change", args=[SMSTemplate.objects.get(key="shipped").pk]),
            reverse("admin:notifications_smslog_changelist"),
            reverse("admin:notifications_smslog_change", args=[SMSLog.objects.get().pk]),
            reverse("admin:core_sitesettings_change", args=[SiteSettings.load().pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_create_discount_code_with_persian_error(self):
        url = reverse("admin:orders_discountcode_add")
        data = {"code": "sale", "kind": "fixed", "value": "1000", "min_order_amount": "0", "per_user_limit": "1"}
        response = self.client.post(url, data)
        self.assertContains(response, "قبلاً ساخته شده")
        data["code"] = "new-code"
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertTrue(DiscountCode.objects.filter(code="NEW-CODE").exists())

    def test_templates_cannot_be_added_or_deleted(self):
        response = self.client.get(reverse("admin:notifications_smstemplate_changelist"))
        self.assertNotContains(response, reverse("admin:notifications_smstemplate_add"))
