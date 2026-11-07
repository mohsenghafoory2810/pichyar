"""Default SMS texts and the placeholders each template may use ({name} in the text)."""

ORDER_VARS = ("order_number", "total", "tracking_code", "site_name")

TEMPLATES = {
    "otp": {
        "label": "کد تأیید (ورود و تسویه حساب)",
        "vars": ("code", "site_name"),
        "text": "کد تأیید شما در {site_name}: {code}\nاین کد را به کسی ندهید.",
    },
    "order_registered": {
        "label": "ثبت سفارش (به مشتری)",
        "vars": ORDER_VARS,
        "text": "سفارش {order_number} در {site_name} ثبت شد.\nمبلغ قابل پرداخت: {total} تومان",
    },
    "payment_confirmed": {
        "label": "تأیید پرداخت (به مشتری)",
        "vars": ORDER_VARS,
        "text": "پرداخت سفارش {order_number} تأیید شد و سفارش شما در حال آماده‌سازی است.\n{site_name}",
    },
    "shipped": {
        "label": "ارسال سفارش (به مشتری، با کد رهگیری)",
        "vars": ORDER_VARS,
        "text": "سفارش {order_number} به پست تحویل داده شد.\nکد رهگیری پست: {tracking_code}\nپیگیری: tracking.post.ir\n{site_name}",
    },
    "admin_new_order": {
        "label": "سفارش جدید (به مدیر)",
        "vars": ("order_text", *ORDER_VARS),
        "text": "{order_text}",
    },
}

KEY_CHOICES = [(key, t["label"]) for key, t in TEMPLATES.items()]
