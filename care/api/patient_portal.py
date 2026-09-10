"""Patient Portal — separate from staff administration, sharing the same
secured backend services (auth session, tenant boundary, audit trail).

Two audiences use this module:
  - Staff (front desk / clinical roles) invite a patient to the portal —
    the one place a `patient_id` is read from a URL, gated the same way as
    every other staff-facing patient action.
  - The patient themselves, once logged in — every endpoint below resolves
    "which patient" exclusively via `require_portal_patient(request)`
    (care/access.py), never from a URL/body/query parameter. This is the
    IDOR defense for the whole portal surface: there is no patient id for
    Patient A to swap for Patient B's in the first place.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from ..access import CLINICAL_ROLES, SCHEDULING_ROLES, portal_patient_or_error, require_patient_access
from ..availability import eligible_providers, get_available_slots
from ..billing_services import build_patient_statement_data, build_patient_superbill_data, patient_combined_balance
from ..booking import (
    BookingError,
    cancel_portal_appointment,
    confirm_portal_appointment,
    create_portal_booking,
    join_portal_waitlist,
    leave_portal_waitlist,
    reschedule_portal_appointment,
)
from ..entitlements import organization_has_feature
from ..form_engine import (
    display_status,
    ensure_form_templates,
    forms_overview,
    get_working_submission,
    record_consent_if_applicable,
    validate_submission_data,
)
from ..models import (
    Appointment,
    AppointmentType,
    BookingConfiguration,
    FormSubmission,
    FormTemplate,
    HomeExercise,
    HomeExerciseLog,
    HomeProgram,
    Location,
    OutcomeAssignment,
    OutcomeScore,
    Patient,
    PatientDocument,
    PatientInsurance,
    PatientPayment,
    PatientProfileChangeRequest,
    PatientStatement,
    Payer,
    PaymentRecord,
    Provider,
    SecureMessage,
    Superbill,
    User,
    Waitlist,
)
from ..notifications import send_secure_message_notification_email
from ..outcome_scoring import outcome_measure_schema, score_outcome_measure, validate_outcome_responses
from ..payment_processor import get_payment_processor
from ..portal_management import invite_patient_to_portal
from ..services import record_audit_event
from ..telehealth import get_telehealth_provider
from .billing import MAX_CARD_UPLOAD_BYTES, _apply_insurance_payload, serialize_patient_insurance
from .documents import MAX_UPLOAD_BYTES
from .serializers import serialize_home_exercise
from .utils import InvalidJSON, api_error, api_login_required, api_validation_error, json_body, organization_or_error


# --- Staff: invite a patient to the portal ---------------------------------

def _staff_patient_or_error(request, patient_id: str):
    _, error = organization_or_error(request, roles=CLINICAL_ROLES | SCHEDULING_ROLES)
    if error:
        return None, error
    patient = Patient.objects.select_related("organization", "portal_user").filter(pk=patient_id).first()
    if patient is None:
        return None, api_error("Patient record was not found.", status=404)
    is_clinician = request.user.role in {User.Role.THERAPIST, User.Role.ASSISTANT}
    try:
        require_patient_access(request, patient, clinical=is_clinician)
    except PermissionDenied as exc:
        return None, api_error(str(exc), status=403)
    return patient, None


@require_POST
@api_login_required
def portal_invite_create(request, patient_id):
    patient, error = _staff_patient_or_error(request, patient_id)
    if error:
        return error
    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)
    email = str(payload.get("email", "")).strip().lower() or patient.email.strip().lower()
    if not email:
        return api_validation_error({"email": "An email address is required to invite this patient."})
    try:
        result = invite_patient_to_portal(patient, email, request.user, request=request)
    except ValueError as exc:
        return api_error(str(exc), status=409)
    return JsonResponse(
        {
            "email": email,
            "reissued": result.reissued,
            # Shown on-screen for staff to relay if email delivery is
            # unavailable in this environment — same fallback pattern as
            # the existing client-admin invitation flow.
            "invitationUrl": result.activation_url,
        },
        status=201,
    )


# --- Patient: dashboard -----------------------------------------------------

# How early a patient may join a telehealth visit before its scheduled
# start — matches typical "waiting room" conventions. The window closes at
# the appointment's own end time.
TELEHEALTH_JOIN_WINDOW_MINUTES_BEFORE = 15


def _can_join_telehealth(appointment: Appointment) -> bool:
    if appointment.kind != Appointment.Kind.TELEHEALTH:
        return False
    if appointment.status not in (Appointment.Status.SCHEDULED, Appointment.Status.CHECKED_IN):
        return False
    now = timezone.now()
    window_opens = appointment.starts_at - timedelta(minutes=TELEHEALTH_JOIN_WINDOW_MINUTES_BEFORE)
    return window_opens <= now <= appointment.ends_at


def _serialize_portal_appointment(appointment: Appointment, *, cutoff_hours: int | None = None) -> dict:
    """Deliberately narrower than the staff serialize_appointment — no
    private_notes, no episode/authorization ids, nothing beyond what a
    patient needs to see (provider, location, date, time, type).

    `cutoff_hours` is opt-in: pass the organization's
    `BookingConfiguration.patient_change_cutoff_hours` to also compute
    canCancel/canReschedule for this appointment. Omitted on read-only views
    (e.g. history) where those actions are never offered."""
    local_start = timezone.localtime(appointment.starts_at)
    local_end = timezone.localtime(appointment.ends_at)
    payload = {
        "id": str(appointment.pk),
        "date": local_start.date().isoformat(),
        "startsAt": local_start.isoformat(),
        "endsAt": local_end.isoformat(),
        "status": appointment.status,
        "statusLabel": appointment.get_status_display(),
        "kind": appointment.kind,
        "kindLabel": appointment.get_kind_display(),
        "providerName": appointment.therapist.get_full_name() or appointment.therapist.username,
        "location": appointment.location_detail.name if appointment.location_detail_id else appointment.location,
        "isHomeVisit": appointment.is_home_visit,
        "isTelehealth": appointment.kind == Appointment.Kind.TELEHEALTH,
        "confirmedAt": appointment.confirmed_at.isoformat() if appointment.confirmed_at else None,
        "canJoinTelehealth": _can_join_telehealth(appointment),
    }
    if cutoff_hours is not None:
        can_change = (
            appointment.status == Appointment.Status.SCHEDULED
            and appointment.starts_at - timezone.now() >= timedelta(hours=cutoff_hours)
        )
        payload["canCancel"] = can_change
        payload["canReschedule"] = can_change
        payload["canConfirm"] = appointment.status == Appointment.Status.SCHEDULED and appointment.confirmed_at is None
        if can_change:
            # Only surfaced when a reschedule is actually offered — the ids a
            # reschedule flow needs to re-browse availability for this same
            # provider/location/type (never used to identify another chart).
            payload["locationId"] = str(appointment.location_detail_id) if appointment.location_detail_id else None
            payload["appointmentTypeId"] = str(appointment.appointment_type_id) if appointment.appointment_type_id else None
            payload["providerId"] = str(appointment.provider_id) if appointment.provider_id else None
    return payload


@require_GET
@api_login_required
def portal_dashboard(request):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    now = timezone.now()
    config, _ = BookingConfiguration.objects.get_or_create(organization=patient.organization)

    appointments = list(
        Appointment.objects.filter(
            patient=patient, starts_at__gte=now, status__in=(Appointment.Status.SCHEDULED, Appointment.Status.CHECKED_IN)
        )
        .select_related("therapist", "location_detail")
        .order_by("starts_at")[:6]
    )
    next_appointment = appointments[0] if appointments else None
    upcoming_appointments = appointments[1:] if len(appointments) > 1 else []

    active_program = (
        HomeProgram.objects.filter(patient=patient, status=HomeProgram.Status.ACTIVE)
        .prefetch_related("exercises")
        .order_by("-created_at")
        .first()
    )

    new_message_count = 0
    if patient.portal_user_id:
        new_message_count = SecureMessage.objects.filter(recipient=patient.portal_user, read_at__isnull=True).count()

    balance = patient_combined_balance(patient)["totalBalance"]

    record_audit_event(actor=request.user, action="patient_portal.dashboard_viewed", obj=patient, patient=patient, request=request)

    return JsonResponse(
        {
            "patient": {"fullName": patient.full_name, "firstName": patient.first_name},
            "nextAppointment": (
                _serialize_portal_appointment(next_appointment, cutoff_hours=config.patient_change_cutoff_hours)
                if next_appointment
                else None
            ),
            "upcomingAppointments": [
                _serialize_portal_appointment(a, cutoff_hours=config.patient_change_cutoff_hours)
                for a in upcoming_appointments
            ],
            "formsDue": [form for form in forms_overview(patient) if form["status"] != FormSubmission.Status.COMPLETED],
            "outstandingBalance": str(balance),
            "newMessageCount": new_message_count,
            "homeExerciseProgram": (
                {
                    "id": str(active_program.pk),
                    "title": active_program.title,
                    "exerciseCount": active_program.exercises.count(),
                }
                if active_program
                else None
            ),
            "outcomeMeasuresDue": [
                _serialize_outcome_assignment(assignment)
                for assignment in OutcomeAssignment.objects.filter(patient=patient, status=OutcomeAssignment.Status.PENDING).order_by("-assigned_at")
            ],
            "recentDocuments": [
                _serialize_portal_document(document, patient)
                for document in PatientDocument.objects.filter(patient=patient, visible_to_patient=True).order_by("-created_at")[:5]
            ],
            "notifications": _portal_notifications(patient),
        }
    )


# --- Patient: appointments — view, book, reschedule, cancel, confirm --------


@require_GET
@api_login_required
def portal_appointments_list(request):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    now = timezone.now()
    config, _ = BookingConfiguration.objects.get_or_create(organization=patient.organization)

    upcoming = (
        Appointment.objects.filter(
            patient=patient, starts_at__gte=now, status__in=(Appointment.Status.SCHEDULED, Appointment.Status.CHECKED_IN)
        )
        .select_related("therapist", "location_detail")
        .order_by("starts_at")
    )
    past = (
        Appointment.objects.filter(patient=patient)
        .exclude(pk__in=upcoming.values_list("pk", flat=True))
        .select_related("therapist", "location_detail")
        .order_by("-starts_at")[:50]
    )
    return JsonResponse(
        {
            "upcoming": [
                _serialize_portal_appointment(a, cutoff_hours=config.patient_change_cutoff_hours) for a in upcoming
            ],
            "past": [_serialize_portal_appointment(a) for a in past],
        }
    )


@require_GET
@api_login_required
def portal_booking_locations(request):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    locations = Location.objects.filter(organization=patient.organization, is_active=True).order_by("name")
    return JsonResponse(
        {
            "locations": [
                {"id": str(location.pk), "name": location.name, "city": location.city, "state": location.state, "timezone": location.timezone}
                for location in locations
            ]
        }
    )


@require_GET
@api_login_required
def portal_booking_appointment_types(request):
    """Excludes `requires_new_patient` types — a portal account is, by
    definition, an existing patient's chart, so those (usually reserved for
    the public new-patient booking funnel) are never offered here."""
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    location_id = request.GET.get("location_id", "").strip()
    queryset = AppointmentType.objects.filter(
        organization=patient.organization, is_active=True, online_booking_enabled=True, requires_new_patient=False
    )
    if location_id:
        queryset = queryset.filter(
            provider_links__active=True,
            provider_links__provider__is_active=True,
            provider_links__provider__online_booking_enabled=True,
            provider_links__provider__locations__pk=location_id,
        ).distinct()
    return JsonResponse(
        {
            "appointmentTypes": [
                {
                    "id": str(appointment_type.pk),
                    "name": appointment_type.name,
                    "description": appointment_type.description,
                    "durationMinutes": appointment_type.default_duration_minutes,
                }
                for appointment_type in queryset.order_by("name")
            ]
        }
    )


@require_GET
@api_login_required
def portal_booking_providers(request):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    location_id = request.GET.get("location_id", "").strip()
    appointment_type_id = request.GET.get("appointment_type_id", "").strip()
    if not location_id or not appointment_type_id:
        return api_error("location_id and appointment_type_id are required.", status=400)
    location = Location.objects.filter(pk=location_id, organization=patient.organization, is_active=True).first()
    if not location:
        return api_error("This location is not available for booking.", status=404)
    providers = eligible_providers(location=location, appointment_type_id=appointment_type_id, organization=patient.organization)
    return JsonResponse(
        {
            "providers": [
                {
                    "id": str(provider.pk),
                    "displayName": f"{provider.first_name} {provider.last_name}".strip(),
                    "credentials": provider.credentials,
                    "specialty": provider.specialty,
                    "bio": provider.bio,
                }
                for provider in providers
            ]
        }
    )


@require_GET
@api_login_required
def portal_booking_availability(request):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    location_id = request.GET.get("location_id", "").strip()
    appointment_type_id = request.GET.get("appointment_type_id", "").strip()
    provider_id = request.GET.get("provider_id", "").strip()
    date_str = request.GET.get("date", "").strip()
    exclude_appointment_id = request.GET.get("exclude_appointment_id", "").strip()

    if not location_id or not appointment_type_id or not date_str:
        return api_error("location_id, appointment_type_id, and date are required.", status=400)
    on_date = parse_date(date_str)
    if not on_date:
        return api_error("Provide date as YYYY-MM-DD.", status=400)

    location = Location.objects.filter(pk=location_id, organization=patient.organization, is_active=True).first()
    if not location:
        return api_error("This location is not available for booking.", status=404)
    appointment_type = AppointmentType.objects.filter(
        pk=appointment_type_id, organization=patient.organization, is_active=True, online_booking_enabled=True
    ).first()
    if not appointment_type:
        return api_error("This appointment type is not available for booking.", status=404)

    provider = None
    if provider_id:
        provider = Provider.objects.filter(
            pk=provider_id, organization=patient.organization, is_active=True, online_booking_enabled=True
        ).first()
        if not provider:
            return api_error("This provider is not available for booking.", status=404)

    exclude_id = None
    if exclude_appointment_id and Appointment.objects.filter(pk=exclude_appointment_id, patient=patient).exists():
        # Only honored when it's actually this patient's own appointment —
        # otherwise silently ignored (worst case, that slot just looks busy).
        exclude_id = exclude_appointment_id

    results = get_available_slots(
        organization=patient.organization,
        location=location,
        appointment_type=appointment_type,
        on_date=on_date,
        provider=provider,
        exclude_appointment_id=exclude_id,
    )
    return JsonResponse(
        {
            "date": on_date.isoformat(),
            "timezone": location.timezone,
            "providers": [
                {
                    "provider": {"id": str(entry.provider.pk), "displayName": f"{entry.provider.first_name} {entry.provider.last_name}".strip()},
                    "slots": [{"start": slot.start.isoformat(), "end": slot.end.isoformat()} for slot in entry.slots],
                }
                for entry in results
            ],
        }
    )


@require_POST
@api_login_required
def portal_booking_create(request):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)
    required = ["locationId", "appointmentTypeId", "providerId", "startDatetime"]
    missing = [key for key in required if not payload.get(key)]
    if missing:
        return api_validation_error({key: "This field is required." for key in missing})
    try:
        appointment = create_portal_booking(
            patient,
            location_id=str(payload["locationId"]),
            appointment_type_id=str(payload["appointmentTypeId"]),
            provider_id=str(payload["providerId"]),
            start_datetime=str(payload["startDatetime"]),
            reason_for_visit=str(payload.get("reasonForVisit", "")),
            django_request=request,
        )
    except BookingError as exc:
        return api_error(exc.message, status=exc.status)
    return JsonResponse({"appointment": _serialize_portal_appointment(appointment)}, status=201)


@require_POST
@api_login_required
def portal_appointment_cancel(request, appointment_id):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    try:
        appointment = cancel_portal_appointment(patient, appointment_id, django_request=request)
    except BookingError as exc:
        return api_error(exc.message, status=exc.status)
    return JsonResponse({"appointment": _serialize_portal_appointment(appointment)})


@require_POST
@api_login_required
def portal_appointment_reschedule(request, appointment_id):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)
    start_datetime = str(payload.get("startDatetime", ""))
    if not start_datetime:
        return api_validation_error({"startDatetime": "Choose a new appointment time."})
    try:
        appointment = reschedule_portal_appointment(
            patient, appointment_id, start_datetime=start_datetime, django_request=request
        )
    except BookingError as exc:
        return api_error(exc.message, status=exc.status)
    return JsonResponse({"appointment": _serialize_portal_appointment(appointment)})


@require_POST
@api_login_required
def portal_appointment_confirm(request, appointment_id):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    try:
        appointment = confirm_portal_appointment(patient, appointment_id, django_request=request)
    except BookingError as exc:
        return api_error(exc.message, status=exc.status)
    return JsonResponse({"appointment": _serialize_portal_appointment(appointment)})


@require_POST
@api_login_required
def portal_appointment_telehealth_join(request, appointment_id):
    """Mints a fresh session via the telehealth adapter — never a stored,
    reusable link. Eligibility (telehealth kind, appropriate status, join
    window) is re-checked here server-side regardless of what the frontend
    showed, and every attempt is audit-logged whether or not it succeeds."""
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    appointment = Appointment.objects.filter(pk=appointment_id, patient=patient).select_related("therapist").first()
    if appointment is None:
        return api_error("Appointment not found.", status=404)
    if not organization_has_feature(patient.organization, "telehealth"):
        return api_error("Telehealth visits are not enabled for this organization.", status=403)
    if not _can_join_telehealth(appointment):
        return api_error(
            "This visit can't be joined right now. Telehealth visits can be joined starting "
            f"{TELEHEALTH_JOIN_WINDOW_MINUTES_BEFORE} minutes before the scheduled time.",
            status=409,
        )
    result = get_telehealth_provider(patient.organization).create_session(appointment)
    record_audit_event(
        actor=patient.portal_user, action="telehealth.join_attempted", obj=appointment, patient=patient, request=request,
        metadata={"joinable": result.joinable},
    )
    return JsonResponse({"joinable": result.joinable, "joinUrl": result.join_url, "message": result.message})


# --- Patient: waitlist -------------------------------------------------------


def _serialize_waitlist_entry(entry: Waitlist) -> dict:
    return {
        "id": str(entry.pk),
        "location": entry.location.name if entry.location_id else None,
        "appointmentType": entry.appointment_type.name if entry.appointment_type_id else None,
        "providerName": f"{entry.provider.first_name} {entry.provider.last_name}".strip() if entry.provider_id else None,
        "earliestDate": entry.earliest_date.isoformat(),
        "latestDate": entry.latest_date.isoformat() if entry.latest_date else None,
        "notes": entry.notes,
        "status": entry.status,
        "statusLabel": entry.get_status_display(),
        "createdAt": entry.created_at.isoformat(),
    }


@require_http_methods(["GET", "POST"])
@api_login_required
def portal_waitlist(request):
    patient, error = portal_patient_or_error(request)
    if error:
        return error

    if request.method == "GET":
        entries = (
            Waitlist.objects.filter(patient=patient)
            .select_related("location", "appointment_type", "provider")
            .order_by("-created_at")
        )
        return JsonResponse({"entries": [_serialize_waitlist_entry(entry) for entry in entries]})

    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)
    earliest_date = str(payload.get("earliestDate", ""))
    if not earliest_date:
        return api_validation_error({"earliestDate": "Choose the earliest date you're available."})
    try:
        entry = join_portal_waitlist(
            patient,
            location_id=str(payload.get("locationId", "")),
            appointment_type_id=str(payload.get("appointmentTypeId", "")),
            provider_id=str(payload.get("providerId", "")),
            earliest_date=earliest_date,
            latest_date=str(payload.get("latestDate", "")),
            notes=str(payload.get("notes", "")),
            django_request=request,
        )
    except BookingError as exc:
        return api_error(exc.message, status=exc.status)
    return JsonResponse({"entry": _serialize_waitlist_entry(entry)}, status=201)


@require_POST
@api_login_required
def portal_waitlist_leave(request, entry_id):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    try:
        entry = leave_portal_waitlist(patient, entry_id, django_request=request)
    except BookingError as exc:
        return api_error(exc.message, status=exc.status)
    return JsonResponse({"entry": _serialize_waitlist_entry(entry)})


# --- Staff: waitlist visibility ----------------------------------------------


@require_GET
@api_login_required
def waitlist_staff_list(request):
    organization, error = organization_or_error(request, roles=SCHEDULING_ROLES)
    if error:
        return error
    entries = (
        Waitlist.objects.filter(organization=organization, status=Waitlist.Status.ACTIVE)
        .select_related("patient", "location", "appointment_type", "provider")
        .order_by("-created_at")
    )
    return JsonResponse(
        {
            "entries": [
                {
                    **_serialize_waitlist_entry(entry),
                    "patient": {"id": str(entry.patient_id), "fullName": entry.patient.full_name},
                }
                for entry in entries
            ]
        }
    )


@require_POST
@api_login_required
def waitlist_staff_update_status(request, entry_id):
    organization, error = organization_or_error(request, roles=SCHEDULING_ROLES)
    if error:
        return error
    entry = Waitlist.objects.filter(pk=entry_id, organization=organization).first()
    if entry is None:
        return api_error("Waitlist entry was not found.", status=404)
    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)
    new_status = str(payload.get("status", ""))
    if new_status not in {Waitlist.Status.FULFILLED, Waitlist.Status.CANCELLED}:
        return api_validation_error({"status": "Choose fulfilled or cancelled."})
    entry.status = new_status
    entry.save(update_fields=["status", "updated_at"])
    record_audit_event(
        actor=request.user,
        action="waitlist.status_updated",
        obj=entry,
        patient=entry.patient,
        request=request,
        metadata={"status": new_status},
    )
    return JsonResponse({"entry": _serialize_waitlist_entry(entry)})


# --- Patient: digital intake / forms engine ---------------------------------


def _serialize_submission(submission: FormSubmission, *, include_schema: bool = False) -> dict:
    payload = {
        "id": str(submission.pk),
        "templateSlug": submission.template.slug,
        "templateName": submission.template.name,
        "category": submission.template.category,
        "status": display_status(submission),
        "data": submission.data,
        "startedAt": submission.started_at.isoformat() if submission.started_at else None,
        "submittedAt": submission.submitted_at.isoformat() if submission.submitted_at else None,
    }
    if include_schema:
        payload["schema"] = submission.template.schema
    return payload


@require_GET
@api_login_required
def portal_forms_list(request):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    return JsonResponse({"forms": forms_overview(patient)})


def _portal_form_template_or_error(patient: Patient, template_slug: str):
    ensure_form_templates(patient.organization)
    template = FormTemplate.objects.filter(organization=patient.organization, slug=template_slug, is_active=True).first()
    if template is None:
        return None, api_error("This form was not found.", status=404)
    return template, None


@require_GET
@api_login_required
def portal_form_detail(request, template_slug):
    """Returns the schema plus whichever submission the patient should
    currently see: their in-progress draft, a still-valid completed
    submission (read-only review), or a fresh row if the prior one expired."""
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    template, error = _portal_form_template_or_error(patient, template_slug)
    if error:
        return error
    submission = get_working_submission(patient, template)
    return JsonResponse({"submission": _serialize_submission(submission, include_schema=True)})


@require_POST
@api_login_required
def portal_form_save(request, template_slug):
    """Save progress without submitting — the form stays editable."""
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    template, error = _portal_form_template_or_error(patient, template_slug)
    if error:
        return error
    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)

    submission = get_working_submission(patient, template)
    if submission.status == FormSubmission.Status.COMPLETED:
        return api_error("This form has already been submitted.", status=409)

    submission.data = {**submission.data, **(payload.get("data") or {})}
    if submission.status == FormSubmission.Status.NOT_STARTED:
        submission.status = FormSubmission.Status.IN_PROGRESS
        submission.started_at = timezone.now()
    submission.save(update_fields=["data", "status", "started_at", "updated_at"])
    record_audit_event(
        actor=request.user, action="form.saved", obj=submission, patient=patient, request=request,
        metadata={"template": template.slug},
    )
    return JsonResponse({"submission": _serialize_submission(submission, include_schema=True)})


@require_POST
@api_login_required
def portal_form_submit(request, template_slug):
    """Finalize a submission: validates every required field from the
    template's own schema (no per-form-type validation code to maintain),
    captures the e-signature (typed name + timestamp + IP), and — for
    templates that map to a Consent.Kind — mirrors a Consent row so staff
    keep seeing patient consent in the one place they already look."""
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    template, error = _portal_form_template_or_error(patient, template_slug)
    if error:
        return error
    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)

    submission = get_working_submission(patient, template)
    if submission.status == FormSubmission.Status.COMPLETED:
        return api_error("This form has already been submitted.", status=409)

    submission.data = {**submission.data, **(payload.get("data") or {})}
    errors = validate_submission_data(template, submission.data)
    if errors:
        return api_validation_error(errors)

    now = timezone.now()
    submission.status = FormSubmission.Status.COMPLETED
    submission.started_at = submission.started_at or now
    submission.submitted_at = now
    submission.signature_name = str(submission.data.get("signatureName", ""))[:160]
    submission.signed_at = now
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    submission.signed_ip = (forwarded.split(",")[0].strip() if forwarded else "") or request.META.get("REMOTE_ADDR") or None
    submission.save()

    record_consent_if_applicable(template, submission, patient)
    record_audit_event(
        actor=request.user, action="form.submitted", obj=submission, patient=patient, request=request,
        metadata={"template": template.slug},
    )
    return JsonResponse({"submission": _serialize_submission(submission, include_schema=True)})


# --- Patient: insurance (self-reported info + card upload) ------------------


@require_GET
@api_login_required
def portal_insurance_payers(request):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    payers = Payer.objects.filter(organization=patient.organization, is_active=True).order_by("name")
    return JsonResponse({"payers": [{"id": str(payer.pk), "name": payer.name} for payer in payers]})


@require_http_methods(["GET", "POST"])
@api_login_required
def portal_insurance(request):
    patient, error = portal_patient_or_error(request)
    if error:
        return error

    if request.method == "GET":
        policies = patient.insurance_policies.select_related("payer").all()
        return JsonResponse({"policies": [serialize_patient_insurance(policy) for policy in policies]})

    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)
    rank = payload.get("rank") or PatientInsurance.Rank.PRIMARY
    if rank not in PatientInsurance.Rank.values:
        return api_validation_error({"rank": "Choose a valid rank."})

    # Upsert by rank: a patient correcting their own still-unverified info
    # (e.g. during intake) edits the same row in place — once staff have
    # billed against a policy they manage further changes from the staff
    # billing workspace instead, same as any other insurance edit there.
    policy = patient.insurance_policies.filter(rank=rank).first()
    if policy is None:
        policy = PatientInsurance(organization=patient.organization, patient=patient, rank=rank, created_by=patient.portal_user)
    payload = {**payload, "rank": rank}
    payload.setdefault("effectiveDate", timezone.localdate().isoformat())
    errors = _apply_insurance_payload(policy, payload, partial=False)
    if errors:
        return api_validation_error(errors)
    try:
        policy.full_clean()
        policy.save()
    except ValidationError as exc:
        return api_validation_error({field: " ".join(messages) for field, messages in exc.message_dict.items()})
    record_audit_event(
        actor=patient.portal_user, action="patient_insurance.self_reported", obj=policy, patient=patient, request=request,
        metadata={"payer_id": str(policy.payer_id), "rank": policy.rank},
    )
    return JsonResponse({"policy": serialize_patient_insurance(policy)}, status=201)


@require_POST
@api_login_required
def portal_insurance_card_upload(request, policy_id, side):
    if side not in ("front", "back"):
        return api_error("Choose front or back.", status=400)
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    policy = PatientInsurance.objects.filter(pk=policy_id, patient=patient).first()
    if not policy:
        return api_error("Insurance policy was not found.", status=404)

    upload = request.FILES.get("file")
    if not upload:
        return api_validation_error({"file": "Choose a file to upload."})
    if upload.size > MAX_CARD_UPLOAD_BYTES:
        return api_validation_error({"file": "Files must be 15 MB or smaller."})
    setattr(policy, "card_%s" % side, upload)
    try:
        policy.full_clean()
    except ValidationError:
        return api_validation_error({"file": "Unsupported file type. Allowed: PNG, JPG, JPEG."})
    policy.save()
    record_audit_event(
        actor=patient.portal_user, action="patient_insurance.card_uploaded", obj=policy, patient=patient, request=request,
        metadata={"side": side, "source": "patient_portal"},
    )
    return JsonResponse({"policy": serialize_patient_insurance(policy)}, status=201)


@require_GET
@api_login_required
def portal_insurance_card_download(request, policy_id, side):
    if side not in ("front", "back"):
        return api_error("Choose front or back.", status=400)
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    policy = PatientInsurance.objects.filter(pk=policy_id, patient=patient).first()
    if not policy:
        return api_error("Insurance policy was not found.", status=404)
    file_field = policy.card_front if side == "front" else policy.card_back
    if not file_field:
        return api_error("No card image has been uploaded for this side.", status=404)
    record_audit_event(
        actor=patient.portal_user, action="patient_insurance.card_downloaded", obj=policy, patient=patient, request=request,
        metadata={"side": side},
    )
    return FileResponse(
        file_field.open("rb"), as_attachment=False, filename="insurance-card-%s%s" % (side, Path(file_field.name).suffix)
    )


# --- Patient: documents (permitted-only view + own uploads) -----------------


def _serialize_portal_document(document: PatientDocument, patient: Patient) -> dict:
    """Deliberately omits `uploadedBy`'s staff identity — a patient sees
    only whether they uploaded it themselves or the clinic shared it, never
    which staff member. Only ever called against a `visible_to_patient=True`
    row; that's enforced by every queryset below, not by this function."""
    return {
        "id": str(document.pk),
        "title": document.title,
        "description": document.description,
        "originalFilename": document.original_filename,
        "sizeBytes": document.size_bytes,
        "uploadedAt": document.created_at.isoformat(),
        "uploadedByPatient": document.uploaded_by_id == patient.portal_user_id,
    }


@require_http_methods(["GET", "POST"])
@api_login_required
def portal_documents(request):
    patient, error = portal_patient_or_error(request)
    if error:
        return error

    if request.method == "GET":
        documents = PatientDocument.objects.filter(patient=patient, visible_to_patient=True).order_by("-created_at")
        return JsonResponse({"documents": [_serialize_portal_document(document, patient) for document in documents]})

    upload = request.FILES.get("file")
    if not upload:
        return api_validation_error({"file": "Choose a file to upload."})
    if upload.size > MAX_UPLOAD_BYTES:
        return api_validation_error({"file": "Files must be 15 MB or smaller."})
    title = request.POST.get("title", "").strip() or upload.name
    document = PatientDocument(
        patient=patient,
        uploaded_by=patient.portal_user,
        file=upload,
        original_filename=upload.name,
        title=title,
        description=request.POST.get("description", "").strip(),
        size_bytes=upload.size,
        # A patient's own upload is always immediately visible to them —
        # only a staff upload defaults hidden pending an explicit share.
        visible_to_patient=True,
    )
    try:
        document.full_clean()
    except ValidationError:
        return api_validation_error({"file": "Unsupported file type. Allowed: PDF, PNG, JPG, DOC, DOCX."})
    document.save()
    record_audit_event(
        actor=patient.portal_user, action="patient_document.uploaded", obj=document, patient=patient, request=request,
        metadata={"source": "patient_portal", "title": title},
    )
    return JsonResponse({"document": _serialize_portal_document(document, patient)}, status=201)


@require_GET
@api_login_required
def portal_document_download(request, document_id):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    document = PatientDocument.objects.filter(pk=document_id, patient=patient, visible_to_patient=True).first()
    if document is None:
        return api_error("Document was not found.", status=404)
    record_audit_event(
        actor=patient.portal_user, action="patient_document.downloaded", obj=document, patient=patient, request=request,
        metadata={"source": "patient_portal"},
    )
    return FileResponse(document.file.open("rb"), as_attachment=True, filename=document.original_filename)


# --- Patient: home exercise program (view, mark completed, adherence) -------


def _serialize_portal_exercise(exercise: HomeExercise) -> dict:
    last_log = exercise.logs.order_by("-completed_at").first()
    return {**serialize_home_exercise(exercise), "lastCompletedAt": last_log.completed_at.isoformat() if last_log else None}


def _serialize_hep_log(log: HomeExerciseLog) -> dict:
    return {
        "id": str(log.pk),
        "exerciseId": str(log.home_exercise_id),
        "exerciseName": log.home_exercise.name,
        "completedAt": log.completed_at.isoformat(),
        "painLevel": log.pain_level,
        "difficultyLevel": log.difficulty_level,
        "comment": log.comment,
    }


@require_GET
@api_login_required
def portal_hep(request):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    if not organization_has_feature(patient.organization, "hep"):
        return JsonResponse({"program": None})

    program = (
        HomeProgram.objects.filter(patient=patient, status=HomeProgram.Status.ACTIVE)
        .prefetch_related("exercises")
        .order_by("-created_at")
        .first()
    )
    if program is None:
        return JsonResponse({"program": None})

    week_ago = timezone.now() - timedelta(days=7)
    completions_last_7_days = HomeExerciseLog.objects.filter(
        patient=patient, home_exercise__home_program=program, completed_at__gte=week_ago
    ).count()
    return JsonResponse(
        {
            "program": {
                "id": str(program.pk),
                "title": program.title,
                "patientInstructions": program.patient_instructions,
                "precautions": program.precautions,
                "exercises": [_serialize_portal_exercise(exercise) for exercise in program.exercises.all()],
                "completionsLast7Days": completions_last_7_days,
            }
        }
    )


def _parse_scale_value(payload: dict, key: str) -> tuple[int | None, bool]:
    value = payload.get(key)
    if value in (None, ""):
        return None, True
    try:
        return int(value), True
    except (TypeError, ValueError):
        return None, False


@require_POST
@api_login_required
def portal_hep_complete(request, exercise_id):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    exercise = HomeExercise.objects.filter(
        pk=exercise_id, home_program__patient=patient, home_program__status=HomeProgram.Status.ACTIVE
    ).first()
    if exercise is None:
        return api_error("Exercise was not found.", status=404)
    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)

    pain_level, pain_ok = _parse_scale_value(payload, "painLevel")
    difficulty_level, difficulty_ok = _parse_scale_value(payload, "difficultyLevel")
    errors = {}
    if not pain_ok:
        errors["painLevel"] = "Enter a whole number from 0 to 10."
    if not difficulty_ok:
        errors["difficultyLevel"] = "Enter a whole number from 0 to 10."
    if errors:
        return api_validation_error(errors)

    log = HomeExerciseLog(
        patient=patient, home_exercise=exercise, pain_level=pain_level, difficulty_level=difficulty_level,
        comment=str(payload.get("comment", ""))[:500],
    )
    try:
        log.full_clean()
        log.save()
    except ValidationError as exc:
        return api_validation_error({field: " ".join(messages) for field, messages in exc.message_dict.items()})
    record_audit_event(
        actor=patient.portal_user, action="home_exercise.completed", obj=log, patient=patient, request=request,
        metadata={"exercise": exercise.name},
    )
    return JsonResponse({"log": _serialize_hep_log(log)}, status=201)


@require_GET
@api_login_required
def portal_hep_logs(request):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    logs = HomeExerciseLog.objects.filter(patient=patient).select_related("home_exercise").order_by("-completed_at")[:100]
    return JsonResponse({"logs": [_serialize_hep_log(log) for log in logs]})


# --- Patient: outcome measures (view due, auto-scored submission) -----------


def _serialize_outcome_assignment(assignment: OutcomeAssignment) -> dict:
    return {
        "id": str(assignment.pk),
        "measure": assignment.measure,
        "measureLabel": assignment.get_measure_display(),
        "status": assignment.status,
        "assignedAt": assignment.assigned_at.isoformat(),
    }


@require_GET
@api_login_required
def portal_outcomes_list(request):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    assignments = OutcomeAssignment.objects.filter(patient=patient).order_by("-assigned_at")[:50]
    return JsonResponse({"assignments": [_serialize_outcome_assignment(assignment) for assignment in assignments]})


@require_GET
@api_login_required
def portal_outcome_detail(request, assignment_id):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    assignment = OutcomeAssignment.objects.filter(pk=assignment_id, patient=patient).first()
    if assignment is None:
        return api_error("This outcome measure was not found.", status=404)
    return JsonResponse(
        {"assignment": _serialize_outcome_assignment(assignment), "schema": outcome_measure_schema(assignment.measure)}
    )


@require_POST
@api_login_required
def portal_outcome_submit(request, assignment_id):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    assignment = OutcomeAssignment.objects.filter(pk=assignment_id, patient=patient).first()
    if assignment is None:
        return api_error("This outcome measure was not found.", status=404)
    if assignment.status == OutcomeAssignment.Status.COMPLETED:
        return api_error("This outcome measure has already been completed.", status=409)
    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)

    item_responses = payload.get("itemResponses")
    if not isinstance(item_responses, dict):
        item_responses = {}
    errors = validate_outcome_responses(assignment.measure, item_responses)
    if errors:
        return api_validation_error(errors)
    score, maximum_score = score_outcome_measure(assignment.measure, item_responses)

    outcome = OutcomeScore(
        patient=patient,
        recorded_by=patient.portal_user,
        measure=assignment.measure,
        measured_on=timezone.localdate(),
        score=score,
        maximum_score=maximum_score,
        item_responses=item_responses,
    )
    try:
        outcome.full_clean()
        outcome.save()
    except ValidationError as exc:
        if "__all__" in exc.message_dict:
            return api_error("You've already completed this measure today — try again tomorrow.", status=409)
        return api_validation_error({field: " ".join(messages) for field, messages in exc.message_dict.items()})

    assignment.status = OutcomeAssignment.Status.COMPLETED
    assignment.completed_score = outcome
    assignment.save(update_fields=["status", "completed_score", "updated_at"])

    record_audit_event(
        actor=patient.portal_user, action="outcome_assignment.completed", obj=assignment, patient=patient, request=request,
        metadata={"measure": assignment.measure},
    )
    return JsonResponse(
        {"assignment": _serialize_outcome_assignment(assignment), "score": str(score), "maximumScore": str(maximum_score)}
    )


# --- Patient: secure messaging (routed, content-free notifications) ---------


def _route_message_recipient(patient: Patient, category: str) -> User | None:
    """Category-based triage to an appropriate staff member — the routing
    the spec calls for (general/appointment/HEP/billing/clinical)."""
    organization = patient.organization
    if category in (SecureMessage.Category.CLINICAL, SecureMessage.Category.HEP):
        if patient.assigned_therapist_id and patient.assigned_therapist.is_active:
            return patient.assigned_therapist
        return (
            User.objects.filter(organization=organization, role=User.Role.THERAPIST, is_active=True)
            .order_by("last_name", "first_name")
            .first()
        )
    if category == SecureMessage.Category.BILLING:
        return (
            User.objects.filter(organization=organization, role=User.Role.BILLER, is_active=True).order_by("last_name").first()
            or User.objects.filter(organization=organization, role=User.Role.ADMIN, is_active=True).order_by("last_name").first()
        )
    # APPOINTMENT, GENERAL
    return (
        User.objects.filter(organization=organization, role=User.Role.SCHEDULER, is_active=True).order_by("last_name").first()
        or User.objects.filter(organization=organization, role=User.Role.ADMIN, is_active=True).order_by("last_name").first()
    )


def _serialize_portal_message(message: SecureMessage, patient: Patient) -> dict:
    is_outbound = message.sender_id == patient.portal_user_id
    counterpart = message.recipient if is_outbound else message.sender
    return {
        "id": str(message.pk),
        "direction": "outbound" if is_outbound else "inbound",
        "category": message.category,
        "categoryLabel": message.get_category_display(),
        "subject": message.subject,
        "body": message.body,
        "counterpartName": counterpart.get_full_name() or counterpart.username,
        "createdAt": message.created_at.isoformat(),
        "readAt": message.read_at.isoformat() if message.read_at else None,
    }


def _portal_notifications(patient: Patient) -> list[dict]:
    """Content-free by construction — category and sender only, never
    subject or body. This is what both the dashboard tile and any future
    notification center are built from."""
    unread = (
        SecureMessage.objects.filter(patient=patient, recipient=patient.portal_user, read_at__isnull=True)
        .select_related("sender")
        .order_by("-created_at")[:10]
        if patient.portal_user_id
        else []
    )
    return [
        {
            "id": str(message.pk),
            "type": "message",
            "categoryLabel": message.get_category_display(),
            "receivedAt": message.created_at.isoformat(),
        }
        for message in unread
    ]


@require_http_methods(["GET", "POST"])
@api_login_required
def portal_messages(request):
    patient, error = portal_patient_or_error(request)
    if error:
        return error

    if request.method == "GET":
        messages = (
            SecureMessage.objects.filter(patient=patient).select_related("sender", "recipient").order_by("-created_at")[:100]
        )
        return JsonResponse({"messages": [_serialize_portal_message(message, patient) for message in messages]})

    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)
    category = payload.get("category") or SecureMessage.Category.GENERAL
    if category not in SecureMessage.Category.values:
        return api_validation_error({"category": "Choose a valid category."})
    subject = str(payload.get("subject", "")).strip()[:180]
    body = str(payload.get("body", "")).strip()
    errors = {}
    if not subject:
        errors["subject"] = "Subject is required."
    if not body:
        errors["body"] = "Message is required."
    if errors:
        return api_validation_error(errors)

    recipient = _route_message_recipient(patient, category)
    if recipient is None:
        return api_error("No staff member is available to receive this message right now. Please call the clinic.", status=409)

    message = SecureMessage(
        patient=patient, sender=patient.portal_user, recipient=recipient, category=category,
        subject=subject, body=body[:50000],
    )
    try:
        message.full_clean()
        message.save()
    except ValidationError as exc:
        return api_validation_error({field: " ".join(messages) for field, messages in exc.message_dict.items()})
    record_audit_event(
        actor=patient.portal_user, action="secure_message.sent", obj=message, patient=patient, request=request,
        metadata={"category": category, "source": "patient_portal"},
    )
    send_secure_message_notification_email(recipient, patient.organization)
    return JsonResponse({"message": _serialize_portal_message(message, patient)}, status=201)


@require_POST
@api_login_required
def portal_message_mark_read(request, message_id):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    message = SecureMessage.objects.filter(pk=message_id, patient=patient, recipient=patient.portal_user).first()
    if message is None:
        return api_error("Message was not found.", status=404)
    if message.read_at is None:
        message.read_at = timezone.now()
        message.save(update_fields=["read_at", "updated_at"])
    return JsonResponse({"message": _serialize_portal_message(message, patient)})


# --- Patient: payments (balance, invoices, receipts, honest online-pay) -----


def _serialize_patient_payment(payment: PatientPayment) -> dict:
    return {
        "id": str(payment.pk),
        "amount": str(payment.amount),
        "status": payment.status,
        "statusLabel": payment.get_status_display(),
        "attemptedAt": payment.attempted_at.isoformat(),
        "message": payment.failure_message,
    }


def _serialize_receipt(record: PaymentRecord) -> dict:
    return {
        "id": str(record.pk),
        "amount": str(record.amount),
        "receivedOn": record.received_on.isoformat(),
        "status": record.status,
        "statusLabel": record.get_status_display(),
        "superbillId": str(record.superbill_id) if record.superbill_id else None,
    }


@require_GET
@api_login_required
def portal_payments(request):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    balance = patient_combined_balance(patient)
    statements = PatientStatement.objects.filter(patient=patient).order_by("-statement_date")[:12]
    received_payments = (
        PaymentRecord.objects.filter(patient=patient, status=PaymentRecord.Status.RECEIVED).order_by("-received_on")[:24]
    )
    online_attempts = PatientPayment.objects.filter(patient=patient).order_by("-attempted_at")[:24]
    return JsonResponse(
        {
            "insuranceBalance": str(balance["insuranceBalance"]),
            "cashBalance": str(balance["cashBalance"]),
            "totalBalance": str(balance["totalBalance"]),
            "statements": [
                {
                    "id": str(statement.pk),
                    "statementDate": statement.statement_date.isoformat(),
                    "dueDate": statement.due_date.isoformat(),
                    "balanceAtGeneration": str(statement.balance_at_generation),
                }
                for statement in statements
            ],
            "receipts": [_serialize_receipt(record) for record in received_payments],
            "onlinePaymentAttempts": [_serialize_patient_payment(payment) for payment in online_attempts],
        }
    )


@require_GET
@api_login_required
def portal_statement_detail(request, statement_id):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    statement = PatientStatement.objects.filter(pk=statement_id, patient=patient).first()
    if statement is None:
        return api_error("Statement was not found.", status=404)
    return JsonResponse({"statement": build_patient_statement_data(statement)})


@require_POST
@api_login_required
def portal_payment_charge(request):
    """Attempts an online payment via care/payment_processor.py. Never
    raises on a decline — a "not connected" result is a normal, honest
    outcome, not an application error, so this always returns 200 with
    `succeeded` telling the frontend what actually happened."""
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    if not organization_has_feature(patient.organization, "billing"):
        return api_error("Online payment is not enabled for this organization.", status=403)
    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)
    try:
        amount = Decimal(str(payload.get("amount", "")))
    except InvalidOperation:
        return api_validation_error({"amount": "Enter a valid amount."})
    if amount <= 0:
        return api_validation_error({"amount": "Enter an amount greater than zero."})

    payment = PatientPayment(patient=patient, amount=amount)
    try:
        payment.full_clean()
        payment.save()
    except ValidationError as exc:
        return api_validation_error({field: " ".join(messages) for field, messages in exc.message_dict.items()})

    result = get_payment_processor(patient.organization).charge(patient=patient, amount=amount)
    payment.status = PatientPayment.Status.SUCCEEDED if result.succeeded else PatientPayment.Status.FAILED
    payment.processor_reference = result.processor_reference
    payment.failure_message = "" if result.succeeded else result.message
    payment.save(update_fields=["status", "processor_reference", "failure_message", "updated_at"])

    record_audit_event(
        actor=patient.portal_user, action="patient_payment.attempted", obj=payment, patient=patient, request=request,
        metadata={"amount": str(amount), "succeeded": result.succeeded},
    )
    return JsonResponse(
        {"payment": _serialize_patient_payment(payment), "succeeded": result.succeeded, "message": result.message}
    )


# --- Patient: superbill (read-only, reuses the staff data builder) ---------


def _serialize_portal_superbill_summary(superbill: Superbill) -> dict:
    return {
        "id": str(superbill.pk),
        "serviceDate": superbill.service_date.isoformat(),
        "amount": str(superbill.amount),
        "status": superbill.status,
        "statusLabel": superbill.get_status_display(),
    }


@require_GET
@api_login_required
def portal_superbills(request):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    superbills = Superbill.objects.filter(patient=patient).order_by("-service_date")[:24]
    return JsonResponse({"superbills": [_serialize_portal_superbill_summary(superbill) for superbill in superbills]})


@require_GET
@api_login_required
def portal_superbill_detail(request, superbill_id):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    superbill = Superbill.objects.filter(pk=superbill_id, patient=patient).first()
    if superbill is None:
        return api_error("Superbill was not found.", status=404)
    return JsonResponse({"superbill": build_patient_superbill_data(superbill)})


# --- Patient: profile self-service -------------------------------------------
#
# Two tiers, by design: low-risk preference fields (pharmacy, how the
# patient prefers to be contacted, whether they want the secure-message
# notification email) write straight to Patient — no one can defraud a
# patient by changing where their pharmacy is. Contact fields that could
# matter for identity or billing (phone/email/address/emergency contact)
# instead go through PatientProfileChangeRequest and require a staff
# decision before they ever touch the Patient row.


def _serialize_profile(patient: Patient) -> dict:
    pending = patient.profile_change_requests.filter(status=PatientProfileChangeRequest.Status.PENDING).first()
    return {
        "fullName": patient.full_name,
        "dateOfBirth": patient.date_of_birth.isoformat(),
        "phone": patient.phone,
        "email": patient.email,
        "address": patient.address,
        "emergencyContact": patient.emergency_contact,
        "pharmacyName": patient.pharmacy_name,
        "pharmacyPhone": patient.pharmacy_phone,
        "pharmacyAddress": patient.pharmacy_address,
        "preferredContactMethod": patient.preferred_contact_method,
        "emailNotificationsEnabled": patient.email_notifications_enabled,
        "pendingChangeRequest": _serialize_profile_change_request(pending) if pending else None,
    }


def _serialize_profile_change_request(change_request: PatientProfileChangeRequest) -> dict:
    return {
        "id": str(change_request.pk),
        "changes": change_request.changes,
        "status": change_request.status,
        "statusLabel": change_request.get_status_display(),
        "createdAt": change_request.created_at.isoformat(),
        "reviewedAt": change_request.reviewed_at.isoformat() if change_request.reviewed_at else None,
        "reviewerNote": change_request.reviewer_note,
    }


@require_GET
@api_login_required
def portal_profile(request):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    return JsonResponse({"profile": _serialize_profile(patient)})


@require_http_methods(["PATCH"])
@api_login_required
def portal_profile_preferences(request):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)

    changed_fields = []
    if "pharmacyName" in payload:
        patient.pharmacy_name = str(payload["pharmacyName"] or "").strip()[:160]
        changed_fields.append("pharmacy_name")
    if "pharmacyPhone" in payload:
        patient.pharmacy_phone = str(payload["pharmacyPhone"] or "").strip()[:32]
        changed_fields.append("pharmacy_phone")
    if "pharmacyAddress" in payload:
        patient.pharmacy_address = str(payload["pharmacyAddress"] or "").strip()
        changed_fields.append("pharmacy_address")
    if "preferredContactMethod" in payload:
        method = payload["preferredContactMethod"]
        if method not in Patient.ContactMethod.values:
            return api_validation_error({"preferredContactMethod": "Choose a valid contact method."})
        patient.preferred_contact_method = method
        changed_fields.append("preferred_contact_method")
    if "emailNotificationsEnabled" in payload:
        patient.email_notifications_enabled = bool(payload["emailNotificationsEnabled"])
        changed_fields.append("email_notifications_enabled")

    if not changed_fields:
        return api_validation_error({"detail": "No recognized fields were provided."})

    patient.full_clean()
    patient.save(update_fields=changed_fields + ["updated_at"])
    record_audit_event(
        actor=patient.portal_user, action="patient_profile.preferences_updated", obj=patient, patient=patient, request=request,
        metadata={"fields": changed_fields},
    )
    return JsonResponse({"profile": _serialize_profile(patient)})


@require_POST
@api_login_required
def portal_profile_change_request_create(request):
    patient, error = portal_patient_or_error(request)
    if error:
        return error
    if patient.profile_change_requests.filter(status=PatientProfileChangeRequest.Status.PENDING).exists():
        return api_error("You already have a pending profile change request awaiting review.", status=409)
    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)

    field_map = {"phone": "phone", "email": "email", "address": "address", "emergencyContact": "emergency_contact"}
    changes = {}
    for payload_key, field_name in field_map.items():
        if payload_key in payload:
            changes[field_name] = str(payload[payload_key] or "").strip()
    if not changes:
        return api_validation_error({"detail": "At least one field change is required."})

    change_request = PatientProfileChangeRequest(patient=patient, requested_by=patient.portal_user, changes=changes)
    try:
        change_request.full_clean()
        change_request.save()
    except ValidationError as exc:
        return api_validation_error({field: " ".join(messages) for field, messages in exc.message_dict.items()})

    record_audit_event(
        actor=patient.portal_user, action="patient_profile.change_requested", obj=change_request, patient=patient, request=request,
        metadata={"fields": list(changes.keys())},
    )
    return JsonResponse({"changeRequest": _serialize_profile_change_request(change_request)}, status=201)


# --- Staff: profile change request review queue ------------------------------


@require_GET
@api_login_required
def profile_change_requests_staff_list(request):
    organization, error = organization_or_error(request, roles=CLINICAL_ROLES)
    if error:
        return error
    requests = (
        PatientProfileChangeRequest.objects.filter(patient__organization=organization, status=PatientProfileChangeRequest.Status.PENDING)
        .select_related("patient", "requested_by")
        .order_by("-created_at")
    )
    return JsonResponse(
        {
            "requests": [
                {
                    **_serialize_profile_change_request(change_request),
                    "patient": {"id": str(change_request.patient_id), "fullName": change_request.patient.full_name},
                }
                for change_request in requests
            ]
        }
    )


@require_POST
@api_login_required
def profile_change_request_staff_decide(request, request_id):
    organization, error = organization_or_error(request, roles=CLINICAL_ROLES)
    if error:
        return error
    change_request = PatientProfileChangeRequest.objects.select_related("patient").filter(
        pk=request_id, patient__organization=organization
    ).first()
    if change_request is None:
        return api_error("Change request was not found.", status=404)
    if change_request.status != PatientProfileChangeRequest.Status.PENDING:
        return api_error("This request has already been decided.", status=409)
    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)
    decision = payload.get("decision")
    if decision not in ("approve", "reject"):
        return api_validation_error({"decision": "Choose approve or reject."})

    patient = change_request.patient
    if decision == "approve":
        for field_name, value in change_request.changes.items():
            setattr(patient, field_name, value)
        patient.full_clean()
        patient.save(update_fields=list(change_request.changes.keys()) + ["updated_at"])
        change_request.status = PatientProfileChangeRequest.Status.APPROVED
    else:
        change_request.status = PatientProfileChangeRequest.Status.REJECTED
    change_request.reviewed_by = request.user
    change_request.reviewed_at = timezone.now()
    change_request.reviewer_note = str(payload.get("note", "")).strip()[:2000]
    change_request.save(update_fields=["status", "reviewed_by", "reviewed_at", "reviewer_note", "updated_at"])

    record_audit_event(
        actor=request.user,
        action="patient_profile.change_approved" if decision == "approve" else "patient_profile.change_rejected",
        obj=change_request,
        patient=patient,
        request=request,
        metadata={"fields": list(change_request.changes.keys())},
    )
    return JsonResponse({"changeRequest": _serialize_profile_change_request(change_request)})
