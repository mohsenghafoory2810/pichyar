from contextlib import contextmanager
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import SiteSettings
from support import services


def make_customer(mobile="09121111111", **kwargs):
    return get_user_model().objects.create_user(mobile, **kwargs)


def make_ticket(user, subject="مشکل در سفارش", text="سفارش من هنوز نرسیده است.", **kwargs):
    return services.create_ticket(user, subject, text, **kwargs)


def update_settings(**fields):
    s = SiteSettings.load()
    for name, value in fields.items():
        setattr(s, name, value)
    s.save()
    return s


@contextmanager
def capture_sms():
    """Collects (mobile, template_key, context) of every SMS the support app sends."""
    sent = []

    def fake(mobile, key, context):
        sent.append((mobile, key, context))
        return True

    with mock.patch("support.services.send_sms", side_effect=fake):
        yield sent


class SupportTestCase(TestCase):
    def setUp(self):
        self.client.cookies[settings.AGE_GATE_COOKIE] = "1"
        self.customer = make_customer(name="سارا احمدی")
