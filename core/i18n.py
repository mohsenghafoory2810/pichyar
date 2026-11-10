"""Persian names the locale/ .po files cannot provide.

- Third-party apps and models whose names are plain English strings, not gettext calls (shown in
  admin breadcrumbs, page titles and the "0 TOTP devices" counter).
- Permission names: Django stores "Can add <model>" in English in the database when it creates them,
  so the permission picker of users and groups showed English. After every migrate they are renamed
  to e.g. «افزودن سفارش».
"""

from django.apps import apps as global_apps
from django.db import DEFAULT_DB_ALIAS
from django.utils import translation

APP_NAMES = {
    "axes": "قفل‌های ورود",
    "otp_totp": "ورود دومرحله‌ای",
}

MODEL_NAMES = {
    ("otp_totp", "totpdevice"): ("دستگاه ورود دومرحله‌ای", "دستگاه‌های ورود دومرحله‌ای"),
}

PERMISSION_ACTIONS = {"add": "افزودن", "change": "ویرایش", "delete": "حذف", "view": "مشاهده"}


def rename_third_party():
    """Set the Persian names on the app configs and model options (no migration: Meta is untouched)."""
    for label, name in APP_NAMES.items():
        try:
            global_apps.get_app_config(label).verbose_name = name
        except LookupError:
            pass
    for (label, model_name), (singular, plural) in MODEL_NAMES.items():
        try:
            opts = global_apps.get_model(label, model_name)._meta
        except LookupError:
            continue
        opts.verbose_name = singular
        opts.verbose_name_plural = plural


def persian_permission_names(sender, app_config=None, using=DEFAULT_DB_ALIAS, **kwargs):
    """post_migrate: rename the default permissions of app_config's models to Persian.

    Runs after django.contrib.auth's create_permissions for the same app (auth connects first).
    Custom permissions (Meta.permissions) keep the name they were given.
    """
    if app_config is None or app_config.models_module is None:
        return
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    with translation.override("fa"):
        for model in app_config.get_models():
            opts = model._meta
            content_type = ContentType.objects.db_manager(using).get_for_model(model, for_concrete_model=False)
            verbose_name = str(opts.verbose_name)
            for action in opts.default_permissions:
                if action not in PERMISSION_ACTIONS:
                    continue
                name = f"{PERMISSION_ACTIONS[action]} {verbose_name}"[:255]
                Permission.objects.using(using).filter(
                    content_type=content_type, codename=f"{action}_{opts.model_name}"
                ).exclude(name=name).update(name=name)
