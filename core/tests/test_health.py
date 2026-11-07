from unittest import mock

from django.test import TestCase


class HealthTests(TestCase):
    def test_ok(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertIn("no-cache", response["Cache-Control"])

    def test_database_down_returns_503(self):
        with mock.patch("core.views.connection.cursor", side_effect=Exception("db down")):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "error")

    def test_reachable_during_maintenance(self):
        from core.models import SiteSettings

        s = SiteSettings.load()
        s.maintenance_mode = True
        s.save()
        self.assertEqual(self.client.get("/health").status_code, 200)
