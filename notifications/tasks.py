"""SMS jobs run by the background worker (django-q2)."""

from . import services


def deliver_sms(log_id):
    return services.deliver(log_id)


def retry_pending_sms():
    """Every minute: retries that are due, and queued messages whose job got lost."""
    return services.deliver_due()
