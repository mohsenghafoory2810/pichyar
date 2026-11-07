from django.core.management.base import BaseCommand, CommandError
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import User
from accounts.validators import normalize_mobile


class Command(BaseCommand):
    help = "Turn two-step login off for one admin (e.g. after losing the phone)."

    def add_arguments(self, parser):
        parser.add_argument("mobile")

    def handle(self, mobile, **options):
        try:
            user = User.objects.get(mobile=normalize_mobile(mobile))
        except Exception:
            raise CommandError(f"No user with mobile {mobile}") from None
        deleted, _ = TOTPDevice.objects.filter(user=user).delete()
        self.stdout.write(self.style.SUCCESS(f"Two-step login is off for {user.mobile} ({deleted} device(s) removed)."))
