import re
from urllib.parse import quote

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from tinymce.models import HTMLField

from catalog.images import process_favicon, validate_favicon_upload, validate_image_upload
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

# Invisible direction marks and joiners that sneak in when a number or ID is pasted from a Persian text.
_INVISIBLE_CHARS = re.compile("[‌‍‎‏‪-‮⁦-⁩﻿]")
_URL_PREFIX = re.compile(r"^(?:https?://)?(?:www\.)?", re.IGNORECASE)


def normalize_whatsapp_number(value):
    """'۰۹۱۲ ۳۴۵ ۶۷۸۹', '+98 912…', '0098912…' or 'wa.me/98912…' -> '989123456789' (international digits only)."""
    value = _INVISIBLE_CHARS.sub("", latin_digits(value)).strip()
    if not value:
        return ""
    link = _URL_PREFIX.sub("", value)
    phone_param = re.search(r"[?&]phone=([^&#]*)", link)
    if phone_param:  # api.whatsapp.com/send?phone=98912…
        link = phone_param.group(1)
    elif re.match(r"wa\.me/", link, re.IGNORECASE):
        link = re.split(r"[?#]", link[len("wa.me/"):])[0]
    number = re.sub(r"[\s\-–().]", "", link).rstrip("/")
    if number.startswith("+"):
        number = number[1:]
    elif number.startswith("00"):
        number = number[2:]
    elif number.startswith("0"):  # Iranian number: 0912… -> 98912…
        number = "98" + number[1:]
    elif len(number) == 10 and number.startswith("9"):  # 912… without the leading 0
        number = "98" + number
    if not re.fullmatch(r"\d{10,15}", number):
        raise ValidationError("شمارهٔ واتساپ معتبر نیست. مثلاً ۰۹۱۲۳۴۵۶۷۸۹ یا ‎+98 912 345 6789‎ وارد کنید.")
    return number


def _normalize_username(value, domains, min_length, error):
    """'@name', 'name', 'https://<domain>/name' -> 'name'."""
    value = _INVISIBLE_CHARS.sub("", latin_digits(value)).strip()
    if not value:
        return ""
    username = _URL_PREFIX.sub("", value)
    for domain in domains:
        if username.lower().startswith(domain + "/"):
            username = username[len(domain) + 1:]
            break
    username = re.split(r"[/?#]", username)[0].lstrip("@")
    if not re.fullmatch(rf"[A-Za-z][A-Za-z0-9_]{{{min_length - 1},31}}", username):
        raise ValidationError(error)
    return username


def normalize_telegram_id(value):
    return _normalize_username(
        value,
        ("t.me", "telegram.me", "telegram.dog"),
        5,
        "آیدی تلگرام معتبر نیست: ۵ تا ۳۲ حرف انگلیسی، رقم یا _ که با حرف شروع شود؛ مثلاً @pichyar_support یا t.me/pichyar_support.",
    )


def normalize_bale_id(value):
    return _normalize_username(
        value,
        ("ble.ir",),
        3,
        "آیدی بله معتبر نیست: ۳ تا ۳۲ حرف انگلیسی، رقم یا _ که با حرف شروع شود؛ مثلاً @pichyar یا ble.ir/pichyar.",
    )


_MESSENGER_NORMALIZERS = (
    ("whatsapp_number", normalize_whatsapp_number),
    ("telegram_id", normalize_telegram_id),
    ("bale_id", normalize_bale_id),
)


class SiteSettings(models.Model):
    """Single-row table holding site-wide settings (always pk=1)."""

    site_name = models.CharField("نام سایت", max_length=100, default="پیچ‌یار")
    logo = models.ImageField(
        "لوگو", upload_to="site/", blank=True, validators=[validate_image_upload], help_text="JPG، PNG یا WebP"
    )
    favicon = models.ImageField(
        "آیکون تب مرورگر (فاوآیکون)",
        upload_to="site/",
        blank=True,
        validators=[validate_favicon_upload],
        help_text="تصویر مربع و ساده (بهتر است دست‌کم ۱۹۲×۱۹۲ پیکسل) با فرمت PNG، ICO، JPG یا WebP. "
        "کنار عنوان صفحه در تب مرورگر و روی صفحهٔ اصلی گوشی نمایش داده می‌شود. خالی باشد، آیکون پیش‌فرض سایت نمایش داده می‌شود.",
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
    sms_site_url = models.URLField(
        "نشانی سایت در پیامک‌ها",
        default="https://pichyar.ir",
        blank=True,
        help_text="در متن پیامک‌ها با متغیر {site_url} نوشته می‌شود.",
    )
    admin_sms_enabled = models.BooleanField(
        "پیامک سفارش جدید به مدیر",
        default=True,
        help_text="برای هر سفارش یک بار، وقتی مشتری سفارش را کامل کرد (رسید کارت به کارت را فرستاد یا پرداخت اینترنتی موفق شد). "
        "اقلام و نشانی سفارش در صفحهٔ همان سفارش برای کپی آماده است.",
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

    # Support: messages inside the site (support app) and messenger links (Bale, WhatsApp, Telegram)
    support_tickets_enabled = models.BooleanField(
        "پیام به پشتیبانی در سایت",
        default=True,
        help_text="مشتریان واردشده می‌توانند از «حساب کاربری ← پیام به پشتیبانی» پیام بفرستند و پاسخ را همان‌جا ببینند.",
    )
    support_intro = models.TextField(
        "متن راهنمای صفحهٔ پیام به پشتیبانی",
        blank=True,
        help_text="مثلاً ساعات پاسخگویی. بالای فرم ارسال پیام نمایش داده می‌شود.",
    )
    support_admin_sms_enabled = models.BooleanField(
        "پیامک پیام جدید پشتیبانی به مدیر",
        default=True,
        help_text="به شماره‌های «پیامک سفارش جدید به مدیر» فرستاده می‌شود.",
    )
    support_reply_sms_enabled = models.BooleanField(
        "پیامک پاسخ پشتیبانی به مشتری", default=True, help_text="وقتی به پیام مشتری پاسخ می‌دهید، با پیامک خبردار می‌شود."
    )
    whatsapp_number = models.CharField(
        "شمارهٔ واتساپ", max_length=20, blank=True, help_text="مثلاً ۰۹۱۲۳۴۵۶۷۸۹ یا ‎+98912…‎. خالی = لینک واتساپ نمایش داده نمی‌شود."
    )
    whatsapp_message = models.CharField(
        "پیام آمادهٔ واتساپ",
        max_length=200,
        blank=True,
        help_text="اختیاری؛ متنی که هنگام باز شدن گفتگو در واتساپ از قبل نوشته شده است.",
    )
    telegram_id = models.CharField(
        "آیدی تلگرام", max_length=100, blank=True, help_text="مثلاً @pichyar_support یا t.me/pichyar_support. خالی = نمایش داده نمی‌شود."
    )
    bale_id = models.CharField(
        "آیدی بله", max_length=100, blank=True, help_text="مثلاً @pichyar یا ble.ir/pichyar. خالی = نمایش داده نمی‌شود."
    )
    messenger_button_enabled = models.BooleanField(
        "دکمهٔ شناور پشتیبانی",
        default=True,
        help_text="دکمه‌ای گوشهٔ پایین صفحه که لینک پیام‌رسان‌ها و پیام در سایت را باز می‌کند.",
    )
    messenger_button_position = models.CharField(
        "جای دکمهٔ شناور", max_length=5, choices=[("left", "پایین چپ"), ("right", "پایین راست")], default="left"
    )
    messenger_button_label = models.CharField("عنوان دکمهٔ شناور", max_length=40, default="پشتیبانی", blank=True)

    class Meta:
        verbose_name = "تنظیمات سایت"
        verbose_name_plural = "تنظیمات سایت"

    def __str__(self):
        return "تنظیمات سایت"

    def save(self, *args, **kwargs):
        self.pk = 1
        if self.favicon and not self.favicon._committed:  # a new upload: store it as a square PNG
            self.favicon = process_favicon(self.favicon)
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
        errors = {}
        try:
            super().clean_fields(exclude)
        except ValidationError as e:
            errors = e.update_error_dict(errors)
        skip = set(exclude or ()) | set(errors)
        if "admin_sms_numbers" not in skip:
            try:
                self._clean_admin_sms_numbers()
            except ValidationError as e:
                errors = e.update_error_dict(errors)
        for name, normalize in _MESSENGER_NORMALIZERS:
            if name in skip:
                continue
            try:
                setattr(self, name, normalize(getattr(self, name)))
            except ValidationError as e:
                errors.setdefault(name, []).extend(e.messages)
        if errors:
            raise ValidationError(errors)

    def _clean_admin_sms_numbers(self):
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
    def whatsapp_url(self):
        if not self.whatsapp_number:
            return ""
        url = f"https://wa.me/{self.whatsapp_number}"
        if self.whatsapp_message.strip():
            url += "?text=" + quote(self.whatsapp_message.strip(), safe="")
        return url

    @property
    def telegram_url(self):
        return f"https://t.me/{self.telegram_id}" if self.telegram_id else ""

    @property
    def bale_url(self):
        return f"https://ble.ir/{self.bale_id}" if self.bale_id else ""

    @property
    def messenger_links(self):
        """Configured messengers, in display order: [{'key': 'bale', 'name': 'بله', 'url': …}, …]."""
        links = (("bale", "بله", self.bale_url), ("whatsapp", "واتساپ", self.whatsapp_url), ("telegram", "تلگرام", self.telegram_url))
        return [{"key": key, "name": name, "url": url} for key, name, url in links if url]

    @property
    def support_button_visible(self):
        """The floating support button is shown only when it has something to offer."""
        return self.messenger_button_enabled and bool(
            self.messenger_links or self.phone.strip() or self.support_tickets_enabled
        )

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
