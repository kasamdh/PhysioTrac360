"""Super-admin-only client management API."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from ..access import require_platform_super_admin
from ..client_management import archive_client, activate_client, invitation_activation_url, issue_invitation, provision_client, serialize_client, suspend_client
from ..models import (
    Appointment,
    AuditEvent,
    ClientInvitation,
    ClinicalNote,
    Feature,
    Location,
    Organization,
    OrganizationSubscription,
    Patient,
    PrivilegedAccessGrant,
    SubscriptionPlan,
    User,
    UserLicense,
    UserSession,
)
from ..privileged_access import ALLOWED_DURATIONS_HOURS, active_grant, request_privileged_access, revoke_privileged_access
from ..services import outcome_trends, record_audit_event
from ..user_management import apply_status_action, sweep_expired_licenses
from ..session_management import revoke_all_sessions_for_user, serialize_session
from .serializers import (
    serialize_appointment,
    serialize_audit_event,
    serialize_feature,
    serialize_goal,
    serialize_note_summary,
    serialize_org_subscription,
    serialize_outcome_trend,
    serialize_patient,
    serialize_plan,
    serialize_user,
    serialize_user_license,
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


def _isoformat(value):
    return value.isoformat() if value else None


def _actor_name(user) -> str | None:
    return (user.get_full_name() or user.username) if user else None


def serialize_client_user(user: User) -> dict:
    effective_status = user.effective_status
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
        "credential": user.credential,
        "licenses": [serialize_user_license(license) for license in user.licenses.all()],
        "licenseAlertStatus": user.license_alert_status,
        "licenseDaysRemaining": user.license_days_remaining,
        "mustUseMfa": user.must_use_mfa,
        "archivedAt": _isoformat(user.archived_at),
        "clientNumber": user.organization.client_number if user.organization_id else None,
        "clientName": user.organization.name if user.organization_id else None,
        "status": effective_status,
        "statusLabel": User.Status(effective_status).label,
        "lastLogin": _isoformat(user.last_login),
        "failedLoginAttempts": user.failed_login_attempts,
        "lastFailedLoginAt": _isoformat(user.last_failed_login_at),
        "lockedAt": _isoformat(user.locked_at),
        "lockedUntil": _isoformat(user.locked_until),
        "suspendedAt": _isoformat(user.suspended_at),
        "suspendedBy": _actor_name(user.suspended_by),
        "suspensionReason": user.suspension_reason,
        "archivedBy": _actor_name(user.archived_by),
        "statusChangedAt": _isoformat(user.status_changed_at),
        "statusChangedBy": _actor_name(user.status_changed_by),
        "activeSessions": [
            serialize_session(session)
            for session in user.sessions.filter(revoked_at__isnull=True, expires_at__gt=timezone.now()).order_by("-created_at")
        ],
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
            if user.role in ASSIGNED_CLINICIAN_ROLES and _string_value(payload, "licenseNumber"):
                license = UserLicense(
                    user=user,
                    license_number=_string_value(payload, "licenseNumber"),
                    issuing_state=_string_value(payload, "licenseIssuingState"),
                    expires_at=_parse_license_date(payload.get("licenseExpiresAt")),
                )
                license.full_clean()
                license.save()
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
    if "username" in payload:
        username = _string_value(payload, "username")
        if not username:
            errors["username"] = "Username is required."
        elif User.objects.filter(username=username).exclude(pk=account.pk).exists():
            errors["username"] = "This username is already in use."
    new_password = payload.get("password", "")
    if isinstance(new_password, str):
        if new_password:
            try:
                validate_password(new_password, account)
            except ValidationError as exc:
                errors["password"] = " ".join(exc.messages)
    elif "password" in payload:
        errors["password"] = "Enter a valid password."
    requested_role = str(payload.get("role", account.role))
    if "role" in payload and requested_role not in TENANT_USER_ROLES:
        errors["role"] = "Choose a tenant-scoped user role."
    for key in ("isSuperuser", "isStaff"):
        if payload.get(key) is True:
            errors[key] = "Platform privileges cannot be assigned to a client user."
    if errors:
        return None, errors, 422

    requested_active = bool(payload.get("active", account.is_active))
    soft_delete = payload.get("archive") is True
    restore = payload.get("archive") is False and account.archived_at is not None
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
        if "username" in payload:
            locked_account.username = _string_value(payload, "username")
        password_changed = bool(new_password)
        if password_changed:
            locked_account.set_password(new_password)
            locked_account.must_change_password = True
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
            locked_account.status = User.Status.DELETED
        elif restore:
            locked_account.archived_at = None
            locked_account.archived_by = None
            locked_account.status = User.Status.ACTIVE
        elif "active" in payload and locked_account.status in (User.Status.ACTIVE, User.Status.INACTIVE):
            # Only sync the Active/Inactive axis here — a Suspended or Locked
            # Out account is governed exclusively by the dedicated status-action
            # endpoint (see `user_status_action`), never by this legacy field.
            locked_account.status = User.Status.ACTIVE if requested_active else User.Status.INACTIVE

        try:
            locked_account.full_clean()
        except ValidationError as exc:
            return None, {field: " ".join(messages) for field, messages in exc.message_dict.items()}, 422
        locked_account.save()

        if soft_delete:
            action = "client_user.archived"
        elif restore:
            action = "client_user.restored"
        elif previous_active and not locked_account.is_active:
            action = "client_user.deactivated"
        elif not previous_active and locked_account.is_active:
            action = "client_user.reactivated"
        elif previous_role != locked_account.role:
            action = "client_user.role_changed"
        elif previous_mfa_policy != locked_account.must_use_mfa:
            action = "client_user.mfa_policy_changed"
        elif password_changed:
            action = "client_user.password_reset"
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
        if password_changed:
            revoke_all_sessions_for_user(locked_account, UserSession.RevokedReason.PASSWORD_RESET, actor=actor, request=request)
    return locked_account, None, 200


def _string_value(payload: dict, key: str) -> str:
    value = payload.get(key, "")
    return value.strip() if isinstance(value, str) else ""


def _parse_license_date(value) -> date | None:
    """Parse an ISO date string from a payload, or None. Callers must validate
    the format first (see `validate_client_user_payload`) — this silently
    drops anything unparseable rather than raising, since by the time this
    runs on the create path validation has already rejected a bad format."""
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


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
    if role in ASSIGNED_CLINICIAN_ROLES:
        if not _string_value(payload, "licenseNumber"):
            errors["licenseNumber"] = "License number is required."
        if not _string_value(payload, "licenseIssuingState"):
            errors["licenseIssuingState"] = "Issuing state is required."
        expires_raw = _string_value(payload, "licenseExpiresAt")
        if not expires_raw:
            errors["licenseExpiresAt"] = "License expiration date is required."
        elif _parse_license_date(expires_raw) is None:
            errors["licenseExpiresAt"] = "Enter a valid date."
    elif _string_value(payload, "licenseExpiresAt") and _parse_license_date(payload.get("licenseExpiresAt")) is None:
        errors["licenseExpiresAt"] = "Enter a valid date."
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


def _serialize_global_audit_event(event) -> dict:
    """Same shape as serializers.serialize_audit_event, plus which client the
    event belongs to — needed here because this feed spans every tenant,
    unlike every other place that serializer is used (already inside one
    client's own scope)."""
    payload = serialize_audit_event(event)
    payload["clientNumber"] = event.organization.client_number if event.organization_id else None
    payload["clientName"] = event.organization.name if event.organization_id else None
    return payload


@require_GET
@api_login_required
def dashboard(request):
    """Platform-wide operational summary — organization/user/patient counts,
    credential expiration alerts, recent activity, and failed-login trend.
    Read-only; every number here is a real aggregate over existing rows, not
    a fabricated metric (matches admin_config.operational_report's own rule)."""
    try:
        require_super_admin(request)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)

    all_orgs = Organization.objects.all()
    live_orgs = all_orgs.filter(archived_at__isnull=True)
    organizations = {
        "total": all_orgs.count(),
        "active": live_orgs.filter(status=Organization.Status.ACTIVE).count(),
        "suspended": live_orgs.filter(status=Organization.Status.SUSPENDED).count(),
        "archived": all_orgs.filter(archived_at__isnull=False).count(),
    }

    locations_total = Location.objects.filter(organization__archived_at__isnull=True).count()

    tenant_users = User.objects.filter(organization__archived_at__isnull=True)
    users = {
        "total": tenant_users.count(),
        "activePts": tenant_users.filter(role=User.Role.THERAPIST, status=User.Status.ACTIVE).count(),
        "activePtas": tenant_users.filter(role=User.Role.ASSISTANT, status=User.Status.ACTIVE).count(),
    }

    patients_total = Patient.objects.filter(organization__archived_at__isnull=True).count()

    # Credential alerts: same computed alert_tier/color_bucket every per-user
    # license banner already uses (care/models.py UserLicense), just
    # aggregated across every tenant instead of one user.
    credential_alerts = {"expired": 0, "critical": 0, "expiring_soon": 0, "valid": 0}
    for license_row in UserLicense.objects.filter(user__organization__archived_at__isnull=True).only("expires_at"):
        credential_alerts[license_row.color_bucket] += 1

    subscription_tiers = {
        row["subscription_tier"]: row["count"]
        for row in live_orgs.values("subscription_tier").annotate(count=Count("id")).order_by()
    }

    recent_organizations = [
        {
            "clientNumber": org.client_number,
            "clientName": org.name,
            "status": org.status,
            "statusLabel": org.get_status_display(),
            "createdAt": org.created_at.isoformat(),
        }
        for org in live_orgs.order_by("-created_at")[:5]
    ]

    recent_audit_events = [
        _serialize_global_audit_event(event)
        for event in AuditEvent.objects.select_related("actor", "organization").order_by("-created_at")[:15]
    ]

    activity_actions = {"SESSION_CREATED", "NEW_DEVICE_LOGIN", "LOGIN_FAILED", "USER_LOCKED", "USER_UNLOCKED"}
    recent_user_activity = [
        _serialize_global_audit_event(event)
        for event in AuditEvent.objects.filter(action__in=activity_actions)
        .select_related("actor", "organization")
        .order_by("-created_at")[:15]
    ]

    since = timezone.now() - timedelta(days=7)
    trend_rows = (
        AuditEvent.objects.filter(action="LOGIN_FAILED", created_at__gte=since)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )
    failed_login_trend = [{"date": row["day"].isoformat(), "count": row["count"]} for row in trend_rows]

    return JsonResponse(
        {
            "organizations": organizations,
            "locationsTotal": locations_total,
            "users": users,
            "patientsTotal": patients_total,
            "credentialAlerts": credential_alerts,
            "subscriptionTiers": subscription_tiers,
            "recentOrganizations": recent_organizations,
            "recentAuditEvents": recent_audit_events,
            "recentUserActivity": recent_user_activity,
            "failedLoginTrend": failed_login_trend,
        }
    )


def _required_action_for(color_bucket: str) -> str:
    if color_bucket == "expired":
        return "Renew immediately — clinical access is suspended"
    if color_bucket == "critical":
        return "Renew immediately"
    if color_bucket == "expiring_soon":
        return "Schedule renewal"
    return "None"


@require_GET
@api_login_required
def credential_dashboard(request):
    """Cross-organization PT/PTA license expiration roster — the same
    alert_tier/color_bucket every per-user license banner already computes
    (care/models.py UserLicense), listed across every tenant instead of one
    user. Expired-license auto-suspension itself already happens in
    user_management.sweep_expired_licenses/suspend_expired_license; this is
    a read-only view onto that, not a second enforcement path."""
    try:
        require_super_admin(request)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)

    include_valid = request.GET.get("includeValid", "").strip().lower() == "true"
    bucket_filter = {b.strip() for b in request.GET.get("bucket", "").split(",") if b.strip()}
    query = request.GET.get("q", "").strip()
    client_number_raw = request.GET.get("clientNumber", "").strip()

    licenses = (
        UserLicense.objects.filter(user__organization__archived_at__isnull=True)
        .select_related("user", "user__organization")
        .prefetch_related("user__provider_profile__locations")
    )
    if client_number_raw:
        try:
            licenses = licenses.filter(user__organization__client_number=int(client_number_raw))
        except ValueError:
            return api_error("clientNumber must be a whole number.", status=400)
    if query:
        licenses = licenses.filter(
            Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(license_number__icontains=query)
            | Q(user__organization__name__icontains=query)
        )

    rows = []
    for license_row in licenses:
        color_bucket = license_row.color_bucket
        if not include_valid and color_bucket == "valid":
            continue
        if bucket_filter and color_bucket not in bucket_filter:
            continue
        provider = license_row.user.provider_profile.first()
        location_names = ", ".join(location.name for location in provider.locations.all()) if provider else ""
        rows.append(
            {
                "licenseId": str(license_row.pk),
                "providerId": str(license_row.user_id),
                "providerName": license_row.user.get_full_name() or license_row.user.username,
                "providerRole": license_row.user.role,
                "providerRoleLabel": license_row.user.get_role_display(),
                "clientNumber": license_row.user.organization.client_number,
                "clientName": license_row.user.organization.name,
                "location": location_names,
                "licenseType": license_row.license_type,
                "licenseNumber": license_row.license_number,
                "issuingState": license_row.issuing_state,
                "expiresAt": license_row.expires_at.isoformat(),
                "daysRemaining": license_row.days_remaining,
                "alertTier": license_row.alert_tier,
                "colorBucket": color_bucket,
                "requiredAction": _required_action_for(color_bucket),
                "accountStatus": license_row.user.status,
            }
        )

    rows.sort(key=lambda row: row["daysRemaining"])

    try:
        page_size = min(max(int(request.GET.get("pageSize", "50")), 10), 200)
        page = max(int(request.GET.get("page", "1")), 1)
    except ValueError:
        return api_error("Page and page size must be whole numbers.", status=400)
    total = len(rows)
    page_rows = rows[(page - 1) * page_size : page * page_size]

    return JsonResponse({"licenses": page_rows, "total": total, "page": page, "pageSize": page_size})


@require_GET
@api_login_required
def features(request):
    """The platform-wide feature catalog (see seed_subscription_catalog)."""
    try:
        require_super_admin(request)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    rows = Feature.objects.filter(is_active=True).order_by("name")
    return JsonResponse({"features": [serialize_feature(feature) for feature in rows]})


@require_GET
@api_login_required
def plans(request):
    """The platform-wide subscription plan catalog."""
    try:
        require_super_admin(request)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    rows = SubscriptionPlan.objects.filter(is_active=True).prefetch_related("features").order_by("monthly_price", "name")
    return JsonResponse({"plans": [serialize_plan(plan) for plan in rows]})


def _date_to_aware_datetime(value: date):
    return timezone.make_aware(datetime.combine(value, time.min))


@require_http_methods(["GET", "PATCH"])
@api_login_required
def client_subscription(request, client_number: int):
    """View or assign one organization's subscription (plan, status,
    billing cycle, dates, seat count) and its effective feature set.
    Creating/changing the plan resets the feature set to that plan's
    baseline unless the request also supplies an explicit `features` list —
    which is also how a super admin grants/revokes an individual feature
    without changing plans (the per-organization "feature flag" override
    the product brief asks for)."""
    try:
        require_super_admin(request)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    client = Organization.objects.filter(client_number=client_number).first()
    if not client:
        return api_error("Client was not found.", status=404)
    subscription = client.subscriptions.order_by("-starts_at").first()

    if request.method == "GET":
        return JsonResponse(
            {
                "subscription": serialize_org_subscription(subscription),
                "plans": [serialize_plan(plan) for plan in SubscriptionPlan.objects.filter(is_active=True).prefetch_related("features").order_by("monthly_price", "name")],
                "features": [serialize_feature(feature) for feature in Feature.objects.filter(is_active=True).order_by("name")],
            }
        )

    try:
        payload = json_body(request)
    except ValueError as exc:
        return api_error(str(exc), status=400)

    plan = None
    plan_code = payload.get("planCode")
    if plan_code:
        plan = SubscriptionPlan.objects.filter(code=plan_code, is_active=True).first()
        if not plan:
            return api_error("Choose a valid subscription plan.", status=422)

    creating = subscription is None
    if creating and not plan:
        return api_error("A plan is required to start a subscription.", status=422)

    changed_fields = []
    plan_changed = False
    with transaction.atomic():
        if creating:
            subscription = OrganizationSubscription(organization=client, plan=plan)
            changed_fields.append("plan")
            plan_changed = True
        elif plan and subscription.plan_id != plan.pk:
            subscription.plan = plan
            changed_fields.append("plan")
            plan_changed = True

        if "status" in payload:
            if payload["status"] not in OrganizationSubscription.Status.values:
                return api_error("Choose a valid subscription status.", status=422)
            subscription.status = payload["status"]
            changed_fields.append("status")

        if "billingCycle" in payload:
            if payload["billingCycle"] not in OrganizationSubscription.BillingCycle.values:
                return api_error("Choose a valid billing cycle.", status=422)
            subscription.billing_cycle = payload["billingCycle"]
            changed_fields.append("billing_cycle")

        if "providerSeatCount" in payload:
            try:
                seat_count = int(payload["providerSeatCount"])
            except (TypeError, ValueError):
                return api_error("Seat count must be a whole number.", status=422)
            if seat_count < 1:
                return api_error("Seat count must be at least 1.", status=422)
            subscription.provider_seat_count = seat_count
            changed_fields.append("provider_seat_count")

        if payload.get("startsAt"):
            parsed = _parse_license_date(payload["startsAt"])
            if parsed is None:
                return api_error("Enter a valid start date.", status=422)
            subscription.starts_at = _date_to_aware_datetime(parsed)
            changed_fields.append("starts_at")

        if "endsAt" in payload:
            if payload["endsAt"]:
                parsed = _parse_license_date(payload["endsAt"])
                if parsed is None:
                    return api_error("Enter a valid end date.", status=422)
                subscription.ends_at = _date_to_aware_datetime(parsed)
            else:
                subscription.ends_at = None
            changed_fields.append("ends_at")

        subscription.full_clean()
        subscription.save()

        explicit_features = payload.get("features")
        if explicit_features is not None:
            if not isinstance(explicit_features, list):
                return api_error("Features must be a list of feature codes.", status=422)
            subscription.features.set(Feature.objects.filter(code__in=explicit_features, is_active=True))
            changed_fields.append("features")
        elif plan_changed:
            subscription.features.set(plan.features.all())
            changed_fields.append("features")

    record_audit_event(
        actor=request.user,
        action="client_subscription.created" if creating else "client_subscription.updated",
        obj=subscription,
        request=request,
        metadata={"client_number": client.client_number, "changed_fields": changed_fields},
    )
    return JsonResponse({"subscription": serialize_org_subscription(subscription)})


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

    sweep_expired_licenses(User.objects.filter(organization__isnull=False))
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
    if status and status in User.Status.values:
        users = users.filter(status=status)
        include_archived = include_archived or status == User.Status.DELETED
    elif status == "archived":
        users = users.filter(status=User.Status.DELETED)
        include_archived = True
    if not include_archived:
        users = users.exclude(status=User.Status.DELETED)
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


@require_POST
@api_login_required
def user_status_action(request, user_id):
    """Super-admin account-status actions: deactivate/activate, suspend/reactivate,
    unlock, delete/restore — one confirmed action at a time, each fully audited.
    """
    try:
        require_super_admin(request)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    account = User.objects.filter(pk=user_id, organization__isnull=False).select_related("organization").first()
    if not account:
        return api_error("User was not found.", status=404)
    try:
        payload = json_body(request)
    except ValueError as exc:
        return api_error(str(exc), status=400)
    action = str(payload.get("action", "")).strip()
    reason = str(payload.get("reason", "") or "")
    updated, errors, status_code = apply_status_action(account, action, request.user, reason=reason, request=request)
    if errors:
        return JsonResponse({"detail": "Please correct the highlighted fields.", "errors": errors}, status=status_code)
    return JsonResponse({"user": serialize_client_user(updated)})


@require_POST
@api_login_required
def user_revoke_sessions(request, user_id):
    """Super-admin 'Sign Out User From All Devices' — signs the target user
    out of every active browser/device immediately, fully audited.
    """
    try:
        require_super_admin(request)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    account = User.objects.filter(pk=user_id, organization__isnull=False).first()
    if not account:
        return api_error("User was not found.", status=404)
    count = revoke_all_sessions_for_user(account, UserSession.RevokedReason.ADMIN_REVOKED, actor=request.user, request=request)
    return JsonResponse({"user": serialize_client_user(account), "revokedCount": count})


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
    sweep_expired_licenses(client.users.all())
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
    administrator = client.users.filter(role=User.Role.ADMIN).order_by("date_joined").first()
    if not administrator:
        return api_error("This client has no administrator account.", status=409)
    token = issue_invitation(client, administrator)
    return JsonResponse({
        "detail": "A new invitation was generated and emailed to the administrator.",
        "email": administrator.email,
        "invitationUrl": invitation_activation_url(client, token),
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
            "invitationUrl": invitation_activation_url(provisioned.organization, provisioned.development_invite_token),
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
