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
from django.utils.dateparse import parse_datetime

from .availability import get_provider_slots
from .models import (
    Appointment,
    AppointmentType,
    BookingConfiguration,
    Location,
    Organization,
    Patient,
    Provider,
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
