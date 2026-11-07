"""The mobile number becomes the username; first/last name become one `name` field.

`username` is renamed (not dropped), so existing accounts keep working: an admin
created as e.g. "admin" still signs in to the admin panel with "admin" until the
mobile is changed there. Usernames that already are mobile numbers are normalised.
"""

from django.core.exceptions import ValidationError
from django.db import migrations, models

import accounts.models
import accounts.validators


def combine_names(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    for user in User.objects.all():
        user.name = f"{user.first_name} {user.last_name}".strip()[:100]
        user.save(update_fields=["name"])


def normalise_mobiles(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    taken = set(User.objects.values_list("mobile", flat=True))
    for user in User.objects.all():
        try:
            mobile = accounts.validators.normalize_mobile(user.mobile)
        except ValidationError:
            continue
        if mobile != user.mobile and mobile not in taken:
            taken.add(mobile)
            user.mobile = mobile
            user.save(update_fields=["mobile"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="name",
            field=models.CharField(blank=True, max_length=100, verbose_name="نام و نام خانوادگی"),
        ),
        migrations.RunPython(combine_names, migrations.RunPython.noop),
        migrations.RenameField(model_name="user", old_name="username", new_name="mobile"),
        migrations.RemoveField(model_name="user", name="first_name"),
        migrations.RemoveField(model_name="user", name="last_name"),
        migrations.RunPython(normalise_mobiles, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="mobile",
            field=models.CharField(
                error_messages={"unique": "کاربری با این شمارهٔ موبایل وجود دارد."},
                max_length=11,
                unique=True,
                validators=[accounts.validators.validate_mobile],
                verbose_name="شمارهٔ موبایل",
            ),
        ),
        migrations.AlterModelManagers(name="user", managers=[("objects", accounts.models.UserManager())]),
    ]
