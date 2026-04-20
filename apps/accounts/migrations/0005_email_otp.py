# Generated manually — email verification OTP (hashed at rest).

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_user_phone_optional"),
    ]

    operations = [
        migrations.CreateModel(
            name="EmailOTP",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("email", models.CharField(db_index=True, max_length=254)),
                ("code_hash", models.CharField(max_length=128)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["email", "-created_at"],
                        name="accounts_em_email_created_idx",
                    ),
                ],
            },
        ),
    ]
