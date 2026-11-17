"""SMS jobs run by the background worker (django-q2)."""

from . import services


def deliver_sms(log_id):
    return services.deliver(log_id)


def retry_pending_sms():
    """Every minute: retries that are due, and queued messages whose job got lost."""
    return services.deliver_due()


def prepare_campaign(campaign_id):
    """Group SMS: create the messages of every recipient, then send them in small batches."""
    log_ids = services.prepare_campaign(campaign_id)
    services.enqueue_batches(log_ids)
    return len(log_ids)


def deliver_sms_batch(log_ids):
    return services.deliver_batch(log_ids)
