from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone

from .iran import PROVINCE_CHOICES
from .validators import normalize_mobile, validate_mobile, validate_postal_code


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, mobile, password, **extra_fields):
        user = self.model(mobile=normalize_mobile(mobile), **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()  # customers sign in with an SMS code only
        user.save(using=self._db)
        return user

    def create_user(self, mobile, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(mobile, password, **extra_fields)

    def create_superuser(self, mobile, password=None, **extra_fields):
        extra_fields["is_staff"] = True
        extra_fields["is_superuser"] = True
        return self._create_user(mobile, password, **extra_fields)


class User(AbstractUser):
    """The mobile number is the username. Customers have no password (SMS code login);
    staff also have a password for the admin."""

    username = None
    first_name = None
    last_name = None
    mobile = models.CharField(
        "شمارهٔ موبایل",
        max_length=11,
        unique=True,
        validators=[validate_mobile],
        error_messages={"unique": "کاربری با این شمارهٔ موبایل وجود دارد."},
    )
    name = models.CharField("نام و نام خانوادگی", max_length=100, blank=True)

    USERNAME_FIELD = "mobile"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        verbose_name = "کاربر"
        verbose_name_plural = "کاربران"

    def __str__(self):
        return f"{self.name} ({self.mobile})" if self.name else self.mobile

    def clean(self):
        super().clean()
        if self.mobile:
            self.mobile = normalize_mobile(self.mobile)

    def get_full_name(self):
        return self.name

    def get_short_name(self):
        return self.name or self.mobile


class CustomerManager(UserManager):
    def get_queryset(self):
        return super().get_queryset().filter(is_staff=False)


class Customer(User):
    """Customers (non-staff users) for the «مشتریان» admin, with their order history."""

    objects = CustomerManager()

    class Meta:
        proxy = True
        verbose_name = "مشتری"
        verbose_name_plural = "مشتریان"


ADDRESS_FIELDS = ("recipient_name", "recipient_mobile", "province", "city", "address", "postal_code")


class Address(models.Model):
    """A saved delivery address of a signed-in customer."""

    MAX_PER_USER = 10

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="کاربر", on_delete=models.CASCADE, related_name="addresses"
    )
    recipient_name = models.CharField("نام گیرنده", max_length=100)
    recipient_mobile = models.CharField("موبایل گیرنده", max_length=11, validators=[validate_mobile])
    province = models.CharField("استان", max_length=40, choices=PROVINCE_CHOICES)
    city = models.CharField("شهر", max_length=60)
    address = models.CharField("نشانی کامل", max_length=400)
    postal_code = models.CharField("کد پستی", max_length=10, validators=[validate_postal_code])
    created_at = models.DateTimeField("تاریخ ایجاد", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین ویرایش", auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        verbose_name = "نشانی"
        verbose_name_plural = "نشانی‌ها"

    def __str__(self):
        return f"{self.province}، {self.city}، {self.address}"

    def as_dict(self):
        return {f: getattr(self, f) for f in ADDRESS_FIELDS}


class OTPCode(models.Model):
    """One SMS verification code. Only an HMAC of the code is stored (see accounts.otp)."""

    class Purpose(models.TextChoices):
        LOGIN = "login", "ورود / ثبت‌نام"
        CHECKOUT = "checkout", "تأیید موبایل هنگام خرید"

    mobile = models.CharField("شمارهٔ موبایل", max_length=11)
    purpose = models.CharField("کاربرد", max_length=20, choices=Purpose.choices)
    code_hash = models.CharField(max_length=64)
    ip = models.GenericIPAddressField("آی‌پی", null=True, blank=True)
    attempts = models.PositiveSmallIntegerField("تلاش‌های نادرست", default=0)
    created_at = models.DateTimeField("زمان ارسال", default=timezone.now)
    expires_at = models.DateTimeField("زمان انقضا")
    consumed_at = models.DateTimeField("زمان استفاده یا ابطال", null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "کد تأیید پیامکی"
        verbose_name_plural = "کدهای تأیید پیامکی"
        indexes = [
            models.Index(fields=["mobile", "created_at"]),
            models.Index(fields=["ip", "created_at"]),
        ]

    def __str__(self):
        return f"{self.mobile} ({self.get_purpose_display()})"
