from django.contrib.auth.backends import ModelBackend


class SMSCodeBackend(ModelBackend):
    """Marks sessions started with the storefront SMS-code login (accounts.views.login_view).
    It never authenticates a password, and core.admin_site refuses such sessions, so the
    admin always needs mobile + password (+ the 2FA code when it is on)."""

    def authenticate(self, request, **credentials):
        return None
