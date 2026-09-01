"""DriverProfile -> CustomerProfile (ADR-020).

``RenameModel`` preserves the table and its rows; the app *label* stays ``drivers``, so
the table remains ``drivers_customerprofile``. See ``apps/customers/apps.py`` for why.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("drivers", "0003_alter_driverprofile_home_latitude_and_more")]

    operations = [
        migrations.RenameModel(old_name="DriverProfile", new_name="CustomerProfile"),
        migrations.RenameField(
            model_name="vehicle", old_name="driver", new_name="customer"
        ),
        migrations.AlterModelOptions(
            name="customerprofile", options={"ordering": ["-created_at"]}
        ),
    ]
