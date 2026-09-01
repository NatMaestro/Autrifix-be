from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0004_seed_servicecategory_keywords"),
        ("mechanics", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="MechanicServiceOffering",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("title", models.CharField(blank=True, max_length=120)),
                ("description", models.TextField(blank=True)),
                ("hourly_rate", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="mechanic_offerings",
                        to="jobs.servicecategory",
                    ),
                ),
                (
                    "mechanic",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="service_offerings",
                        to="mechanics.mechanicprofile",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "unique_together": {("mechanic", "category", "title")},
            },
        ),
        migrations.AddIndex(
            model_name="mechanicserviceoffering",
            index=models.Index(fields=["mechanic", "is_active"], name="mechanics_m_mechani_bf1fb6_idx"),
        ),
    ]
