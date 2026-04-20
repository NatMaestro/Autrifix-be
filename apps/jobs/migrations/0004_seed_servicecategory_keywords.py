from __future__ import annotations

from django.db import migrations


def seed_keywords(apps, schema_editor) -> None:
    ServiceCategory = apps.get_model("jobs", "ServiceCategory")
    by_slug = {c.slug: c for c in ServiceCategory.objects.all()}

    defaults = {
        "general-mechanic": "mechanic,general service,inspection,strange noise,unknown issue",
        "battery-electrical": "battery,jump start,starter,alternator,wiring,fuse,lights,won't start",
        "engine-overheat": "engine,overheat,smoke,misfire,stall,rough idle,timing belt,knocking",
        "tire-flat": "tire,tyre,flat,puncture,blowout,wheel,rim",
        "tow-recovery": "tow,towing,recovery,accident,collision,crash,stuck",
        "brake-pads": "brake,braking,abs,pad,rotor,squeal",
    }
    priorities = {
        "general-mechanic": 10,
        "battery-electrical": 20,
        "engine-overheat": 30,
        "tire-flat": 40,
        "tow-recovery": 50,
        "brake-pads": 60,
    }

    for slug, keywords in defaults.items():
        category = by_slug.get(slug)
        if not category:
            continue
        changed = False
        if not (category.keywords or "").strip():
            category.keywords = keywords
            changed = True
        if category.priority == 100:
            category.priority = priorities.get(slug, 100)
            changed = True
        if changed:
            category.save(update_fields=["keywords", "priority"])


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0003_servicecategory_routing_fields"),
    ]

    operations = [
        migrations.RunPython(seed_keywords, migrations.RunPython.noop),
    ]
