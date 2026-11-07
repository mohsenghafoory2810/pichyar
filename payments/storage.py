import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateStorage(FileSystemStorage):
    """Files outside MEDIA_ROOT (Caddy serves /media/ publicly), e.g. card-to-card receipts.
    They have no public URL; staff open them through payments:receipt."""

    @property
    def base_location(self):
        return settings.PRIVATE_MEDIA_ROOT

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        return None


private_storage = PrivateStorage()
