from django.conf import settings
from django.test import TestCase


class AgeGateTests(TestCase):
    def test_first_visit_shows_gate_as_overlay_without_hiding_the_page(self):
        response = self.client.get("/")
        self.assertContains(response, 'id="age-gate"')
        self.assertContains(response, "آیا بالای ۱۸ سال سن دارید؟")
        # The server never hides content: app.js makes the page inert while the overlay is shown.
        self.assertContains(response, '<div id="page" class="flex min-h-screen flex-col">')
        self.assertNotContains(response, "inert")
        self.assertNotContains(response, 'aria-hidden="true">')
        self.assertNotContains(response, "overflow-hidden")

    def test_confirm_sets_30_day_cookie_and_redirects_back(self):
        response = self.client.post("/age-check/", {"next": "/pages/about/"})
        self.assertRedirects(response, "/pages/about/", fetch_redirect_response=False)
        cookie = response.cookies[settings.AGE_GATE_COOKIE]
        self.assertEqual(cookie.value, "1")
        self.assertEqual(cookie["max-age"], 60 * 60 * 24 * 30)
        self.assertTrue(cookie["httponly"])

    def test_gate_hidden_after_confirmation(self):
        self.client.post("/age-check/", {"next": "/"})
        response = self.client.get("/")
        self.assertNotContains(response, 'id="age-gate"')
        self.assertNotContains(response, "inert")

    def test_confirm_rejects_external_redirect(self):
        response = self.client.post("/age-check/", {"next": "https://evil.example.com/"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_confirm_requires_post(self):
        self.assertEqual(self.client.get("/age-check/").status_code, 405)

    def test_leave_button_points_away(self):
        response = self.client.get("/")
        self.assertContains(response, f'href="{settings.AGE_GATE_EXIT_URL}"')


class AgeGateCrawlerTests(TestCase):
    """Without the cookie (first visit, or any crawler) the full content is in the raw HTML,
    and the HTML does not depend on the user agent."""

    GOOGLEBOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"

    def setUp(self):
        from catalog.models import Category
        from catalog.tests.utils import make_product

        self.product = make_product("دیویدوف آزمایشی", price=345_000, description="توضیح کامل محصول آزمایشی")
        self.category = Category.objects.get(slug="tobacco")

    @staticmethod
    def normalized(response):
        import re

        html = response.content.decode()
        return re.sub(r'(csrfmiddlewaretoken" value=|"X-CSRFToken": )"[^"]*"', r'\1""', html)

    def test_full_content_without_cookie(self):
        for url, texts in (
            (self.product.get_absolute_url(), ["<h1", "دیویدوف آزمایشی", "۳۴۵٬۰۰۰ تومان", "توضیح کامل محصول آزمایشی"]),
            (self.category.get_absolute_url(), ["<h1", self.category.name, "دیویدوف آزمایشی", "۳۴۵٬۰۰۰ تومان"]),
        ):
            response = self.client.get(url, HTTP_USER_AGENT=self.GOOGLEBOT)
            self.assertEqual(response.status_code, 200)
            for text in texts:
                self.assertContains(response, text)
            self.assertContains(response, 'id="age-gate"')
            self.assertNotContains(response, "inert")

    def test_same_html_for_every_user_agent(self):
        for url in ("/", self.product.get_absolute_url(), self.category.get_absolute_url()):
            bot = self.normalized(self.client.get(url, HTTP_USER_AGENT=self.GOOGLEBOT))
            browser = self.normalized(self.client.get(url, HTTP_USER_AGENT=self.BROWSER))
            self.assertEqual(bot, browser, url)

    def test_verified_visitor_sees_the_same_page_without_overlay(self):
        import re

        url = self.product.get_absolute_url()
        without_cookie = self.normalized(self.client.get(url))
        self.client.cookies[settings.AGE_GATE_COOKIE] = "1"
        with_cookie = self.normalized(self.client.get(url))
        gate = re.compile(r'<div id="age-gate".*?</form>\s*</div>\s*</div>\s*', re.S)
        squash = lambda html: re.sub(r"\s+", " ", html)  # noqa: E731
        self.assertEqual(squash(gate.sub("", without_cookie)), squash(with_cookie))
