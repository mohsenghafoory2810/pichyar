from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django_q.models import Schedule


class Command(BaseCommand):
    help = "Create or update the worker's recurring jobs (idempotent)."

    def handle(self, *args, **options):
        now = timezone.localtime()
        backup_at = timezone.make_aware(datetime.combine(now.date(), time(3, 30)))
        if backup_at <= now:
            backup_at += timedelta(days=1)

        Schedule.objects.update_or_create(
            name="daily-database-backup",
            defaults={
                "func": "core.tasks.backup_database",
                "schedule_type": Schedule.DAILY,
                "next_run": backup_at,
                "repeats": -1,
            },
        )
        Schedule.objects.update_or_create(
            name="worker-heartbeat",
            defaults={
                "func": "core.tasks.heartbeat",
                "schedule_type": Schedule.MINUTES,
                "minutes": 5,
                "next_run": now,
                "repeats": -1,
            },
        )
        Schedule.objects.update_or_create(
            name="sms-retry",
            defaults={
                "func": "notifications.tasks.retry_pending_sms",
                "schedule_type": Schedule.MINUTES,
                "minutes": 1,
                "next_run": now,
                "repeats": -1,
            },
        )
        self.stdout.write(self.style.SUCCESS("Schedules ready (daily backup 03:30 Tehran time, SMS retries every minute)."))
