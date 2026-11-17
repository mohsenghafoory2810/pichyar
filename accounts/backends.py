from django.contrib.auth.backends import ModelBackend


class SMSCodeBackend(ModelBackend):
    """Marks sessions started with the storefront SMS-code login (accounts.views.login_view).
    It never authenticates a password, and core.admin_site refuses such sessions, so the
    admin always needs mobile + password (+ the 2FA code when it is on)."""

    def authenticate(self, request, **credentials):
        return None


class StorefrontPasswordBackend(ModelBackend):
    """Marks sessions started with the storefront password login (accounts.password_login,
    which checks the password itself, with its own lockout). Like SMSCodeBackend it
    authenticates nothing through django.contrib.auth.authenticate(), and the admin refuses
    such sessions: the admin login keeps its own 2FA and django-axes protection."""

    def authenticate(self, request, **credentials):
        return None
