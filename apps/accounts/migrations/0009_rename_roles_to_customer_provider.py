"""Rename role values: driver -> customer, mechanic -> provider (ADR-020).

The values are stored strings, so this is a data migration, not just a choices change.
Reversible: the down path restores the old values exactly.
"""

from django.db import migrations, models


def forwards(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="driver").update(role="customer")
    User.objects.filter(role="mechanic").update(role="provider")


def backwards(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="customer").update(role="driver")
    User.objects.filter(role="provider").update(role="mechanic")


class Migration(migrations.Migration):
    dependencies = [("accounts", "0008_user_is_phone_verified")]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("customer", "Customer"),
                    ("provider", "Service provider"),
                    ("admin", "Admin"),
                ],
                db_index=True,
                default="customer",
                max_length=20,
            ),
        ),
    ]
