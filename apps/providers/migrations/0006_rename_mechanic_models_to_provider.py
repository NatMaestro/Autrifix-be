"""Mechanic* -> Provider* models, plus provider_type (ADR-020 / SPEC-014).

Renames preserve tables and rows. The app label stays ``mechanics``, so tables remain
``mechanics_*`` — see ``apps/providers/apps.py``.

**Ordering matters.** ``RenameField`` does not rewrite ``Meta.indexes`` or
``Meta.constraints`` that reference the old field name, and SQLite rebuilds the whole
table on any ``AlterField`` — at which point it tries to recreate an index pointing at a
column that no longer exists. So: drop the dependent index and constraint first, rename,
then recreate them against the new name.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mechanics", "0005_mechanicprofile_verification_level_and_more"),
        # Historical data migrations resolve models by their *old* names, so they must all
        # have run before the rename. Without this the graph may interleave them and
        # reviews/0003 fails with KeyError: 'mechanicprofile'.
        ("reviews", "0003_backfill_mechanic_ratings"),
    ]

    operations = [
        # 1. Drop everything that references the soon-to-be-renamed columns.
        migrations.RemoveIndex(
            model_name="mechanicserviceoffering", name="mechanics_m_mechani_327492_idx"
        ),
        migrations.RemoveConstraint(
            model_name="mechanicverification",
            name="unique_pending_verification_per_mechanic",
        ),
        # 2. Rename the models.
        migrations.RenameModel(old_name="MechanicProfile", new_name="ProviderProfile"),
        migrations.RenameModel(
            old_name="MechanicServiceOffering", new_name="ProviderServiceOffering"
        ),
        migrations.RenameModel(
            old_name="MechanicVerification", new_name="ProviderVerification"
        ),
        # 3. Rename the foreign keys that pointed at the profile.
        migrations.RenameField(
            model_name="providerserviceoffering", old_name="mechanic", new_name="provider"
        ),
        migrations.RenameField(
            model_name="providerverification", old_name="mechanic", new_name="provider"
        ),
        # 4. Recreate the dropped index and constraint against the new field name.
        migrations.AddIndex(
            model_name="providerserviceoffering",
            index=models.Index(
                fields=["provider", "is_active"], name="mechanics_p_provide_7a4352_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="providerverification",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "pending")),
                fields=("provider",),
                name="unique_pending_verification_per_provider",
            ),
        ),
        # 5. The new trade discriminator.
        migrations.AddField(
            model_name="providerprofile",
            name="provider_type",
            field=models.CharField(
                choices=[
                    ("mechanic", "Mechanic"),
                    ("tow", "Tow operator"),
                    ("both", "Mechanic and tow operator"),
                ],
                db_index=True,
                default="mechanic",
                help_text=(
                    "Trade this provider is in. Capability detail lives on service offerings."
                ),
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="providerserviceoffering",
            name="category",
            field=models.ForeignKey(
                on_delete=models.deletion.PROTECT,
                related_name="provider_offerings",
                to="jobs.servicecategory",
            ),
        ),
    ]
