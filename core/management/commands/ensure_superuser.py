import os

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand

from accounts.validators import normalize_mobile


class Command(BaseCommand):
    help = "Create the first superuser from DJANGO_SUPERUSER_MOBILE / DJANGO_SUPERUSER_PASSWORD if no superuser exists."

    def handle(self, *args, **options):
        User = get_user_model()
        if User.objects.filter(is_superuser=True).exists():
            return
        # DJANGO_SUPERUSER_USERNAME is the old name of the setting (before the mobile became the username).
        mobile = os.environ.get("DJANGO_SUPERUSER_MOBILE") or os.environ.get("DJANGO_SUPERUSER_USERNAME")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        if not mobile or not password:
            self.stdout.write("No superuser yet; set DJANGO_SUPERUSER_MOBILE and DJANGO_SUPERUSER_PASSWORD in .env.")
            return
        try:
            mobile = normalize_mobile(mobile)
        except ValidationError:
            self.stdout.write(self.style.ERROR("DJANGO_SUPERUSER_MOBILE must be a mobile number like 09123456789."))
            return
        User.objects.create_superuser(mobile, password=password, email=os.environ.get("DJANGO_SUPERUSER_EMAIL", ""))
        self.stdout.write(self.style.SUCCESS(f"Superuser '{mobile}' created."))
