"""Focused, role-scoped workflow APIs for the React patient workspace.

These endpoints intentionally expose small actions rather than generic model CRUD.
The server remains responsible for tenant boundaries, permissions, validation, and
append-only audit events.
"""
from __future__ import annotations

from datetime import datetime

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET, require_POST

from ..access import (
    BILLING_ROLES,
    CLINICAL_ROLES,
    PAYMENT_COLLECTION_ROLES,
    SCHEDULING_ROLES,
    organization_required,
    patients_for,
    require_patient_access,
    require_role,
)
from ..models import (
    AIArtifact,
    Appointment,
    AuditEvent,
    ClinicalNote,
    Consent,
    FunctionalGoal,
    HomeProgram,
    IntakeSubmission,
    OutcomeScore,
    Patient,
    PaymentRecord,
    Referral,
    SecureMessage,
    Superbill,
    User,
    VoiceCapture,
)
from ..services import (
    compose_draft,
    goal_suggestions as build_goal_suggestions,
    home_program_suggestions,
    note_compliance_findings,
    outcome_measure_defaults,
    outcome_trends,
    patient_compliance_findings,
    record_audit_event,
)
from .serializers import (
    serialize_appointment,
    serialize_artifact,
    serialize_audit_event,
    serialize_consent,
    serialize_goal,
    serialize_home_program,
    serialize_intake,
    serialize_message,
    serialize_note_summary,
    serialize_outcome_trend,
    serialize_patient,
    serialize_payment,
    serialize_referral,
    serialize_superbill,
    serialize_voice_capture,
)
from .utils import (
    InvalidJSON,
    api_error,
    api_login_required,
    api_validation_error,
    json_body,
    organization_or_error,
)


AUDIT_REVIEW_ROLES = {User.Role.ADMIN, User.Role.DIRECTOR, User.Role.COMPLIANCE}
CLINICIAN_SCHEDULE_ROLES = {User.Role.THERAPIST, User.Role.ASSISTANT}


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
    except IntegrityError:
        return api_error(
            "A matching record already exists or the requested change conflicts with current data.",
            status=409,
        )
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


def _optional_text(payload: dict, key: str, default: str = "", *, limit: int | None = None):
    value = payload.get(key, default)
    if value is None:
        return default, None
    if not isinstance(value, str):
        return None, api_error(f"{key} must be text.", status=400)
    value = value.strip()
    if limit is not None and len(value) > limit:
        return None, api_error(f"{key} must be {limit} characters or fewer.", status=400)
    return value, None


def _patient_or_error(request, patient_id: str, *, clinical: bool):
    """Resolve a chart and retain the denied-access audit behavior from HTML views."""
    patient = Patient.objects.select_related("assigned_therapist").filter(pk=patient_id).first()
    if patient is None:
        return None, api_error("Patient record was not found.", status=404)
    try:
        require_patient_access(request, patient, clinical=clinical)
    except PermissionDenied as error:
        return None, api_error(str(error), status=403)
    return patient, None


def _clinical_patient_or_error(request, patient_id: str):
    _, error = organization_or_error(request, roles=CLINICAL_ROLES)
    if error:
        return None, error
    return _patient_or_error(request, patient_id, clinical=True)


def _operations_patient_or_error(request, patient_id: str):
    _, error = organization_or_error(request, roles=SCHEDULING_ROLES | BILLING_ROLES)
    if error:
        return None, error
    # PTs/PTAs retain their assigned-chart scope even when performing a schedule task.
    return _patient_or_error(
        request,
        patient_id,
        clinical=request.user.role in CLINICIAN_SCHEDULE_ROLES,
    )


def _artifact_or_error(request, artifact_id: str):
    artifact = (
        AIArtifact.objects.select_related("patient", "requested_by", "reviewed_by", "applied_note")
        .filter(pk=artifact_id)
        .first()
    )
    if artifact is None:
        return None, api_error("Draft was not found.", status=404)
    _, error = organization_or_error(request, roles=CLINICAL_ROLES)
    if error:
        return None, error
    _, error = _patient_or_error(request, str(artifact.patient_id), clinical=True)
    if error:
        return None, error
    return artifact, None


def _goal_or_error(request, goal_id: str):
    goal = FunctionalGoal.objects.select_related("patient", "approved_by").filter(pk=goal_id).first()
    if goal is None:
        return None, api_error("Goal was not found.", status=404)
    _, error = organization_or_error(request, roles=CLINICAL_ROLES)
    if error:
        return None, error
    _, error = _patient_or_error(request, str(goal.patient_id), clinical=True)
    if error:
        return None, error
    return goal, None


def _program_or_error(request, program_id: str):
    program = (
        HomeProgram.objects.select_related("patient", "prescribed_by")
        .prefetch_related("exercises")
        .filter(pk=program_id)
        .first()
    )
    if program is None:
        return None, api_error("Home program was not found.", status=404)
    _, error = organization_or_error(request, roles=CLINICAL_ROLES)
    if error:
        return None, error
    _, error = _patient_or_error(request, str(program.patient_id), clinical=True)
    if error:
        return None, error
    return program, None


def _note_payload(note: ClinicalNote) -> dict:
    payload = serialize_note_summary(note)
    payload["complianceFindings"] = [
        {
            "code": finding.code,
            "severity": finding.severity,
            "title": finding.title,
            "detail": finding.detail,
            "finalizationBlocker": finding.finalization_blocker,
        }
        for finding in note_compliance_findings(note)
    ]
    return payload


def _timeline_events(patient: Patient, query: str = "") -> list[dict]:
    """Build a compact timeline without returning note/message narrative."""
    query = query.strip().lower()
    events: list[dict] = []

    for note in patient.notes.all()[:80]:
        searchable = " ".join(
            [
                note.get_note_type_display(),
                note.get_status_display(),
                note.subjective,
                note.objective,
                note.assessment,
                note.plan,
            ]
        ).lower()
        if query and query not in searchable:
            continue
        events.append(
            {
                "id": f"note:{note.pk}",
                "occurredAt": note.service_date.isoformat(),
                "kind": "note",
                "label": note.get_note_type_display(),
                "detail": note.get_status_display(),
            }
        )

    for score in patient.outcomes.all()[:80]:
        searchable = f"{score.get_measure_display()} outcome score".lower()
        if query and query not in searchable:
            continue
        events.append(
            {
                "id": f"outcome:{score.pk}",
                "occurredAt": score.measured_on.isoformat(),
                "kind": "outcome",
                "label": score.get_measure_display(),
                "detail": "Outcome measure recorded",
            }
        )

    for artifact in patient.ai_artifacts.all()[:80]:
        searchable = f"{artifact.get_kind_display()} {artifact.get_status_display()}".lower()
        if query and query not in searchable:
            continue
        events.append(
            {
                "id": f"draft:{artifact.pk}",
                "occurredAt": timezone.localtime(artifact.created_at).isoformat(),
                "kind": "draft",
                "label": artifact.get_kind_display(),
                "detail": artifact.get_status_display(),
            }
        )

    for program in patient.home_programs.all()[:80]:
        searchable = f"{program.title} home program {program.get_status_display()}".lower()
        if query and query not in searchable:
            continue
        events.append(
            {
                "id": f"home-program:{program.pk}",
                "occurredAt": timezone.localtime(program.created_at).isoformat(),
                "kind": "home_program",
                "label": program.title,
                "detail": program.get_status_display(),
            }
        )

    for capture in patient.voice_captures.all()[:80]:
        searchable = f"voice transcript {capture.get_status_display()}".lower()
        if query and query not in searchable:
            continue
        events.append(
            {
                "id": f"voice:{capture.pk}",
                "occurredAt": timezone.localtime(capture.created_at).isoformat(),
                "kind": "voice",
                "label": "Reviewed voice transcript",
                "detail": capture.get_status_display(),
            }
        )

    return sorted(events, key=lambda event: event["occurredAt"], reverse=True)[:100]


def _clinical_workspace(patient: Patient) -> dict:
    notes = list(patient.notes.select_related("therapist").all()[:12])
    artifacts = list(
        patient.ai_artifacts.select_related("requested_by", "reviewed_by", "applied_note").all()[:12]
    )
    programs = list(
        patient.home_programs.select_related("prescribed_by").prefetch_related("exercises").all()[:8]
    )
    captures = list(patient.voice_captures.select_related("therapist").all()[:8])
    return {
        "notes": [_note_payload(note) for note in notes],
        "goals": [
            serialize_goal(goal, include_clinical_details=True)
            for goal in patient.goals.select_related("approved_by").all()[:12]
        ],
        "outcomes": [serialize_outcome_trend(item) for item in outcome_trends(patient)],
        "complianceFindings": [
            {
                "code": finding.code,
                "severity": finding.severity,
                "title": finding.title,
                "detail": finding.detail,
                "finalizationBlocker": finding.finalization_blocker,
            }
            for finding in patient_compliance_findings(patient)
        ],
        "artifacts": [
            serialize_artifact(artifact, include_draft_text=True) for artifact in artifacts
        ],
        "homePrograms": [serialize_home_program(program) for program in programs],
        "voiceCaptures": [
            serialize_voice_capture(capture, include_transcript=True) for capture in captures
        ],
        "timeline": _timeline_events(patient),
    }


def _operations_workspace(request, patient: Patient) -> dict:
    organization = organization_required(request.user)
    can_manage_schedule = request.user.can_manage_schedule
    can_manage_billing = request.user.role in BILLING_ROLES
    can_collect_payments = request.user.role in PAYMENT_COLLECTION_ROLES
    messages = patient.messages.filter(
        Q(sender=request.user) | Q(recipient=request.user)
    ).select_related("sender", "recipient")[:30]
    payload = {
        # Billing-only roles receive empty operational intake/consent collections;
        # the shape stays stable without disclosing unrelated administrative data.
        "consents": [],
        "intakes": [],
        "messages": [serialize_message(message, viewer=request.user) for message in messages],
        "recipients": [
            {
                "id": str(user.pk),
                "displayName": user.get_full_name() or user.username,
                "roleLabel": user.get_role_display(),
            }
            for user in User.objects.filter(organization=organization, is_active=True)
            .exclude(pk=request.user.pk)
            .order_by("last_name", "first_name", "username")
        ],
        "canManageSchedule": can_manage_schedule,
        "canManageBilling": can_manage_billing,
        "canCollectPayments": can_collect_payments,
    }
    if can_manage_schedule:
        payload["consents"] = [
            serialize_consent(consent)
            for consent in patient.consents.select_related("recorded_by").all()[:12]
        ]
        payload["intakes"] = [serialize_intake(intake) for intake in patient.intakes.all()[:12]]
        payload["referrals"] = [
            serialize_referral(referral) for referral in patient.referrals.select_related("created_by").all()[:12]
        ]
        payload["appointments"] = [
            serialize_appointment(appointment)
            for appointment in patient.appointments.select_related("therapist", "patient").all()[:12]
        ]
        payload["schedulingStaff"] = [
            {
                "id": str(user.pk),
                "displayName": user.get_full_name() or user.username,
                "roleLabel": user.get_role_display(),
            }
            for user in User.objects.filter(
                organization=organization,
                is_active=True,
                role__in=[
                    User.Role.ADMIN,
                    User.Role.DIRECTOR,
                    User.Role.THERAPIST,
                    User.Role.ASSISTANT,
                ],
            ).order_by("last_name", "first_name", "username")
        ]
    if can_manage_billing:
        payload["superbills"] = [
            serialize_superbill(superbill)
            for superbill in patient.superbills.select_related("clinician").all()[:24]
        ]
    if can_collect_payments:
        payload["payments"] = [
            serialize_payment(payment)
            for payment in patient.payments.select_related("superbill", "recorded_by").all()[:24]
        ]
    return payload


@require_GET
@api_login_required
def patient_workspace(request, patient_id: str):
    """Return only the workspace panels the caller is allowed to see."""
    clinical_allowed = request.user.role in CLINICAL_ROLES
    operations_allowed = request.user.role in (
        SCHEDULING_ROLES | BILLING_ROLES
    )
    if not clinical_allowed and not operations_allowed:
        return api_error("Your role is not permitted to access a patient workspace.", status=403)

    if clinical_allowed:
        patient, error = _clinical_patient_or_error(request, patient_id)
    else:
        patient, error = _operations_patient_or_error(request, patient_id)
    if error:
        return error

    payload = {
        "patient": serialize_patient(patient, include_clinical=clinical_allowed),
        "permissions": {
            "canAccessClinical": clinical_allowed,
            "canManageOperations": operations_allowed,
            "canSignNotes": request.user.can_sign_notes,
            "canManageBilling": request.user.role in BILLING_ROLES,
            "canReviewAudit": request.user.role in AUDIT_REVIEW_ROLES,
        },
    }
    if clinical_allowed:
        payload["clinical"] = _clinical_workspace(patient)
    if operations_allowed:
        payload["operations"] = _operations_workspace(request, patient)
    if request.user.role in AUDIT_REVIEW_ROLES:
        payload["safety"] = {
            "recentAuditEvents": [
                serialize_audit_event(event)
                for event in patient.audit_events.select_related("actor").all()[:12]
            ]
        }
    record_audit_event(
        actor=request.user,
        action="patient.workspace_viewed",
        obj=patient,
        patient=patient,
        request=request,
        metadata={"route": "api-v1-patient-workspace"},
    )
    return JsonResponse(payload)


@require_GET
@api_login_required
def patient_timeline(request, patient_id: str):
    patient, error = _clinical_patient_or_error(request, patient_id)
    if error:
        return error
    query = request.GET.get("q", "")[:160]
    record_audit_event(
        actor=request.user,
        action="timeline.searched",
        obj=patient,
        patient=patient,
        request=request,
        metadata={"has_query": bool(query)},
    )
    return JsonResponse({"query": query, "events": _timeline_events(patient, query)})


@require_POST
@api_login_required
def draft_create(request, patient_id: str):
    patient, error = _clinical_patient_or_error(request, patient_id)
    if error:
        return error
    payload, error = _payload_or_error(request)
    if error:
        return error
    kind = payload.get("kind", AIArtifact.Kind.PROGRESS)
    allowed_kinds = {
        AIArtifact.Kind.PROGRESS,
        AIArtifact.Kind.DISCHARGE,
        AIArtifact.Kind.HANDOFF,
        AIArtifact.Kind.PATIENT_SUMMARY,
    }
    if not isinstance(kind, str) or kind not in allowed_kinds:
        return api_error("Choose a supported draft type.", status=400)
    source = compose_draft(patient, kind)
    artifact = AIArtifact.objects.create(
        patient=patient,
        requested_by=request.user,
        kind=kind,
        source_note_ids=source["source_note_ids"],
        source_fingerprint=source["source_fingerprint"],
        draft_text=source["draft_text"],
    )
    record_audit_event(
        actor=request.user,
        action="ai_draft.created",
        obj=artifact,
        patient=patient,
        request=request,
        metadata={"kind": kind, "source_count": len(source["source_note_ids"])},
    )
    return JsonResponse(
        {"artifact": serialize_artifact(artifact, include_draft_text=True)}, status=201
    )


@require_POST
@api_login_required
def artifact_review(request, artifact_id: str):
    artifact, error = _artifact_or_error(request, artifact_id)
    if error:
        return error
    if not request.user.can_sign_notes:
        return api_error("Only an authorized therapist can approve clinical drafts.", status=403)
    payload, error = _payload_or_error(request)
    if error:
        return error
    action = payload.get("action")
    review_note, error = _optional_text(payload, "reviewNote", limit=1000)
    if error:
        return error

    note = None
    if action == "reject":
        artifact.status = AIArtifact.Status.REJECTED
    elif action == "approve":
        artifact.status = AIArtifact.Status.APPROVED
    elif action == "apply":
        if artifact.status != AIArtifact.Status.APPROVED:
            return api_error("Approve the draft before applying it to an editable note.", status=409)
        note_type = {
            AIArtifact.Kind.PROGRESS: ClinicalNote.Type.PROGRESS,
            AIArtifact.Kind.DISCHARGE: ClinicalNote.Type.DISCHARGE,
            AIArtifact.Kind.HANDOFF: ClinicalNote.Type.HANDOFF,
        }.get(artifact.kind)
        if not note_type:
            return api_error("This draft type cannot be applied to a clinical note.", status=409)
        note = ClinicalNote(
            patient=artifact.patient,
            therapist=request.user,
            note_type=note_type,
            diagnosis_snapshot=artifact.patient.diagnoses,
            precautions_snapshot=artifact.patient.precautions,
            assessment=artifact.draft_text,
            status=ClinicalNote.Status.DRAFT,
        )
        error_response = _save_or_error(note)
        if error_response:
            return error_response
        artifact.status = AIArtifact.Status.APPLIED
        artifact.applied_note = note
    else:
        return api_error("Choose approve, reject, or apply.", status=400)

    artifact.review_note = review_note
    artifact.reviewed_by = request.user
    artifact.reviewed_at = timezone.now()
    error_response = _save_or_error(artifact)
    if error_response:
        return error_response
    record_audit_event(
        actor=request.user,
        action=f"ai_draft.{action}",
        obj=artifact,
        patient=artifact.patient,
        request=request,
        metadata={"kind": artifact.kind},
    )
    response = {"artifact": serialize_artifact(artifact, include_draft_text=True)}
    if note:
        response["appliedNote"] = _note_payload(note)
    return JsonResponse(response)


@require_POST
@api_login_required
def goal_suggestions(request, patient_id: str):
    patient, error = _clinical_patient_or_error(request, patient_id)
    if error:
        return error
    payload, error = _payload_or_error(request)
    if error:
        return error
    limitation, error = _required_text(payload, "functionalLimitation", "Functional limitation", limit=2000)
    if error:
        return error
    measure = payload.get("measure", "")
    if measure and measure not in OutcomeScore.Measure.values:
        return api_error("Choose a supported outcome measure.", status=400)
    suggestions = build_goal_suggestions(limitation, patient.diagnoses, measure)
    record_audit_event(
        actor=request.user,
        action="goal.suggestions_requested",
        obj=patient,
        patient=patient,
        request=request,
        metadata={"measure": measure or "none"},
    )
    return JsonResponse({"suggestions": suggestions})


@require_POST
@api_login_required
def goal_create(request, patient_id: str):
    patient, error = _clinical_patient_or_error(request, patient_id)
    if error:
        return error
    payload, error = _payload_or_error(request)
    if error:
        return error
    required = {
        "functionalLimitation": "Functional limitation",
        "functionalTask": "Functional task",
        "unit": "Unit",
        "measurementMethod": "Measurement method",
        "targetDate": "Target date",
        "suggestedWording": "Suggested wording",
    }
    fields = {}
    for key, label in required.items():
        fields[key], error = _required_text(payload, key, label)
        if error:
            return error
    current_value = payload.get("currentValue")
    if current_value == "":
        current_value = None
    goal = FunctionalGoal(
        patient=patient,
        author=request.user,
        functional_limitation=fields["functionalLimitation"],
        functional_task=fields["functionalTask"],
        baseline_value=payload.get("baselineValue"),
        target_value=payload.get("targetValue"),
        current_value=current_value,
        unit=fields["unit"],
        measurement_method=fields["measurementMethod"],
        target_date=fields["targetDate"],
        suggested_wording=fields["suggestedWording"],
        status=FunctionalGoal.Status.DRAFT,
    )
    error_response = _save_or_error(goal)
    if error_response:
        return error_response
    record_audit_event(
        actor=request.user,
        action="goal.created_draft",
        obj=goal,
        patient=patient,
        request=request,
    )
    return JsonResponse(
        {"goal": serialize_goal(goal, include_clinical_details=True)}, status=201
    )


@require_POST
@api_login_required
def goal_approve(request, goal_id: str):
    goal, error = _goal_or_error(request, goal_id)
    if error:
        return error
    if not request.user.can_sign_notes:
        return api_error("Only an authorized therapist can approve a clinical goal.", status=403)
    goal.status = FunctionalGoal.Status.ACTIVE
    goal.approved_by = request.user
    goal.approved_at = timezone.now()
    error_response = _save_or_error(goal)
    if error_response:
        return error_response
    record_audit_event(
        actor=request.user,
        action="goal.approved",
        obj=goal,
        patient=goal.patient,
        request=request,
    )
    return JsonResponse({"goal": serialize_goal(goal, include_clinical_details=True)})


@require_POST
@api_login_required
def outcome_create(request, patient_id: str):
    patient, error = _clinical_patient_or_error(request, patient_id)
    if error:
        return error
    payload, error = _payload_or_error(request)
    if error:
        return error
    measure = payload.get("measure")
    if measure not in OutcomeScore.Measure.values:
        return api_error("Choose a supported outcome measure.", status=400)
    maximum_score = payload.get("maximumScore")
    if maximum_score in ("", None):
        maximum_score = outcome_measure_defaults(measure).get("maximum")
    outcome = OutcomeScore(
        patient=patient,
        recorded_by=request.user,
        measure=measure,
        measured_on=payload.get("measuredOn") or timezone.localdate(),
        score=payload.get("score"),
        maximum_score=maximum_score,
        notes=payload.get("notes", ""),
    )
    error_response = _save_or_error(outcome)
    if error_response:
        return error_response
    record_audit_event(
        actor=request.user,
        action="outcome.recorded",
        obj=outcome,
        patient=patient,
        request=request,
        metadata={"measure": measure},
    )
    trend = next(
        (item for item in outcome_trends(patient) if item["measure"] == measure), None
    )
    return JsonResponse(
        {
            "outcome": {
                "id": str(outcome.pk),
                "measure": outcome.measure,
                "measuredOn": outcome.measured_on.isoformat(),
                "score": float(outcome.score),
                "maximumScore": float(outcome.maximum_score)
                if outcome.maximum_score is not None
                else None,
            },
            "trend": serialize_outcome_trend(trend) if trend else None,
        },
        status=201,
    )


@require_POST
@api_login_required
def voice_capture_create(request, patient_id: str):
    patient, error = _clinical_patient_or_error(request, patient_id)
    if error:
        return error
    payload, error = _payload_or_error(request)
    if error:
        return error
    if payload.get("consentConfirmed") is not True:
        return api_error("Confirm applicable voice-documentation consent before saving a transcript.", status=400)
    if not patient.consents.filter(
        kind=Consent.Kind.VOICE, status=Consent.Status.SIGNED
    ).exists():
        return api_error(
            "Record a signed voice-documentation consent before saving a transcript.",
            status=409,
        )
    transcript, error = _required_text(payload, "transcript", "Reviewed transcript", limit=50000)
    if error:
        return error
    try:
        duration_seconds = int(payload.get("durationSeconds", 0))
    except (TypeError, ValueError):
        return api_error("Duration must be a whole number of seconds.", status=400)
    if duration_seconds < 0 or duration_seconds > 14_400:
        return api_error("Duration must be between 0 and 14,400 seconds.", status=400)
    capture = VoiceCapture(
        patient=patient,
        therapist=request.user,
        consent_confirmed=True,
        duration_seconds=duration_seconds,
        transcript=transcript,
        status=VoiceCapture.Status.TRANSCRIBED,
    )
    error_response = _save_or_error(capture)
    if error_response:
        return error_response
    record_audit_event(
        actor=request.user,
        action="voice_transcript.saved",
        obj=capture,
        patient=patient,
        request=request,
        metadata={"duration_seconds": duration_seconds},
    )
    return JsonResponse(
        {"voiceCapture": serialize_voice_capture(capture, include_transcript=True)}, status=201
    )


@require_POST
@api_login_required
def voice_capture_create_note(request, capture_id: str):
    capture = (
        VoiceCapture.objects.select_related("patient", "therapist")
        .filter(pk=capture_id)
        .first()
    )
    if capture is None:
        return api_error("Voice transcript was not found.", status=404)
    _, error = _clinical_patient_or_error(request, str(capture.patient_id))
    if error:
        return error
    can_apply = capture.therapist_id == request.user.pk or request.user.role in {
        User.Role.ADMIN,
        User.Role.DIRECTOR,
    }
    if not can_apply:
        return api_error("Only the recording clinician or an authorized director can create this note.", status=403)
    if capture.linked_note_id:
        return api_error("This transcript is already linked to a note.", status=409)
    note = ClinicalNote(
        patient=capture.patient,
        therapist=request.user,
        note_type=ClinicalNote.Type.DAILY,
        diagnosis_snapshot=capture.patient.diagnoses,
        precautions_snapshot=capture.patient.precautions,
        subjective=capture.transcript,
        status=ClinicalNote.Status.DRAFT,
    )
    error_response = _save_or_error(note)
    if error_response:
        return error_response
    capture.linked_note = note
    capture.status = VoiceCapture.Status.REVIEWED
    capture.save(update_fields=["linked_note", "status", "updated_at"])
    record_audit_event(
        actor=request.user,
        action="voice_transcript.applied_to_note",
        obj=capture,
        patient=capture.patient,
        request=request,
        metadata={"note_id": str(note.pk)},
    )
    return JsonResponse({"note": _note_payload(note)})


@require_GET
@api_login_required
def home_program_suggestion_list(request, patient_id: str):
    patient, error = _clinical_patient_or_error(request, patient_id)
    if error:
        return error
    return JsonResponse({"suggestions": home_program_suggestions(patient)})


@require_POST
@api_login_required
def home_program_create(request, patient_id: str):
    patient, error = _clinical_patient_or_error(request, patient_id)
    if error:
        return error
    payload, error = _payload_or_error(request)
    if error:
        return error
    title, error = _required_text(payload, "title", "Home-program title", limit=160)
    if error:
        return error
    instructions, error = _required_text(
        payload, "patientInstructions", "Patient instructions", limit=50000
    )
    if error:
        return error
    diagnosis_context, error = _optional_text(
        payload, "diagnosisContext", patient.diagnoses, limit=50000
    )
    if error:
        return error
    precautions, error = _optional_text(payload, "precautions", patient.precautions, limit=50000)
    if error:
        return error
    program = HomeProgram(
        patient=patient,
        prescribed_by=request.user,
        title=title,
        diagnosis_context=diagnosis_context,
        precautions=precautions,
        patient_instructions=instructions,
        status=HomeProgram.Status.DRAFT,
    )
    error_response = _save_or_error(program)
    if error_response:
        return error_response
    record_audit_event(
        actor=request.user,
        action="home_program.created_draft",
        obj=program,
        patient=patient,
        request=request,
    )
    return JsonResponse({"homeProgram": serialize_home_program(program)}, status=201)


@require_POST
@api_login_required
def home_program_approve(request, program_id: str):
    program, error = _program_or_error(request, program_id)
    if error:
        return error
    if not request.user.can_sign_notes:
        return api_error("Only an authorized therapist can activate a home program.", status=403)
    program.status = HomeProgram.Status.ACTIVE
    program.approved_at = timezone.now()
    error_response = _save_or_error(program)
    if error_response:
        return error_response
    record_audit_event(
        actor=request.user,
        action="home_program.approved",
        obj=program,
        patient=program.patient,
        request=request,
    )
    return JsonResponse({"homeProgram": serialize_home_program(program)})


@require_POST
@api_login_required
def intake_create(request, patient_id: str):
    patient, error = _operations_patient_or_error(request, patient_id)
    if error:
        return error
    try:
        require_role(request.user, SCHEDULING_ROLES)
    except PermissionDenied as error:
        return api_error(str(error), status=403)
    payload, error = _payload_or_error(request)
    if error:
        return error
    chief_complaint, error = _required_text(payload, "chiefComplaint", "Chief complaint", limit=50000)
    if error:
        return error
    functional_goals, error = _required_text(payload, "functionalGoals", "Functional goals", limit=50000)
    if error:
        return error
    relevant_history, error = _optional_text(payload, "relevantHistory", limit=50000)
    if error:
        return error
    form_version, error = _optional_text(payload, "formVersion", "v1", limit=40)
    if error:
        return error
    intake = IntakeSubmission(
        patient=patient,
        form_version=form_version or "v1",
        answers={
            "chief_complaint": chief_complaint,
            "functional_goals": functional_goals,
            "relevant_history": relevant_history,
        },
        status=IntakeSubmission.Status.SUBMITTED,
        submitted_at=timezone.now(),
    )
    error_response = _save_or_error(intake)
    if error_response:
        return error_response
    record_audit_event(
        actor=request.user,
        action="intake.submitted",
        obj=intake,
        patient=patient,
        request=request,
        metadata={"form_version": intake.form_version},
    )
    return JsonResponse({"intake": serialize_intake(intake)}, status=201)


@require_POST
@api_login_required
def consent_create(request, patient_id: str):
    patient, error = _operations_patient_or_error(request, patient_id)
    if error:
        return error
    try:
        require_role(request.user, SCHEDULING_ROLES)
    except PermissionDenied as error:
        return api_error(str(error), status=403)
    payload, error = _payload_or_error(request)
    if error:
        return error
    kind = payload.get("kind")
    if kind not in Consent.Kind.values:
        return api_error("Choose a supported consent type.", status=400)
    document_version, error = _required_text(payload, "documentVersion", "Document version", limit=40)
    if error:
        return error
    signature_name, error = _optional_text(payload, "signatureName", limit=160)
    if error:
        return error
    consent = Consent(
        patient=patient,
        kind=kind,
        document_version=document_version,
        status=Consent.Status.SIGNED,
        signature_name=signature_name,
        signed_at=timezone.now(),
        recorded_by=request.user,
    )
    error_response = _save_or_error(consent)
    if error_response:
        return error_response
    record_audit_event(
        actor=request.user,
        action="consent.recorded",
        obj=consent,
        patient=patient,
        request=request,
        metadata={"kind": kind, "version": document_version},
    )
    return JsonResponse({"consent": serialize_consent(consent)}, status=201)


@require_POST
@api_login_required
def referral_create(request, patient_id: str):
    patient, error = _operations_patient_or_error(request, patient_id)
    if error:
        return error
    try:
        require_role(request.user, SCHEDULING_ROLES)
    except PermissionDenied as error:
        return api_error(str(error), status=403)
    payload, error = _payload_or_error(request)
    if error:
        return error
    direction = payload.get("direction", Referral.Direction.INCOMING)
    if direction not in Referral.Direction.values:
        return api_error("Choose a supported referral direction.", status=400)
    provider_name, error = _required_text(payload, "providerName", "Provider name", limit=200)
    if error:
        return error
    provider_contact, error = _optional_text(payload, "providerContact", limit=200)
    if error:
        return error
    reason, error = _optional_text(payload, "reason", limit=2000)
    if error:
        return error
    referral = Referral(
        patient=patient,
        direction=direction,
        provider_name=provider_name,
        provider_contact=provider_contact,
        reason=reason,
        created_by=request.user,
    )
    error_response = _save_or_error(referral)
    if error_response:
        return error_response
    record_audit_event(
        actor=request.user,
        action="referral.created",
        obj=referral,
        patient=patient,
        request=request,
        metadata={"direction": direction},
    )
    return JsonResponse({"referral": serialize_referral(referral)}, status=201)


@require_POST
@api_login_required
def referral_status_update(request, referral_id: str):
    referral = get_object_or_404(Referral.objects.select_related("patient"), pk=referral_id)
    _, error = _operations_patient_or_error(request, str(referral.patient_id))
    if error:
        return error
    try:
        require_role(request.user, SCHEDULING_ROLES)
    except PermissionDenied as error:
        return api_error(str(error), status=403)
    payload, error = _payload_or_error(request)
    if error:
        return error
    status = payload.get("status")
    if status not in Referral.Status.values:
        return api_error("Choose a supported referral status.", status=400)
    referral.status = status
    error_response = _save_or_error(referral)
    if error_response:
        return error_response
    record_audit_event(
        actor=request.user,
        action="referral.status_changed",
        obj=referral,
        patient=referral.patient,
        request=request,
        metadata={"status": status},
    )
    return JsonResponse({"referral": serialize_referral(referral)})


@require_POST
@api_login_required
def secure_message_create(request, patient_id: str):
    patient, error = _operations_patient_or_error(request, patient_id)
    if error:
        return error
    try:
        require_role(request.user, SCHEDULING_ROLES | BILLING_ROLES)
    except PermissionDenied as error:
        return api_error(str(error), status=403)
    payload, error = _payload_or_error(request)
    if error:
        return error
    recipient_id = payload.get("recipientId")
    recipient = User.objects.filter(
        pk=recipient_id,
        organization=organization_required(request.user),
        is_active=True,
    ).first()
    if recipient is None:
        return api_error("Choose an active recipient in your organization.", status=400)
    subject, error = _required_text(payload, "subject", "Subject", limit=180)
    if error:
        return error
    body, error = _required_text(payload, "body", "Message", limit=50000)
    if error:
        return error
    message = SecureMessage(
        patient=patient,
        sender=request.user,
        recipient=recipient,
        subject=subject,
        body=body,
    )
    error_response = _save_or_error(message)
    if error_response:
        return error_response
    record_audit_event(
        actor=request.user,
        action="secure_message.sent",
        obj=message,
        patient=patient,
        request=request,
        metadata={"recipient_id": str(recipient.pk)},
    )
    return JsonResponse({"message": serialize_message(message, viewer=request.user)}, status=201)


@require_POST
@api_login_required
def superbill_create(request, patient_id: str):
    patient, error = _operations_patient_or_error(request, patient_id)
    if error:
        return error
    try:
        require_role(request.user, BILLING_ROLES)
    except PermissionDenied as error:
        return api_error(str(error), status=403)
    payload, error = _payload_or_error(request)
    if error:
        return error
    raw_codes = payload.get("codes", [])
    if isinstance(raw_codes, str):
        codes = [code.strip().upper() for code in raw_codes.split(",") if code.strip()]
    elif isinstance(raw_codes, list) and all(isinstance(code, str) for code in raw_codes):
        codes = [code.strip().upper() for code in raw_codes if code.strip()]
    else:
        return api_error("Codes must be a list of service codes.", status=400)
    if not codes:
        return api_error("Enter at least one service code.", status=400)
    status = payload.get("status", Superbill.Status.DRAFT)
    if status not in Superbill.Status.values:
        return api_error("Choose a supported superbill status.", status=400)
    reference, error = _optional_text(payload, "paymentProcessorReference", limit=160)
    if error:
        return error
    superbill = Superbill(
        patient=patient,
        clinician=request.user,
        service_date=payload.get("serviceDate"),
        codes=codes,
        amount=payload.get("amount"),
        status=status,
        payment_processor_reference=reference,
    )
    error_response = _save_or_error(superbill)
    if error_response:
        return error_response
    record_audit_event(
        actor=request.user,
        action="superbill.created",
        obj=superbill,
        patient=patient,
        request=request,
        metadata={"status": status, "code_count": len(codes)},
    )
    return JsonResponse({"superbill": serialize_superbill(superbill)}, status=201)


@require_POST
@api_login_required
def payment_create(request, patient_id: str):
    patient, error = _operations_patient_or_error(request, patient_id)
    if error:
        return error
    try:
        require_role(request.user, PAYMENT_COLLECTION_ROLES)
    except PermissionDenied as error:
        return api_error(str(error), status=403)
    payload, error = _payload_or_error(request)
    if error:
        return error
    status = payload.get("status", PaymentRecord.Status.PENDING)
    if status not in PaymentRecord.Status.values:
        return api_error("Choose a supported payment status.", status=400)
    reference, error = _required_text(
        payload, "paymentProcessorReference", "Approved payment-processor reference", limit=160
    )
    if error:
        return error
    superbill_id = payload.get("superbillId")
    superbill = None
    if superbill_id:
        superbill = Superbill.objects.filter(pk=superbill_id, patient=patient).first()
        if superbill is None:
            return api_error("Choose a superbill belonging to this patient.", status=400)
    payment = PaymentRecord(
        patient=patient,
        superbill=superbill,
        recorded_by=request.user,
        amount=payload.get("amount"),
        received_on=payload.get("receivedOn") or timezone.localdate(),
        status=status,
        payment_processor_reference=reference,
    )
    error_response = _save_or_error(payment)
    if error_response:
        return error_response
    record_audit_event(
        actor=request.user,
        action="payment.recorded",
        obj=payment,
        patient=patient,
        request=request,
        metadata={"status": status, "superbill_id": str(superbill_id or "")},
    )
    return JsonResponse({"payment": serialize_payment(payment)}, status=201)


@require_POST
@api_login_required
def appointment_create(request, patient_id: str):
    """Create a schedule item with a server-side clinician-overlap check."""
    patient, error = _operations_patient_or_error(request, patient_id)
    if error:
        return error
    try:
        require_role(request.user, SCHEDULING_ROLES)
    except PermissionDenied as error:
        return api_error(str(error), status=403)
    payload, error = _payload_or_error(request)
    if error:
        return error
    organization = organization_required(request.user)
    therapist = User.objects.filter(
        pk=payload.get("therapistId"),
        organization=organization,
        is_active=True,
        role__in=[
            User.Role.ADMIN,
            User.Role.DIRECTOR,
            User.Role.THERAPIST,
            User.Role.ASSISTANT,
        ],
    ).first()
    if therapist is None:
        return api_error("Choose an active clinician in your organization.", status=400)
    if request.user.role in CLINICIAN_SCHEDULE_ROLES and therapist.pk != request.user.pk:
        return api_error("Clinicians may schedule only their own visits.", status=403)
    starts_at = parse_datetime(str(payload.get("startsAt", "")))
    ends_at = parse_datetime(str(payload.get("endsAt", "")))
    if not starts_at or not ends_at:
        return api_error("Start and end must use an ISO date/time.", status=400)
    if timezone.is_naive(starts_at):
        starts_at = timezone.make_aware(starts_at, timezone.get_current_timezone())
    if timezone.is_naive(ends_at):
        ends_at = timezone.make_aware(ends_at, timezone.get_current_timezone())
    if ends_at <= starts_at:
        return api_error("End time must be after start time.", status=400)
    kind = payload.get("kind", Appointment.Kind.FOLLOW_UP)
    if kind not in Appointment.Kind.values:
        return api_error("Choose a supported appointment type.", status=400)
    location, error = _optional_text(payload, "location", limit=180)
    if error:
        return error
    is_home_visit = payload.get("isHomeVisit", False)
    if not isinstance(is_home_visit, bool):
        return api_error("isHomeVisit must be true or false.", status=400)
    with transaction.atomic():
        has_conflict = (
            Appointment.objects.select_for_update()
            .filter(therapist=therapist, starts_at__lt=ends_at, ends_at__gt=starts_at)
            .exclude(status__in=[Appointment.Status.CANCELLED, Appointment.Status.NO_SHOW])
            .exists()
        )
        if has_conflict:
            return api_error(
                "The assigned clinician already has an appointment at that time.", status=409
            )
        appointment = Appointment(
            patient=patient,
            therapist=therapist,
            kind=kind,
            starts_at=starts_at,
            ends_at=ends_at,
            location=location,
            is_home_visit=is_home_visit,
            created_by=request.user,
        )
        error_response = _save_or_error(appointment)
        if error_response:
            return error_response
    record_audit_event(
        actor=request.user,
        action="appointment.created",
        obj=appointment,
        patient=patient,
        request=request,
    )
    return JsonResponse({"appointment": serialize_appointment(appointment)}, status=201)


@require_GET
@api_login_required
def audit_events(request):
    organization, error = organization_or_error(request, roles=AUDIT_REVIEW_ROLES)
    if error:
        return error
    try:
        limit = min(max(int(request.GET.get("limit", "60")), 1), 100)
    except ValueError:
        return api_error("limit must be a whole number.", status=400)
    action = request.GET.get("action", "").strip()[:80]
    events = AuditEvent.objects.filter(organization=organization).select_related("actor", "patient")
    if action:
        events = events.filter(action__icontains=action)
    payload = [serialize_audit_event(event) for event in events[:limit]]
    record_audit_event(
        actor=request.user,
        action="audit.viewed",
        obj=organization,
        request=request,
        metadata={"has_action_filter": bool(action)},
    )
    return JsonResponse({"events": payload, "limit": limit})
