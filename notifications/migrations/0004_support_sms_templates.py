from django.db import migrations

# Frozen copy of notifications.defaults at the time of this migration.
TEXTS = {
    "support_reply": "پاسخ پیام شما در {site_name} ثبت شد.\nبرای دیدن پاسخ به حساب کاربری خود سر بزنید.",
    "admin_support_message": "پیام جدید پشتیبانی از {customer}\nموضوع: {ticket_subject}\n{text_preview}",
}


def seed(apps, schema_editor):
    SMSTemplate = apps.get_model("notifications", "SMSTemplate")
    for key, text in TEXTS.items():
        SMSTemplate.objects.get_or_create(key=key, defaults={"text": text})


class Migration(migrations.Migration):
    dependencies = [("notifications", "0003_alter_smslog_template_key_alter_smstemplate_key")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
