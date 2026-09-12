"""Close stale open location-sharing sessions, and delete any orphaned GPS
location pings, across every tenant.

care/mobile_care.py's close_location_session() already deletes every ping
the moment a session closes normally (ARRIVED/CANCELLED/provider turns
sharing off) — that's the primary retention mechanism, not this command.
This is only a backstop for the case a session's app crashes or loses
connectivity mid-trip and never sends the status update that would have
closed it: after STALE_SESSION_THRESHOLD (no real home-visit trip runs this
long), any still-open session is force-closed as TIMED_OUT, which deletes
its pings the same way a normal close does. PING_BACKSTOP_RETENTION is a
second, even-shorter backstop against any row that somehow survives without
a session to close it.

Like check_license_expirations, this command does nothing on its own; it
must be invoked periodically by something outside this codebase (Windows
Task Scheduler, cron, or a hosting platform's scheduled-job feature) —
recommended at least every 15-30 minutes, since a stuck session should stop
sharing promptly, not linger for hours.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from care.mobile_care import close_location_session
from care.models import ProviderLocationSession, ProviderLocationSnapshot

STALE_SESSION_THRESHOLD = timezone.timedelta(hours=4)
PING_BACKSTOP_RETENTION = timezone.timedelta(hours=1)


class Command(BaseCommand):
    help = (
        "Force-close any ProviderLocationSession left open longer than a real home-visit "
        "trip ever takes (TIMED_OUT), and delete any ProviderLocationSnapshot orphaned "
        "beyond a short backstop window. Intended to run frequently (e.g. every 15-30 "
        "minutes) by an external scheduler — this command does not schedule itself."
    )

    def handle(self, *args, **options):
        stale_cutoff = timezone.now() - STALE_SESSION_THRESHOLD
        stale_sessions = list(
            ProviderLocationSession.objects.filter(ended_at__isnull=True, started_at__lt=stale_cutoff)
            .select_related("assignment")
        )
        for session in stale_sessions:
            close_location_session(
                session.assignment, end_reason=ProviderLocationSession.EndReason.TIMED_OUT, actor=None,
            )

        ping_cutoff = timezone.now() - PING_BACKSTOP_RETENTION
        deleted_count, _ = ProviderLocationSnapshot.objects.filter(created_at__lt=ping_cutoff).delete()

        self.stdout.write(
            self.style.SUCCESS(
                "Closed %d stale location session(s) and purged %d orphaned ping(s)."
                % (len(stale_sessions), deleted_count)
            )
        )
