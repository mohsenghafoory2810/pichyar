from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import SiteSettings


class MaintenanceModeTests(TestCase):
    def setUp(self):
        s = SiteSettings.load()
        s.maintenance_mode = True
        s.maintenance_message = "تا ساعت ۵ برمی‌گردیم"
        s.save()

    def test_visitors_get_503(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "تا ساعت ۵ برمی‌گردیم", status_code=503)
        self.assertEqual(response["Retry-After"], "3600")

    def test_staff_can_browse(self):
        staff = get_user_model().objects.create_user("09120000001", password="x", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_admin_login_reachable(self):
        response = self.client.get(f"/{settings.ADMIN_URL}login/")
        self.assertEqual(response.status_code, 200)

    def test_off_means_normal_site(self):
        s = SiteSettings.load()
        s.maintenance_mode = False
        s.save()
        self.assertEqual(self.client.get("/").status_code, 200)
