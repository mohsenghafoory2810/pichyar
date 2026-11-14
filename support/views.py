"""«پیام به پشتیبانی» in the account panel: my conversations, a new message and one conversation.

With SiteSettings.support_tickets_enabled off, the list and the old conversations stay
readable, but nothing new can be sent. A closed conversation is read-only: the customer
starts a new one instead.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from core.utils import get_site_settings

from . import services
from .forms import MessageForm, TicketForm
from .models import Ticket

DISABLED = "ارسال پیام به پشتیبانی از طریق سایت در حال حاضر فعال نیست."
CLOSED = "این گفتگو بسته شده است. برای ادامه، یک پیام جدید بفرستید."
SENT = "پیام شما برای پشتیبانی فرستاده شد. پاسخ را همین‌جا می‌بینید و با پیامک خبردار می‌شوید."
REPLY_SENT = "پیام شما فرستاده شد."


def _enabled(request):
    return get_site_settings(request).support_tickets_enabled


@login_required
def ticket_list(request):
    tickets = Ticket.objects.filter(user=request.user).select_related("order")
    return render(request, "support/list.html", {"tickets": tickets, "enabled": _enabled(request), "tab": "support"})


@login_required
def ticket_new(request):
    if not _enabled(request):
        messages.info(request, DISABLED)
        return redirect("support:list")
    form = TicketForm(request.POST or None, user=request.user)
    if request.method == "POST":
        if form.is_bot:
            # Honeypot filled: look like a success, save nothing.
            messages.success(request, SENT)
            return redirect("support:list")
        limit_error = services.rate_limit_error(request.user, new_ticket=True)
        if limit_error:
            form.is_valid()
            form.add_error(None, limit_error)
        if form.is_valid():
            data = form.cleaned_data
            ticket = services.create_ticket(request.user, data["subject"], data["text"], order=data["order"])
            messages.success(request, SENT)
            return redirect(ticket)
    return render(request, "support/new.html", {"form": form, "tab": "support"})


@login_required
def ticket_detail(request, pk):
    ticket = get_object_or_404(Ticket.objects.select_related("order"), pk=pk, user=request.user)
    enabled = _enabled(request)
    can_reply = enabled and not ticket.is_closed
    form = MessageForm(request.POST or None)
    if request.method == "POST":
        if not can_reply:
            messages.error(request, CLOSED if enabled else DISABLED)
            return redirect(ticket)
        if form.is_bot:
            messages.success(request, REPLY_SENT)
            return redirect(ticket)
        limit_error = services.rate_limit_error(request.user)
        if limit_error:
            form.is_valid()
            form.add_error(None, limit_error)
        if form.is_valid():
            services.add_customer_message(ticket, request.user, form.cleaned_data["text"])
            messages.success(request, REPLY_SENT)
            return redirect(f"{ticket.get_absolute_url()}#reply")
    services.mark_read(ticket)
    return render(
        request,
        "support/detail.html",
        {
            "ticket": ticket,
            "thread": ticket.messages.all(),
            "form": form,
            "enabled": enabled,
            "can_reply": can_reply,
            "tab": "support",
        },
    )
