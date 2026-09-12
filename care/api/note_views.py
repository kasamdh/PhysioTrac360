"""Clinical documentation API: list, create, view, edit, sign, cosign, and
addendum for `ClinicalNote` records — the React-facing counterpart to the
legacy server-rendered note views in `care/views.py`. Both call into
`care/note_management.py` for permission checks and lifecycle transitions so
identical rules are enforced everywhere, not just identical UI copy.
"""
from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .. import note_management
from ..access import CLINICAL_ROLES, organization_required, patients_for, require_patient_access
from ..entitlements import organization_has_feature
from ..models import AIArtifact, ClinicalNote, NoteIntervention, Patient, User
from ..services import _source_fingerprint, coding_suggestions, format_coding_draft_text, record_audit_event
from .serializers import serialize_artifact, serialize_intervention, serialize_note_detail, serialize_note_summary
from .utils import InvalidJSON, api_error, api_login_required, api_validation_error, json_body, organization_or_error


def _validation_response(error: ValidationError) -> JsonResponse:
    if hasattr(error, "message_dict"):
        errors = error.message_dict
    else:
        errors = {"nonFieldErrors": error.messages}
    return api_validation_error(errors)


def _save_or_error(instance) -> JsonResponse | None:
    try:
        instance.full_clean()
        instance.save()
    except ValidationError as error:
        return _validation_response(error)
    return None


def _payload_or_error(request):
    try:
        return json_body(request), None
    except InvalidJSON as error:
        return None, api_error(str(error), status=400)


def _required_text(payload: dict, key: str, label: str, *, limit: int | None = None):
    value = payload.get(key, "")
    if not isinstance(value, str) or not value.strip():
        return None, api_error(f"{label} is required.", status=400)
    value = value.strip()
    if limit is not None and len(value) > limit:
        return None, api_error(f"{label} must be {limit} characters or fewer.", status=400)
    return value, None


def _clinical_patient_or_error(request, patient_id: str):
    _, error = organization_or_error(request, roles=CLINICAL_ROLES)
    if error:
        return None, error
    patient = Patient.objects.select_related("assigned_therapist", "organization").filter(pk=patient_id).first()
    if patient is None:
        return None, api_error("Patient record was not found.", status=404)
    try:
        require_patient_access(request, patient, clinical=True)
    except PermissionDenied as error:
        return None, api_error(str(error), status=403)
    return patient, None


def _note_or_error(request, note_id: str):
    _, error = organization_or_error(request, roles=CLINICAL_ROLES)
    if error:
        return None, error
    note = (
        ClinicalNote.objects.select_related("patient", "patient__organization", "therapist")
        .filter(pk=note_id)
        .first()
    )
    if note is None:
        return None, api_error("Note was not found.", status=404)
    try:
        require_patient_access(request, note.patient, clinical=True)
    except PermissionDenied as error:
        return None, api_error(str(error), status=403)
    return note, None


@require_GET
@api_login_required
def documentation_list(request):
    """Org-wide, role-scoped documentation list backing the Documentation landing page."""
    organization = organization_required(request.user)
    notes = (
        ClinicalNote.objects.filter(patient__organization=organization)
        .filter(patient__in=patients_for(request.user, clinical=True))
        .select_related("patient", "therapist")
    )

    status = request.GET.get("status", "").strip()
    if status and status in ClinicalNote.Status.values:
        notes = notes.filter(status=status)
    note_type = request.GET.get("noteType", "").strip()
    if note_type and note_type in ClinicalNote.Type.values:
        notes = notes.filter(note_type=note_type)
    therapist_id = request.GET.get("providerId", "").strip()
    if therapist_id:
        notes = notes.filter(therapist_id=therapist_id)

    quick = request.GET.get("quick", "").strip()
    today = timezone.localdate()
    if quick == "mine":
        notes = notes.filter(therapist=request.user)
    elif quick == "unsigned":
        notes = notes.exclude(status=ClinicalNote.Status.SIGNED)
    elif quick == "today":
        notes = notes.filter(service_date=today)
    elif quick == "drafts":
        notes = notes.filter(status=ClinicalNote.Status.DRAFT)
    elif quick == "completed":
        notes = notes.filter(status=ClinicalNote.Status.SIGNED)

    query = request.GET.get("q", "").strip()
    if query:
        notes = notes.filter(
            Q(patient__first_name__icontains=query)
            | Q(patient__last_name__icontains=query)
            | Q(patient__medical_record_number__icontains=query)
            | Q(therapist__first_name__icontains=query)
            | Q(therapist__last_name__icontains=query)
        )

    notes = notes.order_by("-service_date", "-created_at")
    try:
        page_size = min(max(int(request.GET.get("pageSize", "25")), 10), 100)
        page = max(int(request.GET.get("page", "1")), 1)
    except ValueError:
        return api_error("Page and page size must be whole numbers.", status=400)
    total = notes.count()
    records = list(notes[(page - 1) * page_size: page * page_size])
    return JsonResponse({
        "notes": [serialize_note_summary(note) for note in records],
        "total": total,
        "page": page,
        "pageSize": page_size,
    })


@require_POST
@api_login_required
def note_create(request, patient_id: str):
    patient, error = _clinical_patient_or_error(request, patient_id)
    if error:
        return error
    payload, error = _payload_or_error(request)
    if error:
        return error
    note_type, error = _required_text(payload, "noteType", "Note type")
    if error:
        return error
    if note_type not in ClinicalNote.Type.values:
        return api_error("Choose a supported note type.", status=400)

    appointment = None
    appointment_id = payload.get("appointmentId")
    if appointment_id:
        appointment = patient.appointments.filter(pk=appointment_id).first()
        if appointment is None:
            return api_error("Appointment was not found for this patient.", status=404)
        existing = getattr(appointment, "clinical_note", None)
        if existing is not None:
            # Never create a duplicate encounter note for an appointment that already has one.
            return JsonResponse({"note": serialize_note_detail(existing)}, status=200)

    episode_of_care = None
    episode_id = payload.get("episodeOfCareId")
    if episode_id:
        episode_of_care = patient.episodes_of_care.filter(pk=episode_id).first()
        if episode_of_care is None:
            return api_error("Episode of care was not found for this patient.", status=404)

    note = ClinicalNote(
        patient=patient,
        therapist=request.user,
        appointment=appointment,
        episode_of_care=episode_of_care,
        note_type=note_type,
        diagnosis_snapshot=patient.diagnoses,
        precautions_snapshot=patient.precautions,
    )
    if request.user.role == User.Role.ASSISTANT:
        note.cosign_required = patient.organization.pta_cosign_required
    error_response = _save_or_error(note)
    if error_response:
        return error_response
    record_audit_event(
        actor=request.user, action="note.created", obj=note, patient=patient, request=request,
        metadata={"note_type": note.note_type},
    )
    return JsonResponse({"note": serialize_note_detail(note)}, status=201)


_NOTE_TEXT_FIELDS = {
    "subjective": "subjective", "objective": "objective", "interventions": "interventions",
    "assessment": "assessment", "plan": "plan",
    "diagnosisSnapshot": "diagnosis_snapshot", "precautionsSnapshot": "precautions_snapshot",
}
_NOTE_JSON_FIELDS = {
    "subjectiveDetails": "subjective_details", "objectiveMeasurements": "objective_measurements",
    "dischargeDetails": "discharge_details", "homeVisitDetails": "home_visit_details",
}
_NOTE_DATE_FIELDS = {
    "serviceDate": "service_date", "planOfCareStart": "plan_of_care_start",
    "planOfCareEnd": "plan_of_care_end", "reassessmentDue": "reassessment_due",
}
_NOTE_INT_FIELDS = {"frequencyPerWeek": "frequency_per_week", "durationWeeks": "duration_weeks"}


@require_http_methods(["GET", "PATCH"])
@api_login_required
def note_detail(request, note_id: str):
    """GET returns the note; PATCH edits it (only while editable — see
    `note_management.can_edit_note`). One dispatcher per path, matching this
    codebase's existing convention (e.g. `organization_users`, `user_detail`)."""
    note, error = _note_or_error(request, note_id)
    if error:
        return error

    if request.method == "GET":
        record_audit_event(
            actor=request.user, action="note.viewed", obj=note, patient=note.patient, request=request,
            metadata={"status": note.status},
        )
        return JsonResponse({"note": serialize_note_detail(note)})

    if not note_management.can_edit_note(request.user, note):
        return api_error("This note is locked or belongs to another clinician.", status=403)
    payload, error = _payload_or_error(request)
    if error:
        return error

    for camel, field in _NOTE_TEXT_FIELDS.items():
        if camel in payload and isinstance(payload[camel], str):
            setattr(note, field, payload[camel])
    for camel, field in _NOTE_JSON_FIELDS.items():
        if camel in payload and isinstance(payload[camel], dict):
            setattr(note, field, payload[camel])
    for camel, field in _NOTE_DATE_FIELDS.items():
        if camel in payload:
            setattr(note, field, payload[camel] or None)
    for camel, field in _NOTE_INT_FIELDS.items():
        if camel in payload:
            setattr(note, field, payload[camel] or None)
    if payload.get("submitForReview"):
        note.status = ClinicalNote.Status.REVIEW_REQUIRED

    error_response = _save_or_error(note)
    if error_response:
        return error_response
    record_audit_event(
        actor=request.user, action="note.updated", obj=note, patient=note.patient, request=request,
        metadata={"status": note.status},
    )
    return JsonResponse({"note": serialize_note_detail(note)})


@require_POST
@api_login_required
def note_sign(request, note_id: str):
    note, error = _note_or_error(request, note_id)
    if error:
        return error
    if not note_management.can_finalize_note(request.user, note):
        return api_error("Only the treating therapist or an authorized director may finalize this note.", status=403)
    payload, error = _payload_or_error(request)
    if error:
        return error
    _, errors, status_code = note_management.sign_note(
        note=note, user=request.user, attestation_confirmed=payload.get("attestation") is True, request=request,
    )
    if errors:
        return JsonResponse(
            {"detail": errors.get("status") or errors.get("attestation") or "Unable to finalize this note.", "errors": errors},
            status=status_code,
        )
    return JsonResponse({"note": serialize_note_detail(note)})


@require_POST
@api_login_required
def note_cosign(request, note_id: str):
    note, error = _note_or_error(request, note_id)
    if error:
        return error
    if not note_management.can_cosign_note(request.user, note):
        return api_error("Only an authorized supervising clinician may cosign this note.", status=403)
    _, errors, status_code = note_management.cosign_note(note=note, user=request.user, request=request)
    if errors:
        return JsonResponse({"detail": errors.get("status") or "Unable to cosign this note.", "errors": errors}, status=status_code)
    return JsonResponse({"note": serialize_note_detail(note)})


@require_POST
@api_login_required
def addendum_create(request, note_id: str):
    note, error = _note_or_error(request, note_id)
    if error:
        return error
    if not note_management.can_create_addendum(request.user, note):
        return api_error("Only an authorized therapist can create this addendum.", status=403)
    payload, error = _payload_or_error(request)
    if error:
        return error
    reason, error = _required_text(payload, "reason", "Reason", limit=240)
    if error:
        return error
    body, error = _required_text(payload, "body", "Addendum text")
    if error:
        return error
    _, errors, status_code = note_management.create_addendum(
        note=note, user=request.user, reason=reason, body=body, request=request,
    )
    if errors:
        return JsonResponse({"detail": errors.get("status") or "Unable to save this addendum.", "errors": errors}, status=status_code)
    return JsonResponse({"note": serialize_note_detail(note)}, status=201)


@require_http_methods(["PUT"])
@api_login_required
def interventions_replace(request, note_id: str):
    """Replace the full set of treatment-timer line items for one note in a
    single call — matches how the frontend holds this table in local state
    and autosaves it as one unit, avoiding partial-failure ordering bugs from
    granular per-row endpoints."""
    note, error = _note_or_error(request, note_id)
    if error:
        return error
    if not note_management.can_edit_note(request.user, note):
        return api_error("This note is locked or belongs to another clinician.", status=403)
    payload, error = _payload_or_error(request)
    if error:
        return error
    rows = payload.get("items")
    if not isinstance(rows, list):
        return api_error("Provide a list of intervention line items.", status=400)

    prepared = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            return api_error("Each intervention item must be an object.", status=400)
        description = str(row.get("description", "")).strip()
        if not description:
            return api_error("Each intervention needs a description.", status=400)
        try:
            minutes = int(row.get("minutes") or 0)
            units = int(row["units"]) if row.get("units") not in (None, "") else None
        except (TypeError, ValueError):
            return api_error("Minutes and units must be whole numbers.", status=400)
        category = row.get("category") or ""
        if category and category not in NoteIntervention.Category.values:
            return api_error("Choose a supported intervention category.", status=400)
        item = NoteIntervention(
            note=note,
            description=description,
            body_region=str(row.get("bodyRegion", "")).strip(),
            minutes=minutes,
            units=units,
            is_timed=bool(row.get("isTimed", True)),
            patient_response=str(row.get("patientResponse", "")).strip(),
            order=index,
            category=category,
        )
        try:
            item.full_clean()
        except ValidationError as exc:
            return _validation_response(exc)
        prepared.append(item)

    with transaction.atomic():
        note.intervention_items.all().delete()
        NoteIntervention.objects.bulk_create(prepared)
    record_audit_event(
        actor=request.user, action="note.interventions_updated", obj=note, patient=note.patient, request=request,
        metadata={"count": len(prepared), "total_minutes": sum(item.minutes for item in prepared)},
    )
    return JsonResponse({"interventionItems": [serialize_intervention(item) for item in note.intervention_items.all()]})


@require_POST
@api_login_required
def coding_suggestions_create(request, note_id: str):
    """Deterministic, rule-based CPT-coding suggestions for this note's
    documented interventions — never an autonomous coder. Every result is
    stored as an auditable AIArtifact and must show as suggested, never
    submitted automatically (see `care/services.py:coding_suggestions`)."""
    note, error = _note_or_error(request, note_id)
    if error:
        return error
    if not organization_has_feature(note.patient.organization, "ai_scribe"):
        return api_error(
            "AI-assisted coding suggestions are not enabled for this organization. Contact your administrator.",
            status=403,
        )
    suggestion = coding_suggestions(note)
    artifact = AIArtifact.objects.create(
        patient=note.patient,
        requested_by=request.user,
        kind=AIArtifact.Kind.CODING,
        source_note_ids=[str(note.pk)],
        source_fingerprint=_source_fingerprint([note]),
        draft_text=format_coding_draft_text(note, suggestion),
    )
    record_audit_event(
        actor=request.user, action="ai_coding_suggestion.created", obj=artifact, patient=note.patient, request=request,
        metadata={"note_id": str(note.pk), "cpt_code_count": len(suggestion["cptSuggestions"])},
    )
    return JsonResponse(
        {"artifact": serialize_artifact(artifact, include_draft_text=True), "codingSuggestions": suggestion},
        status=201,
    )
