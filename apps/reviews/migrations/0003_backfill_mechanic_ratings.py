"""Backfill ``MechanicProfile.rating_avg`` / ``rating_count`` from existing reviews.

Nothing wrote these fields before ``apps.reviews.services.recalculate_mechanic_rating``
existed, so any reviews already in the database never reached a mechanic's profile.
"""

from decimal import Decimal

from django.db import migrations
from django.db.models import Avg, Count


def backfill_ratings(apps, schema_editor) -> None:
    Review = apps.get_model("reviews", "Review")
    MechanicProfile = apps.get_model("mechanics", "MechanicProfile")

    aggregates = (
        Review.objects.values("job__mechanic_id")
        .annotate(average=Avg("rating"), total=Count("id"))
        .order_by()
    )
    for row in aggregates:
        mechanic_id = row["job__mechanic_id"]
        if mechanic_id is None:
            continue
        MechanicProfile.objects.filter(pk=mechanic_id).update(
            rating_avg=Decimal(row["average"] or 0).quantize(Decimal("0.01")),
            rating_count=row["total"] or 0,
        )


def reset_ratings(apps, schema_editor) -> None:
    MechanicProfile = apps.get_model("mechanics", "MechanicProfile")
    MechanicProfile.objects.update(rating_avg=Decimal("0.00"), rating_count=0)


class Migration(migrations.Migration):
    dependencies = [
        ("reviews", "0002_alter_review_comment_and_more"),
        ("mechanics", "0004_alter_mechanicprofile_base_latitude_and_more"),
        ("jobs", "0006_alter_job_notes_alter_servicerequest_description_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_ratings, reset_ratings),
    ]
