from django.db import migrations

# (slug, name, [(slug, name), ...]) -- kept here (not imported) so the migration never changes.
TREE = [
    ("tobacco", "توتون", []),
    (
        "accessories",
        "لوازم",
        [
            ("machines", "دستگاه‌ها"),
            ("tubes", "پوکه"),
            ("papers", "پیپر"),
            ("filters", "فیلتر"),
            ("holders", "چوب سیگار"),
            ("pipes", "پیپ"),
            ("cigars", "سیگار برگ"),
            ("other", "سایر"),
        ],
    ),
]


def seed(apps, schema_editor):
    Category = apps.get_model("catalog", "Category")
    for order, (slug, name, children) in enumerate(TREE):
        parent, _ = Category.objects.get_or_create(slug=slug, defaults={"name": name, "order": order})
        for child_order, (child_slug, child_name) in enumerate(children):
            Category.objects.get_or_create(
                slug=child_slug, defaults={"name": child_name, "parent": parent, "order": child_order}
            )


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
