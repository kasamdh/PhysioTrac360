"""Transactional, fully re-validating public booking creation.

The frontend's slot search (care/availability.py) is a convenience preview.
Nothing it returns is trusted here — every constraint (organization active,
location/provider/appointment-type ownership, provider eligibility, working
hours, conflicts, lead time, advance limit) is re-checked against the
database inside one atomic transaction, with the provider row locked to
serialize concurrent booking attempts for the same provider and close the
classic double-booking race (two patients picking the same slot at once).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from .availability import get_provider_slots
from .models import (
    Appointment,
    AppointmentType,
    BookingConfiguration,
    Location,
    Organization,
    Patient,
    Provider,
    Waitlist,
)
from .services import record_audit_event


class BookingError(Exception):
    """Base for booking failures; `code` maps to a stable frontend-facing string."""

    code = "BOOKING_ERROR"
    status = 400

    def __init__(self, message: str, *, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field


class NotFoundError(BookingError):
    code = "NOT_FOUND"
    status = 404


class ValidationFailedError(BookingError):
    code = "VALIDATION_FAILED"
    status = 422


class SlotNoLongerAvailableError(BookingError):
    code = "SLOT_NO_LONGER_AVAILABLE"
    status = 409

    def __init__(self):
        super().__init__("This appointment time was just booked. Please select another available time.")


class ChangeCutoffError(BookingError):
    code = "CHANGE_CUTOFF"
    status = 409

    def __init__(self):
        super().__init__("This appointment is too close to reschedule or cancel online. Please call the clinic.")


@dataclass
class BookingRequest:
    organization_slug: str
    location_id: str
    appointment_type_id: str
    provider_id: str
    start_datetime: str
    is_new_patient: bool
    patient: dict
    reason_for_visit: str = ""


def _resolve_organization(slug: str) -> Organization:
    organization = Organization.objects.filter(slug=slug).first()
    if not organization:
        raise NotFoundError("This booking page is not available.")
    if organization.archived_at is not None or not organization.is_active or organization.status == Organization.Status.SUSPENDED:
        raise NotFoundError("This booking page is not available.")
    config, _ = BookingConfiguration.objects.get_or_create(organization=organization)
    if not config.online_booking_enabled:
        raise NotFoundError("Online booking is not currently available for this organization.")
    return organization, config


def _resolve_location(organization: Organization, location_id: str) -> Location:
    location = Location.objects.filter(pk=location_id, organization=organization, is_active=True).first()
    if not location:
        raise NotFoundError("This location is not available for booking.")
    return location


def _resolve_appointment_type(organization: Organization, appointment_type_id: str) -> AppointmentType:
    appointment_type = AppointmentType.objects.filter(
        pk=appointment_type_id, organization=organization, is_active=True, online_booking_enabled=True
    ).first()
    if not appointment_type:
        raise NotFoundError("This appointment type is not available for booking.")
    return appointment_type

def _resolve_provider(organization: Organization, location: Location, appointment_type: AppointmentType, provider_id: str) -> Provider:
    provider = Provider.objects.filter(
        pk=provider_id,
        organization=organization,
        is_active=True,
        online_booking_enabled=True,
        user__isnull=False,
    ).first()
    if not provider:
        raise NotFoundError("This provider is not available for booking.")
    if not provider.locations.filter(pk=location.pk).exists():
        raise NotFoundError("This provider does not work at the selected location.")
    if not provider.appointment_type_links.filter(appointment_type=appointment_type, active=True).exists():
        raise NotFoundError("This provider does not offer the selected appointment type.")
    return provider


def _find_or_create_patient(organization: Organization, patient_payload: dict, is_new_patient: bool) -> Patient:
    first_name = str(patient_payload.get("firstName", "")).strip()
    last_name = str(patient_payload.get("lastName", "")).strip()
    date_of_birth = patient_payload.get("dateOfBirth")
    email = str(patient_payload.get("email", "")).strip().lower()
    phone = str(patient_payload.get("phone", "")).strip()

    if not first_name or not last_name or not date_of_birth:
        raise ValidationFailedError("First name, last name, and date of birth are required.")

    if not is_new_patient and email:
        matches = list(
            Patient.objects.filter(
                organization=organization,
                email__iexact=email,
                last_name__iexact=last_name,
                date_of_birth=date_of_birth,
            )[:2]
        )
        if len(matches) == 1:
            patient = matches[0]
            patient.phone = phone or patient.phone
            patient.full_clean()
            patient.save()
            return patient

    patient = Patient(
        organization=organization,
        first_name=first_name,
        last_name=last_name,
        date_of_birth=date_of_birth,
        phone=phone,
        email=email,
        address=str(patient_payload.get("address", "")).strip(),
        emergency_contact=str(patient_payload.get("emergencyContact", "")).strip(),
    )
    try:
        patient.full_clean()
        patient.save()
    except ValidationError as exc:
        raise ValidationFailedError("; ".join(msg for messages in exc.message_dict.values() for msg in messages))
    return patient


@transaction.atomic
def create_public_booking(request: BookingRequest, *, django_request=None) -> Appointment:
    organization, config = _resolve_organization(request.organization_slug)
    location = _resolve_location(organization, request.location_id)
    appointment_type = _resolve_appointment_type(organization, request.appointment_type_id)
    if request.is_new_patient and appointment_type.requires_new_patient is False and not config.allow_new_patients:
        raise ValidationFailedError("This organization is not currently accepting new patients online.")
    if not request.is_new_patient and not config.allow_returning_patients:
        raise ValidationFailedError("Returning-patient booking is not currently available online.")

    provider = _resolve_provider(organization, location, appointment_type, request.provider_id)

    # Lock the provider row for the remainder of this transaction so a second,
    # concurrent booking attempt for the same provider blocks here until this
    # one commits or rolls back — closing the double-booking race.
    provider = Provider.objects.select_for_update().get(pk=provider.pk)

    start_datetime = parse_datetime(request.start_datetime)
    if start_datetime is None:
        raise ValidationFailedError("Choose a valid appointment time.", field="startDatetime")
    if timezone.is_naive(start_datetime):
        start_datetime = timezone.make_aware(start_datetime, ZoneInfo(location.timezone))

    local_date = timezone.localtime(start_datetime, ZoneInfo(location.timezone)).date()
    available_slots = get_provider_slots(
        provider=provider, location=location, appointment_type=appointment_type, on_date=local_date, config=config
    )
    matching_slot = next((slot for slot in available_slots if slot.start == start_datetime), None)
    if matching_slot is None:
        raise SlotNoLongerAvailableError()

    patient = _find_or_create_patient(organization, request.patient, request.is_new_patient)

    appointment = Appointment(
        patient=patient,
        therapist=provider.user,
        provider=provider,
        location_detail=location,
        appointment_type=appointment_type,
        kind=appointment_type.default_kind or Appointment.Kind.FOLLOW_UP,
        status=Appointment.Status.SCHEDULED,
        starts_at=matching_slot.start,
        ends_at=matching_slot.end,
        is_home_visit=False,
        reason_for_visit=str(request.reason_for_visit or "")[:240],
        booking_source=Appointment.BookingSource.PUBLIC_BOOKING,
        created_by=provider.user,
    )
    try:
        appointment.full_clean()
        appointment.save()
    except ValidationError as exc:
        errors = "; ".join(msg for messages in exc.message_dict.values() for msg in messages)
        raise ValidationFailedError(errors)

    record_audit_event(
        actor=provider.user,
        action="appointment.created",
        obj=appointment,
        patient=patient,
        request=django_request,
        metadata={
            "booking_source": "public_booking",
            "appointment_type": appointment_type.name,
            "location": location.name,
        },
    )
    return appointment


# --- Patient portal: booking, reschedule, cancel, confirm -------------------
#
# Same re-validation discipline as the public path above — the frontend's
# slot search is a preview only — but scoped to an already-known, already-
# authenticated `Patient` (resolved by the caller via
# care/access.py:require_portal_patient, never from this module) instead of
# finding-or-creating one, and gated by `allow_returning_patients` rather
# than the new/returning-patient split public booking uses.


def _resolve_portal_booking_config(organization: Organization) -> BookingConfiguration:
    config, _ = BookingConfiguration.objects.get_or_create(organization=organization)
    if not config.online_booking_enabled:
        raise NotFoundError("Online scheduling is not currently available for this organization.")
    if not config.allow_returning_patients:
        raise NotFoundError("Online scheduling is not currently available for existing patients.")
    return config


@transaction.atomic
def create_portal_booking(
    patient: Patient,
    *,
    location_id: str,
    appointment_type_id: str,
    provider_id: str,
    start_datetime: str,
    reason_for_visit: str = "",
    django_request=None,
) -> Appointment:
    organization = patient.organization
    config = _resolve_portal_booking_config(organization)
    location = _resolve_location(organization, location_id)
    appointment_type = _resolve_appointment_type(organization, appointment_type_id)
    if appointment_type.requires_new_patient:
        raise ValidationFailedError("This appointment type is only available for new patients.")
    provider = _resolve_provider(organization, location, appointment_type, provider_id)

    # Lock the provider row for the remainder of this transaction — same
    # double-booking defense as create_public_booking above.
    provider = Provider.objects.select_for_update().get(pk=provider.pk)

    start_datetime_value = parse_datetime(start_datetime)
    if start_datetime_value is None:
        raise ValidationFailedError("Choose a valid appointment time.", field="startDatetime")
    if timezone.is_naive(start_datetime_value):
        start_datetime_value = timezone.make_aware(start_datetime_value, ZoneInfo(location.timezone))

    local_date = timezone.localtime(start_datetime_value, ZoneInfo(location.timezone)).date()
    available_slots = get_provider_slots(
        provider=provider, location=location, appointment_type=appointment_type, on_date=local_date, config=config
    )
    matching_slot = next((slot for slot in available_slots if slot.start == start_datetime_value), None)
    if matching_slot is None:
        raise SlotNoLongerAvailableError()

    appointment = Appointment(
        patient=patient,
        therapist=provider.user,
        provider=provider,
        location_detail=location,
        appointment_type=appointment_type,
        kind=appointment_type.default_kind or Appointment.Kind.FOLLOW_UP,
        status=Appointment.Status.SCHEDULED,
        starts_at=matching_slot.start,
        ends_at=matching_slot.end,
        is_home_visit=False,
        reason_for_visit=str(reason_for_visit or "")[:240],
        booking_source=Appointment.BookingSource.PATIENT_PORTAL,
        created_by=patient.portal_user,
    )
    try:
        appointment.full_clean()
        appointment.save()
    except ValidationError as exc:
        errors = "; ".join(msg for messages in exc.message_dict.values() for msg in messages)
        raise ValidationFailedError(errors)

    record_audit_event(
        actor=patient.portal_user,
        action="appointment.created",
        obj=appointment,
        patient=patient,
        request=django_request,
        metadata={
            "booking_source": "patient_portal",
            "appointment_type": appointment_type.name,
            "location": location.name,
        },
    )
    return appointment


def _assert_within_patient_change_window(appointment: Appointment, config: BookingConfiguration) -> None:
    if appointment.is_home_visit:
        # Mobile Care's own configurable "Patient Cancellation Window"
        # (MobileCareConfiguration.patient_cancellation_window_hours),
        # not the general BookingConfiguration cutoff — a clinic may
        # reasonably want a longer notice period for a home visit than
        # for an in-clinic appointment.
        from .mobile_care_settings import effective_patient_cancellation_window_hours

        cutoff_hours = effective_patient_cancellation_window_hours(config.organization)
    else:
        cutoff_hours = config.patient_change_cutoff_hours
    if appointment.starts_at - timezone.now() < timedelta(hours=cutoff_hours):
        raise ChangeCutoffError()


@transaction.atomic
def cancel_portal_appointment(patient: Patient, appointment_id: str, *, django_request=None) -> Appointment:
    config, _ = BookingConfiguration.objects.get_or_create(organization=patient.organization)
    appointment = (
        Appointment.objects.select_for_update()
        .select_related("therapist")
        .filter(pk=appointment_id, patient=patient)
        .first()
    )
    if appointment is None:
        raise NotFoundError("Appointment not found.")
    if appointment.status != Appointment.Status.SCHEDULED:
        raise ValidationFailedError("Only scheduled appointments can be cancelled.")
    _assert_within_patient_change_window(appointment, config)

    appointment.status = Appointment.Status.CANCELLED
    appointment.full_clean()
    appointment.save(update_fields=["status", "updated_at"])
    record_audit_event(
        actor=patient.portal_user,
        action="appointment.cancelled",
        obj=appointment,
        patient=patient,
        request=django_request,
        metadata={"source": "patient_portal"},
    )
    return appointment


@transaction.atomic
def reschedule_portal_appointment(
    patient: Patient, appointment_id: str, *, start_datetime: str, django_request=None
) -> Appointment:
    config, _ = BookingConfiguration.objects.get_or_create(organization=patient.organization)
    # No select_related here: several of these FKs are nullable (SET_NULL),
    # and PostgreSQL rejects SELECT ... FOR UPDATE across an outer join.
    # Related objects are fetched separately below once locked.
    appointment = Appointment.objects.select_for_update().filter(pk=appointment_id, patient=patient).first()
    if appointment is None:
        raise NotFoundError("Appointment not found.")
    if appointment.status != Appointment.Status.SCHEDULED:
        raise ValidationFailedError("Only scheduled appointments can be rescheduled.")
    _assert_within_patient_change_window(appointment, config)
    if not appointment.provider_id or not appointment.location_detail_id or not appointment.appointment_type_id:
        raise ValidationFailedError("This appointment cannot be rescheduled online. Please call the clinic.")

    # Lock the provider row for the remainder of this transaction — same
    # double-booking defense as create_portal_booking above.
    provider = Provider.objects.select_for_update().get(pk=appointment.provider_id)

    start_datetime_value = parse_datetime(start_datetime)
    if start_datetime_value is None:
        raise ValidationFailedError("Choose a valid appointment time.", field="startDatetime")
    location = appointment.location_detail
    if timezone.is_naive(start_datetime_value):
        start_datetime_value = timezone.make_aware(start_datetime_value, ZoneInfo(location.timezone))

    local_date = timezone.localtime(start_datetime_value, ZoneInfo(location.timezone)).date()
    available_slots = get_provider_slots(
        provider=provider,
        location=location,
        appointment_type=appointment.appointment_type,
        on_date=local_date,
        config=config,
        exclude_appointment_id=appointment.pk,
    )
    matching_slot = next((slot for slot in available_slots if slot.start == start_datetime_value), None)
    if matching_slot is None:
        raise SlotNoLongerAvailableError()

    appointment.starts_at = matching_slot.start
    appointment.ends_at = matching_slot.end
    appointment.confirmed_at = None
    try:
        appointment.full_clean()
        appointment.save(update_fields=["starts_at", "ends_at", "confirmed_at", "updated_at"])
    except ValidationError as exc:
        errors = "; ".join(msg for messages in exc.message_dict.values() for msg in messages)
        raise ValidationFailedError(errors)

    record_audit_event(
        actor=patient.portal_user,
        action="appointment.rescheduled",
        obj=appointment,
        patient=patient,
        request=django_request,
        metadata={"source": "patient_portal"},
    )
    return appointment


@transaction.atomic
def confirm_portal_appointment(patient: Patient, appointment_id: str, *, django_request=None) -> Appointment:
    appointment = (
        Appointment.objects.select_for_update().filter(pk=appointment_id, patient=patient).first()
    )
    if appointment is None:
        raise NotFoundError("Appointment not found.")
    if appointment.status != Appointment.Status.SCHEDULED:
        raise ValidationFailedError("Only scheduled appointments can be confirmed.")
    if appointment.confirmed_at is None:
        appointment.confirmed_at = timezone.now()
        appointment.save(update_fields=["confirmed_at", "updated_at"])
        record_audit_event(
            actor=patient.portal_user,
            action="appointment.confirmed",
            obj=appointment,
            patient=patient,
            request=django_request,
            metadata={"source": "patient_portal"},
        )
    return appointment


# --- Patient portal: waitlist ------------------------------------------------


def join_portal_waitlist(
    patient: Patient,
    *,
    location_id: str = "",
    appointment_type_id: str = "",
    provider_id: str = "",
    earliest_date: str,
    latest_date: str = "",
    notes: str = "",
    django_request=None,
) -> Waitlist:
    organization = patient.organization
    location = None
    if location_id:
        location = Location.objects.filter(pk=location_id, organization=organization, is_active=True).first()
        if not location:
            raise NotFoundError("This location is not available.")
    appointment_type = None
    if appointment_type_id:
        appointment_type = AppointmentType.objects.filter(
            pk=appointment_type_id, organization=organization, is_active=True
        ).first()
        if not appointment_type:
            raise NotFoundError("This appointment type is not available.")
    provider = None
    if provider_id:
        provider = Provider.objects.filter(pk=provider_id, organization=organization, is_active=True).first()
        if not provider:
            raise NotFoundError("This provider is not available.")

    earliest = parse_date(earliest_date) if earliest_date else None
    if not earliest:
        raise ValidationFailedError("Choose a valid earliest date.", field="earliestDate")
    latest = None
    if latest_date:
        latest = parse_date(latest_date)
        if not latest:
            raise ValidationFailedError("Choose a valid latest date.", field="latestDate")

    # Idempotent join: re-submitting the same preferences while already
    # active just returns the existing entry rather than duplicating it.
    existing = Waitlist.objects.filter(
        patient=patient,
        status=Waitlist.Status.ACTIVE,
        location=location,
        appointment_type=appointment_type,
        provider=provider,
    ).first()
    if existing:
        return existing

    entry = Waitlist(
        organization=organization,
        patient=patient,
        location=location,
        appointment_type=appointment_type,
        provider=provider,
        earliest_date=earliest,
        latest_date=latest,
        notes=str(notes or "")[:240],
    )
    try:
        entry.full_clean()
        entry.save()
    except ValidationError as exc:
        errors = "; ".join(msg for messages in exc.message_dict.values() for msg in messages)
        raise ValidationFailedError(errors)

    record_audit_event(
        actor=patient.portal_user, action="waitlist.joined", obj=entry, patient=patient, request=django_request
    )
    return entry


def leave_portal_waitlist(patient: Patient, entry_id: str, *, django_request=None) -> Waitlist:
    entry = Waitlist.objects.filter(pk=entry_id, patient=patient).first()
    if entry is None:
        raise NotFoundError("Waitlist entry not found.")
    if entry.status == Waitlist.Status.ACTIVE:
        entry.status = Waitlist.Status.CANCELLED
        entry.save(update_fields=["status", "updated_at"])
        record_audit_event(
            actor=patient.portal_user, action="waitlist.left", obj=entry, patient=patient, request=django_request
        )
    return entry
