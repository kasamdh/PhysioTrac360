"""Mobile Care configuration — Administration, Organization Admin only, own
tenant only. Reuses this app's existing Administration surface
(ClinicSettingsPage's tabbed settings UI) rather than a new one; see
care/mobile_care_settings.py for the underlying settings model and the
effective_*() readers every other Mobile Care function consults.

Service Areas and Self-Pay Pricing/the Travel Fee are configured through
their own, already-existing endpoints (ServiceArea / ServicePrice — see
care/api/mobile_care.py and care/api/billing.py) — this module only covers
the settings that had no home yet."""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.utils.dateparse import parse_time
from django.views.decorators.http import require_http_methods

from ..models import User
from ..mobile_care_settings import CONFIGURATION_FIELDS, get_configuration, update_configuration
from .utils import InvalidJSON, api_error, api_validation_error, api_login_required, json_body, organization_or_error


def serialize_mobile_care_configuration(config) -> dict:
    return {
        "mobileCareEnabled": config.mobile_care_enabled,
        "defaultVisitDurationMinutes": config.default_visit_duration_minutes,
        "availableServices": config.available_services,
        "allowedProviderRoles": config.allowed_provider_roles,
        "maxTravelRadiusMiles": config.max_travel_radius_miles,
        "offerExpirationHours": config.offer_expiration_hours,
        "patientCancellationWindowHours": config.patient_cancellation_window_hours,
        "providerCancellationNoticeHours": config.provider_cancellation_notice_hours,
        "providerCancellationRequiresReason": config.provider_cancellation_requires_reason,
        "sameProviderContinuityPreferred": config.same_provider_continuity_preferred,
        "matchWeightOverrides": config.match_weight_overrides,
        "serviceHoursStart": config.service_hours_start.strftime("%H:%M") if config.service_hours_start else None,
        "serviceHoursEnd": config.service_hours_end.strftime("%H:%M") if config.service_hours_end else None,
        "disabledNotificationEvents": config.disabled_notification_events,
        "updatedAt": config.updated_at.isoformat(),
    }


_FIELD_FROM_PAYLOAD_KEY = {
    "mobileCareEnabled": "mobile_care_enabled",
    "defaultVisitDurationMinutes": "default_visit_duration_minutes",
    "availableServices": "available_services",
    "allowedProviderRoles": "allowed_provider_roles",
    "maxTravelRadiusMiles": "max_travel_radius_miles",
    "offerExpirationHours": "offer_expiration_hours",
    "patientCancellationWindowHours": "patient_cancellation_window_hours",
    "providerCancellationNoticeHours": "provider_cancellation_notice_hours",
    "providerCancellationRequiresReason": "provider_cancellation_requires_reason",
    "sameProviderContinuityPreferred": "same_provider_continuity_preferred",
    "matchWeightOverrides": "match_weight_overrides",
    "serviceHoursStart": "service_hours_start",
    "serviceHoursEnd": "service_hours_end",
    "disabledNotificationEvents": "disabled_notification_events",
}
assert set(_FIELD_FROM_PAYLOAD_KEY.values()) == set(CONFIGURATION_FIELDS)


def _parse_changes(payload: dict) -> tuple[dict, dict[str, str]]:
    changes: dict = {}
    errors: dict[str, str] = {}
    for payload_key, field_name in _FIELD_FROM_PAYLOAD_KEY.items():
        if payload_key not in payload:
            continue
        value = payload[payload_key]
        if field_name in ("service_hours_start", "service_hours_end"):
            if value in (None, ""):
                changes[field_name] = None
                continue
            parsed = parse_time(str(value))
            if parsed is None:
                errors[payload_key] = "Enter a time as HH:MM."
                continue
            changes[field_name] = parsed
            continue
        changes[field_name] = value
    return changes, errors


@require_http_methods(["GET", "PATCH"])
@api_login_required
def mobile_care_configuration(request):
    """Organization Admin's own tenant-scoped Mobile Care settings — every
    field in care/models.py's MobileCareConfiguration except Service Areas/
    Self-Pay Pricing/Travel Fee, which stay on their own existing
    endpoints. GET is read-only for any Organization Admin; PATCH applies
    changes and audits them (see update_configuration())."""
    organization, error = organization_or_error(request, roles={User.Role.ADMIN})
    if error:
        return error
    if request.method == "GET":
        return JsonResponse({"configuration": serialize_mobile_care_configuration(get_configuration(organization))})

    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)
    changes, errors = _parse_changes(payload)
    if errors:
        return api_validation_error(errors)
    if "available_services" in changes and not isinstance(changes["available_services"], list):
        return api_validation_error({"availableServices": "Enter a list of requested-service values."})
    if "allowed_provider_roles" in changes and not isinstance(changes["allowed_provider_roles"], list):
        return api_validation_error({"allowedProviderRoles": "Enter a list of role values."})
    if "match_weight_overrides" in changes and not isinstance(changes["match_weight_overrides"], dict):
        return api_validation_error({"matchWeightOverrides": "Enter an object of dimension -> weight."})
    if "disabled_notification_events" in changes and not isinstance(changes["disabled_notification_events"], list):
        return api_validation_error({"disabledNotificationEvents": "Enter a list of event codes."})
    try:
        config = update_configuration(organization, changes, actor=request.user, django_request=request)
    except ValidationError as exc:
        return api_validation_error({field: " ".join(messages) for field, messages in exc.message_dict.items()})
    return JsonResponse({"configuration": serialize_mobile_care_configuration(config)})
