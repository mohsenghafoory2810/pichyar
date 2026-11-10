from django.conf import settings
from django.shortcuts import render

from .utils import get_site_settings


class MaintenanceModeMiddleware:
    """While maintenance mode is on, everyone except staff gets a 503 page.
    Admin, health check, favicon, static and media stay reachable."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.exempt_prefixes = (
            "/" + settings.ADMIN_URL,
            "/health",
            "/favicon.ico",
            settings.STATIC_URL,
            settings.MEDIA_URL,
        )

    def __call__(self, request):
        if not request.path.startswith(self.exempt_prefixes):
            site_settings = get_site_settings(request)
            if site_settings.maintenance_mode and not request.user.is_staff:
                response = render(request, "maintenance.html", {"site_settings": site_settings}, status=503)
                response["Retry-After"] = "3600"
                response._has_been_logged = True  # an intentional 503, not an error worth logging
                return response
        return self.get_response(request)


class SecurityHeadersMiddleware:
    """Content-Security-Policy and Permissions-Policy on every response (the other
    security headers come from Django's SecurityMiddleware, see config/settings/prod.py)."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.csp = getattr(settings, "CONTENT_SECURITY_POLICY", "")
        self.permissions = getattr(settings, "PERMISSIONS_POLICY", "")

    def __call__(self, request):
        response = self.get_response(request)
        if self.csp:
            response.headers.setdefault("Content-Security-Policy", self.csp)
        if self.permissions:
            response.headers.setdefault("Permissions-Policy", self.permissions)
        return response
