#!/bin/sh
# Web container: apply migrations, create the first admin (if configured), start gunicorn.
set -e
python manage.py migrate --noinput
python manage.py ensure_superuser
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 2 --threads 2 \
    --timeout 60 \
    --max-requests 1000 --max-requests-jitter 100 \
    --forwarded-allow-ips "*" \
    --worker-tmp-dir /dev/shm \
    --access-logfile -
