"""Functions run by the background worker (django-q2)."""

from pathlib import Path

from .backup import create_backup

HEARTBEAT_FILE = Path("/tmp/worker-heartbeat")


def backup_database():
    return str(create_backup())


def heartbeat():
    """Touched every few minutes; the worker's Docker healthcheck reads its age."""
    HEARTBEAT_FILE.touch()
