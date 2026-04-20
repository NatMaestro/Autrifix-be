from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0002_seed_service_categories"),
    ]

    operations = [
        migrations.AddField(
            model_name="servicecategory",
            name="default_radius_km",
            field=models.PositiveSmallIntegerField(default=25),
        ),
        migrations.AddField(
            model_name="servicecategory",
            name="keywords",
            field=models.TextField(
                blank=True,
                help_text="Comma-separated synonyms used by the issue router (e.g. battery,jump start,alternator).",
            ),
        ),
        migrations.AddField(
            model_name="servicecategory",
            name="priority",
            field=models.PositiveSmallIntegerField(default=100),
        ),
    ]
