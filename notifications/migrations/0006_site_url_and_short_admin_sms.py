from django.db import migrations

# Frozen copy of notifications.defaults at the time of this migration.
CUSTOMER_KEYS = ("otp", "order_registered", "payment_confirmed", "shipped", "support_reply")
ADMIN_NEW_ORDER = "سفارش جدید {order_number} ثبت شد.\nمبلغ: {total} تومان - {payment_method}\nجزئیات سفارش در پنل مدیریت."


def forwards(apps, schema_editor):
    """Customer messages get the site address; the admin's new-order message no longer carries
    the whole order (it is shown on the admin order page instead)."""
    SMSTemplate = apps.get_model("notifications", "SMSTemplate")
    for row in SMSTemplate.objects.filter(key__in=CUSTOMER_KEYS):
        if "{site_url}" not in row.text:
            row.text = row.text.rstrip() + "\n{site_url}"
            row.save(update_fields=["text"])
    for row in SMSTemplate.objects.filter(key="admin_new_order"):
        if "{order_text}" in row.text:
            row.text = ADMIN_NEW_ORDER
            row.save(update_fields=["text"])
    SMSTemplate.objects.get_or_create(key="admin_new_order", defaults={"text": ADMIN_NEW_ORDER})


def backwards(apps, schema_editor):
    SMSTemplate = apps.get_model("notifications", "SMSTemplate")
    for row in SMSTemplate.objects.filter(key__in=CUSTOMER_KEYS):
        row.text = row.text.replace("\n{site_url}", "")
        row.save(update_fields=["text"])
    SMSTemplate.objects.filter(key="admin_new_order", text=ADMIN_NEW_ORDER).update(text="{order_text}")


class Migration(migrations.Migration):
    dependencies = [("notifications", "0005_smstemplate_is_active_alter_smslog_template_key_and_more")]

    operations = [migrations.RunPython(forwards, backwards)]
