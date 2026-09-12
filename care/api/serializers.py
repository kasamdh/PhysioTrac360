"""Explicit allow-list serializers for the React workspace API."""
from __future__ import annotations

from django.utils import timezone

from ..services import note_compliance_findings


def _display_name(user) -> str:
    return user.get_full_name() or user.username


def serialize_user_license(license) -> dict:
    return {
        "id": str(license.pk),
        "licenseNumber": license.license_number,
        "issuingState": license.issuing_state,
        "licenseType": license.license_type,
        "issueDate": license.issue_date.isoformat() if license.issue_date else None,
        "expiresAt": license.expires_at.isoformat(),
        "verificationStatus": license.verification_status,
        "verifiedAt": license.verified_at.isoformat() if license.verified_at else None,
        "verifiedByName": _display_name(license.verified_by) if license.verified_by else None,
        "verificationNotes": license.verification_notes,
        "hasDocument": bool(license.document),
        "documentFilename": license.document_original_filename,
        "alertTier": license.alert_tier,
        "colorBucket": license.color_bucket,
        "daysRemaining": license.days_remaining,
    }


def serialize_feature(feature) -> dict:
    return {"code": feature.code, "name": feature.name, "description": feature.description}


def serialize_plan(plan) -> dict:
    return {
        "code": plan.code,
        "name": plan.name,
        "description": plan.description,
        "monthlyPrice": str(plan.monthly_price),
        "annualPrice": str(plan.annual_price),
        "providerSeatLimit": plan.provider_seat_limit,
        "featureCodes": list(plan.features.values_list("code", flat=True)),
    }


def serialize_org_subscription(subscription) -> dict | None:
    if subscription is None:
        return None
    return {
        "id": str(subscription.pk),
        "planCode": subscription.plan.code,
        "planName": subscription.plan.name,
        "status": subscription.status,
        "statusLabel": subscription.get_status_display(),
        "billingCycle": subscription.billing_cycle,
        "billingCycleLabel": subscription.get_billing_cycle_display(),
        "startsAt": subscription.starts_at.isoformat(),
        "endsAt": subscription.ends_at.isoformat() if subscription.ends_at else None,
        "providerSeatCount": subscription.provider_seat_count,
        "featureCodes": list(subscription.features.values_list("code", flat=True)),
        "isActive": subscription.is_active,
    }


def serialize_user(user) -> dict:
    organization = user.organization
    return {
        "id": str(user.pk),
        "username": user.username,
        "displayName": _display_name(user),
        "role": user.role,
        "roleLabel": user.get_role_display(),
        "lastLogin": user.last_login.isoformat() if user.last_login else None,
        "mustChangePassword": user.must_change_password,
        "organization": (
            {
                "id": str(organization.pk),
                "name": organization.name,
                "logoUrl": organization.logo.url if organization.logo else None,
                "timezone": organization.timezone,
            }
            if organization
            else None
        ),
        "capabilities": {
            "isSuperAdmin": user.is_platform_super_admin,
            "isPatient": user.role == user.Role.PATIENT,
            "canAccessClinical": user.can_access_clinical,
            "canManageSchedule": user.can_manage_schedule,
            "canSignNotes": user.can_sign_notes,
            "canCosignNotes": user.role in {user.Role.ADMIN, user.Role.DIRECTOR}
            or (user.role == user.Role.THERAPIST and user.can_sign_notes),
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


def serialize_patient(
    patient, *, include_clinical: bool = False, include_contact: bool = False, include_portal_status: bool = False
) -> dict:
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
    if include_portal_status:
        if patient.portal_user_id is None:
            portal_status = "none"
        elif patient.portal_user.has_usable_password():
            portal_status = "active"
        else:
            portal_status = "invited"
        payload["portalStatus"] = portal_status
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
        "confirmedAt": appointment.confirmed_at.isoformat() if appointment.confirmed_at else None,
        "episodeOfCareId": str(appointment.episode_of_care_id) if appointment.episode_of_care_id else None,
        "authorizationId": str(appointment.authorization_id) if appointment.authorization_id else None,
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
        "updatedAt": note.updated_at.isoformat(),
        "therapistId": str(note.therapist_id),
        "therapistName": _display_name(note.therapist),
        "appointmentId": str(note.appointment_id) if note.appointment_id else None,
        "episodeOfCareId": str(note.episode_of_care_id) if note.episode_of_care_id else None,
        "cosignRequired": note.cosign_required,
    }


def serialize_compliance_finding(finding) -> dict:
    return {
        "code": finding.code,
        "severity": finding.severity,
        "title": finding.title,
        "detail": finding.detail,
        "finalizationBlocker": finding.finalization_blocker,
    }


def serialize_intervention(item) -> dict:
    return {
        "id": str(item.pk),
        "description": item.description,
        "bodyRegion": item.body_region,
        "minutes": item.minutes,
        "units": item.units,
        "isTimed": item.is_timed,
        "patientResponse": item.patient_response,
        "order": item.order,
        "category": item.category,
        "categoryLabel": item.get_category_display(),
    }


def serialize_addendum(addendum) -> dict:
    return {
        "id": str(addendum.pk),
        "author": _display_name(addendum.author),
        "reason": addendum.reason,
        "body": addendum.body,
        "createdAt": addendum.created_at.isoformat(),
    }


def serialize_note_detail(note) -> dict:
    payload = serialize_note_summary(note)
    payload.update({
        "diagnosisSnapshot": note.diagnosis_snapshot,
        "precautionsSnapshot": note.precautions_snapshot,
        "subjective": note.subjective,
        "objective": note.objective,
        "interventions": note.interventions,
        "assessment": note.assessment,
        "plan": note.plan,
        "subjectiveDetails": note.subjective_details,
        "objectiveMeasurements": note.objective_measurements,
        "dischargeDetails": note.discharge_details,
        "homeVisitDetails": note.home_visit_details,
        "planOfCareStart": note.plan_of_care_start.isoformat() if note.plan_of_care_start else None,
        "planOfCareEnd": note.plan_of_care_end.isoformat() if note.plan_of_care_end else None,
        "frequencyPerWeek": note.frequency_per_week,
        "durationWeeks": note.duration_weeks,
        "signatureName": note.signature_name,
        "signedAt": note.signed_at.isoformat() if note.signed_at else None,
        "finalizationAttestation": note.finalization_attestation,
        "cosignedBy": _display_name(note.cosigned_by) if note.cosigned_by_id else None,
        "cosignedAt": note.cosigned_at.isoformat() if note.cosigned_at else None,
        "interventionItems": [serialize_intervention(item) for item in note.intervention_items.all()],
        "addenda": [serialize_addendum(addendum) for addendum in note.addenda.all()],
        "complianceFindings": [serialize_compliance_finding(f) for f in note_compliance_findings(note)],
    })
    return payload


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


def serialize_outcome_assignment(assignment) -> dict:
    return {
        "id": str(assignment.pk),
        "measure": assignment.measure,
        "measureLabel": assignment.get_measure_display(),
        "status": assignment.status,
        "statusLabel": assignment.get_status_display(),
        "assignedBy": _display_name(assignment.assigned_by),
        "assignedAt": assignment.assigned_at.isoformat(),
        "completedScoreId": str(assignment.completed_score_id) if assignment.completed_score_id else None,
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
        "sections": [
            {
                "key": section["key"],
                "label": section["label"],
                "draftText": section["draftText"],
                "status": section["status"],
                "reviewedText": section["reviewedText"],
            }
            for section in artifact.sections
        ],
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
        "exercises": [serialize_home_exercise(exercise) for exercise in program.exercises.all()],
    }


def serialize_home_exercise(exercise) -> dict:
    return {
        "id": str(exercise.pk),
        "name": exercise.name,
        "instructions": exercise.instructions,
        "dosage": exercise.dosage,
        "precautionNote": exercise.precaution_note,
        "videoUrl": exercise.video_url,
        "sortOrder": exercise.sort_order,
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


def serialize_episode_of_care(episode) -> dict:
    next_visit = episode.next_visit
    return {
        "id": str(episode.pk),
        "diagnosis": episode.diagnosis,
        "condition": episode.condition,
        "status": episode.status,
        "statusLabel": episode.get_status_display(),
        "startDate": episode.start_date.isoformat(),
        "endDate": episode.end_date.isoformat() if episode.end_date else None,
        "expectedEndDate": episode.expected_end_date.isoformat() if episode.expected_end_date else None,
        "visitFrequency": episode.visit_frequency,
        "expectedVisitCount": episode.expected_visit_count,
        "visitsCompleted": episode.visits_completed_count,
        "nextVisit": {"id": str(next_visit.pk), "startsAt": next_visit.starts_at.isoformat()} if next_visit else None,
        "planOfCareEndDate": episode.plan_of_care_end_date.isoformat() if episode.plan_of_care_end_date else None,
        "notes": episode.notes,
        "primaryTherapistName": _display_name(episode.primary_therapist) if episode.primary_therapist else None,
        "referralId": str(episode.referral_id) if episode.referral_id else None,
        # Whether this episode was created for/linked to an in-home
        # (Mobile Care) service request — powers the "Mobile Care Episode"
        # panel in the patient chart, distinguishing it from an ordinary
        # in-clinic episode of care.
        "isMobileCareEpisode": episode.mobile_care_requests.exists(),
        "createdBy": _display_name(episode.created_by) if episode.created_by else None,
        "createdAt": timezone.localtime(episode.created_at).isoformat(),
    }


def serialize_authorization(authorization) -> dict:
    return {
        "id": str(authorization.pk),
        "insuranceName": authorization.insurance_name,
        "authorizationNumber": authorization.authorization_number,
        "visitsApproved": authorization.visits_approved,
        "visitsUsed": authorization.visits_used,
        "visitsRemaining": authorization.visits_remaining,
        "startDate": authorization.start_date.isoformat(),
        "expiresAt": authorization.expires_at.isoformat(),
        "daysRemaining": authorization.days_remaining,
        "status": authorization.status,
        "statusLabel": authorization.get_status_display(),
        "dateAlertTier": authorization.date_alert_tier,
        "visitAlertTier": authorization.visit_alert_tier,
        "colorBucket": authorization.overall_color_bucket,
        "episodeOfCareId": str(authorization.episode_of_care_id) if authorization.episode_of_care_id else None,
        "notes": authorization.notes,
        "createdAt": timezone.localtime(authorization.created_at).isoformat(),
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


def serialize_form_submission_summary(submission) -> dict:
    """Status only, for the workspace's operations list — matches
    serialize_intake's shape; full answers are fetched on demand via the
    dedicated staff detail endpoint, not embedded in every workspace load."""
    return {
        "id": str(submission.pk),
        "templateName": submission.template.name,
        "category": submission.template.category,
        "status": submission.status,
        "statusLabel": submission.get_status_display(),
        "submittedAt": submission.submitted_at.isoformat() if submission.submitted_at else None,
        "createdAt": submission.created_at.isoformat(),
    }


def serialize_form_submission_detail(submission) -> dict:
    payload = serialize_form_submission_summary(submission)
    payload["schema"] = submission.template.schema
    payload["data"] = submission.data
    payload["signatureName"] = submission.signature_name
    payload["signedAt"] = submission.signed_at.isoformat() if submission.signed_at else None
    return payload


def serialize_message(message, *, viewer) -> dict:
    """Message bodies are returned only for a thread participant."""
    return {
        "id": str(message.pk),
        "direction": "outbound" if message.sender_id == viewer.pk else "inbound",
        "sender": _display_name(message.sender),
        "recipient": _display_name(message.recipient),
        "category": message.category,
        "categoryLabel": message.get_category_display(),
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
