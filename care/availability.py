"""Authoritative slot-availability calculation for public booking.

The backend is the only source of truth for what's bookable. Nothing here is
ever trusted from the frontend — every call recomputes from the provider's
configured working hours minus existing appointments, time off, and location
closures. See care/booking.py for the transactional, re-validating create path.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_cls, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone

from .models import (
    Appointment,
    BookingConfiguration,
    Location,
    LocationClosure,
    Provider,
    ProviderAppointmentType,
    ProviderAvailability,
    ProviderTimeOff,
)


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime


def eligible_providers(*, location: Location, appointment_type_id, organization) -> list[Provider]:
    """Providers who can be publicly booked for this appointment type at this location."""
    return list(
        Provider.objects.filter(
            organization=organization,
            is_active=True,
            online_booking_enabled=True,
            user__isnull=False,
            locations=location,
            appointment_type_links__appointment_type_id=appointment_type_id,
            appointment_type_links__active=True,
        ).distinct().order_by("last_name", "first_name")
    )


def _duration_minutes(provider: Provider, appointment_type) -> tuple[int, int, int]:
    """Return (duration, buffer_before, buffer_after) for this provider/type pair,
    honoring a provider-specific custom duration override if one is configured."""
    link = ProviderAppointmentType.objects.filter(
        provider=provider, appointment_type=appointment_type, active=True
    ).first()
    duration = (link.custom_duration_minutes if link and link.custom_duration_minutes else None) or appointment_type.default_duration_minutes
    return duration, appointment_type.buffer_before_minutes, appointment_type.buffer_after_minutes


def get_provider_slots(
    *, provider: Provider, location: Location, appointment_type, on_date: date_cls, config: BookingConfiguration
) -> list[Slot]:
    """All bookable slots for one provider, at one location, on one calendar date."""
    duration_minutes, buffer_before, buffer_after = _duration_minutes(provider, appointment_type)
    total_span = timedelta(minutes=duration_minutes + buffer_before + buffer_after)
    interval = timedelta(minutes=config.slot_interval_minutes)

    # Working hours are naive local-clinic times; the location's own IANA
    # timezone (not Django's global TIME_ZONE) is what makes them unambiguous.
    tz = ZoneInfo(location.timezone)
    weekday = on_date.weekday()

    windows = ProviderAvailability.objects.filter(
        provider=provider,
        location=location,
        day_of_week=weekday,
        active=True,
    ).filter(
        Q(effective_from__isnull=True) | Q(effective_from__lte=on_date)
    ).filter(
        Q(effective_until__isnull=True) | Q(effective_until__gte=on_date)
    )

    if not windows.exists():
        return []

    # Busy intervals to subtract: existing appointments, approved time off, location closures.
    day_start = timezone.make_aware(datetime.combine(on_date, time.min), tz)
    day_end = timezone.make_aware(datetime.combine(on_date, time.max), tz)

    busy: list[tuple[datetime, datetime]] = []
    for appt in Appointment.objects.filter(
        provider=provider,
        starts_at__lt=day_end,
        ends_at__gt=day_start,
    ).exclude(status=Appointment.Status.CANCELLED).exclude(status=Appointment.Status.NO_SHOW):
        busy.append((appt.starts_at, appt.ends_at))

    for off in ProviderTimeOff.objects.filter(
        provider=provider,
        status=ProviderTimeOff.Status.APPROVED,
        start_datetime__lt=day_end,
        end_datetime__gt=day_start,
    ):
        busy.append((off.start_datetime, off.end_datetime))

    for closure in LocationClosure.objects.filter(
        location=location,
        active=True,
        start_datetime__lt=day_end,
        end_datetime__gt=day_start,
    ):
        busy.append((closure.start_datetime, closure.end_datetime))

    now = timezone.now()
    earliest_allowed = now + timedelta(hours=config.min_notice_hours)
    latest_allowed = now + timedelta(days=config.max_advance_days)

    slots: list[Slot] = []
    for window in windows:
        window_start = timezone.make_aware(datetime.combine(on_date, window.start_time), tz)
        window_end = timezone.make_aware(datetime.combine(on_date, window.end_time), tz)

        cursor = window_start
        while cursor + total_span <= window_end:
            candidate_start = cursor + timedelta(minutes=buffer_before)
            candidate_end = candidate_start + timedelta(minutes=duration_minutes)
            span_start = candidate_start - timedelta(minutes=buffer_before)
            span_end = candidate_end + timedelta(minutes=buffer_after)

            overlaps_busy = any(span_start < busy_end and span_end > busy_start for busy_start, busy_end in busy)
            within_notice = candidate_start >= earliest_allowed
            within_advance_limit = candidate_start <= latest_allowed

            if not overlaps_busy and within_notice and within_advance_limit:
                slots.append(Slot(start=candidate_start, end=candidate_end))

            cursor += interval

    slots.sort(key=lambda slot: slot.start)
    return slots


@dataclass(frozen=True)
class ProviderSlots:
    provider: Provider
    slots: list[Slot]


def get_available_slots(
    *,
    organization,
    location: Location,
    appointment_type,
    on_date: date_cls,
    provider: Provider | None = None,
) -> list[ProviderSlots]:
    """Slots for one specific provider, or aggregated across every eligible
    provider when provider is None ("Any Available Therapist")."""
    config, _ = BookingConfiguration.objects.get_or_create(organization=organization)
    if not config.online_booking_enabled:
        return []

    if provider is not None:
        providers = [provider]
    else:
        providers = eligible_providers(
            location=location, appointment_type_id=appointment_type.pk, organization=organization
        )

    results = []
    for candidate in providers:
        slots = get_provider_slots(
            provider=candidate, location=location, appointment_type=appointment_type, on_date=on_date, config=config
        )
        if slots:
            results.append(ProviderSlots(provider=candidate, slots=slots))
    return results
