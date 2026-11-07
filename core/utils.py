import ipaddress

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

from .models import SiteSettings


def get_site_settings(request=None):
    """SiteSettings, loaded at most once per request."""
    if request is None:
        return SiteSettings.load()
    if not hasattr(request, "_site_settings"):
        request._site_settings = SiteSettings.load()
    return request._site_settings


def is_age_verified(request):
    return request.COOKIES.get(settings.AGE_GATE_COOKIE) == "1"


def client_ip(request):
    """Visitor IP. Behind Caddy (USE_X_FORWARDED_FOR) the last X-Forwarded-For entry is
    the address Caddy itself saw, so a client can't spoof it."""
    ip = request.META.get("REMOTE_ADDR", "")
    if settings.USE_X_FORWARDED_FOR:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            ip = forwarded.split(",")[-1].strip()
    try:
        return str(ipaddress.ip_address(ip))
    except ValueError:
        return None


def is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def htmx_redirect(request, url):
    """A full-page redirect, also from inside an HTMX request."""
    if is_htmx(request):
        response = HttpResponse(status=204)
        response["HX-Redirect"] = url
        return response
    return redirect(url)


def safe_next_url(request, default="/"):
    url = request.POST.get("next") or request.GET.get("next") or ""
    if url and url_has_allowed_host_and_scheme(url, {request.get_host()}, require_https=request.is_secure()):
        return url
    return default
