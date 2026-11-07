from django.db import migrations

PAGES = [
    ("about", "درباره ما", "<p>متن معرفی فروشگاه را از بخش مدیریت ویرایش کنید.</p>"),
    ("contact", "تماس با ما", "<p>راه‌های تماس با فروشگاه را از بخش مدیریت ویرایش کنید.</p>"),
    ("shipping", "شیوهٔ ارسال", "<p>روش‌ها و هزینهٔ ارسال را از بخش مدیریت ویرایش کنید.</p>"),
    ("terms", "قوانین و مقررات", "<p>فروش محصولات این فروشگاه فقط به افراد بالای ۱۸ سال انجام می‌شود.</p>"),
    ("privacy", "حریم خصوصی", "<p>سیاست حفظ حریم خصوصی را از بخش مدیریت ویرایش کنید.</p>"),
]


def seed(apps, schema_editor):
    SiteSettings = apps.get_model("core", "SiteSettings")
    StaticPage = apps.get_model("core", "StaticPage")
    SiteSettings.objects.get_or_create(pk=1)
    for order, (slug, title, body) in enumerate(PAGES):
        StaticPage.objects.get_or_create(slug=slug, defaults={"title": title, "body": body, "order": order})


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
