from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.backup import list_backups, restore_backup


class Command(BaseCommand):
    help = "Restore the database from a backup. Stop the app and worker first."

    def add_arguments(self, parser):
        parser.add_argument("backup", nargs="?", help="File name inside the backups folder, or a full path.")
        parser.add_argument("--list", action="store_true", help="Only list available backups.")

    def handle(self, *args, **options):
        backups = list_backups()
        if options["list"] or not options["backup"]:
            for b in backups:
                self.stdout.write(b.name)
            if not backups:
                self.stdout.write("No backups found.")
            return
        path = Path(options["backup"])
        if not path.is_absolute():
            path = Path(settings.BACKUP_DIR) / path
        if not path.exists():
            raise CommandError(f"Backup not found: {path}")
        restore_backup(path)
        self.stdout.write(self.style.SUCCESS(f"Database restored from {path.name}"))
