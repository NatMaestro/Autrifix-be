"""Mark the towing category as relocating the vehicle (SPEC-014 REQ-4).

Category-driven rather than slug-driven in application code, but the seed itself has to
name the slug once. Idempotent and reversible.
"""

from django.db import migrations

TOW_SLUGS = ["tow-recovery"]


def forwards(apps, schema_editor):
    ServiceCategory = apps.get_model("jobs", "ServiceCategory")
    ServiceCategory.objects.filter(slug__in=TOW_SLUGS).update(requires_destination=True)


def backwards(apps, schema_editor):
    ServiceCategory = apps.get_model("jobs", "ServiceCategory")
    ServiceCategory.objects.filter(slug__in=TOW_SLUGS).update(requires_destination=False)


class Migration(migrations.Migration):
    dependencies = [("jobs", "0008_servicecategory_requires_destination_and_more")]

    operations = [migrations.RunPython(forwards, backwards)]
