"""Account-status transitions for tenant users.

Deactivate/activate, suspend/reactivate, lock/unlock, and soft-delete/restore
each enforce the same two safeguards ordinary profile edits already enforce
(never remove an organization's last active administrator, never strip
clinical access from a therapist/assistant with an unresolved caseload) and
write an append-only audit event. Mirrors the client-status transition
functions in `care.client_management`.
"""
from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Appointment, ClinicalNote, Patient, User, UserLicense, UserSession
from .services import record_audit_event
from .session_management import revoke_all_sessions_for_user

CLINICAL_ACCESS_ROLES = {
    User.Role.ADMIN,
    User.Role.DIRECTOR,
    User.Role.THERAPIST,
    User.Role.ASSISTANT,
    User.Role.COMPLIANCE,
}
ASSIGNED_CLINICIAN_ROLES = {User.Role.THERAPIST, User.Role.ASSISTANT}


def _blocked_by_safety_guard(locked_account: User, organization, requested_role: str, requested_active: bool):
    """Return an (errors, status_code) pair if disabling this account would
    leave the organization without an active administrator, or would strip
    clinical access from a therapist/assistant with unresolved work — the
    same two guards `_apply_user_update` enforces for ordinary edits.
    """
    if locked_account.role == User.Role.ADMIN and locked_account.is_active:
        removes_admin = requested_role != User.Role.ADMIN or not requested_active
        active_admin_count = User.objects.filter(
            organization=organization, role=User.Role.ADMIN, is_active=True
        ).count()
        if removes_admin and active_admin_count <= 1:
            field = "role" if requested_role != User.Role.ADMIN else "status"
            return {field: "Assign another active organization administrator before removing this access."}, 409

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
            return {
                "status": "Reassign the active caseload and future visits, and resolve unsigned notes before removing clinical access."
            }, 409

    return None


def deactivate_user(account: User, actor: User, *, request=None):
    organization = account.organization
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=account.pk, organization=organization)
        if locked.status != User.Status.ACTIVE:
            return None, {"status": "Only an active account can be deactivated."}, 409
        blocked = _blocked_by_safety_guard(locked, organization, locked.role, False)
        if blocked:
            return None, *blocked
        old_status = locked.status
        locked.status = User.Status.INACTIVE
        locked.is_active = False
        locked.status_changed_at = timezone.now()
        locked.status_changed_by = actor
        locked.save(update_fields=["status", "is_active", "status_changed_at", "status_changed_by"])
        record_audit_event(
            actor=actor, action="USER_DEACTIVATED", obj=locked, request=request,
            metadata={"old_status": old_status, "new_status": locked.status},
        )
        revoke_all_sessions_for_user(locked, UserSession.RevokedReason.ACCOUNT_DEACTIVATED, actor=actor, request=request)
    return locked, None, 200


def activate_user(account: User, actor: User, *, request=None):
    organization = account.organization
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=account.pk, organization=organization)
        if locked.status != User.Status.INACTIVE:
            return None, {"status": "Only an inactive account can be activated."}, 409
        old_status = locked.status
        locked.status = User.Status.ACTIVE
        locked.is_active = True
        locked.status_changed_at = timezone.now()
        locked.status_changed_by = actor
        locked.save(update_fields=["status", "is_active", "status_changed_at", "status_changed_by"])
        record_audit_event(
            actor=actor, action="USER_ACTIVATED", obj=locked, request=request,
            metadata={"old_status": old_status, "new_status": locked.status},
        )
    return locked, None, 200


def suspend_user(account: User, actor: User, *, reason: str = "", request=None):
    organization = account.organization
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=account.pk, organization=organization)
        if locked.status != User.Status.ACTIVE:
            return None, {"status": "Only an active account can be suspended."}, 409
        blocked = _blocked_by_safety_guard(locked, organization, locked.role, False)
        if blocked:
            return None, *blocked
        old_status = locked.status
        locked.status = User.Status.SUSPENDED
        locked.is_active = False
        locked.suspended_at = timezone.now()
        locked.suspended_by = actor
        locked.suspension_reason = reason.strip()
        locked.status_changed_at = locked.suspended_at
        locked.status_changed_by = actor
        locked.save(update_fields=[
            "status", "is_active", "suspended_at", "suspended_by", "suspension_reason",
            "status_changed_at", "status_changed_by",
        ])
        record_audit_event(
            actor=actor, action="USER_SUSPENDED", obj=locked, request=request,
            metadata={"old_status": old_status, "new_status": locked.status, "reason": locked.suspension_reason},
        )
        revoke_all_sessions_for_user(locked, UserSession.RevokedReason.ACCOUNT_SUSPENDED, actor=actor, request=request)
    return locked, None, 200


def suspend_expired_license(candidate: User) -> User | None:
    """System-initiated suspension the moment an active PT/PTA's license has
    expired. Unlike `register_failed_login`/`heal_expired_lockout` (which only
    ever run once per single login request), this can also run from an
    admin-facing list view while an admin's own edit is in flight against the
    same row, so it takes the same row-lock-and-recheck approach as the other
    status transitions above rather than their lighter-weight pattern.

    Deliberately bypasses `_blocked_by_safety_guard` — an expired license is a
    legal/compliance issue that overrides caseload or last-active-admin
    discretion — but records what the guard would have flagged into the audit
    metadata so an admin sees the operational fallout immediately.
    """
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=candidate.pk)
        today = timezone.localdate()
        expired_licenses = list(locked.licenses.filter(expires_at__lt=today))
        if locked.status != User.Status.ACTIVE or locked.role not in ASSIGNED_CLINICIAN_ROLES or not expired_licenses:
            return None
        old_status = locked.status
        locked.status = User.Status.SUSPENDED
        locked.is_active = False
        locked.suspended_at = timezone.now()
        locked.suspended_by = None
        locked.suspension_reason = "Automatically suspended: PT/PTA license expired."
        locked.status_changed_at = locked.suspended_at
        locked.status_changed_by = None
        locked.save(update_fields=[
            "status", "is_active", "suspended_at", "suspended_by", "suspension_reason",
            "status_changed_at", "status_changed_by",
        ])
        active_caseload = Patient.objects.filter(
            assigned_therapist=locked, status=Patient.Status.ACTIVE
        ).count()
        future_visits = Appointment.objects.filter(
            therapist=locked,
            starts_at__gte=timezone.now(),
            status__in=[Appointment.Status.SCHEDULED, Appointment.Status.CHECKED_IN],
        ).count()
        unsigned_notes = ClinicalNote.objects.filter(therapist=locked).exclude(
            status=ClinicalNote.Status.SIGNED
        ).count()
        record_audit_event(
            actor=None, action="USER_LICENSE_EXPIRED", obj=locked, request=None,
            metadata={
                "old_status": old_status,
                "new_status": locked.status,
                "expired_licenses": [
                    {"id": str(license.pk), "issuing_state": license.issuing_state, "license_number": license.license_number,
                     "expires_at": license.expires_at.isoformat()}
                    for license in expired_licenses
                ],
                "active_caseload_count": active_caseload,
                "future_visit_count": future_visits,
                "unsigned_notes_count": unsigned_notes,
            },
        )
        revoke_all_sessions_for_user(locked, UserSession.RevokedReason.ACCOUNT_SUSPENDED)
    return locked


def sweep_expired_licenses(queryset) -> None:
    """Suspend every ACTIVE PT/PTA in `queryset` with at least one expired
    license. Callers should pass an unfiltered-by-status queryset (e.g. all
    of an organization's users) evaluated before any status-filtered/
    paginated queryset is built, so a request filtered to `?status=active`
    still sees — and sweeps — the row it's about to render.
    """
    today = timezone.localdate()
    stale = queryset.filter(
        status=User.Status.ACTIVE,
        role__in=ASSIGNED_CLINICIAN_ROLES,
        licenses__expires_at__lt=today,
    ).distinct()
    for candidate in stale:
        suspend_expired_license(candidate)


def reactivate_user(account: User, actor: User, *, request=None):
    organization = account.organization
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=account.pk, organization=organization)
        if locked.status != User.Status.SUSPENDED:
            return None, {"status": "Only a suspended account can be reactivated."}, 409
        if locked.role in ASSIGNED_CLINICIAN_ROLES:
            today = timezone.localdate()
            # Symmetric with suspend_expired_license's trigger (ANY expired
            # license suspends): reactivation requires every license to be
            # non-expired, not merely that one of several happens to be
            # verified and current — otherwise reactivating would immediately
            # flap back to suspended the next time the list view sweeps.
            has_expired_license = locked.licenses.filter(expires_at__lt=today).exists()
            has_current_verified_license = locked.licenses.filter(
                verification_status=UserLicense.VerificationStatus.VERIFIED, expires_at__gte=today
            ).exists()
            if has_expired_license or not has_current_verified_license:
                return None, {
                    "status": "Renew and verify every license for this provider — none can be expired — before reactivating."
                }, 409
        old_status = locked.status
        locked.status = User.Status.ACTIVE
        locked.is_active = True
        locked.suspended_at = None
        locked.suspended_by = None
        locked.suspension_reason = ""
        locked.status_changed_at = timezone.now()
        locked.status_changed_by = actor
        locked.save(update_fields=[
            "status", "is_active", "suspended_at", "suspended_by", "suspension_reason",
            "status_changed_at", "status_changed_by",
        ])
        record_audit_event(
            actor=actor, action="USER_REACTIVATED", obj=locked, request=request,
            metadata={"old_status": old_status, "new_status": locked.status},
        )
    return locked, None, 200


def unlock_user(account: User, actor: User, *, request=None):
    organization = account.organization
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=account.pk, organization=organization)
        if locked.status != User.Status.LOCKED_OUT:
            return None, {"status": "Only a locked account can be unlocked."}, 409
        old_status = locked.status
        locked.status = User.Status.ACTIVE
        locked.is_active = True
        locked.failed_login_attempts = 0
        locked.locked_at = None
        locked.locked_until = None
        locked.status_changed_at = timezone.now()
        locked.status_changed_by = actor
        locked.save(update_fields=[
            "status", "is_active", "failed_login_attempts", "locked_at", "locked_until",
            "status_changed_at", "status_changed_by",
        ])
        record_audit_event(
            actor=actor, action="USER_UNLOCKED", obj=locked, request=request,
            metadata={"old_status": old_status, "new_status": locked.status},
        )
    return locked, None, 200


def delete_user(account: User, actor: User, *, reason: str = "", request=None):
    organization = account.organization
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=account.pk, organization=organization)
        if locked.status == User.Status.DELETED:
            return None, {"status": "This account is already deleted."}, 409
        blocked = _blocked_by_safety_guard(locked, organization, locked.role, False)
        if blocked:
            return None, *blocked
        old_status = locked.status
        locked.status = User.Status.DELETED
        locked.is_active = False
        locked.archived_at = timezone.now()
        locked.archived_by = actor
        locked.status_changed_at = locked.archived_at
        locked.status_changed_by = actor
        locked.save(update_fields=[
            "status", "is_active", "archived_at", "archived_by", "status_changed_at", "status_changed_by",
        ])
        record_audit_event(
            actor=actor, action="USER_DELETED", obj=locked, request=request,
            metadata={"old_status": old_status, "new_status": locked.status, "reason": reason.strip()},
        )
        revoke_all_sessions_for_user(locked, UserSession.RevokedReason.ACCOUNT_DELETED, actor=actor, request=request)
    return locked, None, 200


def restore_user(account: User, actor: User, *, request=None):
    organization = account.organization
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=account.pk, organization=organization)
        if locked.status != User.Status.DELETED:
            return None, {"status": "Only a deleted account can be restored."}, 409
        old_status = locked.status
        locked.status = User.Status.ACTIVE
        locked.is_active = True
        locked.archived_at = None
        locked.archived_by = None
        locked.status_changed_at = timezone.now()
        locked.status_changed_by = actor
        locked.save(update_fields=[
            "status", "is_active", "archived_at", "archived_by", "status_changed_at", "status_changed_by",
        ])
        record_audit_event(
            actor=actor, action="USER_RESTORED", obj=locked, request=request,
            metadata={"old_status": old_status, "new_status": locked.status},
        )
    return locked, None, 200


_ACTIONS = {
    "deactivate": deactivate_user,
    "activate": activate_user,
    "suspend": suspend_user,
    "reactivate": reactivate_user,
    "unlock": unlock_user,
    "delete": delete_user,
    "restore": restore_user,
}


def apply_status_action(account: User, action: str, actor: User, *, reason: str = "", request=None):
    """Dispatch one of the named account-status actions, after the two
    self-service protections every action shares: nobody can change their own
    account status, and only a recognized action name is accepted.
    """
    if account.pk == actor.pk:
        return None, {"status": "You cannot change your own account status."}, 422
    handler = _ACTIONS.get(action)
    if handler is None:
        return None, {"action": "Choose a valid account action."}, 400
    if action in ("suspend", "delete"):
        return handler(account, actor, reason=reason, request=request)
    return handler(account, actor, request=request)


def register_failed_login(candidate: User) -> None:
    """Track a failed password attempt against an otherwise-active account,
    locking it out for `LOCKOUT_DURATION_MINUTES` once the threshold is hit.
    Not wrapped in its own transaction — the caller (login()) already treats
    this as a best-effort side effect of an unsuccessful login attempt.
    """
    candidate.failed_login_attempts += 1
    candidate.last_failed_login_at = timezone.now()
    update_fields = ["failed_login_attempts", "last_failed_login_at"]
    if candidate.failed_login_attempts >= settings.FAILED_LOGIN_LOCKOUT_THRESHOLD:
        candidate.status = User.Status.LOCKED_OUT
        candidate.is_active = False
        candidate.locked_at = timezone.now()
        candidate.locked_until = candidate.locked_at + timezone.timedelta(minutes=settings.LOCKOUT_DURATION_MINUTES)
        update_fields += ["status", "is_active", "locked_at", "locked_until"]
    candidate.save(update_fields=update_fields)
    if candidate.organization_id:
        # One event per attempt (not just the eventual lockout) — this is
        # the only source of truth for a failed-login trend; no PHI, no
        # password, just the fact and the running attempt count.
        record_audit_event(
            actor=None, action="LOGIN_FAILED", obj=candidate, request=None,
            metadata={"failed_login_attempts": candidate.failed_login_attempts},
        )
    if candidate.status == User.Status.LOCKED_OUT and candidate.organization_id:
        record_audit_event(
            actor=None, action="USER_LOCKED", obj=candidate, request=None,
            metadata={
                "old_status": User.Status.ACTIVE, "new_status": User.Status.LOCKED_OUT,
                "failed_login_attempts": candidate.failed_login_attempts,
            },
        )
        revoke_all_sessions_for_user(candidate, UserSession.RevokedReason.ACCOUNT_LOCKED)


def heal_expired_lockout(candidate: User) -> None:
    """Clear an expired lockout so the pending login attempt can proceed
    against a normal ACTIVE account, exactly as if an admin had unlocked it.
    """
    candidate.status = User.Status.ACTIVE
    candidate.is_active = True
    candidate.failed_login_attempts = 0
    candidate.locked_at = None
    candidate.locked_until = None
    candidate.status_changed_at = timezone.now()
    candidate.save(update_fields=[
        "status", "is_active", "failed_login_attempts", "locked_at", "locked_until", "status_changed_at",
    ])
