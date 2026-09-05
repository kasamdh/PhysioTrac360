"""Role- and tenant-scoped JSON endpoints for the React workspace."""
from __future__ import annotations

import calendar
from datetime import datetime, timedelta

from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout, update_session_auth_hash
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.middleware.csrf import get_token

from ..access import BILLING_ROLES, CLINICAL_ROLES, SCHEDULING_ROLES, patients_for, require_role
from ..models import AIArtifact, Appointment, ClinicalNote, Organization, Patient, SecureMessage, User
from ..services import outcome_trends, patient_compliance_findings, record_audit_event
from .serializers import (
    serialize_appointment,
    serialize_goal,
    serialize_note_summary,
    serialize_outcome_trend,
    serialize_patient,
    serialize_user,
)
from .super_admin import _apply_user_update, _create_client_user, serialize_client_user
from .utils import InvalidJSON, api_error, api_login_required, json_body, organization_or_error


@require_GET
@ensure_csrf_cookie
def csrf(request):
    """Return a masked token because the CSRF cookie remains HttpOnly."""
    return JsonResponse({"csrfToken": get_token(request)})


@require_GET
def facility(request):
    slug = request.GET.get("slug", "").strip()
    organization = Organization.objects.filter(slug=slug, is_active=True).first()
    if not organization:
        return JsonResponse({"detail": "Facility portal was not found."}, status=404)
    return JsonResponse({"name": organization.name, "slug": organization.slug, "status": organization.status})


@require_POST
def login(request):
    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)
    username = str(payload.get("username", "")).strip()
    password = payload.get("password", "")
    portal_slug = str(payload.get("portalSlug", "")).strip()
    if not username or not isinstance(password, str) or not password:
        return api_error("Enter a username and password.", status=400)
    user = authenticate(request, username=username, password=password)
    if user is None:
        return api_error("Invalid username or password.", status=401)
    if (
        portal_slug
        and not user.is_platform_super_admin
        and (not user.organization_id or user.organization.slug != portal_slug)
    ):
        return api_error("This account does not belong to this facility.", status=403)
    if user.organization_id and user.organization.archived_at is not None:
        return JsonResponse({"status": 403, "code": "ORGANIZATION_ARCHIVED", "message": "Your organization account has been archived. Please contact your administrator."}, status=403)
    if user.organization_id and (not user.organization.is_active or user.organization.status == user.organization.Status.SUSPENDED):
        return JsonResponse({"status": 403, "code": "ORGANIZATION_SUSPENDED", "message": "Your organization account is currently suspended. Please contact your administrator."}, status=403)
    auth_login(request, user)
    return JsonResponse({"user": serialize_user(user), "csrfToken": get_token(request)})


@require_POST
@api_login_required
def logout(request):
    auth_logout(request)
    return JsonResponse({"detail": "Signed out."})


@require_POST
@api_login_required
def change_password(request):
    """Self-service password change for the signed-in user (any role)."""
    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)
    current_password = payload.get("currentPassword", "")
    new_password = payload.get("newPassword", "")
    if not isinstance(current_password, str) or not request.user.check_password(current_password):
        return api_error("Current password is incorrect.", status=400)
    if not isinstance(new_password, str) or len(new_password) < 12:
        return api_error("Choose a new password with at least 12 characters.", status=400)
    request.user.set_password(new_password)
    request.user.save(update_fields=["password"])
    update_session_auth_hash(request, request.user)
    if request.user.organization_id:
        # Platform super admins have no organization, and audit events are
        # always organization-scoped, so there is nowhere to log this for them.
        record_audit_event(actor=request.user, action="user.password_changed", obj=request.user, request=request)
    return JsonResponse({"detail": "Password updated."})


@require_GET
@api_login_required
def me(request):
    if request.user.is_platform_super_admin:
        return JsonResponse({"user": serialize_user(request.user)})
    _, error = organization_or_error(request)
    if error:
        return error
    return JsonResponse({"user": serialize_user(request.user)})


@require_http_methods(["GET", "POST"])
@api_login_required
def organization_users(request):
    """Let an organization administrator view and create accounts for their own tenant."""
    organization, error = organization_or_error(request, roles={User.Role.ADMIN})
    if error:
        return error
    if request.method == "POST":
        try:
            payload = json_body(request)
        except InvalidJSON as exc:
            return api_error(str(exc), status=400)
        user, errors = _create_client_user(organization, payload, request.user, request)
        if errors:
            return JsonResponse(
                {"detail": "Please correct the highlighted fields.", "errors": errors}, status=422
            )
        return JsonResponse({"user": serialize_client_user(user)}, status=201)
    users = organization.users.select_related("organization").order_by("last_name", "first_name", "username")
    if request.GET.get("includeArchived", "").strip().lower() != "true":
        users = users.filter(archived_at__isnull=True)
    return JsonResponse({"users": [serialize_client_user(user) for user in users]})


@require_http_methods(["GET", "PATCH", "DELETE"])
@api_login_required
def organization_user_detail(request, user_id):
    """Let an organization administrator edit, deactivate/reactivate, or soft-delete
    an account within their own organization only. The organization is always
    derived from the authenticated admin's own account, never from the request.
    """
    organization, error = organization_or_error(request, roles={User.Role.ADMIN})
    if error:
        return error
    account = User.objects.filter(pk=user_id, organization=organization).first()
    if not account:
        return api_error("User was not found.", status=404)
    if request.method == "GET":
        return JsonResponse({"user": serialize_client_user(account)})

    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)
    if request.method == "DELETE":
        if account.archived_at is not None:
            return api_error("This user is already archived.", status=409)
        payload = {**payload, "archive": True}

    if account.pk == request.user.pk:
        self_errors = {}
        if payload.get("active") is False or payload.get("archive"):
            self_errors["active"] = "You cannot deactivate your own account."
        if "role" in payload and str(payload["role"]) != account.role:
            self_errors["role"] = "You cannot change your own role."
        if payload.get("mustUseMfa") is False:
            self_errors["mustUseMfa"] = "You cannot opt your own account out of MFA policy."
        if self_errors:
            return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": self_errors}, status=422)

    updated, errors, status_code = _apply_user_update(account, payload, request.user, request)
    if errors:
        return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": errors}, status=status_code)
    return JsonResponse({"user": serialize_client_user(updated)})


@require_GET
@api_login_required
def dashboard(request):
    organization, error = organization_or_error(request)
    if error:
        return error

    today = timezone.localdate()
    appointments = Appointment.objects.none()
    if request.user.can_manage_schedule:
        appointments = Appointment.objects.filter(
            patient__organization=organization, starts_at__date=today
        ).select_related("patient", "therapist")
        if request.user.role in {User.Role.THERAPIST, User.Role.ASSISTANT}:
            appointments = appointments.filter(therapist=request.user)

    clinical_patients = patients_for(request.user, clinical=True)
    pending_notes = ClinicalNote.objects.filter(patient__in=clinical_patients).exclude(
        status=ClinicalNote.Status.SIGNED
    )
    due_notes = ClinicalNote.objects.filter(
        patient__in=clinical_patients,
        reassessment_due__isnull=False,
        reassessment_due__lte=today + timedelta(days=7),
    ).exclude(status=ClinicalNote.Status.SIGNED)
    alerts = []
    for patient in clinical_patients[:30]:
        for finding in patient_compliance_findings(patient):
            alerts.append(
                {
                    "patientId": str(patient.pk),
                    "patientName": patient.full_name,
                    "code": finding.code,
                    "severity": finding.severity,
                    "title": finding.title,
                    "detail": finding.detail,
                }
            )

    drafts = AIArtifact.objects.filter(
        patient__in=clinical_patients, status=AIArtifact.Status.DRAFT
    ).select_related("patient")[:5]
    return JsonResponse(
        {
            "today": today.isoformat(),
            "metrics": {
                "appointments": appointments.count(),
                "pendingNotes": pending_notes.count(),
                "dueReassessments": due_notes.count(),
                "unreadMessages": SecureMessage.objects.filter(
                    recipient=request.user, read_at__isnull=True
                ).count(),
            },
            "appointments": [serialize_appointment(item) for item in appointments[:12]],
            "alerts": alerts[:6],
            "pendingNotes": [serialize_note_summary(note) for note in pending_notes[:6]],
            "drafts": [
                {
                    "id": str(draft.pk),
                    "kind": draft.kind,
                    "kindLabel": draft.get_kind_display(),
                    "patientId": str(draft.patient_id),
                    "patientName": draft.patient.full_name,
                    "createdAt": timezone.localtime(draft.created_at).isoformat(),
                }
                for draft in drafts
            ],
        }
    )


def _field(payload: dict, key: str) -> str:
    value = payload.get(key, "")
    return value.strip() if isinstance(value, str) else ""


def validate_patient_payload(payload: dict, *, partial: bool = False) -> dict[str, str]:
    required = {"firstName": "First name", "lastName": "Last name", "dateOfBirth": "Date of birth"}
    errors = {}
    for key, label in required.items():
        if partial and key not in payload:
            continue
        if not str(payload.get(key, "")).strip():
            errors[key] = f"{label} is required."
    email = payload.get("email")
    if email and "@" not in str(email):
        errors["email"] = "Enter a valid email address."
    if payload.get("status") and payload["status"] not in Patient.Status.values:
        errors["status"] = "Choose a supported patient status."
    return errors


def _resolve_assigned_therapist(organization, therapist_id: str):
    """Return the therapist for this org, or None if therapist_id is falsy."""
    if not therapist_id:
        return None, None
    therapist = User.objects.filter(
        pk=therapist_id,
        organization=organization,
        is_active=True,
        role__in=[User.Role.ADMIN, User.Role.DIRECTOR, User.Role.THERAPIST, User.Role.ASSISTANT],
    ).first()
    if not therapist:
        return None, {"assignedTherapistId": "Choose a valid clinician for this organization."}
    return therapist, None


@require_http_methods(["GET", "POST"])
@api_login_required
def patients(request):
    if request.method == "POST":
        organization, error = organization_or_error(request, roles=SCHEDULING_ROLES)
        if error:
            return error
        try:
            payload = json_body(request)
        except InvalidJSON as exc:
            return api_error(str(exc), status=400)
        errors = validate_patient_payload(payload)
        if errors:
            return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": errors}, status=422)
        assigned_therapist, therapist_error = _resolve_assigned_therapist(
            organization, payload.get("assignedTherapistId")
        )
        if therapist_error:
            return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": therapist_error}, status=422)
        if ("diagnoses" in payload or "precautions" in payload) and request.user.role not in CLINICAL_ROLES:
            return api_error("Only clinical roles can set diagnosis or precaution details.", status=403)
        patient = Patient(
            organization=organization,
            first_name=_field(payload, "firstName"),
            last_name=_field(payload, "lastName"),
            date_of_birth=payload["dateOfBirth"],
            phone=_field(payload, "phone"),
            email=_field(payload, "email"),
            address=_field(payload, "address"),
            emergency_contact=_field(payload, "emergencyContact"),
            diagnoses=_field(payload, "diagnoses"),
            precautions=_field(payload, "precautions"),
            status=payload.get("status") or Patient.Status.ACTIVE,
            assigned_therapist=assigned_therapist,
        )
        try:
            patient.full_clean()
            patient.save()
        except ValidationError as exc:
            errors = {field: " ".join(messages) for field, messages in exc.message_dict.items()}
            return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": errors}, status=422)
        record_audit_event(
            actor=request.user, action="patient.created", obj=patient, patient=patient, request=request
        )
        return JsonResponse(
            {"patient": serialize_patient(patient, include_clinical=request.user.role in CLINICAL_ROLES, include_contact=True)},
            status=201,
        )

    _, error = organization_or_error(request)
    if error:
        return error
    if request.user.role in CLINICAL_ROLES:
        queryset = patients_for(request.user, clinical=True)
    else:
        try:
            require_role(request.user, SCHEDULING_ROLES | BILLING_ROLES)
        except PermissionDenied as exc:
            return api_error(str(exc), status=403)
        queryset = patients_for(request.user, clinical=False)

    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(medical_record_number__icontains=query)
        )
    records = list(queryset.select_related("assigned_therapist")[:100])
    return JsonResponse(
        {
            "query": query,
            "count": len(records),
            "truncated": queryset.count() > len(records),
            "patients": [serialize_patient(patient) for patient in records],
        }
    )


@require_http_methods(["GET", "PATCH", "DELETE"])
@api_login_required
def patient_detail(request, patient_id: str):
    if request.method == "GET":
        _, error = organization_or_error(request, roles=CLINICAL_ROLES)
        if error:
            return error
        patient = get_object_or_404(
            patients_for(request.user, clinical=True).select_related("assigned_therapist"),
            pk=patient_id,
        )
        record_audit_event(
            actor=request.user,
            action="patient.viewed",
            obj=patient,
            patient=patient,
            request=request,
            metadata={"route": "api-v1-patient-detail"},
        )
        notes = patient.notes.select_related("patient").all()[:8]
        appointments = patient.appointments.select_related("patient", "therapist").all()[:8]
        findings = patient_compliance_findings(patient)
        return JsonResponse(
            {
                "patient": serialize_patient(patient, include_clinical=True),
                "notes": [serialize_note_summary(note) for note in notes],
                "goals": [serialize_goal(goal) for goal in patient.goals.all()[:8]],
                "outcomes": [
                    serialize_outcome_trend(trend) for trend in outcome_trends(patient)
                ],
                "appointments": [serialize_appointment(item) for item in appointments],
                "complianceFindings": [
                    {
                        "code": finding.code,
                        "severity": finding.severity,
                        "title": finding.title,
                        "detail": finding.detail,
                        "finalizationBlocker": finding.finalization_blocker,
                    }
                    for finding in findings
                ],
            }
        )

    # PATCH / DELETE: broader operational roles, org-wide (non-clinical) lookup —
    # editing a phone number or deactivating a chart is not a caseload decision.
    organization, error = organization_or_error(request, roles=SCHEDULING_ROLES)
    if error:
        return error
    patient = get_object_or_404(
        patients_for(request.user, clinical=False).select_related("assigned_therapist"), pk=patient_id
    )

    if request.method == "DELETE":
        if patient.status == Patient.Status.INACTIVE:
            return api_error("This patient is already inactive.", status=409)
        patient.status = Patient.Status.INACTIVE
        patient.full_clean()
        patient.save(update_fields=["status", "updated_at"])
        record_audit_event(
            actor=request.user, action="patient.deactivated", obj=patient, patient=patient, request=request
        )
        return JsonResponse(
            {"patient": serialize_patient(patient, include_clinical=request.user.role in CLINICAL_ROLES, include_contact=True)}
        )

    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)
    errors = validate_patient_payload(payload, partial=True)
    if errors:
        return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": errors}, status=422)
    if ("diagnoses" in payload or "precautions" in payload) and request.user.role not in CLINICAL_ROLES:
        return api_error("Only clinical roles can update diagnosis or precaution details.", status=403)

    demographic_fields = {
        "first_name": "firstName",
        "last_name": "lastName",
        "date_of_birth": "dateOfBirth",
        "phone": "phone",
        "email": "email",
        "address": "address",
        "emergency_contact": "emergencyContact",
        "status": "status",
        "diagnoses": "diagnoses",
        "precautions": "precautions",
    }
    changed_fields = []
    for field, key in demographic_fields.items():
        if key not in payload:
            continue
        new_value = str(payload[key]).strip()
        if str(getattr(patient, field)) != new_value:
            changed_fields.append(field)
        setattr(patient, field, new_value)
    if "assignedTherapistId" in payload:
        assigned_therapist, therapist_error = _resolve_assigned_therapist(
            organization, payload.get("assignedTherapistId")
        )
        if therapist_error:
            return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": therapist_error}, status=422)
        if patient.assigned_therapist_id != (assigned_therapist.pk if assigned_therapist else None):
            changed_fields.append("assigned_therapist")
        patient.assigned_therapist = assigned_therapist

    try:
        patient.full_clean()
    except ValidationError as exc:
        errors = {field: " ".join(messages) for field, messages in exc.message_dict.items()}
        return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": errors}, status=422)
    patient.save()
    if changed_fields:
        record_audit_event(
            actor=request.user,
            action="patient.updated",
            obj=patient,
            patient=patient,
            request=request,
            metadata={"changed_fields": changed_fields},
        )
    return JsonResponse(
        {"patient": serialize_patient(patient, include_clinical=request.user.role in CLINICAL_ROLES, include_contact=True)}
    )


@require_GET
@api_login_required
def patient_for_edit(request, patient_id: str):
    """Fetch a patient's full editable fields (including contact info) to
    pre-populate the edit form. Deliberately separate from patient_detail and
    the clinical workspace, which must not surface contact info by default.
    """
    _, error = organization_or_error(request, roles=SCHEDULING_ROLES)
    if error:
        return error
    patient = get_object_or_404(
        patients_for(request.user, clinical=False).select_related("assigned_therapist"), pk=patient_id
    )
    return JsonResponse(
        {"patient": serialize_patient(patient, include_clinical=request.user.role in CLINICAL_ROLES, include_contact=True)}
    )


@require_GET
@api_login_required
def staff_options(request):
    """Assignable clinical staff for the caller's organization (e.g. a patient's therapist)."""
    organization, error = organization_or_error(request, roles=SCHEDULING_ROLES)
    if error:
        return error
    staff = User.objects.filter(
        organization=organization,
        is_active=True,
        role__in=[User.Role.ADMIN, User.Role.DIRECTOR, User.Role.THERAPIST, User.Role.ASSISTANT],
    ).order_by("last_name", "first_name")
    return JsonResponse(
        {
            "staff": [
                {"id": str(member.pk), "displayName": member.get_full_name() or member.username, "roleLabel": member.get_role_display()}
                for member in staff
            ]
        }
    )


@require_GET
@api_login_required
def schedule(request):
    organization, error = organization_or_error(request, roles=SCHEDULING_ROLES)
    if error:
        return error
    today = timezone.localdate()
    requested_month = request.GET.get("month", "")
    try:
        month_start = (
            datetime.strptime(requested_month, "%Y-%m").date().replace(day=1)
            if requested_month
            else today.replace(day=1)
        )
    except ValueError:
        return api_error("Month must use YYYY-MM format.", status=400)

    calendar_weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(
        month_start.year, month_start.month
    )
    visible_start = calendar_weeks[0][0]
    visible_end = calendar_weeks[-1][-1]
    appointments = Appointment.objects.filter(
        patient__organization=organization,
        starts_at__date__gte=visible_start,
        starts_at__date__lte=visible_end,
    ).select_related("patient", "therapist")
    if request.user.role in {User.Role.THERAPIST, User.Role.ASSISTANT}:
        appointments = appointments.filter(therapist=request.user)

    return JsonResponse(
        {
            "month": month_start.strftime("%Y-%m"),
            "visibleStart": visible_start.isoformat(),
            "visibleEnd": visible_end.isoformat(),
            "events": [serialize_appointment(item) for item in appointments],
        }
    )
