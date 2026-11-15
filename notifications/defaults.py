"""Default SMS texts and the placeholders each template may use ({name} in the text).

{site_name} and {site_url} (SiteSettings) can be used in every template. "can_disable": False
marks a message that cannot be switched off (the login code)."""

ORDER_VARS = ("order_number", "total", "tracking_code", "site_name", "site_url")

TEMPLATES = {
    "otp": {
        "label": "کد تأیید (ورود و تسویه حساب)",
        "vars": ("code", "site_name", "site_url"),
        "text": "کد تأیید شما در {site_name}: {code}\nاین کد را به کسی ندهید.\n{site_url}",
        "can_disable": False,
    },
    "order_registered": {
        "label": "ثبت سفارش (به مشتری)",
        "vars": ORDER_VARS,
        "text": "سفارش {order_number} در {site_name} ثبت شد.\nمبلغ قابل پرداخت: {total} تومان\n{site_url}",
    },
    "payment_confirmed": {
        "label": "تأیید پرداخت (به مشتری)",
        "vars": ORDER_VARS,
        "text": "پرداخت سفارش {order_number} تأیید شد و سفارش شما در حال آماده‌سازی است.\n{site_name}\n{site_url}",
    },
    "shipped": {
        "label": "ارسال سفارش (به مشتری، با کد رهگیری)",
        "vars": ORDER_VARS,
        "text": "سفارش {order_number} به پست تحویل داده شد.\nکد رهگیری پست: {tracking_code}\nپیگیری: tracking.post.ir\n{site_name}\n{site_url}",
    },
    "admin_new_order": {
        "label": "ثبت سفارش جدید (به مدیر)",
        "vars": ("customer", "payment_method", *ORDER_VARS),
        "text": "سفارش جدید {order_number} ثبت شد.\nمبلغ: {total} تومان - {payment_method}\nجزئیات سفارش در پنل مدیریت.",
    },
    "support_reply": {
        "label": "پاسخ پشتیبانی (به مشتری)",
        "vars": ("ticket_subject", "site_name", "site_url"),
        "text": "پاسخ پیام شما در {site_name} ثبت شد.\nبرای دیدن پاسخ به حساب کاربری خود سر بزنید.\n{site_url}",
    },
    "admin_support_message": {
        "label": "پیام جدید پشتیبانی (به مدیر)",
        "vars": ("customer", "ticket_subject", "text_preview", "site_name", "site_url"),
        "text": "پیام جدید پشتیبانی از {customer}\nموضوع: {ticket_subject}\n{text_preview}",
    },
}

KEY_CHOICES = [(key, t["label"]) for key, t in TEMPLATES.items()]


def can_disable(key):
    return TEMPLATES.get(key, {}).get("can_disable", True)
