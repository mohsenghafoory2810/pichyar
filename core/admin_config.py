from django.contrib.admin.apps import AdminConfig


class ShopAdminConfig(AdminConfig):
    """django.contrib.admin with the shop's AdminSite (dashboard, sidebar groups, 2FA login)."""

    default_site = "core.admin_site.ShopAdminSite"
