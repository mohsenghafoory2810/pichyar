from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils.encoding import iri_to_uri

from seo.models import Redirect

from .utils import SEOTestCase, make_product


class SlugChangeRedirectTests(SEOTestCase):
    def test_product_slug_change(self):
        p = make_product("قدیمی")
        old = p.get_absolute_url()
        p.slug = "جدید"
        p.save()
        response = self.client.get(old)
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], iri_to_uri("/p/جدید/"))
        self.assertEqual(self.client.get(p.get_absolute_url()).status_code, 200)

    def test_category_slug_change_keeps_query(self):
        old = self.pipes.get_absolute_url()
        self.pipes.slug = "pipes-new"
        self.pipes.save()
        response = self.client.get(old, {"page": 2})
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "/c/pipes-new/?page=2")

    def test_chain_is_collapsed(self):
        p = make_product("الف", slug="a")
        p.slug = "b"
        p.save()
        p.slug = "c"
        p.save()
        response = self.client.get("/p/a/")
        self.assertEqual(response["Location"], "/p/c/")
        self.assertEqual(self.client.get("/p/b/")["Location"], "/p/c/")

    def test_manual_redirect_from_admin(self):
        admin = get_user_model().objects.create_superuser("09120000000", "pass-12345")
        self.client.force_login(admin)
        response = self.client.post(
            reverse("admin:seo_redirect_add"), {"old_path": "/old-page/", "new_path": "/pages/about/", "is_active": "on"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Redirect.objects.filter(old_path="/old-page/").exists())
        response = self.client.get("/old-page/")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "/pages/about/")
        self.assertEqual(Redirect.objects.get(old_path="/old-page/").hits, 1)
