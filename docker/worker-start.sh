#!/bin/sh
# Worker container: register recurring jobs (daily backup, heartbeat), then run the queue.
set -e
python manage.py setup_schedules
exec python manage.py qcluster
