import json
import re
from datetime import timedelta

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from catalog.models import Category
from catalog.tests.utils import make_product  # noqa: F401  (re-exported for the tests)

LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def jsonld_blocks(response):
    """Every ld+json block of a response, parsed (fails the test if one is not valid JSON)."""
    return [json.loads(raw) for raw in LD_RE.findall(response.content.decode())]


def jsonld_of_type(response, type_):
    return [b for b in jsonld_blocks(response) if b.get("@type") == type_]


def make_article(title="مقالهٔ آزمایشی", published=True, **kwargs):
    from blog.models import Article

    if published:
        kwargs.setdefault("status", Article.Status.PUBLISHED)
        kwargs.setdefault("published_at", timezone.now() - timedelta(hours=1))
    else:
        kwargs.setdefault("status", Article.Status.DRAFT)
    return Article.objects.create(title=title, **kwargs)


def make_customer(mobile="09121111111", **kwargs):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(mobile, **kwargs)


class SEOTestCase(TestCase):
    def setUp(self):
        self.client.cookies[settings.AGE_GATE_COOKIE] = "1"
        self.tobacco = Category.objects.get(slug="tobacco")
        self.accessories = Category.objects.get(slug="accessories")
        self.pipes = Category.objects.get(slug="pipes")

    def html(self, url, **kwargs):
        response = self.client.get(url, **kwargs)
        self.assertEqual(response.status_code, 200, url)
        return response
