from django.conf import settings
from django.core.validators import MaxValueValidator, MinLengthValidator, MinValueValidator
from django.db import models

REVIEW_MIN_LENGTH = 10


class ReviewQuerySet(models.QuerySet):
    def approved(self):
        return self.filter(status=Review.Status.APPROVED)


class Review(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار بررسی"
        APPROVED = "approved", "تأییدشده"
        REJECTED = "rejected", "ردشده"

    product = models.ForeignKey("catalog.Product", verbose_name="محصول", on_delete=models.CASCADE, related_name="reviews")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="کاربر", on_delete=models.CASCADE, related_name="reviews")
    rating = models.PositiveSmallIntegerField("امتیاز", validators=[MinValueValidator(1), MaxValueValidator(5)])
    title = models.CharField("عنوان", max_length=120, blank=True)
    text = models.TextField("متن نظر", max_length=3000, validators=[MinLengthValidator(REVIEW_MIN_LENGTH)])
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    verified_purchase = models.BooleanField("خرید تأییدشده", default=False)
    admin_reply = models.TextField("پاسخ فروشگاه", blank=True)
    ip_address = models.GenericIPAddressField("IP", null=True, blank=True, editable=False)
    created_at = models.DateTimeField("تاریخ ثبت", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("آخرین ویرایش", auto_now=True)

    objects = ReviewQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "نظر"
        verbose_name_plural = "نظرهای مشتریان"
        constraints = [
            models.UniqueConstraint(fields=["product", "user"], name="one_review_per_user_per_product"),
            models.CheckConstraint(condition=models.Q(rating__gte=1, rating__lte=5), name="review_rating_1_to_5"),
        ]

    def __str__(self):
        return f"{self.product} — {self.rating}"
