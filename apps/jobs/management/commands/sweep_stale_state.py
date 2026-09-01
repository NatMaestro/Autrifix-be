"""Periodic lifecycle sweep — SPEC-016.

Intended for cron (Render Cron Job, systemd timer, `crontab`), roughly hourly::

    python manage.py sweep_stale_state

Idempotent: running it twice in a row does nothing the second time, and running it after a
missed window simply catches up. Safe to run concurrently with live traffic — each row is
re-read under a lock before being changed.

Deliberately **not** a Celery task. It needs no worker, no broker, and no result backend,
and ADR-012 keeps Celery out of the request path; adding a worker process to run two
queries an hour would be more infrastructure than the problem justifies.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.jobs import sweeps


class Command(BaseCommand):
    help = "Auto-confirm jobs the customer never confirmed and expire unclaimed requests."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without changing anything.",
        )
        parser.add_argument(
            "--only",
            choices=["jobs", "requests"],
            help="Run just one of the two sweeps.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        only = options.get("only")
        now = timezone.now()

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — nothing will be written."))

        if only != "requests":
            jobs = sweeps.auto_confirm_stale_jobs(now=now, dry_run=dry_run)
            verb = "would auto-confirm" if dry_run else "auto-confirmed"
            self.stdout.write(f"{verb} {len(jobs)} job(s)")
            for job in jobs:
                self.stdout.write(f"  job {job.id} finished {job.work_finished_at:%Y-%m-%d %H:%M}")

        if only != "jobs":
            requests = sweeps.expire_stale_requests(now=now, dry_run=dry_run)
            verb = "would expire" if dry_run else "expired"
            self.stdout.write(f"{verb} {len(requests)} request(s)")
            for service_request in requests:
                self.stdout.write(
                    f"  request {service_request.id} last touched "
                    f"{service_request.updated_at:%Y-%m-%d %H:%M}"
                )

        if not dry_run:
            self.stdout.write(self.style.SUCCESS("Sweep complete."))
