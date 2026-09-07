"""Sweep every tenant for PT/PTA users whose license has expired and suspend them.

This command does nothing on its own — it must be invoked periodically by
something outside this codebase (Windows Task Scheduler, a cron entry, or a
hosting platform's scheduled-job feature) for license expiration to be
enforced without an admin opening the Users list or the PT/PTA attempting to
log in. Those two lazy-heal paths already cover the common case; this command
is what closes the gap for an account nobody happens to be looking at.
"""
from django.core.management.base import BaseCommand

from care.models import User
from care.user_management import sweep_expired_licenses


class Command(BaseCommand):
    help = (
        "Suspend every ACTIVE PT/PTA user whose license has expired, across all "
        "clients. Intended to be run on a recurring schedule (e.g. daily) by an "
        "external scheduler — this command does not schedule itself."
    )

    def handle(self, *args, **options):
        candidates = User.objects.filter(organization__isnull=False)
        before = set(
            candidates.filter(status=User.Status.ACTIVE).values_list("pk", flat=True)
        )
        sweep_expired_licenses(candidates)
        suspended_count = User.objects.filter(
            pk__in=before, status=User.Status.SUSPENDED
        ).count()
        self.stdout.write(
            self.style.SUCCESS(
                "Checked license expirations: %d account(s) suspended." % suspended_count
            )
        )
