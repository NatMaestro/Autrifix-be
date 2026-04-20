# Remove EmailOTP — email verification deferred to a later release.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_email_otp"),
    ]

    operations = [
        migrations.DeleteModel(name="EmailOTP"),
    ]
