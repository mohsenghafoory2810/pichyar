"""SMS providers. The active one, its API key and sender line are chosen in SiteSettings.

Adding a provider (e.g. Melipayamak, SMS.ir): one new module with a BaseSMSProvider
subclass decorated with @registry.register, imported below. It then appears in SiteSettings.
"""

import logging

from django.conf import settings

from . import registry
from .base import BaseSMSProvider, SMSError, SMSResult
from .console import ConsoleProvider
from .kavenegar import KavenegarProvider  # noqa: F401  (registers itself)

__all__ = ["BaseSMSProvider", "ConsoleProvider", "SMSError", "SMSResult", "get_provider", "registry"]

logger = logging.getLogger("notifications.sms")


def get_provider(site_settings):
    """The provider selected in SiteSettings, or console mode while it has no API key."""
    timeout = getattr(settings, "SMS_PROVIDER_TIMEOUT", 10)
    try:
        cls = registry.get(site_settings.sms_provider)
    except LookupError:
        logger.warning("Unknown SMS provider %r; using console mode", site_settings.sms_provider)
        cls = ConsoleProvider
    if cls.needs_api_key and not site_settings.sms_api_key.strip():
        cls = ConsoleProvider
    return cls.from_settings(site_settings, timeout=timeout)
