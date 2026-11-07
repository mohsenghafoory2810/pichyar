"""Payment gateways. The active one and its credentials are chosen in SiteSettings."""

from django.conf import settings

from . import registry
from .base import BaseGateway, GatewayError, GatewayRedirect, VerifyResult
from .zarinpal import ZarinpalGateway  # noqa: F401  (registers itself)

__all__ = ["BaseGateway", "GatewayError", "GatewayRedirect", "VerifyResult", "get_gateway", "registry"]


def get_gateway(site_settings, key=None):
    """An instance of the gateway `key` (default: the one selected in SiteSettings)."""
    cls = registry.get(key or site_settings.payment_gateway)
    return cls.from_settings(site_settings, timeout=getattr(settings, "PAYMENT_GATEWAY_TIMEOUT", 15))
