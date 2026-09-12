"""Sweep every tenant for OFFERED ProviderMatch rows whose expires_at has
passed, expire them, and cascade an offer to the next PENDING candidate.

This command does nothing on its own — it must be invoked periodically by
something outside this codebase (Windows Task Scheduler, a cron entry, or a
hosting platform's scheduled-job feature) for offer expiration to be
enforced without anyone happening to interact with a specific stale offer.
respond_to_match() and provider_my_offers() already lazily heal a single
stale offer the moment it's touched; this command is what closes the gap
for one nobody is looking at. Mirrors check_license_expirations.py.
"""
from django.core.management.base import BaseCommand

from care.mobile_care import expire_stale_offers


class Command(BaseCommand):
    help = (
        "Expire every OFFERED ProviderMatch whose expires_at has passed, across all "
        "clients, offering the next ranked candidate (if any) for each. Intended to "
        "be run on a recurring schedule (e.g. every 15-30 minutes) by an external "
        "scheduler — this command does not schedule itself."
    )

    def handle(self, *args, **options):
        expired_count = expire_stale_offers()
        self.stdout.write(self.style.SUCCESS("Checked provider offers: %d expired." % expired_count))
