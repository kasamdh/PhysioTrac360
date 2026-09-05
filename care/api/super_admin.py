"""Super-admin-only client management API."""
from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from ..access import require_platform_super_admin
from ..client_management import archive_client, activate_client, issue_invitation, provision_client, serialize_client, suspend_client
from ..models import (
    Appointment,
    AuditEvent,
    ClientInvitation,
    ClinicalNote,
    Organization,
    Patient,
    PrivilegedAccessGrant,
    User,
)
from ..privileged_access import ALLOWED_DURATIONS_HOURS, active_grant, request_privileged_access, revoke_privileged_access
from ..services import outcome_trends, record_audit_event
from .serializers import (
    serialize_appointment,
    serialize_audit_event,
    serialize_goal,
    serialize_note_summary,
    serialize_outcome_trend,
    serialize_patient,
    serialize_user,
)
from .utils import api_error, api_login_required, json_body


TENANT_USER_ROLES = {
    User.Role.ADMIN,
    User.Role.DIRECTOR,
    User.Role.THERAPIST,
    User.Role.ASSISTANT,
    User.Role.SCHEDULER,
    User.Role.BILLER,
    User.Role.COMPLIANCE,
}

CLINICAL_ACCESS_ROLES = {
    User.Role.ADMIN,
    User.Role.DIRECTOR,
    User.Role.THERAPIST,
    User.Role.ASSISTANT,
    User.Role.COMPLIANCE,
}
ASSIGNED_CLINICIAN_ROLES = {User.Role.THERAPIST, User.Role.ASSISTANT}


def require_super_admin(request):
    require_platform_super_admin(request.user)


def serialize_client_user(user: User) -> dict:
    return {
        "id": str(user.pk),
        "name": user.get_full_name() or user.username,
        "firstName": user.first_name,
        "lastName": user.last_name,
        "email": user.email,
        "username": user.username,
        "role": user.role,
        "roleLabel": user.get_role_display(),
        "active": user.is_active,
        "mustUseMfa": user.must_use_mfa,
        "archivedAt": user.archived_at.isoformat() if user.archived_at else None,
        "clientNumber": user.organization.client_number if user.organization_id else None,
        "clientName": user.organization.name if user.organization_id else None,
    }


def _create_client_user(client: Organization, payload: dict, actor: User, request) -> tuple[User | None, dict | None]:
    """Shared creation path for a client-scoped POST and the platform-wide POST."""
    errors = validate_client_user_payload(payload)
    if errors:
        return None, errors
    user = User(
        username=_string_value(payload, "username"),
        first_name=_string_value(payload, "firstName"),
        last_name=_string_value(payload, "lastName"),
        email=_string_value(payload, "email"),
        credential=_string_value(payload, "credential"),
        role=_string_value(payload, "role"),
        organization=client,
        is_active=True,
        is_superuser=False,
        is_staff=False,
        must_use_mfa=payload.get("mustUseMfa", True) is not False,
    )
    user.set_password(payload["password"])
    try:
        with transaction.atomic():
            user.full_clean()
            user.save()
            record_audit_event(
                actor=actor,
                action="client_user.created",
                obj=user,
                request=request,
                metadata={
                    "client_number": client.client_number,
                    "role": user.role,
                    "mfa_policy_required": user.must_use_mfa,
                },
            )
    except ValidationError as exc:
        return None, {field: " ".join(messages) for field, messages in exc.message_dict.items()}
    except IntegrityError:
        return None, {"username": "This username is already in use."}
    return user, None


def _apply_user_update(account: User, payload: dict, actor: User, request) -> tuple[User | None, dict | None, int]:
    """Edit, deactivate/reactivate, or soft-delete a tenant user with the same
    operational safeguards the (retired) HTML access-control form used to enforce:
    never leave an organization without an active administrator, and never strip
    clinical access from a therapist/assistant with an active caseload, future
    visits, or unsigned notes without those being reassigned or resolved first.
    """
    organization = account.organization
    errors: dict[str, str] = {}
    if "email" in payload:
        try:
            validate_email(str(payload["email"]))
        except ValidationError:
            errors["email"] = "Enter a valid email address."
    requested_role = str(payload.get("role", account.role))
    if "role" in payload and requested_role not in TENANT_USER_ROLES:
        errors["role"] = "Choose a tenant-scoped user role."
    for key in ("isSuperuser", "isStaff"):
        if payload.get(key) is True:
            errors[key] = "Platform privileges cannot be assigned to a client user."
    if errors:
        return None, errors, 422

    requested_active = bool(payload.get("active", account.is_active))
    soft_delete = bool(payload.get("archive"))
    if soft_delete:
        requested_active = False

    with transaction.atomic():
        locked_account = User.objects.select_for_update().get(pk=account.pk, organization=organization)

        if locked_account.role == User.Role.ADMIN and locked_account.is_active:
            removes_admin = requested_role != User.Role.ADMIN or not requested_active
            active_admin_count = User.objects.filter(
                organization=organization, role=User.Role.ADMIN, is_active=True
            ).count()
            if removes_admin and active_admin_count <= 1:
                error_field = "role" if requested_role != User.Role.ADMIN else "active"
                return None, {
                    error_field: "Assign another active organization administrator before removing this access."
                }, 409

        leaves_clinical_scope = locked_account.role in ASSIGNED_CLINICIAN_ROLES and (
            not requested_active or requested_role not in CLINICAL_ACCESS_ROLES
        )
        if leaves_clinical_scope:
            active_caseload = Patient.objects.filter(
                assigned_therapist=locked_account, status=Patient.Status.ACTIVE
            ).exists()
            future_visits = Appointment.objects.filter(
                therapist=locked_account,
                starts_at__gte=timezone.now(),
                status__in=[Appointment.Status.SCHEDULED, Appointment.Status.CHECKED_IN],
            ).exists()
            unsigned_notes = ClinicalNote.objects.filter(therapist=locked_account).exclude(
                status=ClinicalNote.Status.SIGNED
            ).exists()
            if active_caseload or future_visits or unsigned_notes:
                error_field = "active" if not requested_active else "role"
                return None, {
                    error_field: "Reassign the active caseload and future visits, and resolve unsigned notes before removing clinical access."
                }, 409

        previous_role = locked_account.role
        previous_active = locked_account.is_active
        previous_mfa_policy = locked_account.must_use_mfa

        if "firstName" in payload:
            locked_account.first_name = _string_value(payload, "firstName")
        if "lastName" in payload:
            locked_account.last_name = _string_value(payload, "lastName")
        if "email" in payload:
            locked_account.email = _string_value(payload, "email")
        if "role" in payload:
            locked_account.role = requested_role
        if "credential" in payload:
            locked_account.credential = _string_value(payload, "credential")
        if "mustUseMfa" in payload:
            locked_account.must_use_mfa = bool(payload["mustUseMfa"])
        if "active" in payload or soft_delete:
            locked_account.is_active = requested_active
        if soft_delete:
            locked_account.archived_at = timezone.now()
            locked_account.archived_by = actor

        try:
            locked_account.full_clean()
        except ValidationError as exc:
            return None, {field: " ".join(messages) for field, messages in exc.message_dict.items()}, 422
        locked_account.save()

        if soft_delete:
            action = "client_user.archived"
        elif previous_active and not locked_account.is_active:
            action = "client_user.deactivated"
        elif not previous_active and locked_account.is_active:
            action = "client_user.reactivated"
        elif previous_role != locked_account.role:
            action = "client_user.role_changed"
        elif previous_mfa_policy != locked_account.must_use_mfa:
            action = "client_user.mfa_policy_changed"
        else:
            action = "client_user.updated"
        record_audit_event(
            actor=actor,
            action=action,
            obj=locked_account,
            request=request,
            metadata={
                "client_number": organization.client_number if organization else None,
                "previous_role": previous_role,
                "role": locked_account.role,
                "active": locked_account.is_active,
                "mfa_policy_required": locked_account.must_use_mfa,
            },
        )
    return locked_account, None, 200


def _string_value(payload: dict, key: str) -> str:
    value = payload.get(key, "")
    return value.strip() if isinstance(value, str) else ""


def validate_client_user_payload(payload: dict) -> dict[str, str]:
    required = {
        "username": "Username",
        "firstName": "First name",
        "lastName": "Last name",
        "email": "Email",
        "role": "Role",
        "password": "Temporary password",
        "confirmPassword": "Confirm temporary password",
    }
    errors = {
        key: f"{label} is required."
        for key, label in required.items()
        if not _string_value(payload, key)
    }
    username = _string_value(payload, "username")
    email = _string_value(payload, "email")
    role = _string_value(payload, "role")
    password = payload.get("password", "")
    confirm_password = payload.get("confirmPassword", "")

    if username and User.objects.filter(username=username).exists():
        errors["username"] = "This username is already in use."
    if email:
        try:
            validate_email(email)
        except ValidationError:
            errors["email"] = "Enter a valid email address."
    if role and role not in TENANT_USER_ROLES:
        errors["role"] = "Choose a tenant-scoped user role."
    if isinstance(password, str) and isinstance(confirm_password, str):
        if password and confirm_password and password != confirm_password:
            errors["confirmPassword"] = "The passwords do not match."
        if password:
            prospective_user = User(
                username=username,
                first_name=_string_value(payload, "firstName"),
                last_name=_string_value(payload, "lastName"),
                email=email,
                role=role or User.Role.THERAPIST,
            )
            try:
                validate_password(password, prospective_user)
            except ValidationError as exc:
                errors["password"] = " ".join(exc.messages)
    else:
        errors["password"] = "Enter a valid temporary password."

    for key in ("isSuperuser", "isStaff"):
        if payload.get(key) is True:
            errors[key] = "Platform privileges cannot be assigned to a client user."
    if "mustUseMfa" in payload and not isinstance(payload["mustUseMfa"], bool):
        errors["mustUseMfa"] = "MFA policy must be specified as true or false."
    return errors


def validate_client_payload(payload: dict, *, partial=False):
    required = {
        "clientName": "Client name",
        "clientEmail": "Client email",
        "addressLine1": "Address",
        "city": "City",
        "state": "State",
        "zipCode": "ZIP code",
        "subscriptionTier": "Subscription tier",
        "timezone": "Timezone",
    }
    if not partial:
        required.update({"adminFirstName": "Admin first name", "adminLastName": "Admin last name", "adminEmail": "Admin email"})
    errors = {key: f"{label} is required." for key, label in required.items() if not str(payload.get(key, "")).strip()}
    for key in ("clientEmail", "adminEmail"):
        if payload.get(key) and ("@" not in str(payload[key]) or "." not in str(payload[key]).split("@")[-1]):
            errors[key] = "Enter a valid email address."
    if payload.get("subscriptionTier") and payload["subscriptionTier"] not in Organization.SubscriptionTier.values:
        errors["subscriptionTier"] = "Choose a supported subscription tier."
    if payload.get("timezone"):
        try:
            ZoneInfo(payload["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            errors["timezone"] = "Choose a valid IANA timezone."
    if payload.get("status") and payload["status"] not in Organization.Status.values:
        errors["status"] = "Choose a supported client status."
    return errors


@require_GET
@api_login_required
def clients(request):
    try:
        require_super_admin(request)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    queryset = Organization.objects.all().prefetch_related("users")
    include_archived = request.GET.get("includeArchived", "").strip().lower() == "true"
    query = request.GET.get("q", "").strip()
    if query:
        query_filter = Q(name__icontains=query) | Q(support_email__icontains=query) | Q(city__icontains=query) | Q(users__first_name__icontains=query) | Q(users__last_name__icontains=query)
        if query.isdigit():
            query_filter |= Q(client_number=int(query))
        queryset = queryset.filter(query_filter).distinct()
    status = request.GET.get("status", "").strip()
    tier = request.GET.get("subscriptionTier", "").strip()
    state = request.GET.get("state", "").strip()
    timezone = request.GET.get("timezone", "").strip()
    if status == "archived":
        queryset = queryset.filter(archived_at__isnull=False)
        include_archived = True
    elif status:
        queryset = queryset.filter(status=status)
    if tier: queryset = queryset.filter(subscription_tier=tier)
    if state: queryset = queryset.filter(state__iexact=state)
    if timezone: queryset = queryset.filter(timezone=timezone)
    if not include_archived:
        queryset = queryset.filter(archived_at__isnull=True)
    sort = request.GET.get("sort", "client_number")
    sort_map = {"client_number": "client_number", "client_name": "name", "created": "created_at", "users": "users_count"}
    if sort == "users":
        from django.db.models import Count
        queryset = queryset.annotate(users_count=Count("users")).order_by("users_count", "name")
    else:
        queryset = queryset.order_by(sort_map.get(sort, "client_number"))
    try:
        page_size = min(max(int(request.GET.get("pageSize", "25")), 10), 100)
        page = max(int(request.GET.get("page", "1")), 1)
    except ValueError:
        return api_error("Page and page size must be whole numbers.", status=400)
    total = queryset.count()
    records = list(queryset[(page - 1) * page_size : page * page_size])
    return JsonResponse({"clients": [serialize_client(client) for client in records], "total": total, "page": page, "pageSize": page_size})


@require_http_methods(["GET", "PUT", "PATCH", "DELETE"])
@api_login_required
def client_detail(request, client_number: int):
    try:
        require_super_admin(request)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    client = Organization.objects.filter(client_number=client_number).first()
    if not client:
        return api_error("Client was not found.", status=404)
    if request.method == "GET":
        return JsonResponse({"client": serialize_client(client)})
    if request.method == "DELETE":
        if client.archived_at is not None:
            return api_error("Client is already archived.", status=409)
        try:
            payload = json_body(request)
        except ValueError:
            payload = {}
        client = archive_client(client, request.user, str(payload.get("reason", "")).strip())
        return JsonResponse({"client": serialize_client(client)})
    try:
        payload = json_body(request)
    except ValueError as exc:
        return api_error(str(exc), status=400)
    errors = validate_client_payload(payload, partial=True)
    if errors:
        return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": errors}, status=422)
    fields = {"name": "clientName", "support_email": "clientEmail", "support_phone": "clientPhone", "address_line_1": "addressLine1", "address_line_2": "addressLine2", "city": "city", "state": "state", "zip_code": "zipCode", "country": "country", "subscription_tier": "subscriptionTier", "timezone": "timezone", "comments": "comments"}
    changed_fields = []
    for field, key in fields.items():
        if key in payload:
            new_value = str(payload[key]).strip()
            if getattr(client, field) != new_value:
                changed_fields.append(field)
            setattr(client, field, new_value)
    client.updated_by = request.user
    client.full_clean()
    client.save(update_fields=list(fields.keys()) + ["updated_by", "updated_at"])
    if changed_fields:
        record_audit_event(
            actor=request.user,
            action="client.updated",
            obj=client,
            request=request,
            metadata={"client_number": client.client_number, "changed_fields": changed_fields},
        )
    return JsonResponse({"client": serialize_client(client)})


@require_http_methods(["GET", "POST"])
@api_login_required
def all_users(request):
    """Platform-wide user directory: every tenant-scoped user across every client."""
    try:
        require_super_admin(request)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)

    if request.method == "POST":
        try:
            payload = json_body(request)
        except ValueError as exc:
            return api_error(str(exc), status=400)
        client_number = payload.get("clientNumber")
        client = Organization.objects.filter(client_number=client_number).first() if client_number else None
        if not client:
            return JsonResponse(
                {"detail": "Please correct the highlighted fields.", "errors": {"clientNumber": "Choose a client."}},
                status=422,
            )
        user, errors = _create_client_user(client, payload, request.user, request)
        if errors:
            return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": errors}, status=422)
        return JsonResponse({"user": serialize_client_user(user)}, status=201)

    users = User.objects.filter(organization__isnull=False).select_related("organization").order_by(
        "organization__client_number", "last_name", "first_name"
    )
    query = request.GET.get("q", "").strip()
    if query:
        user_filter = (
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
            | Q(username__icontains=query)
            | Q(organization__name__icontains=query)
        )
        if query.isdigit():
            user_filter |= Q(organization__client_number=int(query))
        users = users.filter(user_filter)
    role = request.GET.get("role", "").strip()
    if role:
        users = users.filter(role=role)
    client_number = request.GET.get("clientNumber", "").strip()
    if client_number:
        users = users.filter(organization__client_number=client_number)
    status = request.GET.get("status", "").strip()
    include_archived = request.GET.get("includeArchived", "").strip().lower() == "true"
    if status == "archived":
        users = users.filter(archived_at__isnull=False)
        include_archived = True
    elif status == "active":
        users = users.filter(is_active=True)
    elif status == "inactive":
        users = users.filter(is_active=False)
    if not include_archived:
        users = users.filter(archived_at__isnull=True)
    try:
        page_size = min(max(int(request.GET.get("pageSize", "25")), 10), 100)
        page = max(int(request.GET.get("page", "1")), 1)
    except ValueError:
        return api_error("Page and page size must be whole numbers.", status=400)
    total = users.count()
    records = list(users[(page - 1) * page_size : page * page_size])
    return JsonResponse({
        "users": [serialize_client_user(user) for user in records],
        "total": total,
        "page": page,
        "pageSize": page_size,
    })


@require_http_methods(["GET", "PATCH", "DELETE"])
@api_login_required
def user_detail(request, user_id):
    """Super-admin edit / deactivate-reactivate / soft-delete for one tenant user."""
    try:
        require_super_admin(request)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    account = User.objects.filter(pk=user_id, organization__isnull=False).select_related("organization").first()
    if not account:
        return api_error("User was not found.", status=404)
    if request.method == "GET":
        return JsonResponse({"user": serialize_client_user(account)})

    try:
        payload = json_body(request)
    except ValueError as exc:
        return api_error(str(exc), status=400)
    if request.method == "DELETE":
        if account.archived_at is not None:
            return api_error("This user is already archived.", status=409)
        payload = {**payload, "archive": True}

    updated, errors, status_code = _apply_user_update(account, payload, request.user, request)
    if errors:
        return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": errors}, status=status_code)
    return JsonResponse({"user": serialize_client_user(updated)})


@require_http_methods(["GET", "POST"])
@api_login_required
def client_users(request, client_number: int):
    try:
        require_super_admin(request)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    client = Organization.objects.filter(client_number=client_number).first()
    if not client:
        return api_error("Client was not found.", status=404)
    if request.method == "POST":
        try:
            payload = json_body(request)
        except ValueError as exc:
            return api_error(str(exc), status=400)
        user, errors = _create_client_user(client, payload, request.user, request)
        if errors:
            return JsonResponse(
                {"detail": "Please correct the highlighted fields.", "errors": errors},
                status=422,
            )
        return JsonResponse({"user": serialize_client_user(user)}, status=201)
    users = client.users.select_related("organization").order_by("last_name", "first_name", "username")
    return JsonResponse(
        {
            "client": serialize_client(client),
            "users": [serialize_client_user(user) for user in users],
        }
    )


@require_GET
@api_login_required
def client_audit_events(request, client_number: int):
    try:
        require_super_admin(request)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    client = Organization.objects.filter(client_number=client_number).first()
    if not client:
        return api_error("Client was not found.", status=404)
    events = (
        AuditEvent.objects.filter(organization=client, patient__isnull=True)
        .select_related("actor")
        .order_by("-created_at")[:100]
    )
    return JsonResponse({"events": [serialize_audit_event(event) for event in events]})


def serialize_privileged_access_grant(grant: PrivilegedAccessGrant) -> dict:
    return {
        "id": str(grant.pk),
        "actor": grant.actor.get_full_name() or grant.actor.username,
        "reason": grant.reason,
        "requestedAt": grant.created_at.isoformat(),
        "expiresAt": grant.expires_at.isoformat(),
        "revokedAt": grant.revoked_at.isoformat() if grant.revoked_at else None,
        "revokedBy": (grant.revoked_by.get_full_name() or grant.revoked_by.username) if grant.revoked_by else None,
        "isActive": grant.is_active,
    }


def _client_or_404(client_number: int) -> Organization | None:
    return Organization.objects.filter(client_number=client_number).first()


@require_http_methods(["GET", "POST"])
@api_login_required
def privileged_access_grants(request, client_number: int):
    """Request or review break-glass clinical-access grants for one client.

    Super admins have no standing clinical access (access.organization_required
    denies them outright). This is the only path in: a reasoned, time-boxed
    grant, fully audited at request time, revoke time, and on every chart read
    taken under it (see privileged_patients / privileged_patient_detail).
    """
    try:
        require_super_admin(request)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    client = _client_or_404(client_number)
    if not client:
        return api_error("Client was not found.", status=404)

    if request.method == "POST":
        try:
            payload = json_body(request)
        except ValueError as exc:
            return api_error(str(exc), status=400)
        reason = str(payload.get("reason", "")).strip()
        try:
            duration_hours = int(payload.get("durationHours", 0))
        except (TypeError, ValueError):
            duration_hours = 0
        errors = {}
        if not reason:
            errors["reason"] = "Explain why this access is needed."
        if duration_hours not in ALLOWED_DURATIONS_HOURS:
            errors["durationHours"] = "Choose a supported access duration."
        if errors:
            return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": errors}, status=422)
        grant = request_privileged_access(client, request.user, reason, duration_hours)
        return JsonResponse({"grant": serialize_privileged_access_grant(grant)}, status=201)

    grants = PrivilegedAccessGrant.objects.filter(organization=client).select_related("actor", "revoked_by")[:50]
    return JsonResponse({"grants": [serialize_privileged_access_grant(grant) for grant in grants]})


@require_http_methods(["PATCH"])
@api_login_required
def privileged_access_revoke(request, client_number: int, grant_id):
    try:
        require_super_admin(request)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    grant = PrivilegedAccessGrant.objects.filter(pk=grant_id, organization__client_number=client_number).first()
    if not grant:
        return api_error("Access grant was not found.", status=404)
    if not grant.is_active:
        return api_error("This access grant is not active.", status=409)
    grant = revoke_privileged_access(grant, request.user)
    return JsonResponse({"grant": serialize_privileged_access_grant(grant)})


def _require_active_grant(client: Organization, actor: User):
    """Return the active grant, or a 403 JsonResponse directing the caller to request one."""
    grant = active_grant(client, actor)
    if not grant:
        return None, JsonResponse(
            {
                "timestamp": timezone.now().isoformat(),
                "status": 403,
                "code": "PRIVILEGED_ACCESS_REQUIRED",
                "message": "Request time-boxed privileged access to this client before viewing clinical records.",
            },
            status=403,
        )
    return grant, None


@require_GET
@api_login_required
def privileged_patients(request, client_number: int):
    try:
        require_super_admin(request)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    client = _client_or_404(client_number)
    if not client:
        return api_error("Client was not found.", status=404)
    grant, error = _require_active_grant(client, request.user)
    if error:
        return error
    patients = Patient.objects.filter(organization=client).select_related("assigned_therapist").order_by(
        "last_name", "first_name"
    )
    record_audit_event(
        actor=request.user,
        action="privileged_access.patient_list_viewed",
        obj=grant,
        request=request,
        metadata={"client_number": client.client_number, "patient_count": patients.count()},
    )
    return JsonResponse({"patients": [serialize_patient(patient) for patient in patients]})


@require_GET
@api_login_required
def privileged_patient_detail(request, client_number: int, patient_id):
    try:
        require_super_admin(request)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    client = _client_or_404(client_number)
    if not client:
        return api_error("Client was not found.", status=404)
    grant, error = _require_active_grant(client, request.user)
    if error:
        return error
    patient = Patient.objects.filter(pk=patient_id, organization=client).select_related("assigned_therapist").first()
    if not patient:
        return api_error("Patient was not found.", status=404)

    record_audit_event(
        actor=request.user,
        action="privileged_access.patient_viewed",
        obj=grant,
        patient=patient,
        request=request,
        metadata={"client_number": client.client_number, "reason": grant.reason},
    )
    notes = patient.notes.order_by("-service_date", "-created_at")[:20]
    appointments = patient.appointments.select_related("therapist").order_by("-starts_at")[:20]
    goals = patient.goals.order_by("status", "target_date")[:20]
    return JsonResponse(
        {
            "patient": serialize_patient(patient, include_clinical=True),
            "notes": [serialize_note_summary(note) for note in notes],
            "appointments": [serialize_appointment(appointment) for appointment in appointments],
            "goals": [serialize_goal(goal) for goal in goals],
            "outcomes": [serialize_outcome_trend(trend) for trend in outcome_trends(patient)],
            "grant": serialize_privileged_access_grant(grant),
        }
    )


@require_POST
@api_login_required
def resend_admin_invitation(request, client_number: int):
    try:
        require_super_admin(request)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    client = Organization.objects.filter(client_number=client_number).first()
    if not client:
        return api_error("Client was not found.", status=404)
    administrator = client.users.filter(role=User.Role.ADMIN).order_by("created_at").first()
    if not administrator:
        return api_error("This client has no administrator account.", status=409)
    token = issue_invitation(client, administrator)
    return JsonResponse({
        "detail": "A new development invitation was generated.",
        "email": administrator.email,
        "invitationUrl": f"http://localhost:5173/{client.slug}/activate?token={token}",
    })


@require_http_methods(["GET", "POST"])
def activate_invitation(request):
    import hashlib

    if request.method == "GET":
        token = request.GET.get("token", "")
        if not token:
            return api_error("A valid invitation token is required.", status=400)
        invitation = ClientInvitation.objects.select_related("user", "organization").filter(
            token_hash=hashlib.sha256(token.encode()).hexdigest()
        ).first()
        if not invitation or not invitation.is_usable:
            return api_error("This invitation is expired or has already been used.", status=410)
        return JsonResponse(
            {
                "organizationName": invitation.organization.name,
                "email": invitation.user.email,
            }
        )

    try:
        payload = json_body(request)
    except ValueError as exc:
        return api_error(str(exc), status=400)
    from django.contrib.auth import login

    token = str(payload.get("token", ""))
    password = payload.get("password", "")
    if not token or not isinstance(password, str) or len(password) < 12:
        return api_error("A valid invitation token and password of at least 12 characters are required.", status=400)
    invitation = ClientInvitation.objects.select_related("user", "organization").filter(token_hash=hashlib.sha256(token.encode()).hexdigest()).first()
    if not invitation or not invitation.is_usable:
        return api_error("This invitation is expired or has already been used.", status=410)
    if invitation.organization.status != Organization.Status.ACTIVE:
        return JsonResponse(
            {
                "timestamp": timezone.now().isoformat(),
                "status": 403,
                "code": "ORGANIZATION_SUSPENDED",
                "message": "Your organization account is currently suspended. Please contact your administrator.",
            },
            status=403,
        )
    invitation.user.set_password(password)
    invitation.user.save(update_fields=["password"])
    invitation.used_at = timezone.now()
    invitation.save(update_fields=["used_at"])
    login(request, invitation.user)
    return JsonResponse({"user": serialize_user(invitation.user), "csrfToken": get_token(request)})


@require_POST
@api_login_required
def client_create(request):
    try:
        require_super_admin(request)
        payload = json_body(request)
    except (PermissionDenied, ValueError) as exc:
        return api_error(str(exc), status=403 if isinstance(exc, PermissionDenied) else 400)
    errors = validate_client_payload(payload)
    if errors:
        return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": errors}, status=422)
    try:
        provisioned = provision_client(payload, request.user)
    except ValueError as exc:
        return api_error(str(exc), status=409)
    return JsonResponse(
        {
            "client": serialize_client(provisioned.organization),
            "administrator": {"id": str(provisioned.administrator.pk), "email": provisioned.administrator.email},
            "developmentInviteToken": provisioned.development_invite_token,
            "invitationUrl": f"http://localhost:5173/{provisioned.organization.slug}/activate?token={provisioned.development_invite_token}",
        },
        status=201,
    )


@require_http_methods(["PATCH"])
@api_login_required
def client_status(request, client_number: int, action: str):
    try:
        require_super_admin(request)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    client = Organization.objects.filter(client_number=client_number).first()
    if not client: return api_error("Client was not found.", status=404)
    try: payload = json_body(request)
    except ValueError: payload = {}
    if action == "suspend":
        if client.status == Organization.Status.SUSPENDED: return api_error("Client is already suspended.", status=409)
        client = suspend_client(client, request.user, str(payload.get("reason", "")).strip())
    elif action == "activate":
        if client.status == Organization.Status.ACTIVE: return api_error("Client is already active.", status=409)
        client = activate_client(client, request.user)
    else: return api_error("Unsupported client status action.", status=400)
    return JsonResponse({"client": serialize_client(client)})
