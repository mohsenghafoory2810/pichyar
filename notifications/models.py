import string

from django.core.exceptions import ValidationError
from django.db import models

from . import defaults


class SMSTemplate(models.Model):
    """Editable text of each SMS. Placeholders like {order_number} are filled in when sending."""

    key = models.CharField("نوع پیامک", max_length=30, choices=defaults.KEY_CHOICES, unique=True)
    text = models.TextField(
        "متن پیامک",
        help_text="متغیرها را با آکولاد بنویسید، مثل {order_number}. پیامک طولانی چندبخشی فرستاده می‌شود و کوتاه نمی‌شود.",
    )
    updated_at = models.DateTimeField("آخرین ویرایش", auto_now=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "متن پیامک"
        verbose_name_plural = "متن‌های پیامک"

    def __str__(self):
        return self.get_key_display()

    @property
    def allowed_vars(self):
        return defaults.TEMPLATES.get(self.key, {}).get("vars", ())

    def clean(self):
        allowed = set(self.allowed_vars)
        try:
            used = {name for _, name, _, _ in string.Formatter().parse(self.text or "") if name is not None}
        except ValueError:
            raise ValidationError(
                {"text": "آکولادهای متن درست باز و بسته نشده‌اند. برای نوشتن خود آکولاد از {{ و }} استفاده کنید."}
            ) from None
        unknown = sorted(used - allowed)
        if unknown:
            names = "، ".join("{" + n + "}" for n in unknown)
            raise ValidationError(
                {"text": f"متغیر {names} برای این پیامک تعریف نشده است. متغیرهای مجاز: "
                 + "، ".join("{" + v + "}" for v in self.allowed_vars)}
            )

    @classmethod
    def text_for(cls, key):
        row = cls.objects.filter(key=key).values_list("text", flat=True).first()
        if row:
            return row
        try:
            return defaults.TEMPLATES[key]["text"]
        except KeyError:
            raise LookupError(f"Unknown SMS template: {key!r}") from None


def sms_parts(text):
    """Number of SMS parts: Persian (UCS-2) is 70 characters, or 67 per part when concatenated;
    Latin-only (GSM) text is 160 / 153."""
    length = len(text)
    if all(ord(c) < 128 for c in text):
        single, multi = 160, 153
    else:
        single, multi = 70, 67
    if length <= single:
        return 1
    return -(-length // multi)


class SMSLog(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "در صف ارسال"
        SENDING = "sending", "در حال ارسال"
        RETRYING = "retrying", "در انتظار تلاش دوباره"
        SENT = "sent", "ارسال‌شده"
        FAILED = "failed", "ناموفق"

    mobile = models.CharField("موبایل", max_length=11, db_index=True)
    text = models.TextField("متن")
    template_key = models.CharField("نوع پیامک", max_length=30, choices=defaults.KEY_CHOICES, blank=True)
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.QUEUED, db_index=True)
    provider = models.CharField("سرویس پیامک", max_length=30, blank=True)
    provider_response = models.TextField("پاسخ سرویس", blank=True)
    message_id = models.CharField("شناسهٔ پیامک نزد سرویس", max_length=64, blank=True)
    error = models.CharField("خطا", max_length=255, blank=True)
    parts = models.PositiveSmallIntegerField("تعداد بخش", default=1)
    attempts = models.PositiveSmallIntegerField("تعداد تلاش", default=0)
    next_attempt_at = models.DateTimeField("تلاش بعدی", null=True, blank=True)
    created_at = models.DateTimeField("زمان ایجاد", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("آخرین تغییر", auto_now=True)
    sent_at = models.DateTimeField("زمان ارسال", null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "گزارش پیامک"
        verbose_name_plural = "گزارش پیامک‌ها"

    def __str__(self):
        return f"{self.mobile} - {self.get_status_display()}"
