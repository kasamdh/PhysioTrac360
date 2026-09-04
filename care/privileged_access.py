"""Break-glass workflow: time-boxed, reasoned, audited clinical access for
platform super administrators. Super admins have no standing clinical access
(see access.organization_required); this module is the only path in, and it
never bypasses the audit trail.
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from .models import Organization, PrivilegedAccessGrant, User
from .services import record_audit_event


ALLOWED_DURATIONS_HOURS = (1, 4, 24)


def active_grant(organization: Organization, actor: User) -> PrivilegedAccessGrant | None:
    return (
        PrivilegedAccessGrant.objects.filter(
            organization=organization,
            actor=actor,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .order_by("-created_at")
        .first()
    )


def request_privileged_access(
    organization: Organization, actor: User, reason: str, duration_hours: int
) -> PrivilegedAccessGrant:
    if duration_hours not in ALLOWED_DURATIONS_HOURS:
        raise ValueError("Choose a supported access duration.")
    reason = reason.strip()
    if not reason:
        raise ValueError("A reason is required to request privileged clinical access.")
    grant = PrivilegedAccessGrant.objects.create(
        organization=organization,
        actor=actor,
        reason=reason,
        expires_at=timezone.now() + timedelta(hours=duration_hours),
    )
    record_audit_event(
        actor=actor,
        action="privileged_access.requested",
        obj=grant,
        request=None,
        metadata={
            "client_number": organization.client_number,
            "reason": reason,
            "duration_hours": duration_hours,
            "expires_at": grant.expires_at.isoformat(),
        },
    )
    return grant


def revoke_privileged_access(grant: PrivilegedAccessGrant, actor: User) -> PrivilegedAccessGrant:
    grant.revoked_at = timezone.now()
    grant.revoked_by = actor
    grant.save(update_fields=["revoked_at", "revoked_by"])
    record_audit_event(
        actor=actor,
        action="privileged_access.revoked",
        obj=grant,
        request=None,
        metadata={"client_number": grant.organization.client_number},
    )
    return grant
