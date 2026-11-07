"""Outgoing SMS.

    send_sms(mobile, template_key, context)   render an SMSTemplate and queue it; never raises
    send_text(mobile, text, template_key="")  queue a ready text; never raises
    build_admin_order_text(order)             the admin's new-order message
    notify_admin_new_order(order)             once per order, when it becomes paid_processing
    resend_admin_sms(order)                   send the admin message again (admin button, part 5)

Every message is an SMSLog row. It is delivered by a django-q2 job (deliver); a failed
attempt is retried with backoff (RETRY_DELAYS) by the every-minute retry_pending_sms
job, up to MAX_ATTEMPTS. A message is claimed with a conditional UPDATE before sending,
so two jobs never send the same row twice. With no API key in SiteSettings the
provider is console mode: the text is only logged, delivered at once without the
queue (so login codes also show up in development without a running worker).
"""

import logging
import re
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .defaults import TEMPLATES
from .models import SMSLog, SMSTemplate, sms_parts
from .providers import SMSError, get_provider

logger = logging.getLogger("notifications.sms")

MAX_ATTEMPTS = 5
RETRY_DELAYS = [60, 5 * 60, 15 * 60, 60 * 60]  # seconds after attempt 1, 2, 3, 4
LOST_JOB_AFTER = timedelta(minutes=1)  # a queued row older than this is picked up by the retry job
STUCK_SENDING_AFTER = timedelta(minutes=10)

S = SMSLog.Status


def _site_settings():
    from core.models import SiteSettings

    return SiteSettings.load()


class _Blank(dict):
    def __missing__(self, key):
        return ""


def _format(value):
    if value is None:
        return ""
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    return str(value)


def render(template_key, context, site_settings=None):
    """The SMSTemplate text with {placeholders} filled (numbers as 1,250,000; unknown ones empty)."""
    site_settings = site_settings or _site_settings()
    values = _Blank({"site_name": site_settings.site_name})
    values.update({k: _format(v) for k, v in (context or {}).items()})
    text = SMSTemplate.text_for(template_key)
    try:
        return text.format_map(values).strip()
    except (ValueError, IndexError, AttributeError, KeyError):
        logger.error("SMS template %r is broken; using the default text", template_key)
        return TEMPLATES[template_key]["text"].format_map(values).strip()


def send_sms(mobile, template_key, context):
    """Render the template and queue the SMS. Returns the SMSLog, or None if it could not even be
    queued (logged; a failing SMS never breaks the caller, e.g. checkout)."""
    try:
        text = render(template_key, context)
    except Exception:
        logger.exception("Could not render SMS %r for %s", template_key, mobile)
        return None
    return send_text(mobile, text, template_key)


def send_text(mobile, text, template_key=""):
    try:
        provider = get_provider(_site_settings())
        log = SMSLog.objects.create(
            mobile=mobile, text=text, template_key=template_key, provider=provider.key, parts=sms_parts(text)
        )
    except Exception:
        logger.exception("Could not queue SMS %r for %s", template_key, mobile)
        return None
    if provider.is_console:
        try:
            deliver(log.pk)
        except Exception:
            logger.exception("Console SMS %s failed", log.pk)
    else:
        # After commit, so the worker can see the row (and nothing goes out for a rolled-back change).
        transaction.on_commit(lambda: _enqueue(log.pk))
    return log


def _enqueue(log_id):
    try:
        from django_q.tasks import async_task

        async_task("notifications.tasks.deliver_sms", log_id)
    except Exception:  # the every-minute retry job picks the row up later
        logger.exception("Could not enqueue SMS %s", log_id)


def _claim(log_id, now):
    ready = Q(status=S.QUEUED) | Q(status=S.RETRYING, next_attempt_at__lte=now)
    stuck = Q(status=S.SENDING, updated_at__lte=now - STUCK_SENDING_AFTER)
    return bool(SMSLog.objects.filter(ready | stuck, pk=log_id).update(status=S.SENDING, updated_at=now))


def _mask_code(log):
    """Login codes are not kept in the log once the message is finished."""
    if log.template_key == "otp":
        log.text = re.sub(r"\d{4,}", lambda m: "•" * len(m.group()), log.text)


def deliver(log_id):
    """One delivery attempt. Returns the new status, or None when the row is not due / taken by another job."""
    now = timezone.now()
    if not _claim(log_id, now):
        return None
    log = SMSLog.objects.get(pk=log_id)
    log.attempts += 1
    try:
        provider = get_provider(_site_settings())
        result = provider.send(log.mobile, log.text)
    except Exception as e:
        if not isinstance(e, SMSError):
            logger.exception("SMS %s: unexpected provider error", log.pk)
        log.error = str(getattr(e, "message", e))[:255]
        log.provider_response = str(getattr(e, "response", ""))[:2000]
        if getattr(e, "retryable", True) and log.attempts < MAX_ATTEMPTS:
            delay = RETRY_DELAYS[min(log.attempts, len(RETRY_DELAYS)) - 1]
            log.status = S.RETRYING
            log.next_attempt_at = timezone.now() + timedelta(seconds=delay)
        else:
            log.status = S.FAILED
            log.next_attempt_at = None
            _mask_code(log)
            logger.error("SMS %s to %s failed: %s", log.pk, log.mobile, log.error)
    else:
        log.status = S.SENT
        log.provider = provider.key
        log.provider_response = result.response
        log.message_id = result.message_id
        log.error = ""
        log.sent_at = timezone.now()
        log.next_attempt_at = None
        _mask_code(log)
    log.save()
    return log.status


def deliver_due():
    """Deliver every message that is due (retries, lost jobs, stuck sends). -> number attempted."""
    now = timezone.now()
    due = SMSLog.objects.filter(
        Q(status=S.RETRYING, next_attempt_at__lte=now)
        | Q(status=S.QUEUED, created_at__lte=now - LOST_JOB_AFTER)
        | Q(status=S.SENDING, updated_at__lte=now - STUCK_SENDING_AFTER)
    ).values_list("pk", flat=True)[:100]
    return sum(1 for pk in list(due) if deliver(pk) is not None)


# --- admin message about a new paid order -------------------------------------------


def build_admin_order_text(order):
    """One line per item ("short_name quantity", gifts marked), then the recipient's name,
    mobile, postal code and full postal address. Never truncated."""
    lines = []
    for item in order.items.all():
        line = f"{item.short_name or item.name} {item.quantity}"
        if item.is_gift:
            line += " (هدیه)"
        lines.append(line)
    lines += [
        order.recipient_name,
        order.recipient_mobile,
        order.postal_code,
        f"{order.province}، {order.city}، {order.address}",
    ]
    return "\n".join(lines)


def _send_admin_order_sms(order, site_settings):
    context = {**order.sms_context(), "order_text": build_admin_order_text(order)}
    text = render("admin_new_order", context, site_settings)
    return [log for mobile in site_settings.admin_mobiles if (log := send_text(mobile, text, "admin_new_order"))]


def notify_admin_new_order(order):
    """The admin SMS of a newly paid order (Order sends it once, when it becomes paid_processing).
    Never raises."""
    try:
        site_settings = _site_settings()
        if not site_settings.admin_sms_enabled:
            return []
        return _send_admin_order_sms(order, site_settings)
    except Exception:
        logger.exception("Admin SMS for order %s failed", getattr(order, "pk", None))
        return []


def resend_admin_sms(order):
    """Send the admin message of `order` again to every admin number (also when the automatic
    admin SMS is switched off: this is an explicit request). -> the SMSLog rows."""
    return _send_admin_order_sms(order, _site_settings())
