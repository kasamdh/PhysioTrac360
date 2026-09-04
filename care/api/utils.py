"""Small JSON API helpers that preserve Django's session and CSRF controls."""
from __future__ import annotations

import json
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.utils import timezone

from ..access import organization_required, require_role


class InvalidJSON(ValueError):
    """Raised when an API request body is not a JSON object."""


def api_error(detail: str, *, status: int) -> JsonResponse:
    return JsonResponse({"detail": detail}, status=status)


def api_validation_error(errors, *, detail: str = "Please correct the highlighted fields.") -> JsonResponse:
    """Return validation failures without reflecting a request body into logs."""
    return JsonResponse({"detail": detail, "errors": errors}, status=422)


def api_login_required(view):
    """Return JSON 401 responses instead of redirecting a SPA to an HTML page."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return api_error("Authentication is required.", status=401)
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
