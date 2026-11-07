from django.db import migrations

# Frozen copy of notifications.defaults at the time of this migration.
TEXTS = {
    "otp": "کد تأیید شما در {site_name}: {code}\nاین کد را به کسی ندهید.",
    "order_registered": "سفارش {order_number} در {site_name} ثبت شد.\nمبلغ قابل پرداخت: {total} تومان",
    "payment_confirmed": "پرداخت سفارش {order_number} تأیید شد و سفارش شما در حال آماده‌سازی است.\n{site_name}",
    "shipped": "سفارش {order_number} به پست تحویل داده شد.\nکد رهگیری پست: {tracking_code}\nپیگیری: tracking.post.ir\n{site_name}",
    "admin_new_order": "{order_text}",
}


def seed(apps, schema_editor):
    SMSTemplate = apps.get_model("notifications", "SMSTemplate")
    for key, text in TEXTS.items():
        SMSTemplate.objects.get_or_create(key=key, defaults={"text": text})


class Migration(migrations.Migration):
    dependencies = [("notifications", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
