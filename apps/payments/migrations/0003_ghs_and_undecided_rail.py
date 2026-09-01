"""Correct two market assumptions baked into the payment stub.

``currency`` defaulted to ``USD`` and ``provider`` to ``stripe``. Neither survives contact
with the launch market: Ghana settles in cedis, and predominantly over mobile money rather
than cards. Nothing writes ``Payment`` today, so this is a correction to scaffolding rather
than a data migration with real rows at stake — but the backfill runs anyway, because
"there are no rows" is an assumption about production this migration should not make.

Renames rather than drop-and-add: ``amount_cents`` -> ``amount_minor`` (pesewas are not
cents) and ``provider`` -> ``processor`` (``provider`` collides with the platform's word
for a service provider, which made the field actively misleading).

See ``specs/015-money-model.md`` and ``docs/DECISIONS.md`` ADR-022.
"""

from django.db import migrations, models

import apps.payments.models


def clear_stale_defaults(apps, schema_editor):
    Payment = apps.get_model("payments", "Payment")
    Payment.objects.filter(processor="stripe").update(processor="")
    Payment.objects.filter(currency="USD").update(currency="GHS")


def restore_stale_defaults(apps, schema_editor):
    """Reverse is deliberately a no-op on values.

    Re-stamping rows with ``USD``/``stripe`` would reintroduce the wrong data; unwinding
    the schema is enough.
    """


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0002_alter_payment_escrow_status"),
    ]

    operations = [
        migrations.RenameField(
            model_name="payment",
            old_name="amount_cents",
            new_name="amount_minor",
        ),
        migrations.RenameField(
            model_name="payment",
            old_name="provider",
            new_name="processor",
        ),
        migrations.AlterField(
            model_name="payment",
            name="amount_minor",
            field=models.PositiveIntegerField(
                help_text="Amount in minor units (pesewas for GHS)."
            ),
        ),
        migrations.AlterField(
            model_name="payment",
            name="processor",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AlterField(
            model_name="payment",
            name="currency",
            field=models.CharField(
                default=apps.payments.models.default_currency, max_length=3
            ),
        ),
        migrations.AddField(
            model_name="payment",
            name="rail",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "Undecided"),
                    ("mobile_money", "Mobile money"),
                    ("card", "Card"),
                    ("bank_transfer", "Bank transfer"),
                    ("cash", "Cash, settled off-platform"),
                ],
                default="",
                max_length=32,
            ),
        ),
        migrations.RunPython(clear_stale_defaults, restore_stale_defaults),
    ]
