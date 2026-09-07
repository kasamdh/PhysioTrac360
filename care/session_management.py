"""Per-device login-session tracking: creation, per-role concurrency limits,
revocation, and validation. Built alongside Django's own session framework
(never replacing it) — a `UserSession` row is a record *about* a Django
session, keyed by its session key, that lets an already-issued session be
revoked, listed, and capped per user without touching cookies directly.

Sessions created before this feature existed (or created directly via
`Client.force_login()` in tests, which bypasses `care.api.views.login`) have
no matching `UserSession` row. `validate_session()` treats that as valid —
untracked sessions are neither enforced nor limited — so this is additive:
only logins that go through the real `login()` view are covered.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import User, UserSession
from .services import record_audit_event

SESSION_MESSAGES = {
    UserSession.RevokedReason.NEW_LOGIN: "Your session has ended because your account was signed in from another browser or device.",
    UserSession.RevokedReason.USER_LOGOUT: "You have been signed out.",
    UserSession.RevokedReason.IDLE_TIMEOUT: "Your session expired due to inactivity. Please sign in again.",
    UserSession.RevokedReason.ABSOLUTE_TIMEOUT: "Your session expired. Please sign in again.",
    UserSession.RevokedReason.PASSWORD_CHANGED: "Your session has ended because your password or security credentials were changed.",
    UserSession.RevokedReason.PASSWORD_RESET: "Your session has ended because your password or security credentials were changed.",
    UserSession.RevokedReason.ACCOUNT_LOCKED: "Your session has ended because your account was locked.",
    UserSession.RevokedReason.ACCOUNT_SUSPENDED: "Your session has ended because your account was suspended.",
    UserSession.RevokedReason.ACCOUNT_DEACTIVATED: "Your session has ended because your account was deactivated.",
    UserSession.RevokedReason.ACCOUNT_DELETED: "Your session has ended because your account was deleted.",
    UserSession.RevokedReason.ADMIN_REVOKED: "Your session has ended because an administrator signed you out.",
}


def _client_ip(request) -> str | None:
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _parse_user_agent(user_agent: str) -> tuple[str, str]:
    ua = user_agent.lower()
    if "edg/" in ua or "edge" in ua:
        browser = "Edge"
    elif "chrome" in ua and "chromium" not in ua:
        browser = "Chrome"
    elif "firefox" in ua:
        browser = "Firefox"
    elif "safari" in ua and "chrome" not in ua:
        browser = "Safari"
    elif ua:
        browser = "Other browser"
    else:
        browser = ""
    if "iphone" in ua:
        device = "iPhone"
    elif "ipad" in ua:
        device = "iPad"
    elif "android" in ua:
        device = "Android"
    elif "windows" in ua:
        device = "Windows"
    elif "mac os" in ua or "macintosh" in ua:
        device = "Mac"
    elif "linux" in ua:
        device = "Linux"
    else:
        device = ""
    return device, browser


def session_limit_for(user: User) -> int:
    return settings.SESSION_LIMITS_BY_ROLE.get(user.role, settings.DEFAULT_SESSION_LIMIT)


def create_session(user: User, request) -> UserSession:
    """Record the session Django just created for `user`, then enforce the
    role's concurrency limit by revoking the oldest sessions over it.
    """
    session_key = request.session.session_key
    user_agent = request.META.get("HTTP_USER_AGENT", "")[:400]
    device_name, browser_name = _parse_user_agent(user_agent)
    now = timezone.now()
    is_new_device = (
        user_agent
        and not UserSession.objects.filter(user=user, user_agent=user_agent).exists()
    )
    tracked = UserSession.objects.create(
        user=user,
        organization=user.organization,
        django_session_key=session_key,
        last_activity_at=now,
        expires_at=now + timedelta(hours=settings.ABSOLUTE_SESSION_HOURS),
        ip_address=_client_ip(request),
        user_agent=user_agent,
        device_name=device_name,
        browser_name=browser_name,
    )
    if user.organization_id:
        # Audit events are always organization-scoped; the platform Super
        # Admin has no organization, so there is nowhere to log this for them.
        record_audit_event(
            actor=user, action="SESSION_CREATED", obj=tracked, request=request,
            metadata={"device_name": device_name, "browser_name": browser_name},
        )
        if is_new_device:
            record_audit_event(
                actor=user, action="NEW_DEVICE_LOGIN", obj=tracked, request=request,
                metadata={"device_name": device_name, "browser_name": browser_name},
            )
    _enforce_session_limit(user, keep=tracked, request=request)
    return tracked


def _enforce_session_limit(user: User, *, keep: UserSession, request=None) -> None:
    limit = session_limit_for(user)
    active = list(
        UserSession.objects.filter(user=user, revoked_at__isnull=True, expires_at__gt=timezone.now())
        .order_by("-created_at")
    )
    if len(active) <= limit:
        return
    if user.organization_id:
        record_audit_event(
            actor=user, action="CONCURRENT_SESSION_LIMIT_REACHED", obj=keep, request=request,
            metadata={"limit": limit, "active_count": len(active)},
        )
    for stale in active[limit:]:
        revoke_session(stale, UserSession.RevokedReason.NEW_LOGIN, actor=user, request=request)


def revoke_session(session: UserSession, reason: str, *, actor: User | None = None, request=None) -> None:
    if session.revoked_at is not None:
        return
    session.revoked_at = timezone.now()
    session.revoked_reason = reason
    session.save(update_fields=["revoked_at", "revoked_reason"])
    action = "SESSION_REVOKED_NEW_LOGIN" if reason == UserSession.RevokedReason.NEW_LOGIN else "SESSION_REVOKED"
    if session.organization_id or (actor and actor.organization_id):
        record_audit_event(
            actor=actor, action=action, obj=session, request=request,
            metadata={"reason": reason, "session_user_id": str(session.user_id)},
        )


def revoke_all_sessions_for_user(
    user: User, reason: str, *, actor: User | None = None, request=None, except_session_key: str | None = None
) -> int:
    """Revoke every currently-active session for `user`, optionally sparing
    one (e.g. the session performing a self-service password change).
    Returns the number of sessions revoked.
    """
    queryset = UserSession.objects.filter(user=user, revoked_at__isnull=True)
    if except_session_key:
        queryset = queryset.exclude(django_session_key=except_session_key)
    count = 0
    for session in queryset:
        revoke_session(session, reason, actor=actor, request=request)
        count += 1
    return count


def touch_session(session: UserSession) -> None:
    """Bump last-activity, throttled to avoid a DB write on every request."""
    now = timezone.now()
    if (now - session.last_activity_at) < timedelta(minutes=1):
        return
    session.last_activity_at = now
    session.save(update_fields=["last_activity_at"])


def validate_session(request) -> tuple[UserSession | None, str | None]:
    """Return (tracked_session_or_None, invalid_reason_or_None).

    `invalid_reason` is one of `UserSession.RevokedReason` values when the
    request should be rejected; `None` means the session is fine to use
    (including the "untracked, pre-existing session" fail-open case).
    """
    session_key = request.session.session_key
    if not session_key:
        return None, None
    tracked = UserSession.objects.filter(django_session_key=session_key).first()
    if tracked is None:
        return None, None
    if tracked.revoked_at is not None:
        return tracked, tracked.revoked_reason or UserSession.RevokedReason.ADMIN_REVOKED
    now = timezone.now()
    if tracked.expires_at <= now:
        revoke_session(tracked, UserSession.RevokedReason.ABSOLUTE_TIMEOUT)
        return tracked, UserSession.RevokedReason.ABSOLUTE_TIMEOUT
    idle_cutoff = tracked.last_activity_at + timedelta(minutes=settings.IDLE_TIMEOUT_MINUTES)
    if idle_cutoff <= now:
        revoke_session(tracked, UserSession.RevokedReason.IDLE_TIMEOUT)
        return tracked, UserSession.RevokedReason.IDLE_TIMEOUT
    touch_session(tracked)
    return tracked, None


def serialize_session(session: UserSession, *, current_session_key: str | None = None) -> dict:
    return {
        "id": str(session.pk),
        "deviceName": session.device_name or "Unknown device",
        "browserName": session.browser_name or "Unknown browser",
        "ipAddress": session.ip_address,
        "createdAt": session.created_at.isoformat(),
        "lastActivityAt": session.last_activity_at.isoformat(),
        "isCurrent": bool(current_session_key) and session.django_session_key == current_session_key,
    }
