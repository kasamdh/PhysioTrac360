"""Mobile Care configuration — Administration.

Two tiers, mirroring how organization_has_feature() already layers a
subscription entitlement under an organization's own opt-in:
  - MobileCarePlatformDefaults: one global row, Super Admin only — the
    starting point every organization inherits until it configures
    otherwise.
  - MobileCareConfiguration: one row per Organization, Organization Admin
    only for their own tenant — a null/blank field here falls back to the
    matching platform default, never a fabricated value.

Service Areas (ServiceArea) and Self-Pay Pricing/the Travel Fee
(ServicePrice) already have dedicated storage from earlier Mobile Care
work and are NOT duplicated here — the effective_*() readers below are the
single place every other Mobile Care function should read a configured
value from, rather than each reaching into MobileCareConfiguration
directly (so a future new setting only has to change one place)."""
from __future__ import annotations

from .entitlements import organization_has_feature
from .models import MobileCareConfiguration, MobileCarePlatformDefaults
from .services import record_audit_event, record_platform_audit_event


def get_platform_defaults() -> MobileCarePlatformDefaults:
    defaults = MobileCarePlatformDefaults.objects.first()
    if defaults is None:
        defaults = MobileCarePlatformDefaults.objects.create()
    return defaults


def get_configuration(organization) -> MobileCareConfiguration:
    config, _ = MobileCareConfiguration.objects.get_or_create(organization=organization)
    return config


def is_mobile_care_enabled(organization) -> bool:
    """Both gates must pass: the "mobile_care" subscription entitlement AND
    this organization's own opt-in switch — the same two-gate posture
    BookingConfiguration.online_booking_enabled already has relative to
    whatever plan grants a booking feature."""
    if not organization_has_feature(organization, "mobile_care"):
        return False
    return get_configuration(organization).mobile_care_enabled


def effective_default_visit_duration_minutes(organization) -> int:
    value = get_configuration(organization).default_visit_duration_minutes
    return value if value is not None else get_platform_defaults().default_visit_duration_minutes


def effective_offer_expiration_hours(organization) -> float:
    value = get_configuration(organization).offer_expiration_hours
    return value if value is not None else get_platform_defaults().offer_expiration_hours


def effective_patient_cancellation_window_hours(organization) -> int:
    value = get_configuration(organization).patient_cancellation_window_hours
    return value if value is not None else get_platform_defaults().patient_cancellation_window_hours


def effective_provider_cancellation_notice_hours(organization) -> int:
    value = get_configuration(organization).provider_cancellation_notice_hours
    return value if value is not None else get_platform_defaults().provider_cancellation_notice_hours


def effective_max_travel_radius_miles(organization) -> int:
    value = get_configuration(organization).max_travel_radius_miles
    return value if value is not None else get_platform_defaults().max_travel_radius_miles


def effective_continuity_preferred(organization) -> bool:
    value = get_configuration(organization).same_provider_continuity_preferred
    return value if value is not None else get_platform_defaults().same_provider_continuity_preferred


def effective_match_weights(organization) -> dict[str, float]:
    from .mobile_care import DEFAULT_MATCH_WEIGHTS  # local import — see MobileCareConfiguration.clean()

    weights = dict(DEFAULT_MATCH_WEIGHTS)
    weights.update(get_configuration(organization).match_weight_overrides or {})
    if not effective_continuity_preferred(organization):
        weights["continuity"] = 0.0
    return weights


def effective_service_hours(organization):
    """(start, end) TimeField values, either of which may be None (no
    restriction on that end)."""
    config = get_configuration(organization)
    return config.service_hours_start, config.service_hours_end


def is_notification_event_enabled(organization, event_code: str) -> bool:
    return event_code not in (get_configuration(organization).disabled_notification_events or [])


def is_requested_service_available(organization, requested_service: str) -> bool:
    allowed = get_configuration(organization).available_services or []
    return not allowed or requested_service in allowed


def is_provider_role_allowed(organization, role: str) -> bool:
    allowed = get_configuration(organization).allowed_provider_roles or []
    return not allowed or role in allowed


CONFIGURATION_FIELDS = (
    "mobile_care_enabled",
    "default_visit_duration_minutes",
    "available_services",
    "allowed_provider_roles",
    "max_travel_radius_miles",
    "offer_expiration_hours",
    "patient_cancellation_window_hours",
    "provider_cancellation_notice_hours",
    "provider_cancellation_requires_reason",
    "same_provider_continuity_preferred",
    "match_weight_overrides",
    "service_hours_start",
    "service_hours_end",
    "disabled_notification_events",
)


def _json_safe(value):
    """AuditEvent.metadata is a plain JSONField (no DjangoJSONEncoder), so
    a raw datetime.time (service_hours_start/_end) isn't serializable —
    stringify anything that isn't already a JSON-native type."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, dict)):
        return value
    return str(value)


def update_configuration(organization, changes: dict, *, actor, django_request=None) -> MobileCareConfiguration:
    """Organization Admin's own tenant-scoped update. Trusts its caller
    (care/api/mobile_care_settings.py) already enforced "only your own
    tenant, only an Organization Admin" — the same division of labor as
    everywhere else in this codebase (HTTP/auth in the view, the rule
    itself here)."""
    config = get_configuration(organization)
    changed: dict[str, dict] = {}
    for field in CONFIGURATION_FIELDS:
        if field not in changes:
            continue
        old_value = getattr(config, field)
        new_value = changes[field]
        if old_value != new_value:
            changed[field] = {"old": _json_safe(old_value), "new": _json_safe(new_value)}
        setattr(config, field, new_value)
    if not changed:
        return config
    config.updated_by = actor
    config.full_clean()
    config.save()
    record_audit_event(
        actor=actor, action="mobile_care_configuration.updated", obj=config,
        request=django_request, metadata={"changed": changed},
    )
    return config


PLATFORM_DEFAULT_FIELDS = (
    "default_visit_duration_minutes",
    "offer_expiration_hours",
    "patient_cancellation_window_hours",
    "provider_cancellation_notice_hours",
    "max_travel_radius_miles",
    "same_provider_continuity_preferred",
)


def update_platform_defaults(changes: dict, *, actor, django_request=None) -> MobileCarePlatformDefaults:
    """Super Admin only — see care/api/super_admin.py's role gate. Audited
    via record_platform_audit_event() since this has no single owning
    tenant (see that function's docstring)."""
    defaults = get_platform_defaults()
    changed: dict[str, dict] = {}
    for field in PLATFORM_DEFAULT_FIELDS:
        if field not in changes:
            continue
        old_value = getattr(defaults, field)
        new_value = changes[field]
        if old_value != new_value:
            changed[field] = {"old": _json_safe(old_value), "new": _json_safe(new_value)}
        setattr(defaults, field, new_value)
    if not changed:
        return defaults
    defaults.updated_by = actor
    defaults.full_clean()
    defaults.save()
    record_platform_audit_event(
        actor=actor, action="mobile_care_platform_defaults.updated", obj=defaults,
        request=django_request, metadata={"changed": changed},
    )
    return defaults
