from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalog.tests.utils import make_product
from reviews.models import Review

from .utils import make_customer, make_review

S = Review.Status


class ReviewAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("09120000001", password="pass")

    def setUp(self):
        self.client.force_login(self.admin)
        self.product = make_product("آریزونا")
        self.r1 = make_review(self.product, make_customer("09121111111"), status=S.PENDING, text="نظر اول برای آزمون")
        self.r2 = make_review(self.product, make_customer("09122222222"), status=S.PENDING, text="نظر دوم برای آزمون")
        self.changelist = reverse("admin:reviews_review_changelist")

    def test_changelist_and_filters(self):
        self.assertContains(self.client.get(self.changelist), "نظر اول برای آزمون")
        response = self.client.get(self.changelist, {"status__exact": "pending", "q": "۰۹۱۲۱۱۱"})
        self.assertContains(response, "نظر اول برای آزمون")
        self.assertNotContains(response, "نظر دوم برای آزمون")

    def test_change_page_and_reply(self):
        url = reverse("admin:reviews_review_change", args=[self.r1.pk])
        self.assertContains(self.client.get(url), "پاسخ فروشگاه")
        response = self.client.post(url, {"status": S.APPROVED, "admin_reply": "سپاس از نظر شما"})
        self.assertEqual(response.status_code, 302)
        self.r1.refresh_from_db()
        self.assertEqual((self.r1.status, self.r1.admin_reply), (S.APPROVED, "سپاس از نظر شما"))
        self.assertEqual(self.r1.text, "نظر اول برای آزمون")

    def test_no_add(self):
        self.assertEqual(self.client.get(reverse("admin:reviews_review_add")).status_code, 403)

    def bulk(self, action):
        return self.client.post(
            self.changelist, {"action": action, "_selected_action": [self.r1.pk, self.r2.pk]}, follow=True
        )

    def test_bulk_approve_and_reject(self):
        self.assertContains(self.bulk("approve_selected"), "۲ نظر تأیید شد")
        self.assertEqual(set(Review.objects.values_list("status", flat=True)), {S.APPROVED})
        self.bulk("reject_selected")
        self.assertEqual(set(Review.objects.values_list("status", flat=True)), {S.REJECTED})

    def test_dashboard_pending_count(self):
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.context["pending_reviews_count"], 2)
        self.assertContains(response, "نظرهای در انتظار بررسی")
        self.assertContains(response, f"{self.changelist}?status__exact=pending")
