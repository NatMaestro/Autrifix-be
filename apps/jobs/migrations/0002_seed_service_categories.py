from __future__ import annotations

from django.db import migrations


def seed_service_categories(apps, schema_editor) -> None:
    ServiceCategory = apps.get_model("jobs", "ServiceCategory")

    # Idempotent: only seed if the table is empty.
    if ServiceCategory.objects.exists():
        return

    seeds = [
        {
            "name": "General Mechanic",
            "slug": "general-mechanic",
            "description": "General mechanical assistance when no specific specialist is needed.",
            "is_active": True,
        },
        {
            "name": "Auto Electrical (Battery / Starter)",
            "slug": "battery-electrical",
            "description": "Battery, starter, alternator, wiring and electrical faults.",
            "is_active": True,
        },
        {
            "name": "Engine Expert",
            "slug": "engine-overheat",
            "description": "Overheating, smoke, misfire, stalling and engine running issues.",
            "is_active": True,
        },
        {
            "name": "Tire / Wheel Service",
            "slug": "tire-flat",
            "description": "Flat tire, punctures, wheels and related roadside tire issues.",
            "is_active": True,
        },
        {
            "name": "Towing / Recovery",
            "slug": "tow-recovery",
            "description": "Accidents, recovery, towing and vehicle retrieval.",
            "is_active": True,
        },
        {
            "name": "Brake Service",
            "slug": "brake-pads",
            "description": "Brakes, brake warning, ABS and pad/rotor related issues.",
            "is_active": True,
        },
    ]

    for s in seeds:
        ServiceCategory.objects.create(**s)


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_service_categories, migrations.RunPython.noop),
    ]

