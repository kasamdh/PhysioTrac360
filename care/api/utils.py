"""Small JSON API helpers that preserve Django's session and CSRF controls."""
from __future__ import annotations

import json
from functools import wraps

from django.contrib.auth import logout as auth_logout
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.utils import timezone

from ..access import organization_required, require_role
from ..models import UserSession
from ..session_management import SESSION_MESSAGES, validate_session


class InvalidJSON(ValueError):
    """Raised when an API request body is not a JSON object."""


def api_error(detail: str, *, status: int) -> JsonResponse:
    return JsonResponse({"detail": detail}, status=status)


def api_validation_error(errors, *, detail: str = "Please correct the highlighted fields.") -> JsonResponse:
    """Return validation failures without reflecting a request body into logs."""
    return JsonResponse({"detail": detail, "errors": errors}, status=422)


PASSWORD_CHANGE_EXEMPT_PATHS = ("/auth/logout/", "/auth/change-password/", "/auth/me/")
SESSION_CHECK_EXEMPT_PATHS = ("/auth/logout/",)


def api_login_required(view):
    """Return JSON 401 responses instead of redirecting a SPA to an HTML page.

    Deactivating, suspending, locking, or deleting a user, or changing their
    password, takes effect on their very next request even with an existing
    session: Django's own auth backend already re-checks `is_active` and the
    session auth hash on every request, resolving `request.user` to
    `AnonymousUser` before this decorator's own session-revocation check ever
    runs. When that happens, recover the specific reason from our own
    session-tracking table (if this session was one we ever tracked) so the
    frontend can still show why, instead of a bare "not authenticated".
    """

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        # Captured before the first touch of `request.user`: Django's own
        # `get_user()` calls `request.session.flush()` — replacing the
        # session key with a brand-new one — the instant it notices the
        # password hash no longer matches, and that resolution happens
        # lazily on first access. Reading the key any later would see the
        # post-flush key, which was never in our tracking table.
        pre_auth_session_key = request.session.session_key
        if not request.user.is_authenticated:
            tracked = (
                UserSession.objects.filter(django_session_key=pre_auth_session_key, revoked_at__isnull=False).first()
                if pre_auth_session_key else None
            )
            if tracked:
                message = SESSION_MESSAGES.get(tracked.revoked_reason, "Your session has ended. Please sign in again.")
                return JsonResponse({"detail": message, "code": str(tracked.revoked_reason).upper()}, status=401)
            return api_error("Authentication is required.", status=401)
        if not request.path.endswith(SESSION_CHECK_EXEMPT_PATHS):
            _tracked_session, invalid_reason = validate_session(request)
            if invalid_reason:
                auth_logout(request)
                message = SESSION_MESSAGES.get(invalid_reason, "Your session has ended. Please sign in again.")
                return JsonResponse({"detail": message, "code": str(invalid_reason).upper()}, status=401)
        if request.user.must_change_password and not request.path.endswith(PASSWORD_CHANGE_EXEMPT_PATHS):
            return api_error("You must set a new password before continuing.", status=403)
        if not request.user.is_platform_super_admin and request.user.organization_id:
            organization = request.user.organization
            if organization.archived_at is not None:
                return JsonResponse({"timestamp": timezone.now().isoformat(), "status": 403, "code": "ORGANIZATION_ARCHIVED", "message": "Your organization account has been archived. Please contact your administrator."}, status=403)
            if not organization.is_active or organization.status == organization.Status.SUSPENDED:
                return JsonResponse({"timestamp": timezone.now().isoformat(), "status": 403, "code": "ORGANIZATION_SUSPENDED", "message": "Your organization account is currently suspended. Please contact your administrator."}, status=403)
        return view(request, *args, **kwargs)

    return wrapped


def json_body(request) -> dict:
    """Read a JSON object without logging request data or accepting arrays."""
    try:
        payload = json.loads(request.body.decode("utf-8")) if request.body else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidJSON("Request body must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise InvalidJSON("Request body must be a JSON object.")
    return payload


def organization_or_error(request, *, roles: set[str] | None = None):
    """Apply the same tenant and role boundary used by HTML views."""
    try:
        if roles is not None:
            require_role(request.user, roles)
        return organization_required(request.user), None
    except PermissionDenied as exc:
        return None, api_error(str(exc), status=403)
