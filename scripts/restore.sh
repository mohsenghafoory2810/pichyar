#!/bin/sh
# Restore the database from a backup.
#   sh scripts/restore.sh                         -> list backups
#   sh scripts/restore.sh db-20250101-033000.sqlite3  -> restore that backup
set -e
cd "$(dirname "$0")/.."

if [ -z "$1" ]; then
    docker compose run --rm --no-deps app python manage.py restore_db --list
    exit 0
fi

docker compose stop app worker
docker compose run --rm --no-deps app python manage.py restore_db "$1"
docker compose up -d
echo "Done."
