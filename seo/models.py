from django.core.exceptions import ValidationError
from django.db import models

META_TITLE_MAX = 60
META_DESCRIPTION_MAX = 160


class SEOFields(models.Model):
    """Per-object SEO fields. Empty fields fall back to smart defaults (seo.meta)."""

    meta_title = models.CharField(
        "عنوان سئو (title)",
        max_length=70,
        blank=True,
        help_text=f"حداکثر حدود {META_TITLE_MAX} نویسه. خالی بماند، از نام/عنوان ساخته می‌شود.",
    )
    meta_description = models.CharField(
        "توضیح متا (description)",
        max_length=200,
        blank=True,
        help_text=f"حدود ۷۰ تا {META_DESCRIPTION_MAX} نویسه. خالی بماند، خودکار از متن ساخته می‌شود.",
    )
    canonical_url = models.CharField(
        "نشانی canonical دلخواه",
        max_length=300,
        blank=True,
        help_text="فقط وقتی این صفحه کپی صفحهٔ دیگری است. خالی = نشانی خود همین صفحه (پیشنهادی).",
    )
    noindex = models.BooleanField(
        "عدم نمایش در نتایج جستجو (noindex)",
        default=False,
        help_text="روشن باشد، موتورهای جستجو این صفحه را فهرست نمی‌کنند و در نقشهٔ سایت نمی‌آید.",
    )

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        url = (self.canonical_url or "").strip()
        if url and not (url.startswith("/") or url.startswith("https://")):
            raise ValidationError({"canonical_url": "نشانی canonical باید با / یا https:// شروع شود."})


class Redirect(models.Model):
    """A permanent (301) redirect from an old path. Created by hand or automatically
    when a slug changes (seo.redirects)."""

    old_path = models.CharField(
        "نشانی قدیمی",
        max_length=300,
        unique=True,
        help_text="مسیر نسبی، مثلاً /p/نام-قدیمی/ (بدون دامنه).",
    )
    new_path = models.CharField("نشانی جدید", max_length=300, help_text="مسیر نسبی مثل /p/نام-جدید/ یا نشانی کامل https://")
    is_active = models.BooleanField("فعال", default=True)
    is_automatic = models.BooleanField("خودکار (تغییر نشانی)", default=False, editable=False)
    hits = models.PositiveIntegerField("تعداد بازدید", default=0, editable=False)
    created_at = models.DateTimeField("تاریخ ایجاد", auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "ریدایرکت ۳۰۱"
        verbose_name_plural = "ریدایرکت‌ها (۳۰۱)"

    def __str__(self):
        return f"{self.old_path} → {self.new_path}"

    def clean(self):
        errors = {}
        if not self.old_path.startswith("/"):
            errors["old_path"] = "نشانی قدیمی باید با / شروع شود."
        if not (self.new_path.startswith("/") or self.new_path.startswith("https://")):
            errors["new_path"] = "نشانی جدید باید با / یا https:// شروع شود."
        if self.old_path and self.old_path == self.new_path:
            errors["new_path"] = "نشانی جدید نمی‌تواند همان نشانی قدیمی باشد."
        if errors:
            raise ValidationError(errors)
