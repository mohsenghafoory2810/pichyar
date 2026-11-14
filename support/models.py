"""Support conversations: a customer's message to the shop (Ticket) and its replies (TicketMessage)."""

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.persian import jalali_format

SUBJECT_MAX_LENGTH = 120
TEXT_MAX_LENGTH = 3000


class Ticket(models.Model):
    class Status(models.TextChoices):
        WAITING = "waiting", "در انتظار پاسخ"
        ANSWERED = "answered", "پاسخ داده شد"
        CLOSED = "closed", "بسته‌شده"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="مشتری", on_delete=models.CASCADE, related_name="support_tickets"
    )
    subject = models.CharField("موضوع", max_length=SUBJECT_MAX_LENGTH)
    order = models.ForeignKey(
        "orders.Order",
        verbose_name="سفارش مرتبط",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_tickets",
    )
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.WAITING, db_index=True)
    customer_unread = models.BooleanField(
        "پاسخ خوانده‌نشده", default=False, help_text="پاسخی از پشتیبانی که مشتری هنوز ندیده است."
    )
    created_at = models.DateTimeField("تاریخ ثبت", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین ویرایش", auto_now=True)
    last_message_at = models.DateTimeField("آخرین پیام", default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-last_message_at", "-id"]
        verbose_name = "پیام پشتیبانی"
        verbose_name_plural = "پیام‌های پشتیبانی"

    def __str__(self):
        return self.subject

    def get_absolute_url(self):
        return reverse("support:detail", args=[self.pk])

    @property
    def is_closed(self):
        return self.status == self.Status.CLOSED


class TicketMessage(models.Model):
    ticket = models.ForeignKey(Ticket, verbose_name="پیام پشتیبانی", on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="نویسنده",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    is_staff_reply = models.BooleanField("پاسخ پشتیبانی", default=False)
    text = models.TextField("متن", max_length=TEXT_MAX_LENGTH)
    created_at = models.DateTimeField("زمان ارسال", auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name = "پیام گفتگو"
        verbose_name_plural = "پیام‌های گفتگو"

    def __str__(self):
        return f"{self.ticket} — {jalali_format(self.created_at, '%Y/%m/%d - %H:%M')}"
