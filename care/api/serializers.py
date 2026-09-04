"""Explicit allow-list serializers for the React workspace API."""
from __future__ import annotations

from django.utils import timezone


def _display_name(user) -> str:
    return user.get_full_name() or user.username


def serialize_user(user) -> dict:
    organization = user.organization
    return {
        "id": str(user.pk),
        "username": user.username,
        "displayName": _display_name(user),
        "role": user.role,
        "roleLabel": user.get_role_display(),
        "organization": (
            {
                "id": str(organization.pk),
                "name": organization.name,
                "logoUrl": organization.logo.url if organization.logo else None,
            }
            if organization
            else None
        ),
        "capabilities": {
            "isSuperAdmin": user.is_platform_super_admin,
            "canAccessClinical": user.can_access_clinical,
            "canManageSchedule": user.can_manage_schedule,
            "canSignNotes": user.can_sign_notes,
            "canManageAccess": user.is_platform_super_admin or user.role == user.Role.ADMIN,
            "canManageOperations": user.role
            in {
                user.Role.ADMIN,
                user.Role.DIRECTOR,
                user.Role.THERAPIST,
                user.Role.ASSISTANT,
                user.Role.SCHEDULER,
                user.Role.BILLER,
            },
            "canManageBilling": user.role in {
                user.Role.ADMIN,
                user.Role.DIRECTOR,
                user.Role.BILLER,
            },
            "canReviewAudit": user.role
            in {user.Role.ADMIN, user.Role.DIRECTOR, user.Role.COMPLIANCE},
        },
    }


def serialize_patient(patient, *, include_clinical: bool = False, include_contact: bool = False) -> dict:
    """`include_contact` is opt-in and deliberately narrow: the day-to-day clinical
    workspace and patient list must NOT surface phone/email/address by default
    (minimum-necessary). Only the create/update/edit-form endpoints, which exist
    specifically to manage that contact information, pass include_contact=True.
    """
    assigned_therapist = patient.assigned_therapist
    payload = {
        "id": str(patient.pk),
        "fullName": patient.full_name,
        "firstName": patient.first_name,
        "lastName": patient.last_name,
        "medicalRecordNumber": patient.medical_record_number,
        "dateOfBirth": patient.date_of_birth.isoformat(),
        "status": patient.status,
        "statusLabel": patient.get_status_display(),
        "assignedTherapist": (
            {"id": str(assigned_therapist.pk), "displayName": _display_name(assigned_therapist)}
            if assigned_therapist
            else None
        ),
    }
    if include_contact:
        payload.update(
            {
                "phone": patient.phone,
                "email": patient.email,
                "address": patient.address,
                "emergencyContact": patient.emergency_contact,
            }
        )
    if include_clinical:
        payload.update(
            {
                "diagnoses": patient.diagnoses,
                "precautions": patient.precautions,
            }
        )
    return payload


def serialize_appointment(appointment) -> dict:
    local_start = timezone.localtime(appointment.starts_at)
    local_end = timezone.localtime(appointment.ends_at)
    return {
        "id": str(appointment.pk),
        "date": local_start.date().isoformat(),
        "startsAt": local_start.isoformat(),
        "endsAt": local_end.isoformat(),
        "status": appointment.status,
        "statusLabel": appointment.get_status_display(),
        "kind": appointment.kind,
        "kindLabel": appointment.get_kind_display(),
        "location": appointment.location,
        "isHomeVisit": appointment.is_home_visit,
        "patient": {
            "id": str(appointment.patient_id),
            "fullName": appointment.patient.full_name,
        },
        "therapist": {
            "id": str(appointment.therapist_id),
            "displayName": _display_name(appointment.therapist),
        },
    }


def serialize_note_summary(note) -> dict:
    return {
        "id": str(note.pk),
        "patientId": str(note.patient_id),
        "patientName": note.patient.full_name,
        "noteType": note.note_type,
        "noteTypeLabel": note.get_note_type_display(),
        "status": note.status,
        "statusLabel": note.get_status_display(),
        "serviceDate": note.service_date.isoformat(),
        "reassessmentDue": note.reassessment_due.isoformat() if note.reassessment_due else None,
    }


def serialize_goal(goal, *, include_clinical_details: bool = False) -> dict:
    payload = {
        "id": str(goal.pk),
        "functionalTask": goal.functional_task,
        "baselineValue": float(goal.baseline_value),
        "targetValue": float(goal.target_value),
        "currentValue": float(goal.current_value) if goal.current_value is not None else None,
        "unit": goal.unit,
        "targetDate": goal.target_date.isoformat(),
        "status": goal.status,
        "statusLabel": goal.get_status_display(),
        "progressPercent": goal.progress_percent,
    }
    if include_clinical_details:
        payload.update(
            {
                "functionalLimitation": goal.functional_limitation,
                "measurementMethod": goal.measurement_method,
                "suggestedWording": goal.suggested_wording,
                "approvedBy": _display_name(goal.approved_by)
                if goal.approved_by
                else None,
                "approvedAt": timezone.localtime(goal.approved_at).isoformat()
                if goal.approved_at
                else None,
            }
        )
    return payload


def serialize_outcome_trend(trend: dict) -> dict:
    return {
        "measure": trend["measure"],
        "label": trend["label"],
        "latest": float(trend["latest"]),
        "maximum": float(trend["maximum"]) if trend["maximum"] is not None else None,
        "unit": trend["unit"],
        "trend": trend["trend"],
        "delta": float(trend["delta"]),
        "points": [
            {
                "measuredOn": point["measured_on"].isoformat(),
                "score": float(point["score"]),
                "maximumScore": float(point["maximum_score"])
                if point["maximum_score"] is not None
                else None,
            }
            for point in trend["points"]
        ],
    }


def serialize_artifact(artifact, *, include_draft_text: bool = False) -> dict:
    """Serialize an auditable clinical draft only for chart-authorized callers."""
    payload = {
        "id": str(artifact.pk),
        "kind": artifact.kind,
        "kindLabel": artifact.get_kind_display(),
        "status": artifact.status,
        "statusLabel": artifact.get_status_display(),
        "sourceNoteCount": len(artifact.source_note_ids),
        "provider": artifact.provider,
        "modelVersion": artifact.model_version,
        "safetyNotice": artifact.safety_notice,
        "requestedBy": _display_name(artifact.requested_by),
        "createdAt": timezone.localtime(artifact.created_at).isoformat(),
        "reviewedBy": _display_name(artifact.reviewed_by)
        if artifact.reviewed_by
        else None,
        "reviewedAt": timezone.localtime(artifact.reviewed_at).isoformat()
        if artifact.reviewed_at
        else None,
        "reviewNote": artifact.review_note,
        "appliedNoteId": str(artifact.applied_note_id) if artifact.applied_note_id else None,
    }
    if include_draft_text:
        payload["draftText"] = artifact.draft_text
    return payload


def serialize_home_program(program) -> dict:
    return {
        "id": str(program.pk),
        "title": program.title,
        "diagnosisContext": program.diagnosis_context,
        "precautions": program.precautions,
        "patientInstructions": program.patient_instructions,
        "status": program.status,
        "statusLabel": program.get_status_display(),
        "prescribedBy": _display_name(program.prescribed_by),
        "approvedAt": timezone.localtime(program.approved_at).isoformat()
        if program.approved_at
        else None,
        "createdAt": timezone.localtime(program.created_at).isoformat(),
        "exercises": [
            {
                "id": str(exercise.pk),
                "name": exercise.name,
                "instructions": exercise.instructions,
                "dosage": exercise.dosage,
                "precautionNote": exercise.precaution_note,
            }
            for exercise in program.exercises.all()
        ],
    }


def serialize_voice_capture(capture, *, include_transcript: bool = False) -> dict:
    payload = {
        "id": str(capture.pk),
        "status": capture.status,
        "statusLabel": capture.get_status_display(),
        "consentConfirmed": capture.consent_confirmed,
        "durationSeconds": capture.duration_seconds,
        "therapist": _display_name(capture.therapist),
        "createdAt": timezone.localtime(capture.created_at).isoformat(),
        "linkedNoteId": str(capture.linked_note_id) if capture.linked_note_id else None,
    }
    if include_transcript:
        payload["transcript"] = capture.transcript
    return payload


def serialize_referral(referral) -> dict:
    return {
        "id": str(referral.pk),
        "direction": referral.direction,
        "directionLabel": referral.get_direction_display(),
        "providerName": referral.provider_name,
        "providerContact": referral.provider_contact,
        "reason": referral.reason,
        "status": referral.status,
        "statusLabel": referral.get_status_display(),
        "createdBy": _display_name(referral.created_by),
        "createdAt": timezone.localtime(referral.created_at).isoformat(),
    }


def serialize_consent(consent) -> dict:
    return {
        "id": str(consent.pk),
        "kind": consent.kind,
        "kindLabel": consent.get_kind_display(),
        "documentVersion": consent.document_version,
        "status": consent.status,
        "statusLabel": consent.get_status_display(),
        "signedAt": timezone.localtime(consent.signed_at).isoformat()
        if consent.signed_at
        else None,
        "recordedBy": _display_name(consent.recorded_by),
    }


def serialize_intake(intake) -> dict:
    """Return intake status only; answers are not needed for operations lists."""
    return {
        "id": str(intake.pk),
        "formVersion": intake.form_version,
        "status": intake.status,
        "statusLabel": intake.get_status_display(),
        "submittedAt": timezone.localtime(intake.submitted_at).isoformat()
        if intake.submitted_at
        else None,
        "createdAt": timezone.localtime(intake.created_at).isoformat(),
    }


def serialize_message(message, *, viewer) -> dict:
    """Message bodies are returned only for a thread participant."""
    return {
        "id": str(message.pk),
        "direction": "outbound" if message.sender_id == viewer.pk else "inbound",
        "sender": _display_name(message.sender),
        "recipient": _display_name(message.recipient),
        "subject": message.subject,
        "body": message.body,
        "createdAt": timezone.localtime(message.created_at).isoformat(),
        "readAt": timezone.localtime(message.read_at).isoformat()
        if message.read_at
        else None,
    }


def serialize_superbill(superbill) -> dict:
    return {
        "id": str(superbill.pk),
        "serviceDate": superbill.service_date.isoformat(),
        "codes": superbill.codes,
        "amount": float(superbill.amount),
        "status": superbill.status,
        "statusLabel": superbill.get_status_display(),
        "clinician": _display_name(superbill.clinician),
        "createdAt": timezone.localtime(superbill.created_at).isoformat(),
    }


def serialize_payment(payment) -> dict:
    """Never expose payment-processor references through the workspace API."""
    return {
        "id": str(payment.pk),
        "superbillId": str(payment.superbill_id) if payment.superbill_id else None,
        "amount": float(payment.amount),
        "receivedOn": payment.received_on.isoformat(),
        "status": payment.status,
        "statusLabel": payment.get_status_display(),
        "recordedBy": _display_name(payment.recorded_by),
    }


def serialize_audit_event(event) -> dict:
    """Audit metadata is intentionally narrative-free at write time."""
    return {
        "id": str(event.pk),
        "action": event.action,
        "objectType": event.object_type,
        "objectId": str(event.object_id) if event.object_id else None,
        "patientId": str(event.patient_id) if event.patient_id else None,
        "actor": _display_name(event.actor) if event.actor else "System",
        "createdAt": timezone.localtime(event.created_at).isoformat(),
        "metadata": event.metadata,
    }
