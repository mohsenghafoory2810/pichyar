"""SQLite backup/restore using SQLite's online backup API (same as the `.backup` CLI command).

It is safe to run while the site is serving traffic."""

import logging
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import connections

logger = logging.getLogger(__name__)

BACKUP_PREFIX = "db-"
BACKUP_SUFFIX = ".sqlite3"


def _db_path() -> Path:
    db = settings.DATABASES["default"]
    if db["ENGINE"] != "django.db.backends.sqlite3":
        raise RuntimeError("Backups here only support SQLite; use pg_dump for PostgreSQL.")
    return Path(db["NAME"])


def list_backups(backup_dir: Path | None = None) -> list[Path]:
    backup_dir = Path(backup_dir or settings.BACKUP_DIR)
    return sorted(backup_dir.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"))


def create_backup(backup_dir: Path | None = None, keep: int | None = None) -> Path:
    backup_dir = Path(backup_dir or settings.BACKUP_DIR)
    keep = settings.BACKUP_KEEP if keep is None else keep
    backup_dir.mkdir(parents=True, exist_ok=True)

    target = backup_dir / f"{BACKUP_PREFIX}{datetime.now():%Y%m%d-%H%M%S}{BACKUP_SUFFIX}"
    tmp = target.with_suffix(".tmp")
    src = sqlite3.connect(_db_path())
    dst = sqlite3.connect(tmp)
    try:
        with dst:
            src.backup(dst)
        ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise RuntimeError(f"Backup integrity check failed: {ok}")
    finally:
        dst.close()
        src.close()
    tmp.replace(target)

    for old in list_backups(backup_dir)[:-keep] if keep > 0 else []:
        old.unlink()
    logger.info("Database backup written to %s", target)
    return target


def restore_backup(backup_file: Path) -> None:
    """Replace the live database with a backup. Stop the app and worker first."""
    backup_file = Path(backup_file)
    check = sqlite3.connect(backup_file)
    try:
        ok = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()
    if ok != "ok":
        raise RuntimeError(f"Backup file is damaged: {ok}")

    connections.close_all()
    db_path = _db_path()
    for extra in (db_path.with_name(db_path.name + "-wal"), db_path.with_name(db_path.name + "-shm")):
        extra.unlink(missing_ok=True)
    shutil.copy2(backup_file, db_path)
    logger.info("Database restored from %s", backup_file)
