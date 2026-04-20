# Generated manually — allow email-only accounts (Google / password email signup).

from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_user_avatar"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="phone",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=20,
                null=True,
                unique=True,
                verbose_name="phone number",
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=Q(phone__isnull=False) | Q(email__isnull=False),
                name="accounts_user_phone_or_email",
            ),
        ),
    ]
