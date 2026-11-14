"""Support conversations: creating tickets and messages, rate limits and SMS notifications.

    create_ticket(user, subject, text, order=None)   a new conversation with its first message
    add_customer_message(ticket, user, text)          the customer writes again → «در انتظار پاسخ»
    add_staff_reply(ticket, author, text, close=False) support answers → «پاسخ داده شد» (+ SMS)
    rate_limit_error(user, new_ticket=False)          too many messages in the last hour?
    mark_read(ticket)                                 the customer has seen the replies
    tab_info(user)                                    the account-panel tab (shown? unread count)

SMS (never raises, sent after the transaction commits):
- admin_support_message to every number in SiteSettings.admin_mobiles on a new ticket or a new
  customer message (SiteSettings.support_admin_sms_enabled);
- support_reply to the customer when support answers (SiteSettings.support_reply_sms_enabled).
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.text import Truncator

from notifications.services import send_sms

from .models import Ticket, TicketMessage

S = Ticket.Status

# Overridable in Django settings.
TICKETS_HOURLY_LIMIT = 5
MESSAGES_HOURLY_LIMIT = 20
SMS_PREVIEW_LENGTH = 100

RATE_LIMIT_ERROR = "تعداد پیام‌های ارسال‌شده در یک ساعت گذشته زیاد است. لطفاً کمی بعد دوباره تلاش کنید."


def setting(name, default):
    return getattr(settings, name, default)


def tickets_limit():
    return setting("SUPPORT_TICKETS_HOURLY_LIMIT", TICKETS_HOURLY_LIMIT)


def messages_limit():
    return setting("SUPPORT_MESSAGES_HOURLY_LIMIT", MESSAGES_HOURLY_LIMIT)


def _site_settings():
    from core.models import SiteSettings

    return SiteSettings.load()


def rate_limit_error(user, new_ticket=False):
    """RATE_LIMIT_ERROR when the user started too many conversations (new_ticket) or wrote too
    many messages in the last hour; else None."""
    since = timezone.now() - timedelta(hours=1)
    if new_ticket and Ticket.objects.filter(user=user, created_at__gte=since).count() >= tickets_limit():
        return RATE_LIMIT_ERROR
    sent = TicketMessage.objects.filter(ticket__user=user, is_staff_reply=False, created_at__gte=since).count()
    if sent >= messages_limit():
        return RATE_LIMIT_ERROR
    return None


@transaction.atomic
def create_ticket(user, subject, text, order=None):
    ticket = Ticket.objects.create(user=user, subject=subject, order=order, status=S.WAITING)
    message = TicketMessage.objects.create(ticket=ticket, author=user, text=text)
    ticket.last_message_at = message.created_at
    ticket.save(update_fields=["last_message_at"])
    transaction.on_commit(lambda: notify_admin(ticket, message))
    return ticket


@transaction.atomic
def add_customer_message(ticket, user, text):
    """The customer's follow-up. The conversation waits for support again."""
    message = TicketMessage.objects.create(ticket=ticket, author=user, text=text)
    ticket.status = S.WAITING
    ticket.last_message_at = message.created_at
    ticket.save(update_fields=["status", "last_message_at", "updated_at"])
    transaction.on_commit(lambda: notify_admin(ticket, message))
    return message


@transaction.atomic
def add_staff_reply(ticket, author, text, close=False):
    """Support's answer: the customer sees it as unread in their panel and gets an SMS."""
    message = TicketMessage.objects.create(ticket=ticket, author=author, text=text, is_staff_reply=True)
    ticket.status = S.CLOSED if close else S.ANSWERED
    ticket.customer_unread = True
    ticket.last_message_at = message.created_at
    ticket.save(update_fields=["status", "customer_unread", "last_message_at", "updated_at"])
    transaction.on_commit(lambda: notify_customer(ticket))
    return message


def mark_read(ticket):
    if ticket.customer_unread:
        ticket.customer_unread = False
        Ticket.objects.filter(pk=ticket.pk).update(customer_unread=False)


def tab_info(user):
    """{"tickets": number of the user's conversations, "unread": those with an unseen reply}
    — one query."""
    if not getattr(user, "is_authenticated", False):
        return {"tickets": 0, "unread": 0}
    return Ticket.objects.filter(user=user).aggregate(
        tickets=Count("pk"), unread=Count("pk", filter=Q(customer_unread=True))
    )


# --- SMS ---------------------------------------------------------------------------


def customer_label(user):
    name = (getattr(user, "name", "") or "").strip()
    mobile = getattr(user, "mobile", "") or ""
    return f"{name} ({mobile})" if name and mobile else name or mobile


def notify_admin(ticket, message):
    """«پیام جدید پشتیبانی» to every admin number. Never raises."""
    site_settings = _site_settings()
    if not site_settings.support_admin_sms_enabled:
        return []
    context = {
        "customer": customer_label(ticket.user),
        "ticket_subject": ticket.subject,
        "text_preview": Truncator(" ".join(message.text.split())).chars(SMS_PREVIEW_LENGTH),
    }
    return [log for mobile in site_settings.admin_mobiles if (log := send_sms(mobile, "admin_support_message", context))]


def notify_customer(ticket):
    """«پاسخ پشتیبانی» to the customer. Never raises."""
    mobile = getattr(ticket.user, "mobile", "")
    if not mobile or not _site_settings().support_reply_sms_enabled:
        return None
    return send_sms(mobile, "support_reply", {"ticket_subject": ticket.subject})
