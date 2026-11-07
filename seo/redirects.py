"""Automatic 301 redirects when an object's URL (slug) changes.

register(Model) connects pre_save/post_save: if get_absolute_url() differs after the save,
a Redirect old → new is stored, earlier redirects to the old URL are re-pointed (no chains)
and a redirect *from* the new URL is removed (no loops).
"""

from urllib.parse import unquote

from django.apps import apps
from django.db.models.signals import post_save, pre_save

from .models import Redirect

DEFAULT_MODELS = [
    "catalog.Product",
    "catalog.Category",
    "core.StaticPage",
    "blog.Article",
    "blog.ArticleCategory",
]


def _path(url):
    return unquote(url) if url else url


def _remember_old_url(sender, instance, raw=False, **kwargs):
    instance._seo_old_url = None
    if raw or not instance.pk:
        return
    old = sender._default_manager.filter(pk=instance.pk).first()
    if old is not None:
        instance._seo_old_url = _path(old.get_absolute_url())


def _store_redirect(sender, instance, created=False, raw=False, **kwargs):
    old_url = getattr(instance, "_seo_old_url", None)
    if raw or created or not old_url:
        return
    new_url = _path(instance.get_absolute_url())
    if new_url == old_url:
        return
    Redirect.objects.filter(old_path=new_url).delete()
    Redirect.objects.filter(new_path=old_url).update(new_path=new_url)
    Redirect.objects.update_or_create(
        old_path=old_url, defaults={"new_path": new_url, "is_active": True, "is_automatic": True}
    )


def register(model):
    uid = f"seo-redirect-{model._meta.label_lower}"
    pre_save.connect(_remember_old_url, sender=model, dispatch_uid=f"{uid}-pre")
    post_save.connect(_store_redirect, sender=model, dispatch_uid=f"{uid}-post")


def connect_default_models():
    for label in DEFAULT_MODELS:
        try:
            register(apps.get_model(label))
        except LookupError:
            pass
