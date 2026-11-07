"""Orders, discount codes and the gift pool. Items and the address are snapshots: later
product or price changes never alter an order.

Status changes go through the methods below (confirm_payment, approve, reject,
cancel, mark_shipped, ...). Each one locks the order row, keeps stock in sync
(product stock and gift stock reserved when the payment is confirmed, released when a
confirmed order is canceled), counts the discount code use on confirmation (given
back on cancel), writes an OrderStatusLog row and sends the customer SMS after
commit. The admin SMS goes out once per order, when it becomes paid_processing.
"""

import re
import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.urls import reverse
from django.utils import timezone

from accounts.iran import PROVINCE_CHOICES
from accounts.validators import validate_mobile, validate_postal_code
from catalog import stock
from core.persian import fa_digits, jalali_format, latin_digits, toman
from notifications.services import notify_admin_new_order, send_sms


class OrderStatus(models.TextChoices):
    PENDING_PAYMENT = "pending_payment", "در انتظار پرداخت"
    AWAITING_APPROVAL = "awaiting_approval", "در انتظار تأیید پرداخت"
    PAID_PROCESSING = "paid_processing", "پرداخت‌شده، در حال آماده‌سازی"
    SHIPPED = "shipped", "ارسال‌شده"
    DELIVERED = "delivered", "تحویل‌شده"
    CANCELED = "canceled", "لغوشده"
    FAILED = "failed", "پرداخت ناموفق"


class PaymentMethod(models.TextChoices):
    ONLINE = "online", "پرداخت اینترنتی"
    CARD = "card", "کارت به کارت"


S = OrderStatus
TRANSITIONS = {
    S.PENDING_PAYMENT: {S.AWAITING_APPROVAL, S.PAID_PROCESSING, S.FAILED, S.CANCELED},
    S.AWAITING_APPROVAL: {S.PAID_PROCESSING, S.CANCELED},
    S.FAILED: {S.PENDING_PAYMENT, S.CANCELED},
    S.PAID_PROCESSING: {S.SHIPPED, S.CANCELED},
    S.SHIPPED: {S.DELIVERED},
    S.DELIVERED: set(),
    S.CANCELED: set(),
}
CONFIRMED_STATUSES = {S.PAID_PROCESSING, S.SHIPPED, S.DELIVERED}
SMS_ON_STATUS = {S.PAID_PROCESSING: "payment_confirmed", S.SHIPPED: "shipped"}


class InvalidTransition(Exception):
    pass


def generate_order_number():
    """Seven random digits (not sequential, so numbers don't reveal sales volume)."""
    for _ in range(50):
        number = str(1_000_000 + secrets.randbelow(9_000_000))
        if not Order.objects.filter(number=number).exists():
            return number
    raise RuntimeError("Could not find a free order number.")


# --- discount codes ------------------------------------------------------------------


class DiscountError(Exception):
    """The code can't be used; `message` is shown to the customer."""

    def __init__(self, message):
        self.message = message
        super().__init__(message)


def normalize_code(text):
    """' sale-۲۰ ' -> 'SALE-20' (codes are case-insensitive)."""
    return latin_digits(text or "").strip().replace(" ", "").upper()


class DiscountType(models.TextChoices):
    PERCENT = "percent", "درصدی"
    FIXED = "fixed", "مبلغ ثابت"


class DiscountCodeQuerySet(models.QuerySet):
    def find(self, text):
        code = normalize_code(text)
        return self.filter(code=code).first() if code else None


class DiscountCode(models.Model):
    """Applies to the items subtotal (never to shipping). A use is counted when an order with the
    code is confirmed and given back if that order is canceled."""

    code = models.CharField(
        "کد",
        max_length=30,
        help_text="حروف انگلیسی، عدد، خط تیره یا زیرخط (۳ تا ۳۰ نویسه). بزرگی و کوچکی حروف فرقی ندارد.",
    )
    kind = models.CharField("نوع تخفیف", max_length=10, choices=DiscountType.choices, default=DiscountType.PERCENT)
    value = models.PositiveIntegerField("مقدار", help_text="برای کد درصدی عدد ۱ تا ۱۰۰؛ برای مبلغ ثابت، مبلغ به تومان.")
    max_discount = models.PositiveBigIntegerField(
        "سقف مبلغ تخفیف (تومان)",
        null=True,
        blank=True,
        help_text="فقط برای کد درصدی. خالی یعنی بدون سقف.",
    )
    min_order_amount = models.PositiveBigIntegerField(
        "حداقل مبلغ خرید (تومان)", default=0, help_text="جمع کالاها، بدون هزینهٔ ارسال. صفر یعنی بدون حداقل."
    )
    usage_limit = models.PositiveIntegerField(
        "سقف کل دفعات استفاده", null=True, blank=True, help_text="خالی یعنی بدون محدودیت."
    )
    per_user_limit = models.PositiveIntegerField(
        "سقف استفادهٔ هر مشتری",
        null=True,
        blank=True,
        default=1,
        help_text="بر اساس حساب کاربری یا شمارهٔ موبایل تأییدشده. خالی یعنی بدون محدودیت.",
    )
    starts_at = models.DateTimeField("شروع اعتبار", null=True, blank=True, help_text="خالی یعنی از همین حالا.")
    ends_at = models.DateTimeField("پایان اعتبار", null=True, blank=True, help_text="خالی یعنی بدون تاریخ پایان.")
    is_active = models.BooleanField("فعال", default=True)
    used_count = models.PositiveIntegerField("دفعات استفاده", default=0, editable=False)
    created_at = models.DateTimeField("تاریخ ایجاد", auto_now_add=True)

    objects = DiscountCodeQuerySet.as_manager()

    CODE_RE = r"^[A-Z0-9_-]{3,30}$"

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "کد تخفیف"
        verbose_name_plural = "کدهای تخفیف"
        constraints = [
            models.UniqueConstraint(
                Lower("code"),
                name="discount_code_unique_ci",
                violation_error_message="این کد تخفیف قبلاً ساخته شده است (بزرگی و کوچکی حروف فرقی ندارد).",
            ),
        ]

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        self.code = normalize_code(self.code)
        super().save(*args, **kwargs)

    def clean_fields(self, exclude=None):
        self.code = normalize_code(self.code)
        super().clean_fields(exclude)

    def clean(self):
        errors = {}
        if self.code and not re.match(self.CODE_RE, self.code):
            errors["code"] = "کد فقط می‌تواند حروف انگلیسی، عدد، خط تیره (-) و زیرخط (_) داشته باشد و ۳ تا ۳۰ نویسه باشد."
        if self.value is not None:
            if self.kind == DiscountType.PERCENT and not 1 <= self.value <= 100:
                errors["value"] = "درصد تخفیف باید بین ۱ تا ۱۰۰ باشد."
            elif self.kind == DiscountType.FIXED and self.value < 1:
                errors["value"] = "مبلغ تخفیف باید بیشتر از صفر باشد."
        if self.max_discount is not None:
            if self.kind == DiscountType.FIXED:
                errors["max_discount"] = "سقف مبلغ تخفیف فقط برای کد درصدی است؛ برای مبلغ ثابت آن را خالی بگذارید."
            elif self.max_discount < 1:
                errors["max_discount"] = "سقف مبلغ تخفیف باید بیشتر از صفر باشد یا خالی بماند."
        if self.usage_limit is not None and self.usage_limit < 1:
            errors["usage_limit"] = "سقف کل استفاده باید دست‌کم ۱ باشد یا خالی بماند."
        if self.per_user_limit is not None and self.per_user_limit < 1:
            errors["per_user_limit"] = "سقف استفادهٔ هر مشتری باید دست‌کم ۱ باشد یا خالی بماند."
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            errors["ends_at"] = "پایان اعتبار باید بعد از شروع اعتبار باشد."
        if errors:
            raise ValidationError(errors)

    @property
    def value_display(self):
        if self.kind == DiscountType.PERCENT:
            text = f"{fa_digits(self.value)}٪"
            return f"{text} (حداکثر {toman(self.max_discount)})" if self.max_discount else text
        return toman(self.value)

    def amount(self, items_subtotal, lines=None):
        """The discount in Toman for this items subtotal (orders.pricing.calculate's `discount`)."""
        items_subtotal = int(items_subtotal)
        if self.kind == DiscountType.PERCENT:
            amount = items_subtotal * self.value // 100
            if self.max_discount:
                amount = min(amount, self.max_discount)
        else:
            amount = self.value
        return max(0, min(amount, items_subtotal))

    def uses_by(self, user=None, mobile=None):
        """Confirmed orders with this code by the user's account or by the (verified) mobile."""
        if user is not None and user.is_authenticated:
            mobile = mobile or user.mobile
            who = Q(user=user) | Q(mobile=mobile) if mobile else Q(user=user)
        elif mobile:
            who = Q(mobile=mobile)
        else:
            return 0
        return self.orders.filter(who, discount_counted=True).count()

    def check_usable(self, items_subtotal, user=None, mobile=None, now=None):
        """Raise DiscountError unless the code can be used now for this items subtotal. The per-customer
        limit is only checked once the customer is known (signed in or a verified mobile)."""
        now = now or timezone.now()
        if not self.is_active:
            raise DiscountError("کد تخفیف معتبر نیست.")
        if self.starts_at and now < self.starts_at:
            raise DiscountError(
                f"این کد تخفیف از {jalali_format(self.starts_at, '%Y/%m/%d ساعت %H:%M')} قابل استفاده است."
            )
        if self.ends_at and now >= self.ends_at:
            raise DiscountError("مهلت استفاده از این کد تخفیف تمام شده است.")
        if self.usage_limit is not None and self.used_count >= self.usage_limit:
            raise DiscountError("ظرفیت استفاده از این کد تخفیف تمام شده است.")
        if items_subtotal < self.min_order_amount:
            raise DiscountError(
                f"این کد تخفیف برای خرید دست‌کم {toman(self.min_order_amount)} است؛ "
                f"{toman(self.min_order_amount - items_subtotal)} دیگر کالا به سبد اضافه کنید."
            )
        if self.per_user_limit is not None and self.uses_by(user, mobile) >= self.per_user_limit:
            if self.per_user_limit == 1:
                raise DiscountError("شما قبلاً از این کد تخفیف استفاده کرده‌اید.")
            raise DiscountError(f"سقف استفادهٔ هر مشتری از این کد ({fa_digits(self.per_user_limit)} بار) پر شده است.")


def find_usable_code(text, items_subtotal, user=None, mobile=None):
    """The DiscountCode for `text`, or raise DiscountError with a Persian message."""
    if not normalize_code(text):
        raise DiscountError("کد تخفیف را وارد کنید.")
    code = DiscountCode.objects.find(text)
    if code is None:
        raise DiscountError("کد تخفیف معتبر نیست.")
    code.check_usable(items_subtotal, user=user, mobile=mobile)
    return code


# --- gift pool -----------------------------------------------------------------------


class GiftStockShortage(stock.InsufficientStock):
    """Not enough gift stock left (a subclass, so payment code treats it like any stock shortage)."""

    @property
    def messages(self):
        out = []
        for product, requested, available in self.shortages:
            if available <= 0:
                out.append(f"هدیهٔ «{product.name}» تمام شده است.")
            else:
                out.append(
                    f"موجودی هدیهٔ «{product.name}» کافی نیست (درخواست: {fa_digits(requested)}، باقی‌مانده: {fa_digits(available)})."
                )
        return out


class GiftPoolItemQuerySet(models.QuerySet):
    def available(self):
        """Gifts a customer can pick now: active, with gift stock, product on sale and in stock."""
        from catalog.models import Product

        on_sale = Product.objects.active().filter(stock__gt=0)
        return self.filter(is_active=True, gift_stock__gt=0, product__in=on_sale).select_related("product")


class GiftPoolItem(models.Model):
    product = models.OneToOneField(
        "catalog.Product", verbose_name="محصول", on_delete=models.CASCADE, related_name="gift_pool_item"
    )
    gift_stock = models.PositiveIntegerField(
        "موجودی هدیه",
        default=0,
        help_text="چند عدد از این کالا هدیه داده شود. با هر سفارش تأییدشده کم می‌شود و با لغو آن برمی‌گردد. "
        "موجودی خود محصول هم باید کافی باشد.",
    )
    is_active = models.BooleanField("فعال", default=True)
    order = models.PositiveIntegerField("ترتیب", default=0)

    objects = GiftPoolItemQuerySet.as_manager()

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "کالای هدیه"
        verbose_name_plural = "کالاهای هدیه"

    def __str__(self):
        return self.product.name

    @staticmethod
    def _totals(pairs):
        totals = {}
        for product_id, qty in pairs:
            totals[product_id] = totals.get(product_id, 0) + int(qty)
        return dict(sorted(totals.items()))

    @classmethod
    def reserve(cls, pairs):
        """Take gift stock for [(product_id, qty)]: all or nothing (raises GiftStockShortage)."""
        wanted = cls._totals(pairs)
        if not wanted:
            return
        from catalog.models import Product

        with transaction.atomic():
            items = {i.product_id: i for i in cls.objects.select_for_update().filter(product_id__in=wanted)}
            shortages = []
            for product_id, qty in wanted.items():
                available = items[product_id].gift_stock if product_id in items else 0
                if available < qty:
                    shortages.append((Product.objects.get(pk=product_id), qty, available))
            if shortages:
                raise GiftStockShortage(shortages)
            for product_id, qty in wanted.items():
                if not cls.objects.filter(product_id=product_id, gift_stock__gte=qty).update(
                    gift_stock=F("gift_stock") - qty
                ):
                    raise GiftStockShortage([(Product.objects.get(pk=product_id), qty, 0)])

    @classmethod
    def release(cls, pairs):
        """Give gift stock back (a gift whose pool row was deleted meanwhile is skipped)."""
        for product_id, qty in cls._totals(pairs).items():
            cls.objects.filter(product_id=product_id).update(gift_stock=F("gift_stock") + qty)


class OrderQuerySet(models.QuerySet):
    def for_user(self, user):
        """The user's orders, plus guest orders placed earlier with the same (verified) mobile."""
        return self.filter(Q(user=user) | Q(user__isnull=True, mobile=user.mobile))


class Order(models.Model):
    number = models.CharField("شمارهٔ سفارش", max_length=12, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="کاربر",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
        help_text="خالی یعنی خرید مهمان.",
    )
    mobile = models.CharField("موبایل سفارش‌دهنده", max_length=11, validators=[validate_mobile], db_index=True)

    # Address snapshot
    recipient_name = models.CharField("نام گیرنده", max_length=100)
    recipient_mobile = models.CharField("موبایل گیرنده", max_length=11, validators=[validate_mobile])
    province = models.CharField("استان", max_length=40, choices=PROVINCE_CHOICES)
    city = models.CharField("شهر", max_length=60)
    address = models.CharField("نشانی کامل", max_length=400)
    postal_code = models.CharField("کد پستی", max_length=10, validators=[validate_postal_code])
    note = models.TextField("توضیحات مشتری", max_length=500, blank=True)

    age_confirmed = models.BooleanField("تأیید سن بالای ۱۸ سال", default=False)
    age_confirmed_at = models.DateTimeField("زمان تأیید سن", null=True, blank=True)

    status = models.CharField(
        "وضعیت", max_length=20, choices=OrderStatus.choices, default=OrderStatus.PENDING_PAYMENT, db_index=True
    )
    payment_method = models.CharField("روش پرداخت", max_length=10, choices=PaymentMethod.choices)

    items_subtotal = models.PositiveBigIntegerField("جمع کالاها (تومان)", default=0)
    discount_amount = models.PositiveBigIntegerField("تخفیف (تومان)", default=0)
    discount_code = models.ForeignKey(
        DiscountCode,
        verbose_name="کد تخفیف",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    discount_code_text = models.CharField("کد تخفیف واردشده", max_length=30, blank=True)
    discount_counted = models.BooleanField("استفاده از کد تخفیف شمرده شده", default=False, editable=False)
    shipping_fee = models.PositiveBigIntegerField("هزینهٔ ارسال (تومان)", default=0)
    total = models.PositiveBigIntegerField("مبلغ قابل پرداخت (تومان)", default=0)

    post_tracking_code = models.CharField("کد رهگیری پست", max_length=40, blank=True)
    stock_reserved = models.BooleanField("موجودی کسر شده", default=False, editable=False)
    admin_sms_queued_at = models.DateTimeField("زمان پیامک به مدیر", null=True, blank=True, editable=False)

    created_at = models.DateTimeField("تاریخ ثبت", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("آخرین تغییر", auto_now=True)
    paid_at = models.DateTimeField("زمان تأیید پرداخت", null=True, blank=True)
    shipped_at = models.DateTimeField("زمان ارسال", null=True, blank=True)

    objects = OrderQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "سفارش"
        verbose_name_plural = "سفارش‌ها"
        constraints = [
            models.CheckConstraint(condition=Q(age_confirmed=True), name="order_age_confirmed"),
        ]

    def __str__(self):
        return f"سفارش {self.number}"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = generate_order_number()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("orders:detail", kwargs={"number": self.number})

    # --- read helpers ------------------------------------------------------------

    @property
    def is_confirmed(self):
        return self.status in CONFIRMED_STATUSES

    @property
    def can_pay_online(self):
        return self.payment_method == PaymentMethod.ONLINE and self.status in (S.PENDING_PAYMENT, S.FAILED)

    @property
    def can_submit_card_transfer(self):
        return self.payment_method == PaymentMethod.CARD and self.status == S.PENDING_PAYMENT

    def stock_items(self):
        """Paid items and gifts: both take product stock."""
        return [(item.product_id, item.quantity) for item in self.items.all() if item.product_id]

    def gift_items(self):
        return [(item.product_id, item.quantity) for item in self.items.all() if item.product_id and item.is_gift]

    def sms_context(self):
        return {"order_number": self.number, "total": self.total, "tracking_code": self.post_tracking_code}

    # --- state changes (each runs in its own transaction on a locked row) ------------

    def _locked(self):
        return Order.objects.select_for_update().get(pk=self.pk)

    def _apply(self, new_status, note="", by=None):
        """On a locked instance inside a transaction."""
        if new_status not in TRANSITIONS[self.status]:
            raise InvalidTransition(
                f"تغییر وضعیت از «{S(self.status).label}» به «{S(new_status).label}» مجاز نیست."
            )
        old = self.status
        self.status = new_status
        notify_admin = new_status == S.PAID_PROCESSING and self.admin_sms_queued_at is None
        if notify_admin:  # exactly once per order
            self.admin_sms_queued_at = timezone.now()
        self.save()
        OrderStatusLog.objects.create(
            order=self,
            from_status=old,
            to_status=new_status,
            note=note,
            changed_by=by if by is not None and by.is_authenticated else None,
        )
        key = SMS_ON_STATUS.get(new_status)
        if key:
            mobile, context = self.mobile, self.sms_context()
            transaction.on_commit(lambda: send_sms(mobile, key, context))
        if notify_admin:
            order = self
            transaction.on_commit(lambda: notify_admin_new_order(order))

    def _reserve_stock(self):
        """Product stock (paid items and gifts) and gift stock, all or nothing. Raises
        stock.InsufficientStock / GiftStockShortage and then nothing is taken."""
        if not self.stock_reserved:
            with transaction.atomic():  # a savepoint: a gift shortage also undoes the product stock
                items = self.stock_items()
                if items:
                    stock.reserve(items)
                GiftPoolItem.reserve(self.gift_items())
                self.stock_reserved = True
                self.save(update_fields=["stock_reserved", "updated_at"])

    def _release_stock(self):
        if self.stock_reserved:
            items = self.stock_items()
            if items:
                stock.release(items)
            GiftPoolItem.release(self.gift_items())
            self.stock_reserved = False
            self.save(update_fields=["stock_reserved", "updated_at"])
        self._restore_discount_use()

    def _count_discount_use(self):
        if self.discount_code_id and not self.discount_counted:
            DiscountCode.objects.filter(pk=self.discount_code_id).update(used_count=F("used_count") + 1)
            self.discount_counted = True
            self.save(update_fields=["discount_counted", "updated_at"])

    def _restore_discount_use(self):
        if self.discount_counted:
            DiscountCode.objects.filter(pk=self.discount_code_id, used_count__gt=0).update(
                used_count=F("used_count") - 1
            )
            self.discount_counted = False
            self.save(update_fields=["discount_counted", "updated_at"])

    def change_status(self, new_status, note="", by=None):
        with transaction.atomic():
            self._locked()._apply(new_status, note, by)
        self.refresh_from_db()

    def confirm_payment(self, note="پرداخت تأیید شد.", by=None):
        """Reserve stock and move to paid_processing. Idempotent: False if it was already confirmed.
        Raises stock.InsufficientStock (nothing changes) if stock ran out meanwhile."""
        with transaction.atomic():
            order = self._locked()
            changed = not order.is_confirmed
            if changed:
                order._reserve_stock()
                order._count_discount_use()
                order.paid_at = timezone.now()
                order._apply(S.PAID_PROCESSING, note, by)
        self.refresh_from_db()
        return changed

    def approve(self, by=None, note="پرداخت کارت به کارت تأیید شد."):
        """Admin approves a card-to-card payment. Idempotent; raises InsufficientStock if stock ran out."""
        with transaction.atomic():
            order = self._locked()
            changed = not order.is_confirmed
            if changed:
                if order.status != S.AWAITING_APPROVAL:
                    raise InvalidTransition("فقط سفارش‌های «در انتظار تأیید پرداخت» قابل تأیید هستند.")
                order._reserve_stock()
                order._count_discount_use()
                order.paid_at = timezone.now()
                order._apply(S.PAID_PROCESSING, note, by)
                Payment = order.payments.model
                order.payments.filter(method=PaymentMethod.CARD, status=Payment.Status.PENDING).update(
                    status=Payment.Status.SUCCEEDED, verified_at=order.paid_at
                )
        self.refresh_from_db()
        return changed

    def reject(self, by=None, reason=""):
        """Admin rejects a card-to-card payment: the order is canceled."""
        with transaction.atomic():
            order = self._locked()
            if order.status != S.AWAITING_APPROVAL:
                raise InvalidTransition("فقط سفارش‌های «در انتظار تأیید پرداخت» قابل رد هستند.")
            Payment = order.payments.model
            order.payments.filter(method=PaymentMethod.CARD, status=Payment.Status.PENDING).update(
                status=Payment.Status.REJECTED, message=reason[:255]
            )
            order._release_stock()
            order._apply(S.CANCELED, reason or "پرداخت کارت به کارت رد شد.", by)
        self.refresh_from_db()

    def cancel(self, by=None, note=""):
        """Cancel; stock of a confirmed order goes back."""
        with transaction.atomic():
            order = self._locked()
            if S.CANCELED not in TRANSITIONS[order.status]:
                raise InvalidTransition(f"سفارش «{S(order.status).label}» قابل لغو نیست.")
            order._release_stock()
            order._apply(S.CANCELED, note or "سفارش لغو شد.", by)
        self.refresh_from_db()

    def mark_failed(self, note=""):
        with transaction.atomic():
            order = self._locked()
            order._release_stock()
            order._apply(S.FAILED, note)
        self.refresh_from_db()

    def mark_shipped(self, tracking_code, by=None):
        with transaction.atomic():
            order = self._locked()
            order.post_tracking_code = tracking_code.strip()
            order.shipped_at = timezone.now()
            order._apply(S.SHIPPED, f"کد رهگیری پست: {order.post_tracking_code}", by)
        self.refresh_from_db()

    def mark_delivered(self, by=None):
        self.change_status(S.DELIVERED, by=by)


class OrderItem(models.Model):
    order = models.ForeignKey(Order, verbose_name="سفارش", on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        "catalog.Product", verbose_name="محصول", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    name = models.CharField("نام کالا", max_length=150)
    short_name = models.CharField("نام کوتاه", max_length=40)
    unit = models.CharField("واحد", max_length=30, blank=True)
    unit_price = models.PositiveIntegerField("قیمت واحد (تومان)")
    quantity = models.PositiveIntegerField("تعداد")
    is_gift = models.BooleanField("هدیه", default=False)

    class Meta:
        ordering = ["id"]
        verbose_name = "قلم سفارش"
        verbose_name_plural = "اقلام سفارش"

    def __str__(self):
        return f"{self.name} × {self.quantity}" + (" (هدیه)" if self.is_gift else "")

    @property
    def line_total(self):
        return self.unit_price * self.quantity


class OrderStatusLog(models.Model):
    order = models.ForeignKey(Order, verbose_name="سفارش", on_delete=models.CASCADE, related_name="status_logs")
    from_status = models.CharField("از وضعیت", max_length=20, choices=OrderStatus.choices, blank=True)
    to_status = models.CharField("به وضعیت", max_length=20, choices=OrderStatus.choices)
    note = models.CharField("توضیح", max_length=255, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="توسط", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField("زمان", auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name = "تغییر وضعیت سفارش"
        verbose_name_plural = "تاریخچهٔ وضعیت سفارش‌ها"

    def __str__(self):
        return f"{self.order.number}: {self.from_status} → {self.to_status}"
