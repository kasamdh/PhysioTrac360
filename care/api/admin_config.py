"""Clinic-administrator configuration: locations, appointment types, and
operational reports. Every endpoint here requires the tenant ADMIN role —
these are "configure the clinic" actions, not day-to-day clinical work.
"""
from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from ..models import Appointment, AppointmentType, ClinicalNote, Location, OutcomeScore, Patient, User
from ..services import record_audit_event
from .utils import api_error, api_login_required, json_body, organization_or_error


def _admin_org_or_error(request):
    return organization_or_error(request, roles={User.Role.ADMIN})


# --- Locations ---------------------------------------------------------

LOCATION_FIELDS = {
    "name": "name",
    "address_line_1": "addressLine1",
    "address_line_2": "addressLine2",
    "city": "city",
    "state": "state",
    "zip_code": "zipCode",
    "phone": "phone",
    "timezone": "timezone",
}


def serialize_location(location: Location) -> dict:
    return {
        "id": str(location.pk),
        "name": location.name,
        "addressLine1": location.address_line_1,
        "addressLine2": location.address_line_2,
        "city": location.city,
        "state": location.state,
        "zipCode": location.zip_code,
        "phone": location.phone,
        "timezone": location.timezone,
        "isActive": location.is_active,
    }


def validate_location_payload(payload: dict, *, partial: bool = False) -> dict[str, str]:
    errors = {}
    if "name" in payload or not partial:
        if not str(payload.get("name", "")).strip():
            errors["name"] = "Location name is required."
    timezone_value = payload.get("timezone")
    if timezone_value:
        try:
            ZoneInfo(str(timezone_value))
        except (ZoneInfoNotFoundError, ValueError):
            errors["timezone"] = "Choose a valid IANA timezone."
    return errors


@require_http_methods(["GET", "POST"])
@api_login_required
def locations(request):
    organization, error = _admin_org_or_error(request)
    if error:
        return error
    if request.method == "POST":
        try:
            payload = json_body(request)
        except ValueError as exc:
            return api_error(str(exc), status=400)
        errors = validate_location_payload(payload)
        if errors:
            return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": errors}, status=422)
        location = Location(organization=organization, timezone=organization.timezone)
        for field, key in LOCATION_FIELDS.items():
            if key in payload:
                setattr(location, field, str(payload[key]).strip())
        try:
            location.full_clean()
            location.save()
        except ValidationError as exc:
            errors = {field: " ".join(messages) for field, messages in exc.message_dict.items()}
            return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": errors}, status=422)
        record_audit_event(actor=request.user, action="location.created", obj=location, request=request)
        return JsonResponse({"location": serialize_location(location)}, status=201)

    records = Location.objects.filter(organization=organization).order_by("name")
    return JsonResponse({"locations": [serialize_location(record) for record in records]})


@require_http_methods(["GET", "PATCH", "DELETE"])
@api_login_required
def location_detail(request, location_id):
    organization, error = _admin_org_or_error(request)
    if error:
        return error
    location = Location.objects.filter(pk=location_id, organization=organization).first()
    if not location:
        return api_error("Location was not found.", status=404)
    if request.method == "GET":
        return JsonResponse({"location": serialize_location(location)})
    if request.method == "DELETE":
        if not location.is_active:
            return api_error("This location is already inactive.", status=409)
        location.is_active = False
        location.save(update_fields=["is_active", "updated_at"])
        record_audit_event(actor=request.user, action="location.deactivated", obj=location, request=request)
        return JsonResponse({"location": serialize_location(location)})

    try:
        payload = json_body(request)
    except ValueError as exc:
        return api_error(str(exc), status=400)
    errors = validate_location_payload(payload, partial=True)
    if errors:
        return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": errors}, status=422)
    for field, key in LOCATION_FIELDS.items():
        if key in payload:
            setattr(location, field, str(payload[key]).strip())
    if "isActive" in payload:
        location.is_active = bool(payload["isActive"])
    try:
        location.full_clean()
    except ValidationError as exc:
        errors = {field: " ".join(messages) for field, messages in exc.message_dict.items()}
        return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": errors}, status=422)
    location.save()
    record_audit_event(actor=request.user, action="location.updated", obj=location, request=request)
    return JsonResponse({"location": serialize_location(location)})


# --- Appointment types ---------------------------------------------------

def serialize_appointment_type(appointment_type: AppointmentType) -> dict:
    return {
        "id": str(appointment_type.pk),
        "name": appointment_type.name,
        "defaultDurationMinutes": appointment_type.default_duration_minutes,
        "color": appointment_type.color,
        "isActive": appointment_type.is_active,
    }


def validate_appointment_type_payload(payload: dict, *, partial: bool = False) -> dict[str, str]:
    errors = {}
    if "name" in payload or not partial:
        if not str(payload.get("name", "")).strip():
            errors["name"] = "Appointment type name is required."
    if "defaultDurationMinutes" in payload:
        try:
            minutes = int(payload["defaultDurationMinutes"])
            if minutes <= 0 or minutes > 480:
                raise ValueError
        except (TypeError, ValueError):
            errors["defaultDurationMinutes"] = "Enter a duration between 1 and 480 minutes."
    return errors


@require_http_methods(["GET", "POST"])
@api_login_required
def appointment_types(request):
    organization, error = _admin_org_or_error(request)
    if error:
        return error
    if request.method == "POST":
        try:
            payload = json_body(request)
        except ValueError as exc:
            return api_error(str(exc), status=400)
        errors = validate_appointment_type_payload(payload)
        if errors:
            return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": errors}, status=422)
        appointment_type = AppointmentType(
            organization=organization,
            name=str(payload["name"]).strip(),
            default_duration_minutes=int(payload.get("defaultDurationMinutes", 30)),
            color=str(payload.get("color", "")).strip(),
        )
        try:
            appointment_type.full_clean()
            appointment_type.save()
        except ValidationError as exc:
            errors = {field: " ".join(messages) for field, messages in exc.message_dict.items()}
            return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": errors}, status=422)
        record_audit_event(actor=request.user, action="appointment_type.created", obj=appointment_type, request=request)
        return JsonResponse({"appointmentType": serialize_appointment_type(appointment_type)}, status=201)

    records = AppointmentType.objects.filter(organization=organization).order_by("name")
    return JsonResponse({"appointmentTypes": [serialize_appointment_type(record) for record in records]})


@require_http_methods(["GET", "PATCH", "DELETE"])
@api_login_required
def appointment_type_detail(request, appointment_type_id):
    organization, error = _admin_org_or_error(request)
    if error:
        return error
    appointment_type = AppointmentType.objects.filter(pk=appointment_type_id, organization=organization).first()
    if not appointment_type:
        return api_error("Appointment type was not found.", status=404)
    if request.method == "GET":
        return JsonResponse({"appointmentType": serialize_appointment_type(appointment_type)})
    if request.method == "DELETE":
        if not appointment_type.is_active:
            return api_error("This appointment type is already inactive.", status=409)
        appointment_type.is_active = False
        appointment_type.save(update_fields=["is_active", "updated_at"])
        record_audit_event(actor=request.user, action="appointment_type.deactivated", obj=appointment_type, request=request)
        return JsonResponse({"appointmentType": serialize_appointment_type(appointment_type)})

    try:
        payload = json_body(request)
    except ValueError as exc:
        return api_error(str(exc), status=400)
    errors = validate_appointment_type_payload(payload, partial=True)
    if errors:
        return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": errors}, status=422)
    if "name" in payload:
        appointment_type.name = str(payload["name"]).strip()
    if "defaultDurationMinutes" in payload:
        appointment_type.default_duration_minutes = int(payload["defaultDurationMinutes"])
    if "color" in payload:
        appointment_type.color = str(payload["color"]).strip()
    if "isActive" in payload:
        appointment_type.is_active = bool(payload["isActive"])
    try:
        appointment_type.full_clean()
    except ValidationError as exc:
        errors = {field: " ".join(messages) for field, messages in exc.message_dict.items()}
        return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": errors}, status=422)
    appointment_type.save()
    record_audit_event(actor=request.user, action="appointment_type.updated", obj=appointment_type, request=request)
    return JsonResponse({"appointmentType": serialize_appointment_type(appointment_type)})


# --- Operational reports --------------------------------------------------

@require_GET
@api_login_required
def operational_report(request):
    """Real, currently-queryable operational metrics for the last 30 days.
    Deliberately does not fabricate anything (no revenue, no NPS, etc.) —
    only counts derivable from data this app actually stores.
    """
    organization, error = _admin_org_or_error(request)
    if error:
        return error
    since = timezone.now() - timedelta(days=30)

    appointment_rows = (
        Appointment.objects.filter(patient__organization=organization, starts_at__gte=since)
        .values("status")
        .annotate(count=Count("id"))
    )
    appointments_by_status = {row["status"]: row["count"] for row in appointment_rows}

    notes_qs = ClinicalNote.objects.filter(patient__organization=organization, created_at__gte=since)
    signed_count = notes_qs.filter(status=ClinicalNote.Status.SIGNED).count()
    unsigned_count = notes_qs.exclude(status=ClinicalNote.Status.SIGNED).count()

    caseload = list(
        User.objects.filter(
            organization=organization,
            role__in=[User.Role.THERAPIST, User.Role.ASSISTANT],
            is_active=True,
        )
        .annotate(
            active_patient_count=Count(
                "assigned_patients", filter=Q(assigned_patients__status=Patient.Status.ACTIVE), distinct=True
            )
        )
        .order_by("last_name", "first_name")
        .values("id", "first_name", "last_name", "active_patient_count")
    )

    return JsonResponse(
        {
            "windowDays": 30,
            "newPatients": Patient.objects.filter(organization=organization, created_at__gte=since).count(),
            "appointmentsByStatus": appointments_by_status,
            "notes": {"signed": signed_count, "unsigned": unsigned_count},
            "outcomesRecorded": OutcomeScore.objects.filter(
                patient__organization=organization, created_at__gte=since
            ).count(),
            "reassessmentsOverdue": ClinicalNote.objects.filter(
                patient__organization=organization,
                reassessment_due__isnull=False,
                reassessment_due__lt=timezone.localdate(),
            ).exclude(status=ClinicalNote.Status.SIGNED).values("patient_id").distinct().count(),
            "caseloadByProvider": [
                {
                    "id": str(row["id"]),
                    "displayName": f"{row['first_name']} {row['last_name']}".strip(),
                    "activePatientCount": row["active_patient_count"],
                }
                for row in caseload
            ],
        }
    )
