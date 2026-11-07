from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .images import create_variants, delete_variants
from .models import ProductImage


@receiver(post_delete, sender=ProductImage)
def delete_image_file(sender, instance, **kwargs):
    """Remove the file (and its smaller variants) once the deletion is committed (not if it is rolled back)."""
    if instance.image:
        storage, name = instance.image.storage, instance.image.name

        def cleanup():
            storage.delete(name)
            delete_variants(storage, name)

        transaction.on_commit(cleanup)


@receiver(pre_save, sender=ProductImage)
def remember_old_image(sender, instance, raw=False, **kwargs):
    instance._old_image_name = None
    if not raw and instance.pk:
        instance._old_image_name = sender.objects.filter(pk=instance.pk).values_list("image", flat=True).first()


@receiver(post_save, sender=ProductImage)
def make_variants(sender, instance, raw=False, **kwargs):
    """400/800 px WebP copies for srcset; a replaced image's variants are removed."""
    if raw or not instance.image:
        return
    old = getattr(instance, "_old_image_name", None)
    if old and old != instance.image.name:
        storage = instance.image.storage
        transaction.on_commit(lambda: delete_variants(storage, old))
    create_variants(instance.image)
