from django.db import models

from orders.models import PaymentMethod

from .storage import private_storage


def receipt_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    return f"receipts/{instance.order.number}-{instance.order.payments.count() + 1}.{ext}"


class Payment(models.Model):
    """One payment attempt: an online gateway transaction or a card-to-card report."""

    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار"
        VERIFYING = "verifying", "در حال بررسی"
        SUCCEEDED = "succeeded", "موفق"
        FAILED = "failed", "ناموفق"
        CANCELED = "canceled", "انصراف مشتری"
        REJECTED = "rejected", "ردشده"

    FINAL = {Status.SUCCEEDED, Status.FAILED, Status.CANCELED, Status.REJECTED}

    order = models.ForeignKey("orders.Order", verbose_name="سفارش", on_delete=models.CASCADE, related_name="payments")
    method = models.CharField("روش", max_length=10, choices=PaymentMethod.choices)
    gateway = models.CharField("درگاه", max_length=30, blank=True)
    amount = models.PositiveBigIntegerField("مبلغ (تومان)")
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)

    # online
    authority = models.CharField("شناسهٔ تراکنش درگاه", max_length=100, blank=True, db_index=True)
    ref_id = models.CharField("کد پیگیری بانکی", max_length=100, blank=True)
    card_pan = models.CharField("کارت پرداخت‌کننده", max_length=30, blank=True)
    # card to card
    tracking_number = models.CharField("کد پیگیری کارت به کارت", max_length=50, blank=True)
    receipt = models.ImageField("تصویر رسید", upload_to=receipt_path, storage=private_storage, blank=True)

    message = models.CharField("پیام", max_length=255, blank=True)
    raw = models.JSONField("پاسخ خام درگاه", default=dict, blank=True)
    created_at = models.DateTimeField("زمان ایجاد", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین تغییر", auto_now=True)
    verified_at = models.DateTimeField("زمان تأیید", null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "پرداخت"
        verbose_name_plural = "پرداخت‌ها"

    def __str__(self):
        return f"{self.get_method_display()} - سفارش {self.order.number}"

    @property
    def is_final(self):
        return self.status in self.FINAL
