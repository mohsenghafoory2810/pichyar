import re

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from tinymce.models import HTMLField

from catalog.images import validate_image_upload
from seo.models import SEOFields

from .html import sanitize_html
from .persian import latin_digits

SHIPPING_ROUNDING_CHOICES = [("ceil", "رو به بالا (هر بخش ناقص یک پله)"), ("floor", "رو به پایین")]


def gateway_choices():
    from payments.gateways import registry

    return registry.choices()


def sms_provider_choices():
    from notifications.providers import registry

    return registry.choices()


_ADMIN_NUMBER_SEPARATORS = re.compile(r"[\n,،;]+")


class SiteSettings(models.Model):
    """Single-row table holding site-wide settings (always pk=1)."""

    site_name = models.CharField("نام سایت", max_length=100, default="پیچ‌یار")
    logo = models.ImageField(
        "لوگو", upload_to="site/", blank=True, validators=[validate_image_upload], help_text="JPG، PNG یا WebP"
    )
    phone = models.CharField("تلفن پشتیبانی", max_length=30, blank=True)
    support_info = models.TextField(
        "اطلاعات پشتیبانی", blank=True, help_text="مثلاً ساعات پاسخگویی یا آدرس. در پایین صفحه نمایش داده می‌شود."
    )
    maintenance_mode = models.BooleanField(
        "حالت تعمیر و نگهداری",
        default=False,
        help_text="اگر روشن باشد، بازدیدکنندگان صفحهٔ «در حال به‌روزرسانی» را می‌بینند. مدیران سایت همچنان دسترسی دارند.",
    )
    maintenance_message = models.TextField(
        "پیام حالت تعمیر", default="سایت در حال به‌روزرسانی است. به‌زودی برمی‌گردیم.", blank=True
    )

    # Shipping (Iran Post): fee = steps × step fee, steps = subtotal ÷ step amount (rounded).
    shipping_step_amount = models.PositiveIntegerField(
        "هر پلهٔ هزینهٔ ارسال (تومان)",
        default=3_000_000,
        validators=[MinValueValidator(1)],
        help_text="مبلغ خرید هر پله. مثلاً با ۳٬۰۰۰٬۰۰۰، خرید ۴ میلیونی دو پله حساب می‌شود (با گرد کردن رو به بالا).",
    )
    shipping_step_fee = models.PositiveIntegerField(
        "هزینهٔ ارسال هر پله (تومان)", default=200_000, help_text="برای ارسال رایگان صفر بگذارید."
    )
    shipping_rounding = models.CharField(
        "گرد کردن تعداد پله‌ها", max_length=5, choices=SHIPPING_ROUNDING_CHOICES, default="ceil"
    )

    # Payment
    online_payment_enabled = models.BooleanField(
        "پرداخت اینترنتی فعال باشد", default=True, help_text="فقط وقتی کار می‌کند که شناسهٔ پذیرنده (مرچنت) پر شده باشد."
    )
    payment_gateway = models.CharField("درگاه پرداخت", max_length=30, choices=gateway_choices, default="zarinpal")
    gateway_merchant_id = models.CharField(
        "شناسهٔ پذیرنده (مرچنت کد)", max_length=100, blank=True, help_text="از پنل درگاه پرداخت (مثلاً زرین‌پال) بگیرید."
    )
    gateway_sandbox = models.BooleanField(
        "حالت آزمایشی درگاه (سندباکس)",
        default=False,
        help_text="فقط برای آزمایش! در این حالت پولی جابه‌جا نمی‌شود ولی سفارش «پرداخت‌شده» ثبت می‌شود. حتماً بعد از آزمایش خاموش کنید.",
    )
    card_to_card_enabled = models.BooleanField(
        "کارت به کارت فعال باشد", default=True, help_text="کارت‌های فعال پایین همین صفحه به مشتری نشان داده می‌شوند."
    )

    # Gifts: one gift per full threshold of the items subtotal after discount (shipping excluded).
    gift_enabled = models.BooleanField(
        "هدیه فعال باشد", default=True, help_text="کالاهای قابل انتخاب به‌عنوان هدیه در «سفارش‌ها ← کالاهای هدیه» تعیین می‌شوند."
    )
    gift_threshold = models.PositiveBigIntegerField(
        "مبلغ خرید برای هر هدیه (تومان)",
        default=3_000_000,
        validators=[MinValueValidator(1)],
        help_text="به ازای هر بار این مبلغ (جمع کالاها پس از تخفیف، بدون هزینهٔ ارسال) یک هدیه. مثلاً با ۳٬۰۰۰٬۰۰۰، خرید ۷ میلیونی ۲ هدیه دارد.",
    )

    # SMS
    sms_provider = models.CharField("سرویس پیامک", max_length=30, choices=sms_provider_choices, default="kavenegar")
    sms_api_key = models.CharField(
        "کلید API سرویس پیامک",
        max_length=200,
        blank=True,
        help_text="تا وقتی خالی است، پیامکی فرستاده نمی‌شود و متن پیامک‌ها فقط در گزارش برنامه و «گزارش پیامک‌ها» ثبت می‌شود.",
    )
    sms_sender = models.CharField(
        "شمارهٔ فرستنده (خط پیامک)", max_length=30, blank=True, help_text="خالی یعنی خط پیش‌فرض حساب شما در سرویس پیامک."
    )
    admin_sms_enabled = models.BooleanField(
        "پیامک سفارش جدید به مدیر", default=True, help_text="برای هر سفارش، یک بار و پس از تأیید پرداخت فرستاده می‌شود."
    )
    admin_sms_numbers = models.TextField(
        "شماره‌های موبایل مدیر", blank=True, help_text="یک یا چند شماره؛ هر شماره در یک خط (یا جدا با ویرگول)."
    )

    # SEO and content
    site_description = models.TextField(
        "معرفی کوتاه و بی‌طرف سایت",
        blank=True,
        help_text="یکی دو جملهٔ واقعی دربارهٔ فروشگاه. توضیح پیش‌فرض صفحه‌ها و فایل llms.txt از این ساخته می‌شود.",
    )
    organization_name = models.CharField(
        "نام رسمی کسب‌وکار", max_length=150, blank=True, help_text="برای داده‌های ساختاریافته (Organization). خالی = نام سایت."
    )
    social_links = models.TextField(
        "شبکه‌های اجتماعی", blank=True, help_text="نشانی کامل هر صفحه (https://...) در یک خط؛ مثلاً اینستاگرام یا تلگرام."
    )
    default_og_image = models.ImageField(
        "تصویر پیش‌فرض اشتراک‌گذاری (OG)",
        upload_to="site/",
        blank=True,
        validators=[validate_image_upload],
        help_text="وقتی صفحه تصویر خودش را ندارد، در تلگرام، واتساپ و ... نمایش داده می‌شود. پیشنهاد: ۱۲۰۰×۶۳۰ پیکسل.",
    )
    health_warning = models.CharField(
        "هشدار سلامت",
        max_length=300,
        default="استعمال دخانیات برای سلامت مضر است",
        blank=True,
        help_text="در پایین همهٔ صفحه‌ها و در صفحهٔ هر محصول نمایش داده می‌شود.",
    )
    google_site_verification = models.CharField(
        "کد تأیید Google Search Console",
        max_length=200,
        blank=True,
        help_text='فقط مقدار content از تگ متا، مثلاً abc123 در <meta name="google-site-verification" content="abc123">.',
    )
    bing_site_verification = models.CharField(
        "کد تأیید Bing Webmaster", max_length=200, blank=True, help_text="فقط مقدار content از تگ msvalidate.01."
    )
    analytics_snippet = models.TextField(
        "کد آمار بازدید (اختیاری)",
        blank=True,
        help_text="کد کامل اسکریپت آمار (مثلاً یک سرویس آمار خودمیزبان). پایین همهٔ صفحه‌های عمومی قرار می‌گیرد. "
        "فقط کدی را که به منبع آن اطمینان دارید وارد کنید.",
    )
    allow_ai_crawlers = models.BooleanField(
        "اجازه به خزنده‌های هوش مصنوعی",
        default=True,
        help_text="GPTBot، ClaudeBot، PerplexityBot، Google-Extended و CCBot. خاموش باشد، در robots.txt مسدود می‌شوند.",
    )

    class Meta:
        verbose_name = "تنظیمات سایت"
        verbose_name_plural = "تنظیمات سایت"

    def __str__(self):
        return "تنظیمات سایت"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass  # singleton: never deleted

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def active_cards(self):
        return self.cards.filter(is_active=True)

    def clean_fields(self, exclude=None):
        super().clean_fields(exclude)
        if exclude and "admin_sms_numbers" in exclude:
            return
        from accounts.validators import normalize_mobile

        numbers, bad = [], []
        for part in _ADMIN_NUMBER_SEPARATORS.split(self.admin_sms_numbers or ""):
            if not part.strip():
                continue
            try:
                number = normalize_mobile(part)
            except ValidationError:
                bad.append(part.strip())
            else:
                if number not in numbers:
                    numbers.append(number)
        if bad:
            raise ValidationError(
                {"admin_sms_numbers": f"این شماره‌ها معتبر نیستند: {'، '.join(bad)}. هر شماره باید مثل ۰۹۱۲۳۴۵۶۷۸۹ باشد."}
            )
        self.admin_sms_numbers = "\n".join(numbers)

    @property
    def organization_display_name(self):
        return self.organization_name or self.site_name

    @property
    def social_urls(self):
        return [u.strip() for u in (self.social_links or "").splitlines() if u.strip().startswith("https://")]

    @property
    def admin_mobiles(self):
        return [n.strip() for n in _ADMIN_NUMBER_SEPARATORS.split(self.admin_sms_numbers or "") if n.strip()]

    @property
    def sms_configured(self):
        return bool(self.sms_api_key.strip())

    @property
    def online_payment_available(self):
        return self.online_payment_enabled and bool(self.gateway_merchant_id.strip())

    @property
    def card_to_card_available(self):
        return self.card_to_card_enabled and self.active_cards().exists()


card_number_validator = RegexValidator(r"^\d{16}$", "شماره کارت باید ۱۶ رقم باشد.")


class BankCard(models.Model):
    """Card numbers shown to customers for card-to-card payment."""

    settings = models.ForeignKey(SiteSettings, on_delete=models.CASCADE, related_name="cards")
    card_number = models.CharField("شماره کارت", max_length=24, validators=[card_number_validator])
    holder_name = models.CharField("نام صاحب کارت", max_length=100)
    bank_name = models.CharField("نام بانک", max_length=50, blank=True)
    is_active = models.BooleanField("فعال", default=True)
    order = models.PositiveIntegerField("ترتیب", default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "کارت بانکی"
        verbose_name_plural = "کارت‌های بانکی"

    def __str__(self):
        return f"{self.holder_name} - {self.card_number}"

    def clean_fields(self, exclude=None):
        # Accept Persian digits and spaces/dashes typed by the admin.
        self.card_number = latin_digits(self.card_number).replace(" ", "").replace("-", "")
        super().clean_fields(exclude)

    @property
    def card_number_display(self):
        """'6037991234567890' -> '6037-9912-3456-7890' (LTR groups of four)."""
        return "-".join(self.card_number[i : i + 4] for i in range(0, len(self.card_number), 4))


class StaticPage(SEOFields, models.Model):
    title = models.CharField("عنوان", max_length=150)
    slug = models.SlugField("نشانی (slug)", max_length=80, unique=True, allow_unicode=True)
    body = HTMLField("متن", blank=True)
    is_active = models.BooleanField("فعال", default=True)
    show_in_footer = models.BooleanField("نمایش در پایین سایت", default=True)
    order = models.PositiveIntegerField("ترتیب", default=0)
    updated_at = models.DateTimeField("آخرین ویرایش", auto_now=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "صفحهٔ ثابت"
        verbose_name_plural = "صفحه‌های ثابت"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        self.body = sanitize_html(self.body)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("core:page", kwargs={"slug": self.slug})


class Banner(models.Model):
    title = models.CharField("عنوان", max_length=150, help_text="برای نابینایان و موتورهای جستجو خوانده می‌شود.")
    image = models.ImageField(
        "تصویر",
        upload_to="banners/",
        validators=[validate_image_upload],
        help_text="JPG، PNG یا WebP. پیشنهاد: ۱۶۰۰×۶۴۰ پیکسل",
    )
    alt_text = models.CharField(
        "متن جایگزین تصویر (alt)", max_length=150, blank=True, help_text="خالی بماند، عنوان بنر استفاده می‌شود."
    )
    link = models.CharField("لینک", max_length=300, blank=True, help_text="مثلاً /pages/about/ یا نشانی کامل")
    order = models.PositiveIntegerField("ترتیب", default=0)
    is_active = models.BooleanField("فعال", default=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "بنر صفحهٔ اصلی"
        verbose_name_plural = "بنرهای صفحهٔ اصلی"

    def __str__(self):
        return self.title

    def clean(self):
        if self.link and not (self.link.startswith("/") or self.link.startswith("https://")):
            raise ValidationError({"link": "لینک باید با / یا https:// شروع شود."})
