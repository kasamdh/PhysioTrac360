"""Send a VISIT_REMINDER notification for every home-visit appointment
scheduled for tomorrow that hasn't already gotten one.

This command does nothing on its own — it must be invoked periodically by
something outside this codebase (Windows Task Scheduler, a cron entry, or a
hosting platform's scheduled-job feature), once daily, for visit reminders
to go out without anyone happening to look at a specific appointment.
Mirrors check_license_expirations.py / expire_stale_provider_offers.py.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from care.mobile_care_notifications import notify_visit_reminder, reminder_already_sent
from care.models import Appointment


class Command(BaseCommand):
    help = (
        "Send a VISIT_REMINDER notification for every home-visit appointment scheduled for "
        "tomorrow, across all clients. Intended to be run once daily by an external scheduler — "
        "this command does not schedule itself."
    )

    def handle(self, *args, **options):
        tomorrow = timezone.localdate() + timedelta(days=1)
        appointments = (
            Appointment.objects.filter(
                is_home_visit=True, starts_at__date=tomorrow,
                status__in=(Appointment.Status.SCHEDULED, Appointment.Status.CHECKED_IN),
            )
            .select_related("mobile_care_request", "mobile_care_request__patient")
        )
        sent_count = 0
        for appointment in appointments:
            mobile_care_request = getattr(appointment, "mobile_care_request", None)
            if mobile_care_request is None:
                # No Patient Service Request behind this appointment (the
                # legacy "Home visit" checkbox path) — nothing to hang a
                # Mobile Care reminder on; see update_home_visit_status()'s
                # docstring for the same scope boundary.
                continue
            if reminder_already_sent(appointment):
                continue
            notify_visit_reminder(appointment, mobile_care_request=mobile_care_request)
            sent_count += 1
        self.stdout.write(self.style.SUCCESS("Sent %d home visit reminder(s) for %s." % (sent_count, tomorrow)))
