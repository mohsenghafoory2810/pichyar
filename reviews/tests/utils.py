from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalog.tests.utils import make_product
from reviews.models import Review

HTMX = {"HTTP_HX_REQUEST": "true"}


def make_customer(mobile="09121111111", **kwargs):
    return get_user_model().objects.create_user(mobile, **kwargs)


def make_review(product, user, rating=4, text="محصول خوبی بود و به‌موقع رسید.", status=Review.Status.APPROVED, **kwargs):
    return Review.objects.create(product=product, user=user, rating=rating, text=text, status=status, **kwargs)


class ReviewTestCase(TestCase):
    def setUp(self):
        self.client.cookies[settings.AGE_GATE_COOKIE] = "1"
        self.product = make_product("آریزونا")
        self.customer = make_customer()

    def submit_url(self, product=None):
        return reverse("reviews:submit", args=[(product or self.product).pk])

    def list_url(self, product=None):
        return reverse("reviews:list", args=[(product or self.product).pk])

    def post_review(self, data=None, htmx=True, product=None, **extra):
        payload = {"rating": "5", "title": "", "text": "عطر و طعم خوبی داشت، راضی بودم."}
        payload.update(data or {})
        return self.client.post(self.submit_url(product), payload, **(HTMX if htmx else {}), **extra)
