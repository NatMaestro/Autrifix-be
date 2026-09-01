"""ServiceRequest.driver -> customer, Job.mechanic -> provider (ADR-020).

``RenameField`` renames the column in place; no data movement.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0006_alter_job_notes_alter_servicerequest_description_and_more"),
        ("drivers", "0004_rename_driverprofile_customerprofile"),
        ("mechanics", "0006_rename_mechanic_models_to_provider"),
    ]

    operations = [
        migrations.RenameField(
            model_name="servicerequest", old_name="driver", new_name="customer"
        ),
        migrations.RenameField(model_name="job", old_name="mechanic", new_name="provider"),
    ]
