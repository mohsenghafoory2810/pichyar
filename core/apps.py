from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "هسته و تنظیمات سایت"

    def ready(self):
        from django.db.models.signals import post_migrate

        from . import signals  # noqa: F401
        from .i18n import persian_permission_names, rename_third_party

        rename_third_party()
        post_migrate.connect(persian_permission_names, dispatch_uid="core.persian_permission_names")
