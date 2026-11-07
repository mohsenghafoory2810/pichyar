from django.core.management.base import BaseCommand

from core.backup import create_backup


class Command(BaseCommand):
    help = "Create a SQLite backup now (keeps the newest BACKUP_KEEP files)."

    def handle(self, *args, **options):
        path = create_backup()
        self.stdout.write(self.style.SUCCESS(f"Backup created: {path}"))
