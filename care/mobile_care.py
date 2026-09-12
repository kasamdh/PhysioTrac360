"""In-home PT requests, matching/scheduling, and the provider's field queue.

Mirrors the existing split between care/availability.py (read-only preview)
and care/booking.py (transactional, re-validating create): matching_providers()
is a preview of who could plausibly cover a request, while match_provider()
and schedule_appointment() are the actions that actually change state.

Home visits have no clinic Location, so they never run through
care/availability.py's slot engine — staff pick a provider and a time
directly, the same manual-scheduling path
care/api/workflow_views.py:appointment_create already uses for the existing
"Home visit" checkbox on a regular appointment.

home_visit_queue()/update_home_visit_status() below aren't specific to
MobileCareRequest — they cover every is_home_visit appointment, including
ones scheduled the older, direct way (the checkbox in SchedulePage /
PatientWorkspace) — so a provider's field queue is complete regardless of
how the visit was originally booked.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from django.utils import timezone

from .models import (
    Appointment,
    AuditEvent,
    EpisodeOfCare,
    HomeVisitAssignment,
    HomeVisitAvailability,
    MobileCareRequest,
    Patient,
    Provider,
    ProviderLocationSession,
    ProviderLocationSnapshot,
    ProviderMatch,
    User,
    UserLicense,
    VisitTravelStatus,
)
from .mobile_care_notifications import (
    notify_provider_arrived,
    notify_provider_en_route,
    notify_provider_match_found,
    notify_provider_offer_accepted,
    notify_provider_offer_created,
    notify_provider_offer_declined,
    notify_service_request_created,
    notify_visit_cancelled,
    notify_visit_completed,
    notify_visit_scheduled,
)
from .mapping import Coordinates, DistanceResult, GeocodeResult, get_directions_service, get_distance_service, get_geocoding_service
from .mobile_care_settings import (
    effective_match_weights,
    effective_offer_expiration_hours,
    effective_provider_cancellation_notice_hours,
    effective_service_hours,
    get_configuration,
    is_provider_role_allowed,
    is_requested_service_available,
)
from .services import record_audit_event


def _home_visit_address(service_request: MobileCareRequest) -> str:
    return ", ".join(
        part
        for part in (
            service_request.address_line_1,
            service_request.address_line_2,
            service_request.city,
            f"{service_request.state} {service_request.zip_code}".strip(),
        )
        if part
    )[:180]


def _assert_within_service_hours(organization, *, starts_at, ends_at) -> None:
    """"Service Hours" — an org-wide operating window for home visits
    (MobileCareConfiguration.service_hours_start/_end), distinct from any
    one provider's own HomeVisitAvailability rows. Either bound may be
    unset (no restriction on that end); checked against local wall-clock
    time, same as every other time-of-day comparison in this module."""
    start_bound, end_bound = effective_service_hours(organization)
    if start_bound is None and end_bound is None:
        return
    local_start = timezone.localtime(starts_at).time()
    local_end = timezone.localtime(ends_at).time()
    if start_bound and local_start < start_bound:
        raise ValidationError(f"This organization's home visits cannot start before {start_bound.strftime('%I:%M %p')}.")
    if end_bound and local_end > end_bound:
        raise ValidationError(f"This organization's home visits cannot end after {end_bound.strftime('%I:%M %p')}.")


# --- Route/distance support (care/mapping.py's abstraction layer) ----------
#
# Basic geocoding/distance/directions — no continuous provider GPS tracking
# here (see ProviderLocationSnapshot/record_location_snapshot() for that
# separate, opt-in concern). Distance always originates from a provider's
# DECLARED ServiceArea (a coverage-area ZIP/city/state), never a home
# address (none is stored for a provider) and never live GPS.


def geocode_mobile_care_request(mobile_care_request: MobileCareRequest):
    """Geocode (and cache) a request's visit address — returns the cached
    result on a second call rather than re-geocoding. See
    care/mapping.py's GeocodeResult; `geocoded` is False today for every
    organization since no geocoding provider is connected."""
    if mobile_care_request.latitude is not None and mobile_care_request.longitude is not None:
        return GeocodeResult(
            geocoded=True,
            coordinates=Coordinates(float(mobile_care_request.latitude), float(mobile_care_request.longitude)),
            formatted_address=_home_visit_address(mobile_care_request),
            message="",
        )
    service = get_geocoding_service(mobile_care_request.organization)
    result = service.geocode(
        address_line_1=mobile_care_request.address_line_1,
        city=mobile_care_request.city,
        state=mobile_care_request.state,
        zip_code=mobile_care_request.zip_code,
    )
    if result.geocoded and result.coordinates:
        mobile_care_request.latitude = Decimal(str(result.coordinates.latitude))
        mobile_care_request.longitude = Decimal(str(result.coordinates.longitude))
        mobile_care_request.save(update_fields=["latitude", "longitude", "updated_at"])
    return result


def geocode_service_area(service_area):
    """Geocode (and cache) a provider's declared service-area origin — the
    primary ZIP/city/state they cover. Never a home address; this app
    stores no such thing for a provider."""
    if service_area.latitude is not None and service_area.longitude is not None:
        return GeocodeResult(
            geocoded=True,
            coordinates=Coordinates(float(service_area.latitude), float(service_area.longitude)),
            formatted_address=f"{service_area.city}, {service_area.state} {service_area.primary_zip_code}".strip(", "),
            message="",
        )
    service = get_geocoding_service(service_area.organization)
    result = service.geocode(
        address_line_1="", city=service_area.city, state=service_area.state, zip_code=service_area.primary_zip_code,
    )
    if result.geocoded and result.coordinates:
        service_area.latitude = Decimal(str(result.coordinates.latitude))
        service_area.longitude = Decimal(str(result.coordinates.longitude))
        service_area.save(update_fields=["latitude", "longitude", "updated_at"])
    return result


def estimate_provider_distance(provider: Provider, mobile_care_request: MobileCareRequest):
    """Approximate provider-to-patient distance/drive time — see
    care/mapping.py's DistanceResult. Honestly reports `available=False`
    unless both the provider's declared service-area origin and the
    visit's address are geocoded, which requires a connected geocoding
    provider (none is connected today, so this always reports
    unavailable) — never fabricated. Distinct from the coarse
    ZIP-membership distance_score used for ranking (score_provider_match())
    — that heuristic needs no geocoding and is unaffected by this."""
    service_area = (
        provider.service_areas.filter(is_active=True)
        .exclude(primary_zip_code="")
        .order_by("name")
        .first()
    )
    if service_area is None:
        return DistanceResult(
            available=False, distance_miles=None, estimated_drive_minutes=None,
            message="This provider has no declared service area with an origin ZIP.",
        )
    origin = geocode_service_area(service_area)
    destination = geocode_mobile_care_request(mobile_care_request)
    if not (origin.geocoded and origin.coordinates and destination.geocoded and destination.coordinates):
        return DistanceResult(available=False, distance_miles=None, estimated_drive_minutes=None, message=origin.message or destination.message)
    return get_distance_service(provider.organization).estimate(origin=origin.coordinates, destination=destination.coordinates)


def build_visit_directions_url(mobile_care_request: MobileCareRequest):
    """A URL a provider or staff member can open for turn-by-turn
    directions to this visit's address — see care/mapping.py's
    DirectionsService; the vendor is chosen there, never in a view or
    template."""
    return get_directions_service(mobile_care_request.organization).build_directions_url(
        destination_address=_home_visit_address(mobile_care_request)
    )


def build_directions_url_for_address(organization, address: str):
    """Same as build_visit_directions_url() but for any plain address
    string — used by the legacy home-visit queue, whose Appointment rows
    carry a free-text `location` rather than always having a
    MobileCareRequest behind them."""
    return get_directions_service(organization).build_directions_url(destination_address=address)


def _establish_continuity(service_request: MobileCareRequest, provider: Provider) -> None:
    """If this episode had no primary therapist yet, this visit establishes
    one — so the *next* request for this patient's episode defaults to the
    same provider via create_request()."""
    if service_request.episode_of_care_id and not service_request.episode_of_care.primary_therapist_id:
        service_request.episode_of_care.primary_therapist = provider.user
        service_request.episode_of_care.save(update_fields=["primary_therapist", "updated_at"])


def provider_ineligibility_reason(provider: Provider) -> str | None:
    """None if this provider may be matched/assigned to a home visit right
    now; otherwise a human-readable reason. A single enforcement point for
    the license-expiry and account-status checks both pipelines need —
    matching_providers() uses it to filter the preview list, match_provider()
    and respond_to_match() use it as a hard gate at the point of commitment
    (a preview filter alone wouldn't stop match_provider()'s deliberate
    "any org provider, not just a matched one" override)."""
    if not provider.is_active:
        return "This provider is not active."
    if not provider.user_id or not provider.user.is_active:
        return "This provider has no active user account."
    if provider.user.effective_status != provider.user.Status.ACTIVE:
        return "This provider's account is not currently active."
    if provider.user.license_alert_status == "expired":
        return "This provider's license has expired."
    return None


def provider_licensed_for_state(provider: Provider, state: str) -> bool:
    """Whether this provider holds a currently-active (non-expired) license
    for the given state — matched case-insensitively since UserLicense.issuing_state
    is free text, not a fixed-choice field. Used by service_area_ineligibility_reason()
    for the "must have an active license for the patient's state" rule."""
    state = (state or "").strip()
    if not provider.user_id or not state:
        return False
    return provider.user.licenses.filter(issuing_state__iexact=state, expires_at__gte=timezone.localdate()).exists()


def service_area_ineligibility_reason(service_area) -> str | None:
    """None if this service area's provider is currently eligible for an
    in-home visit in this area; otherwise a human-readable reason. Combines
    the general provider gate (active account, no expired license anywhere)
    with the state-specific licensing check for this particular area — a
    provider might be generally eligible but not licensed for THIS area's
    state (e.g. they cover a ZIP just over a state line)."""
    general_reason = provider_ineligibility_reason(service_area.provider)
    if general_reason:
        return general_reason
    if service_area.state and not provider_licensed_for_state(service_area.provider, service_area.state):
        return f"Provider has no active license for {service_area.state}."
    return None


class EligibilityReason:
    """Reason codes for check_provider_eligibility(). Staff/internal use
    only — several of these (ACCOUNT_SUSPENDED, ACCOUNT_LOCKED, ...) reveal
    account-security state that a patient has no legitimate reason to see
    about a clinician, so a patient-facing view must never surface these
    codes directly; show a generic "not available" message instead."""

    WRONG_ORGANIZATION = "WRONG_ORGANIZATION"
    PROVIDER_INACTIVE = "PROVIDER_INACTIVE"
    NO_USER_ACCOUNT = "NO_USER_ACCOUNT"
    ACCOUNT_INACTIVE = "ACCOUNT_INACTIVE"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    ACCOUNT_SUSPENDED = "ACCOUNT_SUSPENDED"
    ACCOUNT_DELETED = "ACCOUNT_DELETED"
    PROVIDER_TYPE_NOT_PERMITTED = "PROVIDER_TYPE_NOT_PERMITTED"
    LICENSE_EXPIRED = "LICENSE_EXPIRED"
    WRONG_STATE_LICENSE = "WRONG_STATE_LICENSE"
    OUTSIDE_SERVICE_AREA = "OUTSIDE_SERVICE_AREA"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    ALREADY_BOOKED = "ALREADY_BOOKED"
    SPECIALTY_MISMATCH = "SPECIALTY_MISMATCH"
    ORGANIZATION_RULE_FAILED = "ORGANIZATION_RULE_FAILED"


@dataclass(frozen=True)
class ProviderEligibility:
    eligible: bool
    reasons: tuple[str, ...] = ()


# requested_service values a PTA (User.Role.ASSISTANT) may not independently
# perform — an initial evaluation and a discharge visit both require a PT's
# clinical judgment under most state practice acts; follow-up/progress visits
# are ordinary assigned clinical work a PTA already performs unsupervised
# elsewhere in this app (see care/note_management.py's PTA cosign rule, which
# draws the same PT/PTA line).
_PTA_RESTRICTED_SERVICES = (
    MobileCareRequest.RequestedService.EVALUATION,
    MobileCareRequest.RequestedService.DISCHARGE,
)

# Coarse time-of-day bounds for MobileCareRequest.preferred_time_window —
# used only to check availability/booking overlap at preview granularity;
# blank or ANY means "no time-of-day constraint".
_TIME_WINDOW_BOUNDS: dict[str, tuple[time, time]] = {
    MobileCareRequest.TimeWindow.MORNING: (time(8, 0), time(12, 0)),
    MobileCareRequest.TimeWindow.AFTERNOON: (time(12, 0), time(17, 0)),
    MobileCareRequest.TimeWindow.EVENING: (time(17, 0), time(21, 0)),
}

# How far past earliest_date to look when latest_date leaves the request's
# window open-ended — bounds the day-by-day availability scan below.
_ELIGIBILITY_DATE_WINDOW_CAP_DAYS = 13


def _time_ranges_overlap(a_start: time, a_end: time, b_start: time, b_end: time) -> bool:
    return a_start < b_end and b_start < a_end


def _availability_fit_score(provider: Provider, mobile_care_request: MobileCareRequest) -> float:
    """1.0 if the provider has a fitting AVAILABLE HomeVisitAvailability
    window — not cancelled out by an UNAVAILABLE/BLOCKED one covering the
    same day/time — on the exact preferred (earliest) date, overlapping the
    requested time window (any time of day, if unspecified); 0.6 if only a
    later day within the request's flexible date range fits; 0.0 if none
    does. The single source of truth for both the hard NOT_AVAILABLE
    eligibility gate (any score > 0 passes — see
    check_provider_eligibility()) and the softer availability_score used to
    rank eligible candidates (an exact-date fit outranks one that only
    works later in the patient's flexible window).

    A preview-level signal, like matching_providers() — not a real-time slot
    reservation. Two eligible providers can both show available for the
    same window until one is actually assigned; that's fine, this only
    answers "could this provider plausibly take this visit," not "is this
    the only provider who could.\""""
    start_date = mobile_care_request.earliest_date
    end_date = mobile_care_request.latest_date or start_date
    end_date = min(end_date, start_date + timedelta(days=_ELIGIBILITY_DATE_WINDOW_CAP_DAYS))
    window_bounds = _TIME_WINDOW_BOUNDS.get(mobile_care_request.preferred_time_window)

    rows = list(provider.home_visit_availabilities.filter(is_active=True))
    if not rows:
        return 0.0

    def overlaps(row) -> bool:
        if window_bounds is None:
            return True
        return _time_ranges_overlap(row.start_time, row.end_time, *window_bounds)

    def fits(current) -> bool:
        weekday = current.weekday()
        day_rows = [
            row
            for row in rows
            if (row.effective_from is None or row.effective_from <= current)
            and (row.effective_until is None or row.effective_until >= current)
            and (
                (row.is_recurring and row.day_of_week == weekday)
                or (not row.is_recurring and row.specific_date == current)
            )
        ]
        blocked = any(
            row.availability_type in (HomeVisitAvailability.AvailabilityType.UNAVAILABLE, HomeVisitAvailability.AvailabilityType.BLOCKED)
            and overlaps(row)
            for row in day_rows
        )
        return not blocked and any(
            row.availability_type == HomeVisitAvailability.AvailabilityType.AVAILABLE and overlaps(row) for row in day_rows
        )

    if fits(start_date):
        return 1.0
    current = start_date + timedelta(days=1)
    while current <= end_date:
        if fits(current):
            return 0.6
        current += timedelta(days=1)
    return 0.0


def _has_overlapping_availability(provider: Provider, mobile_care_request: MobileCareRequest) -> bool:
    return _availability_fit_score(provider, mobile_care_request) > 0.0


def _has_conflicting_booking(provider: Provider, mobile_care_request: MobileCareRequest) -> bool:
    """Whether this provider already has a non-cancelled appointment on the
    request's preferred date, within the same time-of-day window (or
    anywhere that day, if no time window was specified). A coarse "already
    has something on the books" signal, not a precise slot conflict check —
    a Patient Service Request only carries a date plus a time-of-day
    preference, not an exact start/end time, until a visit is scheduled."""
    if provider.user_id is None:
        return False
    day_appointments = Appointment.objects.filter(
        therapist_id=provider.user_id,
        starts_at__date=mobile_care_request.earliest_date,
    ).exclude(status__in=(Appointment.Status.CANCELLED, Appointment.Status.NO_SHOW))
    window_bounds = _TIME_WINDOW_BOUNDS.get(mobile_care_request.preferred_time_window)
    if window_bounds is None:
        return day_appointments.exists()
    start_bound, end_bound = window_bounds
    for appointment in day_appointments:
        local_start = timezone.localtime(appointment.starts_at).time()
        local_end = timezone.localtime(appointment.ends_at).time()
        if local_start < end_bound and start_bound < local_end:
            return True
    return False


def _organization_specific_ineligibility_reason(provider: Provider, mobile_care_request: MobileCareRequest) -> str | None:
    """Extension point for organization-configured eligibility rules beyond
    the universal checks in check_provider_eligibility(). Currently backs
    "Provider Types" (MobileCareConfiguration.allowed_provider_roles) — an
    org admin may restrict Mobile Care to therapists only, excluding
    assistants, on top of (not instead of) the universal PT/PTA
    scope-of-practice rule check_provider_eligibility() already applies.
    Empty/unset means no additional restriction — never a fabricated one."""
    if provider.user_id and not is_provider_role_allowed(provider.organization, provider.user.role):
        return EligibilityReason.PROVIDER_TYPE_NOT_PERMITTED
    return None


def check_provider_eligibility(provider: Provider, mobile_care_request: MobileCareRequest) -> ProviderEligibility:
    """Structured eligibility determination for one provider against one
    Patient Service Request — the comprehensive, machine-readable
    counterpart to provider_ineligibility_reason() above (which only covers
    account/license status and returns a single human-readable string for
    the staff matching-preview and hard-gate call sites). This additionally
    evaluates organization scope, PT/PTA scope-of-practice for the
    requested service, service-area coverage, availability, an
    already-booked conflict, and specialty match — collecting every
    applicable reason rather than stopping at the first failure, so a
    caller can show or log the complete picture.

    Read-only and side-effect free. Does not implement ranking or scoring —
    see matching_providers() for the existing ZIP-based preview list — only
    a yes/no-with-reasons determination for a single candidate."""
    reasons: list[str] = []

    if provider.organization_id != mobile_care_request.organization_id:
        reasons.append(EligibilityReason.WRONG_ORGANIZATION)

    if not provider.is_active:
        reasons.append(EligibilityReason.PROVIDER_INACTIVE)

    user = provider.user
    if user is None:
        reasons.append(EligibilityReason.NO_USER_ACCOUNT)
    else:
        # `status` is the authoritative, specific signal — every status
        # transition in care/user_management.py sets is_active=False in
        # lockstep with it, so is_active alone can't distinguish INACTIVE
        # from SUSPENDED from LOCKED_OUT. Only fall back to a generic
        # ACCOUNT_INACTIVE when is_active is off but status still somehow
        # reads ACTIVE (e.g. a manual override outside the normal flows).
        status = user.effective_status
        if status == User.Status.INACTIVE:
            reasons.append(EligibilityReason.ACCOUNT_INACTIVE)
        elif status == User.Status.LOCKED_OUT:
            reasons.append(EligibilityReason.ACCOUNT_LOCKED)
        elif status == User.Status.SUSPENDED:
            reasons.append(EligibilityReason.ACCOUNT_SUSPENDED)
        elif status == User.Status.DELETED:
            reasons.append(EligibilityReason.ACCOUNT_DELETED)
        elif not user.is_active:
            reasons.append(EligibilityReason.ACCOUNT_INACTIVE)

        if user.role == User.Role.ASSISTANT and mobile_care_request.requested_service in _PTA_RESTRICTED_SERVICES:
            reasons.append(EligibilityReason.PROVIDER_TYPE_NOT_PERMITTED)

        # No verified license on file — whether because none exists or the
        # only one(s) on file are still pending_verification — reads the
        # same as an expired one from this request's point of view: there's
        # no currently usable credential either way. LICENSE_EXPIRED is the
        # one code from the requested reason vocabulary that covers it.
        verified_licenses = user.licenses.filter(verification_status=UserLicense.VerificationStatus.VERIFIED)
        state = (mobile_care_request.state or "").strip()
        if not verified_licenses.exists():
            reasons.append(EligibilityReason.LICENSE_EXPIRED)
        elif state:
            state_licenses = verified_licenses.filter(issuing_state__iexact=state)
            if not state_licenses.exists():
                reasons.append(EligibilityReason.WRONG_STATE_LICENSE)
            elif not state_licenses.filter(expires_at__gte=timezone.localdate()).exists():
                reasons.append(EligibilityReason.LICENSE_EXPIRED)

    if mobile_care_request.zip_code and not provider.service_areas.filter(
        is_active=True, zip_codes__zip_code=mobile_care_request.zip_code
    ).exists():
        reasons.append(EligibilityReason.OUTSIDE_SERVICE_AREA)

    if not _has_overlapping_availability(provider, mobile_care_request):
        reasons.append(EligibilityReason.NOT_AVAILABLE)

    if _has_conflicting_booking(provider, mobile_care_request):
        reasons.append(EligibilityReason.ALREADY_BOOKED)

    specialty_requested = (mobile_care_request.specialty_requested or "").strip()
    if specialty_requested and specialty_requested.lower() not in (provider.specialty or "").lower():
        reasons.append(EligibilityReason.SPECIALTY_MISMATCH)

    org_reason = _organization_specific_ineligibility_reason(provider, mobile_care_request)
    if org_reason:
        reasons.append(org_reason)

    return ProviderEligibility(eligible=not reasons, reasons=tuple(reasons))


@dataclass(frozen=True)
class ProviderMatchScore:
    """One eligible provider's ranking result — the *ranked, scored*
    counterpart to ProviderEligibility (which only answers yes/no). Never
    serialize this to the patient portal — see rank_eligible_providers()."""

    provider: Provider
    total: float
    continuity_score: float
    specialty_score: float
    availability_score: float
    distance_score: float
    preference_score: float
    caseload_score: float
    reasons: tuple[str, ...]


# Recommended matching priority (highest weight first), per the requested
# order: (1) continuity, (3) specialty, (4) availability, (5) service
# area/distance, (8) patient preference, (7) existing caseload. Items (2)
# correct/active state license and (6)/(9) are handled elsewhere:
#   - (2) license validity is a hard eligibility gate (check_provider_eligibility),
#     not a ranking weight — a provider is either licensed to see this
#     patient or they are not offered at all.
#   - (6) insurance/network eligibility has no corresponding data model in
#     this codebase yet (no provider-network/payer-panel concept) — "if
#     available" is honored by omitting it rather than fabricating a signal.
#   - (9) travel efficiency folds into distance_score — no geocoding
#     provider is connected (see ServiceArea's docstring), so ZIP-level
#     proximity is the only travel signal available for either concept.
# A caller may pass a different mapping to re-prioritize per organization —
# see rank_eligible_providers()'s `weights` parameter.
DEFAULT_MATCH_WEIGHTS: dict[str, float] = {
    "continuity": 30.0,
    "specialty": 20.0,
    "availability": 15.0,
    "distance": 15.0,
    "preference": 12.0,
    "caseload": 8.0,
}


def _continuity_score(provider: Provider, mobile_care_request: MobileCareRequest) -> float:
    """1.0 if this provider is the request's preferred_provider — set by
    create_request() from the patient's episode continuity when one exists,
    or chosen explicitly by staff/patient otherwise (see the "Preferred
    Provider" field) — 0.0 otherwise. The highest-weighted dimension by
    default, per "prioritize continuity ... not pure nearest-provider
    matching.\""""
    return 1.0 if mobile_care_request.preferred_provider_id == provider.pk else 0.0


def _specialty_score(provider: Provider, mobile_care_request: MobileCareRequest) -> float:
    """1.0 for an exact (case-insensitive) match to specialty_requested,
    0.75 for a partial/contains match, 1.0 (neutral — not a ranking factor)
    when no specialty was requested. A provider whose specialty doesn't
    contain the requested one at all is already excluded before scoring —
    see EligibilityReason.SPECIALTY_MISMATCH — so 0.0 here is only a
    defensive fallback, never expected among already-eligible candidates."""
    requested = (mobile_care_request.specialty_requested or "").strip().lower()
    if not requested:
        return 1.0
    specialty = (provider.specialty or "").strip().lower()
    if specialty == requested:
        return 1.0
    if requested in specialty:
        return 0.75
    return 0.0


def _distance_score(provider: Provider, mobile_care_request: MobileCareRequest) -> float:
    """Coarse proximity proxy — no geocoding provider is connected in this
    codebase (see ServiceArea's docstring), so this uses ZIP-level signals
    only: an exact match to one of the provider's service areas' declared
    primary ZIP scores highest; covering the visit ZIP only via the broader
    ServiceAreaZipCode list (not as the area's primary ZIP) scores lower.
    Also stands in for "travel efficiency" — see DEFAULT_MATCH_WEIGHTS."""
    areas = provider.service_areas.filter(is_active=True, zip_codes__zip_code=mobile_care_request.zip_code)
    if areas.filter(primary_zip_code=mobile_care_request.zip_code).exists():
        return 1.0
    if areas.exists():
        return 0.6
    return 0.0


def _preference_score(provider: Provider, mobile_care_request: MobileCareRequest) -> float:
    """provider_gender_preference is the only patient-stated preference on
    the request distinct from preferred_provider (already captured by
    continuity_score) — but Provider has no gender attribute to score
    against, and this task doesn't ask for adding one. A neutral 1.0
    placeholder until that data exists, so the absence of the capability
    never penalizes a candidate."""
    return 1.0


def _caseload_score(provider: Provider) -> float:
    """1.0 for no upcoming scheduled work, decaying toward 0.0 as the
    provider's near-term caseload grows — a light load-balancing nudge
    among otherwise-comparable candidates, not a hard limit."""
    if provider.user_id is None:
        return 1.0
    active_count = Appointment.objects.filter(
        therapist_id=provider.user_id,
        starts_at__gte=timezone.now(),
        status__in=(Appointment.Status.SCHEDULED, Appointment.Status.CHECKED_IN),
    ).count()
    return max(0.0, 1.0 - min(active_count, 10) * 0.1)


def score_provider_match(
    provider: Provider, mobile_care_request: MobileCareRequest, *, weights: dict[str, float] | None = None
) -> ProviderMatchScore:
    """Weighted 0-100 match score plus a breakdown and human-readable
    reasons for one provider against one request — assumes the caller has
    already confirmed eligibility (see check_provider_eligibility()); this
    only ranks, it does not gate."""
    weights = weights or DEFAULT_MATCH_WEIGHTS
    continuity = _continuity_score(provider, mobile_care_request)
    specialty = _specialty_score(provider, mobile_care_request)
    availability = _availability_fit_score(provider, mobile_care_request)
    distance = _distance_score(provider, mobile_care_request)
    preference = _preference_score(provider, mobile_care_request)
    caseload = _caseload_score(provider)

    total = (
        continuity * weights["continuity"]
        + specialty * weights["specialty"]
        + availability * weights["availability"]
        + distance * weights["distance"]
        + preference * weights["preference"]
        + caseload * weights["caseload"]
    )

    reasons: list[str] = []
    if continuity >= 1.0:
        reasons.append("Existing care relationship with this patient")
    if (mobile_care_request.specialty_requested or "").strip():
        if specialty >= 1.0:
            reasons.append("Exact specialty match")
        elif specialty > 0:
            reasons.append("Related specialty")
    if availability >= 1.0:
        reasons.append("Available on the preferred date")
    elif availability > 0:
        reasons.append("Available within the requested date range")
    if distance >= 1.0:
        reasons.append("Primary coverage ZIP matches the visit address")
    elif distance > 0:
        reasons.append("Covers the visit ZIP")
    if caseload >= 0.9:
        reasons.append("Low current caseload")

    return ProviderMatchScore(
        provider=provider,
        total=round(total, 2),
        continuity_score=continuity,
        specialty_score=specialty,
        availability_score=availability,
        distance_score=distance,
        preference_score=preference,
        caseload_score=caseload,
        reasons=tuple(reasons),
    )


def rank_eligible_providers(
    mobile_care_request: MobileCareRequest, *, weights: dict[str, float] | None = None
) -> list[ProviderMatchScore]:
    """Ranked, scored list of every currently-eligible provider for this
    request — the configurable-priority counterpart to
    matching_providers()'s plain ZIP-coverage preview list.

    Eligibility (license, account status, service area, availability,
    specialty, organization scope — see check_provider_eligibility()) is a
    hard gate applied first; ranking only orders the survivors, so this
    never recommends a clinically inappropriate provider just because they
    scored well on the softer dimensions. Deliberately not "nearest
    provider first" — continuity of care carries the largest weight by
    default (see DEFAULT_MATCH_WEIGHTS), and a caller may pass a different
    `weights` mapping to reprioritize.

    Read-only. Staff/admin use only — never call this from a patient-facing
    view; see generate_matches() for how this becomes persisted,
    staff-visible ProviderMatch rows."""
    weights = weights or effective_match_weights(mobile_care_request.organization)
    candidates = (
        Provider.objects.filter(
            organization=mobile_care_request.organization_id,
            is_active=True,
            service_areas__is_active=True,
            service_areas__zip_codes__zip_code=mobile_care_request.zip_code,
        )
        .select_related("user")
        .distinct()
    )
    scored = [
        score_provider_match(provider, mobile_care_request, weights=weights)
        for provider in candidates
        if check_provider_eligibility(provider, mobile_care_request).eligible
    ]
    scored.sort(key=lambda entry: (-entry.total, entry.provider.last_name, entry.provider.first_name))
    return scored


# Allowed field-workflow status transitions for a home-visit appointment —
# deliberately narrower than the full Appointment.Status set: a provider in
# the field checks in, then completes (or marks a no-show); anything else
# (cancelling, rescheduling) goes through the normal scheduling views.
HOME_VISIT_STATUS_TRANSITIONS = {
    Appointment.Status.SCHEDULED: {Appointment.Status.CHECKED_IN, Appointment.Status.NO_SHOW},
    Appointment.Status.CHECKED_IN: {Appointment.Status.COMPLETED, Appointment.Status.NO_SHOW},
}


def home_visit_queue(therapist, *, on_date):
    """This clinician's own home-visit appointments for one calendar date,
    earliest first — the data behind their mobile field queue."""
    return (
        Appointment.objects.filter(therapist=therapist, is_home_visit=True, starts_at__date=on_date)
        .exclude(status=Appointment.Status.CANCELLED)
        .select_related("patient")
        .order_by("starts_at")
    )


def update_home_visit_status(appointment: Appointment, new_status: str, *, actor, django_request=None) -> Appointment:
    """The legacy field-day workflow (checked_in -> completed/no_show) for
    ANY is_home_visit appointment, including ones with no MobileCareRequest
    at all (booked directly via the schedule page's "Home visit" checkbox)
    — so, unlike the accept-first pipeline's update_assignment_status()
    above, this deliberately does not send Mobile Care notifications
    (VISIT_COMPLETED, etc.): those events are all specifically framed
    around a Patient Service Request/offer, which may not exist here."""
    if not appointment.is_home_visit:
        raise ValidationError("Only home-visit appointments use this workflow.")
    allowed = HOME_VISIT_STATUS_TRANSITIONS.get(appointment.status, set())
    if new_status not in allowed:
        raise ValidationError(f"Cannot move this visit from {appointment.get_status_display()} to that status.")
    appointment.status = new_status
    appointment.save(update_fields=["status", "updated_at"])
    record_audit_event(
        actor=actor,
        action="appointment.status_updated",
        obj=appointment,
        patient=appointment.patient,
        request=django_request,
        metadata={"status": new_status, "source": "mobile_queue"},
    )
    return appointment


# Fields a caller may set at creation or edit them later while the request
# is still editable (see EDITABLE_REQUEST_STATUSES / update_request() below).
# Centralized here so create_request() and update_request() apply the exact
# same whitelist rather than drifting apart.
REQUEST_DETAIL_FIELDS = (
    "requested_service",
    "specialty_requested",
    "preferred_time_window",
    "primary_condition",
    "provider_gender_preference",
    "is_new_patient",
    "payment_method",
    "mobility_notes",
    "home_access_notes",
)

EDITABLE_REQUEST_STATUSES = (
    MobileCareRequest.Status.PENDING,
    MobileCareRequest.Status.MATCHING,
    MobileCareRequest.Status.PROVIDER_OFFERED,
)

# Non-terminal: a request in any of these statuses can still be cancelled.
# Terminal statuses (COMPLETED/CANCELLED/DECLINED/EXPIRED) cannot be
# cancelled again.
CANCELLABLE_REQUEST_STATUSES = (
    MobileCareRequest.Status.PENDING,
    MobileCareRequest.Status.MATCHING,
    MobileCareRequest.Status.PROVIDER_OFFERED,
    MobileCareRequest.Status.MATCHED,
    MobileCareRequest.Status.ACCEPTED,
    MobileCareRequest.Status.SCHEDULED,
    MobileCareRequest.Status.IN_PROGRESS,
)


def create_request(
    patient: Patient,
    *,
    source: str,
    address_line_1: str,
    city: str,
    state: str,
    zip_code: str,
    earliest_date,
    address_line_2: str = "",
    reason_for_visit: str = "",
    notes: str = "",
    latest_date=None,
    preferred_time_window: str = "",
    requested_service: str = "",
    specialty_requested: str = "",
    primary_condition: str = "",
    provider_gender_preference: str = MobileCareRequest.GenderPreference.NO_PREFERENCE,
    is_new_patient: bool = False,
    payment_method: str = MobileCareRequest.PaymentMethod.INSURANCE,
    mobility_notes: str = "",
    home_access_notes: str = "",
    preferred_provider: Provider | None = None,
    created_by,
    django_request=None,
) -> MobileCareRequest:
    """Shared creation path for both the staff-entered ("front desk called
    it in") and patient-portal-submitted request forms — same validation,
    same audit trail, differing only in `source` and who's authorized to
    call it (see the two callers in care/api/mobile_care.py and
    care/api/patient_portal.py).

    Continuity: if the caller doesn't explicitly name a `preferred_provider`
    (the "Preferred Provider if any" field) and the patient has an ACTIVE
    Care Episode with a primary therapist already assigned, this request
    defaults to that clinician's Provider profile — but only if they're
    still eligible for THIS visit (active, licensed for the visit's state,
    available, within the service area, not suspended — the same
    check_provider_eligibility() gate used everywhere else) — so continuity
    is preferred, not forced: a provider who's since gone on leave, let
    their license lapse, or stopped covering this area doesn't silently
    block the request. See matching_providers() and schedule_appointment()
    below for the other two halves of continuity."""
    if requested_service and not is_requested_service_available(patient.organization, requested_service):
        raise ValidationError(
            {"requestedService": "This organization does not offer that service via Mobile Care."}
        )
    episode = patient.episodes_of_care.filter(status=EpisodeOfCare.Status.ACTIVE).order_by("-start_date").first()
    if preferred_provider is None and episode and episode.primary_therapist_id:
        continuity_candidate = Provider.objects.filter(
            organization=patient.organization_id, user_id=episode.primary_therapist_id, is_active=True
        ).first()
        if continuity_candidate is not None:
            # A lightweight, unsaved probe carrying just the fields
            # eligibility actually reads (zip/state/dates/service/specialty)
            # — cheaper than constructing and discarding a real row, and
            # none of those checks require a saved instance.
            probe = MobileCareRequest(
                organization=patient.organization,
                zip_code=zip_code,
                state=state,
                earliest_date=earliest_date,
                latest_date=latest_date,
                preferred_time_window=preferred_time_window,
                requested_service=requested_service,
                specialty_requested=specialty_requested,
            )
            if check_provider_eligibility(continuity_candidate, probe).eligible:
                preferred_provider = continuity_candidate
    entry = MobileCareRequest(
        organization=patient.organization,
        patient=patient,
        source=source,
        address_line_1=address_line_1,
        address_line_2=address_line_2,
        city=city,
        state=state,
        zip_code=zip_code,
        reason_for_visit=reason_for_visit,
        notes=notes,
        earliest_date=earliest_date,
        latest_date=latest_date,
        preferred_time_window=preferred_time_window,
        requested_service=requested_service,
        specialty_requested=specialty_requested,
        primary_condition=primary_condition,
        provider_gender_preference=provider_gender_preference,
        is_new_patient=is_new_patient,
        payment_method=payment_method,
        mobility_notes=mobility_notes,
        home_access_notes=home_access_notes,
        episode_of_care=episode,
        preferred_provider=preferred_provider,
        created_by=created_by,
    )
    entry.full_clean()
    entry.save()
    record_audit_event(
        actor=created_by,
        action="mobile_care_request.created",
        obj=entry,
        patient=patient,
        request=django_request,
        metadata={"source": source},
    )
    notify_service_request_created(entry, django_request=django_request)
    return entry


def update_request(mobile_care_request: MobileCareRequest, fields: dict, *, actor, django_request=None) -> MobileCareRequest:
    """Edit a request's own details — address, dates, and the descriptive
    fields in REQUEST_DETAIL_FIELDS — while it's still editable (before a
    provider has been matched/accepted; see EDITABLE_REQUEST_STATUSES).
    `fields` is a plain {model_field_name: value} dict, already validated/
    type-coerced by the caller (the view layer) — this function only
    enforces the "still editable" business rule and applies the change."""
    if mobile_care_request.status not in EDITABLE_REQUEST_STATUSES:
        raise ValidationError(
            f"This request can no longer be edited (status: {mobile_care_request.get_status_display()})."
        )
    allowed_fields = {
        "address_line_1", "address_line_2", "city", "state", "zip_code",
        "reason_for_visit", "notes", "earliest_date", "latest_date", "preferred_provider",
        *REQUEST_DETAIL_FIELDS,
    }
    for field_name, value in fields.items():
        if field_name not in allowed_fields:
            raise ValueError(f"{field_name} is not an editable field.")
        setattr(mobile_care_request, field_name, value)
    if mobile_care_request.requested_service and not is_requested_service_available(
        mobile_care_request.organization, mobile_care_request.requested_service
    ):
        raise ValidationError(
            {"requestedService": "This organization does not offer that service via Mobile Care."}
        )
    mobile_care_request.updated_by = actor
    mobile_care_request.full_clean()
    mobile_care_request.save()
    record_audit_event(
        actor=actor,
        action="mobile_care_request.updated",
        obj=mobile_care_request,
        patient=mobile_care_request.patient,
        request=django_request,
        metadata={"fields": sorted(fields.keys())},
    )
    return mobile_care_request


def cancel_request(mobile_care_request: MobileCareRequest, *, actor, reason: str = "", django_request=None) -> MobileCareRequest:
    """Staff-side cancellation — distinct from decline_request() (which
    records a specific candidate/offer declining) and from
    cancel_portal_request() (the patient's own, narrower-scoped cancel).
    Available from any non-terminal status, including after scheduling —
    cancelling the request also cancels its linked Appointment, if any, so
    the two records never disagree about whether the visit is happening."""
    if mobile_care_request.status not in CANCELLABLE_REQUEST_STATUSES:
        raise ValidationError(
            f"This request can no longer be cancelled (status: {mobile_care_request.get_status_display()})."
        )
    mobile_care_request.status = MobileCareRequest.Status.CANCELLED
    mobile_care_request.updated_by = actor
    mobile_care_request.save(update_fields=["status", "updated_by", "updated_at"])
    if mobile_care_request.appointment_id and mobile_care_request.appointment.status not in (
        Appointment.Status.CANCELLED, Appointment.Status.COMPLETED, Appointment.Status.NO_SHOW,
    ):
        mobile_care_request.appointment.status = Appointment.Status.CANCELLED
        mobile_care_request.appointment.save(update_fields=["status", "updated_at"])
    # A request stays cancellable through IN_PROGRESS (see
    # CANCELLABLE_REQUEST_STATUSES), and the request's own status never
    # advances past SCHEDULED for EN_ROUTE/ARRIVED (see
    # _ASSIGNMENT_TO_REQUEST_STATUS) — so this path, unlike
    # update_assignment_status(), can cancel a request whose assignment is
    # still EN_ROUTE. Close any open location session directly here rather
    # than relying on that function, so a cancelled visit never leaves live
    # location sharing running.
    for assignment in HomeVisitAssignment.objects.filter(
        service_request=mobile_care_request, status=HomeVisitAssignment.Status.EN_ROUTE,
    ):
        close_location_session(
            assignment, end_reason=ProviderLocationSession.EndReason.CANCELLED, actor=actor, django_request=django_request,
        )
    record_audit_event(
        actor=actor,
        action="mobile_care_request.cancelled",
        obj=mobile_care_request,
        patient=mobile_care_request.patient,
        request=django_request,
        metadata={"reason": reason, "source": "staff"},
    )
    notify_visit_cancelled(mobile_care_request, reason=reason, django_request=django_request)
    return mobile_care_request


def request_status_history(mobile_care_request: MobileCareRequest):
    """The request's status/action timeline — reuses the existing,
    append-only AuditEvent trail (every mutation in this module already
    writes one) rather than a dedicated history table: this request's own
    events, plus any recorded against its linked ProviderMatch/
    HomeVisitAssignment/Appointment rows, merged into one chronological
    list. See care/api/mobile_care.py's serializer for the shape returned."""
    object_ids = [mobile_care_request.pk]
    object_ids += list(mobile_care_request.matches.values_list("pk", flat=True))
    object_ids += list(HomeVisitAssignment.objects.filter(service_request=mobile_care_request).values_list("pk", flat=True))
    if mobile_care_request.appointment_id:
        object_ids.append(mobile_care_request.appointment_id)
    return (
        AuditEvent.objects.filter(object_id__in=object_ids)
        .select_related("actor")
        .order_by("created_at")
    )


def cancel_portal_request(patient: Patient, request_id: str, *, django_request=None) -> MobileCareRequest:
    """A patient withdrawing their own request. Only available before staff
    has scheduled it — once an Appointment exists, cancellation goes through
    the normal appointment-cancellation flow (care/booking.py), matching the
    principle that Appointment is the single source of truth for the visit
    itself once one exists."""
    entry = MobileCareRequest.objects.filter(pk=request_id, patient=patient).first()
    if entry is None:
        raise MobileCareRequest.DoesNotExist("Request not found.")
    if entry.status not in (MobileCareRequest.Status.PENDING, MobileCareRequest.Status.MATCHED):
        raise ValidationError("This request can no longer be cancelled online.")
    entry.status = MobileCareRequest.Status.CANCELLED
    entry.updated_by = patient.portal_user
    entry.save(update_fields=["status", "updated_by", "updated_at"])
    record_audit_event(
        actor=patient.portal_user,
        action="mobile_care_request.cancelled",
        obj=entry,
        patient=patient,
        request=django_request,
        metadata={"source": "patient_portal"},
    )
    notify_visit_cancelled(entry, django_request=django_request)
    return entry


def matching_providers(mobile_care_request: MobileCareRequest) -> list[Provider]:
    """Providers to offer staff for this request, continuity provider first.

    The request's `preferred_provider` (set by create_request() from the
    patient's active episode, when one exists) is listed first regardless of
    ZIP coverage — an established relationship can outweigh a strict service
    area for a returning patient — followed by every other active provider
    whose active service area covers the ZIP. A coverage hint, not a hard
    constraint; see match_provider(). Providers with an expired license or an
    inactive account are never offered here — see provider_ineligibility_reason()."""
    zip_matches = [
        provider
        for provider in Provider.objects.filter(
            organization=mobile_care_request.organization_id,
            is_active=True,
            service_areas__is_active=True,
            service_areas__zip_codes__zip_code=mobile_care_request.zip_code,
        )
        .select_related("user")
        .distinct()
        .order_by("last_name", "first_name")
        if provider_ineligibility_reason(provider) is None
    ]
    preferred = mobile_care_request.preferred_provider
    if preferred is None or provider_ineligibility_reason(preferred) is not None:
        return zip_matches
    others = [provider for provider in zip_matches if provider.pk != preferred.pk]
    return [preferred, *others]


def match_provider(mobile_care_request: MobileCareRequest, provider: Provider, *, actor, django_request=None) -> MobileCareRequest:
    """Record staff's choice of provider for this request. Deliberately does
    not require `provider` to appear in matching_providers() — a service
    area is a coverage hint a staff member can override (e.g. a provider
    willing to make a one-off exception), not a hard gate. License-expiry and
    active-account status are NOT overridable the same way, though — those
    are a hard gate here even though they're just a filter in the preview."""
    if provider.organization_id != mobile_care_request.organization_id:
        raise ValidationError({"provider": "Provider must belong to this organization."})
    if mobile_care_request.status not in (MobileCareRequest.Status.PENDING, MobileCareRequest.Status.MATCHED):
        raise ValidationError("Only a pending or matched request can be matched to a provider.")
    # Checked against a fresh fetch, not the caller's `provider` instance
    # directly — see respond_to_match()'s identical fix/comment for why a
    # possibly-stale in-memory object could otherwise silently skip this.
    ineligibility_reason = provider_ineligibility_reason(Provider.objects.select_related("user").get(pk=provider.pk))
    if ineligibility_reason:
        raise ValidationError({"provider": ineligibility_reason})
    mobile_care_request.matched_provider = provider
    mobile_care_request.status = MobileCareRequest.Status.MATCHED
    mobile_care_request.updated_by = actor
    mobile_care_request.full_clean()
    mobile_care_request.save(update_fields=["matched_provider", "status", "updated_by", "updated_at"])
    record_audit_event(
        actor=actor,
        action="mobile_care_request.matched",
        obj=mobile_care_request,
        patient=mobile_care_request.patient,
        request=django_request,
        metadata={"provider": str(provider)},
    )
    return mobile_care_request


@transaction.atomic
def schedule_appointment(
    mobile_care_request: MobileCareRequest,
    *,
    starts_at,
    ends_at,
    kind: str,
    actor,
    django_request=None,
) -> Appointment:
    """Convert a matched request into a real, home-visit Appointment. Locks
    the request row so it can't be double-scheduled, and re-checks the
    matched provider's calendar the same way
    workflow_views.appointment_create does for any other manually-scheduled
    visit."""
    locked = MobileCareRequest.objects.select_for_update().get(pk=mobile_care_request.pk)
    if locked.status != MobileCareRequest.Status.MATCHED or not locked.matched_provider_id:
        raise ValidationError("A provider must be matched before this request can be scheduled.")
    if locked.appointment_id:
        raise ValidationError("This request has already been scheduled.")
    provider = locked.matched_provider
    if not provider.user_id:
        raise ValidationError("The matched provider has no linked user account and cannot be scheduled.")
    _assert_within_service_hours(locked.organization, starts_at=starts_at, ends_at=ends_at)

    has_conflict = (
        Appointment.objects.select_for_update()
        .filter(therapist_id=provider.user_id, starts_at__lt=ends_at, ends_at__gt=starts_at)
        .exclude(status__in=[Appointment.Status.CANCELLED, Appointment.Status.NO_SHOW])
        .exists()
    )
    if has_conflict:
        raise ValidationError("The matched provider already has an appointment at that time.")

    appointment = Appointment(
        patient=locked.patient,
        therapist=provider.user,
        provider=provider,
        kind=kind,
        starts_at=starts_at,
        ends_at=ends_at,
        location=_home_visit_address(locked),
        is_home_visit=True,
        reason_for_visit=locked.reason_for_visit,
        episode_of_care=locked.episode_of_care,
        booking_source=Appointment.BookingSource.MOBILE_APP,
        created_by=actor,
    )
    appointment.full_clean()
    appointment.save()

    locked.appointment = appointment
    locked.status = MobileCareRequest.Status.SCHEDULED
    locked.updated_by = actor
    locked.full_clean()
    locked.save(update_fields=["appointment", "status", "updated_by", "updated_at"])

    _establish_continuity(locked, provider)

    record_audit_event(
        actor=actor,
        action="mobile_care_request.scheduled",
        obj=appointment,
        patient=locked.patient,
        request=django_request,
        metadata={"mobile_care_request_id": str(locked.pk)},
    )
    notify_visit_scheduled(appointment, mobile_care_request=locked, django_request=django_request)
    return appointment


def decline_request(mobile_care_request: MobileCareRequest, *, actor, django_request=None) -> MobileCareRequest:
    if mobile_care_request.status in (MobileCareRequest.Status.SCHEDULED, MobileCareRequest.Status.CANCELLED):
        raise ValidationError("This request can no longer be declined.")
    mobile_care_request.status = MobileCareRequest.Status.DECLINED
    mobile_care_request.updated_by = actor
    mobile_care_request.save(update_fields=["status", "updated_by", "updated_at"])
    record_audit_event(
        actor=actor,
        action="mobile_care_request.declined",
        obj=mobile_care_request,
        patient=mobile_care_request.patient,
        request=django_request,
    )
    return mobile_care_request


# --- Persisted offer/accept pipeline (ProviderMatch + HomeVisitAssignment) --
#
# A second, additive pipeline alongside match_provider()/schedule_appointment()
# above: instead of staff unilaterally assigning a provider, this persists a
# ranked candidate list (ProviderMatch) and requires the chosen provider to
# explicitly accept or decline (HomeVisitAssignment) before a time is picked.
# Neither pipeline is required to touch the other's rows — a request handled
# through match_provider() never gets ProviderMatch rows, and one handled
# here still sets the legacy `matched_provider`/`appointment` fields so any
# existing view that only reads those keeps working.


def generate_matches(mobile_care_request: MobileCareRequest, *, actor, django_request=None) -> list[ProviderMatch]:
    """Persist rank_eligible_providers()'s current ranking as PENDING
    ProviderMatch rows — candidates identified as eligible and ranked by
    continuity/specialty/availability/distance/preference/caseload fit, but
    not yet sent to anyone. Staff review the ranked list (score + reasons)
    and explicitly choose who to actually offer via offer_match() — this
    keeps a human in the loop on a clinical-fit decision rather than
    auto-blasting an offer to whoever scored highest.

    Idempotent and additive only — never touches a match a provider has
    already responded to (or is currently offered), so re-running after a
    decline just fills in any new candidates rather than resetting
    existing ones."""
    ranked = rank_eligible_providers(mobile_care_request)
    already_matched_ids = set(mobile_care_request.matches.values_list("provider_id", flat=True))
    continuity_id = mobile_care_request.preferred_provider_id
    created: list[ProviderMatch] = []
    for index, entry in enumerate(ranked, start=1):
        provider = entry.provider
        if provider.pk in already_matched_ids:
            continue
        match = ProviderMatch(
            organization=mobile_care_request.organization,
            service_request=mobile_care_request,
            provider=provider,
            rank=index,
            match_reason=(
                ProviderMatch.MatchReason.CONTINUITY
                if provider.pk == continuity_id
                else ProviderMatch.MatchReason.ZIP_COVERAGE
            ),
            status=ProviderMatch.Status.PENDING,
            # Decimal(str(...)), not Decimal(entry.total) directly — a raw
            # float's exact binary expansion has far more than 2 decimal
            # places and fails the field's decimal_places validation.
            score=Decimal(str(entry.total)),
            score_breakdown={
                "continuity": entry.continuity_score,
                "specialty": entry.specialty_score,
                "availability": entry.availability_score,
                "distance": entry.distance_score,
                "preference": entry.preference_score,
                "caseload": entry.caseload_score,
                "reasons": list(entry.reasons),
            },
            created_by=actor,
        )
        match.full_clean()
        match.save()
        created.append(match)

    if created and mobile_care_request.status == MobileCareRequest.Status.PENDING:
        mobile_care_request.status = MobileCareRequest.Status.MATCHING
        mobile_care_request.updated_by = actor
        mobile_care_request.save(update_fields=["status", "updated_by", "updated_at"])
    if created:
        record_audit_event(
            actor=actor,
            action="provider_match.ranked",
            obj=mobile_care_request,
            patient=mobile_care_request.patient,
            request=django_request,
            metadata={"count": len(created)},
        )
        notify_provider_match_found(mobile_care_request, django_request=django_request)
    return created


# How long a provider has to respond before an OFFERED candidate lapses and
# (if another PENDING candidate exists) the offer cascades to the next one —
# "expires after configurable time." A caller may pass a different
# `expires_in_hours` to offer_match() to reprioritize per request/org; this
# is only the default.
DEFAULT_OFFER_EXPIRATION_HOURS = 4

# Estimated visit duration shown to a provider on an offer, before any exact
# time has been picked (that only happens once accepted, via
# schedule_assignment()) — a simple, documented default per requested
# service rather than a real scheduling estimate; mirrors the same
# 45-minute default the staff-assign ScheduleDialog UI already assumes for
# follow_up/progress/discharge, with a longer window for an initial eval.
ESTIMATED_VISIT_DURATION_MINUTES = {
    MobileCareRequest.RequestedService.EVALUATION: 60,
    MobileCareRequest.RequestedService.FOLLOW_UP: 45,
    MobileCareRequest.RequestedService.PROGRESS: 45,
    MobileCareRequest.RequestedService.DISCHARGE: 45,
}
DEFAULT_VISIT_DURATION_MINUTES = 45


def offer_match(
    provider_match: ProviderMatch,
    *,
    actor,
    django_request=None,
    expires_in_hours: float | None = None,
) -> ProviderMatch:
    """Staff's explicit choice to actually send one ranked, PENDING
    candidate an offer — the deliberate human-in-the-loop step
    generate_matches() defers (see its docstring). Re-checks eligibility at
    offer time, not just at ranking time, since time has necessarily passed
    since generate_matches() ran. Sets `expires_at` so the offer can lapse —
    see expire_stale_offers().

    `expires_in_hours` defaults to this organization's configured Offer
    Expiration Time (MobileCareConfiguration.offer_expiration_hours,
    falling back to the platform default) — pass an explicit value to
    override for one particular offer."""
    if provider_match.status != ProviderMatch.Status.PENDING:
        raise ValidationError("Only a pending candidate can be offered.")
    ineligibility_reason = provider_ineligibility_reason(provider_match.provider)
    if ineligibility_reason:
        raise ValidationError(ineligibility_reason)
    if expires_in_hours is None:
        expires_in_hours = effective_offer_expiration_hours(provider_match.service_request.organization)
    now = timezone.now()
    provider_match.status = ProviderMatch.Status.OFFERED
    provider_match.offered_at = now
    provider_match.expires_at = now + timedelta(hours=expires_in_hours)
    provider_match.updated_by = actor
    provider_match.full_clean()
    provider_match.save()
    record_audit_event(
        actor=actor,
        # SCREAMING_SNAKE_CASE here (not this module's usual "object.verb"
        # style) deliberately matches care/user_management.py's convention
        # for account/workflow lifecycle events (USER_LOCKED, USER_LICENSE_EXPIRED,
        # ...) — the requested OFFER_CREATED/VIEWED/ACCEPTED/DECLINED/EXPIRED
        # vocabulary for this workflow.
        action="OFFER_CREATED",
        obj=provider_match,
        patient=provider_match.service_request.patient,
        request=django_request,
        metadata={"provider": str(provider_match.provider), "expiresAt": provider_match.expires_at.isoformat()},
    )
    notify_provider_offer_created(provider_match, django_request=django_request)
    return provider_match


def mark_offer_viewed(provider_match: ProviderMatch, *, actor, django_request=None) -> ProviderMatch:
    """Record that the offered provider has seen this offer — idempotent,
    only the first view is recorded/audited, so polling the offers list
    doesn't spam the audit trail. Safe to call for any match; a no-op
    unless it's currently OFFERED and not yet viewed."""
    if provider_match.status != ProviderMatch.Status.OFFERED or provider_match.viewed_at is not None:
        return provider_match
    provider_match.viewed_at = timezone.now()
    provider_match.save(update_fields=["viewed_at"])
    record_audit_event(
        actor=actor,
        action="OFFER_VIEWED",
        obj=provider_match,
        patient=provider_match.service_request.patient,
        request=django_request,
    )
    return provider_match


def _offer_next_candidate(service_request: MobileCareRequest, *, actor, django_request=None) -> ProviderMatch | None:
    """After a decline or expiry, automatically offer the next-ranked
    PENDING candidate for this request, if any — "if declined/expired,
    system can offer to next provider." Silently does nothing if no more
    PENDING candidates remain (or the next one turns out ineligible by the
    time this runs — offer_match() re-checks); staff can always run
    generate_matches() again to refresh the pool."""
    next_candidate = service_request.matches.filter(status=ProviderMatch.Status.PENDING).order_by("rank").first()
    if next_candidate is None:
        return None
    try:
        return offer_match(next_candidate, actor=actor, django_request=django_request)
    except ValidationError:
        return None


def expire_stale_offers(matches=None) -> int:
    """Transition every OFFERED ProviderMatch whose expires_at has passed
    into EXPIRED, cascading an offer to the next PENDING candidate for the
    same request (if any). `matches` optionally scopes the sweep (e.g. to
    one provider); defaults to every organization.

    Call this periodically from an external scheduler — see
    care/management/commands/expire_stale_provider_offers.py, which mirrors
    check_license_expirations.py's "this command does not schedule itself"
    pattern — for offers nobody happens to be looking at. Also invoked
    lazily from respond_to_match() and provider_my_offers() so an
    individual stale offer is caught the moment anyone interacts with it,
    without waiting for the sweep."""
    queryset = matches if matches is not None else ProviderMatch.objects.all()
    stale = list(
        queryset.filter(
            status=ProviderMatch.Status.OFFERED, expires_at__isnull=False, expires_at__lte=timezone.now()
        ).select_related("service_request", "service_request__patient")
    )
    for match in stale:
        match.status = ProviderMatch.Status.EXPIRED
        match.responded_at = timezone.now()
        match.save(update_fields=["status", "responded_at", "updated_at"])
        record_audit_event(
            actor=None,
            action="OFFER_EXPIRED",
            obj=match,
            patient=match.service_request.patient,
            metadata={"provider": str(match.provider)},
        )
        _offer_next_candidate(match.service_request, actor=None)
    return len(stale)


def respond_to_match(
    provider_match: ProviderMatch, *, accept: bool, decline_reason: str = "", actor, django_request=None
) -> tuple[ProviderMatch, HomeVisitAssignment | None]:
    """A provider's explicit accept/decline of one offer — the "Provider
    Acceptance" capability this pipeline exists for. Accepting creates the
    HomeVisitAssignment; declining automatically offers the next-ranked
    PENDING candidate for this request, if any (see _offer_next_candidate())."""
    if provider_match.status == ProviderMatch.Status.OFFERED and provider_match.expires_at and provider_match.expires_at <= timezone.now():
        # Lazily heal a stale offer the moment anyone tries to act on it,
        # same "heal on the read/write path, don't wait for the sweep"
        # pattern as User.effective_status / heal_expired_lockout().
        expire_stale_offers(ProviderMatch.objects.filter(pk=provider_match.pk))
        provider_match.refresh_from_db()
    if provider_match.status != ProviderMatch.Status.OFFERED:
        raise ValidationError("This offer has already been responded to.")
    if accept:
        # Re-check eligibility at accept time, not just at offer time — a
        # license can expire or an account can be suspended in the gap
        # between generate_matches() offering this and the provider
        # responding. Explicitly re-fetched fresh (not provider_match.provider,
        # which may be a Provider/User instance the caller has held onto
        # since before that change happened) — is_active/effective_status
        # are plain fields on whatever Python object is in memory, unlike
        # license_alert_status (a property that always queries fresh), so
        # trusting a possibly-stale instance here would silently skip the
        # very check this re-check exists for.
        fresh_provider = Provider.objects.select_related("user").get(pk=provider_match.provider_id)
        ineligibility_reason = provider_ineligibility_reason(fresh_provider)
        if ineligibility_reason:
            raise ValidationError(ineligibility_reason)
    if accept:
        # Friendly pre-check ahead of the DB-level unique_active_assignment_per_request
        # constraint (models.py) — that constraint is the real, race-safe
        # defense (two different matches for the same request could
        # otherwise both be accepted concurrently); this just gives a clean
        # error message in the ordinary, non-racing case.
        already_assigned = HomeVisitAssignment.objects.filter(
            service_request=provider_match.service_request,
            status__in=[
                HomeVisitAssignment.Status.OFFERED,
                HomeVisitAssignment.Status.ACCEPTED,
                HomeVisitAssignment.Status.SCHEDULED,
                HomeVisitAssignment.Status.EN_ROUTE,
                HomeVisitAssignment.Status.ARRIVED,
                HomeVisitAssignment.Status.IN_PROGRESS,
            ],
        ).exists()
        if already_assigned:
            raise ValidationError("This request already has an accepted provider.")
    provider_match.status = ProviderMatch.Status.ACCEPTED if accept else ProviderMatch.Status.DECLINED
    provider_match.responded_at = timezone.now()
    provider_match.updated_by = actor
    if not accept:
        provider_match.decline_reason = decline_reason
    provider_match.full_clean()
    provider_match.save()

    service_request = provider_match.service_request
    record_audit_event(
        actor=actor,
        action="OFFER_ACCEPTED" if accept else "OFFER_DECLINED",
        obj=provider_match,
        patient=service_request.patient,
        request=django_request,
    )
    if not accept:
        notify_provider_offer_declined(provider_match, django_request=django_request)
        _offer_next_candidate(service_request, actor=actor, django_request=django_request)
        return provider_match, None
    notify_provider_offer_accepted(provider_match, django_request=django_request)

    service_request.status = MobileCareRequest.Status.ACCEPTED
    service_request.matched_provider = provider_match.provider
    service_request.updated_by = actor
    service_request.save(update_fields=["status", "matched_provider", "updated_by", "updated_at"])

    assignment = HomeVisitAssignment(
        organization=provider_match.organization,
        service_request=service_request,
        provider_match=provider_match,
        provider=provider_match.provider,
        status=HomeVisitAssignment.Status.ACCEPTED,
        accepted_at=timezone.now(),
        created_by=actor,
    )
    assignment.full_clean()
    assignment.save()
    record_audit_event(
        actor=actor,
        action="home_visit_assignment.accepted",
        obj=assignment,
        patient=service_request.patient,
        request=django_request,
    )
    return provider_match, assignment


@transaction.atomic
def schedule_assignment(
    assignment: HomeVisitAssignment, *, starts_at, ends_at, kind: str, actor, django_request=None
) -> Appointment:
    """Turn an accepted assignment into a real, home-visit Appointment —
    the same manual time-picking and conflict-recheck as schedule_appointment()
    above, just entered from the accept-first pipeline instead of the
    staff-assigns-first one."""
    locked = HomeVisitAssignment.objects.select_for_update().get(pk=assignment.pk)
    if locked.status != HomeVisitAssignment.Status.ACCEPTED:
        raise ValidationError("Only an accepted assignment can be scheduled.")
    if locked.appointment_id:
        raise ValidationError("This assignment has already been scheduled.")
    provider = locked.provider
    if not provider.user_id:
        raise ValidationError("This provider has no linked user account and cannot be scheduled.")
    _assert_within_service_hours(locked.organization, starts_at=starts_at, ends_at=ends_at)

    has_conflict = (
        Appointment.objects.select_for_update()
        .filter(therapist_id=provider.user_id, starts_at__lt=ends_at, ends_at__gt=starts_at)
        .exclude(status__in=[Appointment.Status.CANCELLED, Appointment.Status.NO_SHOW])
        .exists()
    )
    if has_conflict:
        raise ValidationError("This provider already has an appointment at that time.")

    service_request = locked.service_request
    appointment = Appointment(
        patient=service_request.patient,
        therapist=provider.user,
        provider=provider,
        kind=kind,
        starts_at=starts_at,
        ends_at=ends_at,
        location=_home_visit_address(service_request),
        is_home_visit=True,
        reason_for_visit=service_request.reason_for_visit,
        episode_of_care=service_request.episode_of_care,
        booking_source=Appointment.BookingSource.MOBILE_APP,
        created_by=actor,
    )
    appointment.full_clean()
    appointment.save()

    locked.appointment = appointment
    locked.status = HomeVisitAssignment.Status.SCHEDULED
    locked.scheduled_at = timezone.now()
    locked.updated_by = actor
    locked.full_clean()
    locked.save(update_fields=["appointment", "status", "scheduled_at", "updated_by", "updated_at"])

    service_request.status = MobileCareRequest.Status.SCHEDULED
    service_request.appointment = appointment
    service_request.updated_by = actor
    service_request.full_clean()
    service_request.save(update_fields=["status", "appointment", "updated_by", "updated_at"])

    _establish_continuity(service_request, provider)

    record_audit_event(
        actor=actor,
        action="home_visit_assignment.scheduled",
        obj=appointment,
        patient=service_request.patient,
        request=django_request,
        metadata={"assignment_id": str(locked.pk)},
    )
    notify_visit_scheduled(appointment, mobile_care_request=service_request, django_request=django_request)
    return appointment


# The provider's field-day state machine, per the app's own state-machine
# convention (see HOME_VISIT_STATUS_TRANSITIONS above for the legacy
# pipeline's narrower version): only a SCHEDULED assignment (one with an
# actual appointment time — see schedule_assignment()) can start traveling;
# an OFFERED or merely ACCEPTED-but-not-yet-scheduled assignment has no
# entry here at all, so update_assignment_status() rejects any attempt to
# skip straight to EN_ROUTE before a time is picked. Cancellation is
# allowed from every non-terminal state.
ASSIGNMENT_STATUS_TRANSITIONS = {
    HomeVisitAssignment.Status.SCHEDULED: {HomeVisitAssignment.Status.EN_ROUTE, HomeVisitAssignment.Status.CANCELLED},
    HomeVisitAssignment.Status.EN_ROUTE: {HomeVisitAssignment.Status.ARRIVED, HomeVisitAssignment.Status.CANCELLED},
    HomeVisitAssignment.Status.ARRIVED: {HomeVisitAssignment.Status.IN_PROGRESS, HomeVisitAssignment.Status.CANCELLED},
    HomeVisitAssignment.Status.IN_PROGRESS: {HomeVisitAssignment.Status.COMPLETED, HomeVisitAssignment.Status.CANCELLED},
}
_ASSIGNMENT_TIMESTAMP_FIELD = {
    HomeVisitAssignment.Status.EN_ROUTE: "en_route_at",
    HomeVisitAssignment.Status.ARRIVED: "arrived_at",
    HomeVisitAssignment.Status.COMPLETED: "completed_at",
    HomeVisitAssignment.Status.CANCELLED: "cancelled_at",
}
_ASSIGNMENT_TO_REQUEST_STATUS = {
    HomeVisitAssignment.Status.IN_PROGRESS: MobileCareRequest.Status.IN_PROGRESS,
    HomeVisitAssignment.Status.COMPLETED: MobileCareRequest.Status.COMPLETED,
    HomeVisitAssignment.Status.CANCELLED: MobileCareRequest.Status.CANCELLED,
}
_ASSIGNMENT_TO_APPOINTMENT_STATUS = {
    HomeVisitAssignment.Status.IN_PROGRESS: Appointment.Status.CHECKED_IN,
    HomeVisitAssignment.Status.COMPLETED: Appointment.Status.COMPLETED,
    HomeVisitAssignment.Status.CANCELLED: Appointment.Status.CANCELLED,
}


def update_assignment_status(
    assignment: HomeVisitAssignment, new_status: str, *, actor, reason: str = "", django_request=None
) -> HomeVisitAssignment:
    """The travel/visit-day workflow: scheduled -> en route -> arrived ->
    in progress -> completed (or cancelled from any non-terminal state) —
    see ASSIGNMENT_STATUS_TRANSITIONS for the allowed edges. Rejects any
    other transition with a ValidationError (never silently ignored) and
    records an audit event for every transition that succeeds, whether
    called here or via the lazy-expire/cascade paths elsewhere in this
    module. Mirrors onto the linked Appointment and MobileCareRequest at
    the same checkpoints update_home_visit_status() already uses for the
    legacy pipeline, so both pipelines leave the platform-wide Appointment
    record in a consistent state regardless of which one scheduled it.

    "Provider Cancellation Rules": when the assigned provider themselves
    (not staff) cancels within this organization's configured Provider
    Cancellation Notice window of the visit's scheduled start, a `reason`
    is required if MobileCareConfiguration.provider_cancellation_requires_reason
    is on (the default) — staff cancelling, or a provider cancelling with
    plenty of notice, are never required to give one. Any reason given is
    always stored on `cancel_reason`, required or not."""
    allowed = ASSIGNMENT_STATUS_TRANSITIONS.get(assignment.status, set())
    if new_status not in allowed:
        raise ValidationError(f"Cannot move this assignment from {assignment.get_status_display()} to that status.")
    if new_status == HomeVisitAssignment.Status.CANCELLED:
        is_provider_initiated = bool(assignment.provider.user_id) and assignment.provider.user_id == getattr(actor, "pk", None)
        if is_provider_initiated and assignment.appointment_id and not reason.strip():
            config = get_configuration(assignment.organization)
            if config.provider_cancellation_requires_reason:
                notice_hours = effective_provider_cancellation_notice_hours(assignment.organization)
                if assignment.appointment.starts_at - timezone.now() < timedelta(hours=notice_hours):
                    raise ValidationError(
                        f"Cancelling within {notice_hours} hours of the visit requires a reason."
                    )
    assignment.status = new_status
    assignment.updated_by = actor
    update_fields = ["status", "updated_by", "updated_at"]
    if reason.strip():
        assignment.cancel_reason = reason.strip()
        update_fields.append("cancel_reason")
    timestamp_field = _ASSIGNMENT_TIMESTAMP_FIELD.get(new_status)
    if timestamp_field:
        setattr(assignment, timestamp_field, timezone.now())
        update_fields.append(timestamp_field)
    assignment.save(update_fields=update_fields)

    service_request = assignment.service_request
    request_status = _ASSIGNMENT_TO_REQUEST_STATUS.get(new_status)
    if request_status:
        service_request.status = request_status
        service_request.updated_by = actor
        service_request.save(update_fields=["status", "updated_by", "updated_at"])

    appointment_status = _ASSIGNMENT_TO_APPOINTMENT_STATUS.get(new_status)
    if appointment_status and assignment.appointment_id:
        assignment.appointment.status = appointment_status
        assignment.appointment.save(update_fields=["status", "updated_at"])

    if new_status in (HomeVisitAssignment.Status.EN_ROUTE, HomeVisitAssignment.Status.ARRIVED):
        VisitTravelStatus.objects.create(assignment=assignment, status=new_status, created_by=actor)

    # Live-location sharing window — see care/models.py's ProviderLocationSession.
    # Opens exactly when travel starts, closes (and deletes every ping)
    # exactly when it stops being EN_ROUTE for any reason.
    if new_status == HomeVisitAssignment.Status.EN_ROUTE:
        open_location_session(assignment, actor=actor, django_request=django_request)
    elif new_status == HomeVisitAssignment.Status.ARRIVED:
        close_location_session(
            assignment, end_reason=ProviderLocationSession.EndReason.ARRIVED, actor=actor, django_request=django_request,
        )
    elif new_status == HomeVisitAssignment.Status.CANCELLED:
        close_location_session(
            assignment, end_reason=ProviderLocationSession.EndReason.CANCELLED, actor=actor, django_request=django_request,
        )

    record_audit_event(
        actor=actor,
        action="home_visit_assignment.status_updated",
        obj=assignment,
        patient=service_request.patient,
        request=django_request,
        metadata={"status": new_status, "reason": reason.strip()} if reason.strip() else {"status": new_status},
    )
    if new_status == HomeVisitAssignment.Status.EN_ROUTE:
        notify_provider_en_route(assignment, django_request=django_request)
    elif new_status == HomeVisitAssignment.Status.ARRIVED:
        notify_provider_arrived(assignment, django_request=django_request)
    elif new_status == HomeVisitAssignment.Status.COMPLETED:
        notify_visit_completed(assignment, django_request=django_request)
    elif new_status == HomeVisitAssignment.Status.CANCELLED:
        notify_visit_cancelled(service_request, django_request=django_request)
    return assignment


def log_travel_delay(assignment: HomeVisitAssignment, *, note: str = "", actor, django_request=None) -> VisitTravelStatus:
    """A provider flagging they're running late while still EN_ROUTE — logs
    to the travel timeline without changing the assignment's main status
    (unlike update_assignment_status(), there's no DELAYED state on
    HomeVisitAssignment itself; only the log distinguishes it)."""
    if assignment.status != HomeVisitAssignment.Status.EN_ROUTE:
        raise ValidationError("Only an en-route assignment can log a delay.")
    entry = VisitTravelStatus(assignment=assignment, status=VisitTravelStatus.Status.DELAYED, note=note, created_by=actor)
    entry.full_clean()
    entry.save()
    record_audit_event(
        actor=actor,
        action="home_visit_assignment.delay_logged",
        obj=assignment,
        patient=assignment.service_request.patient,
        request=django_request,
        metadata={"note": note},
    )
    return entry


def open_location_session(assignment: HomeVisitAssignment, *, actor, django_request=None) -> ProviderLocationSession:
    """Opens the sharing window for one EN_ROUTE travel segment — called
    from update_assignment_status() at the SCHEDULED/ARRIVED -> EN_ROUTE
    edge, the same place VisitTravelStatus is already logged. Lightweight,
    coordinate-free audit event (this is a lifecycle boundary, not a ping —
    see record_location_snapshot()'s docstring for why per-ping volume isn't
    audited)."""
    session = ProviderLocationSession.objects.create(assignment=assignment, created_by=actor)
    record_audit_event(
        actor=actor,
        action="provider_location_session.opened",
        obj=session,
        patient=assignment.service_request.patient,
        request=django_request,
    )
    return session


def close_location_session(
    assignment: HomeVisitAssignment, *, end_reason: str, actor, django_request=None
) -> ProviderLocationSession | None:
    """Closes assignment's currently-open location session, if any, and
    deletes every ping tied to it in the same operation — the actual
    "visit completion/cancellation removes temporary location" enforcement
    point. A no-op returning None if nothing is open (e.g. a visit
    cancelled before ever going EN_ROUTE)."""
    session = assignment.location_sessions.filter(ended_at__isnull=True).order_by("-started_at").first()
    if session is None:
        return None
    session.ended_at = timezone.now()
    session.end_reason = end_reason
    session.save(update_fields=["ended_at", "end_reason", "updated_at"])
    session.pings.all().delete()
    record_audit_event(
        actor=actor,
        action="provider_location_session.closed",
        obj=session,
        patient=assignment.service_request.patient,
        request=django_request,
        metadata={"endReason": end_reason},
    )
    return session


def record_location_snapshot(
    assignment: HomeVisitAssignment, *, latitude, longitude, accuracy_meters=None
) -> ProviderLocationSnapshot:
    """One GPS ping during the travel segment. Deliberately no audit event
    and no `actor`/`django_request` parameter — this fires frequently (every
    few seconds while en route) and the audit trail isn't the right place
    for that volume; provider_location_sharing_update() below is what's
    audited (the consent decision), and the session's own open/close is
    audited (see open_location_session()/close_location_session()) — not
    each individual ping.

    Two hard gates, in order: the provider must have explicitly opted in
    (Provider.location_sharing_enabled), and an open ProviderLocationSession
    must exist for this assignment — that session only ever exists while the
    assignment is EN_ROUTE (see update_assignment_status()), so this is
    equivalent to "no pings before travel starts or after arrival" without
    re-deriving it from assignment.status directly."""
    if not assignment.provider.location_sharing_enabled:
        raise ValidationError("This provider has not enabled location sharing.")
    session = assignment.location_sessions.filter(ended_at__isnull=True).order_by("-started_at").first()
    if session is None:
        raise ValidationError("Location can only be recorded while a visit is en route.")
    snapshot = ProviderLocationSnapshot(
        session=session, latitude=latitude, longitude=longitude, accuracy_meters=accuracy_meters
    )
    snapshot.full_clean()
    snapshot.save()
    return snapshot


def estimate_assignment_arrival(assignment: HomeVisitAssignment) -> DistanceResult:
    """Patient-facing arrival estimate for an EN_ROUTE assignment — derived
    from the provider's most recent live ping in their open
    ProviderLocationSession, never exposed to the patient as raw
    coordinates or a ping history (see
    care/api/patient_portal.py:_serialize_portal_mobile_care_request).
    Honestly reports unavailable — never a fabricated ETA — when the visit
    isn't currently EN_ROUTE, no ping has arrived yet, or (as today) no
    distance provider is connected."""
    if assignment.status != HomeVisitAssignment.Status.EN_ROUTE:
        return DistanceResult(
            available=False, distance_miles=None, estimated_drive_minutes=None,
            message="Provider is not currently en route.",
        )
    session = assignment.location_sessions.filter(ended_at__isnull=True).order_by("-started_at").first()
    latest_ping = session.pings.order_by("-created_at").first() if session else None
    if latest_ping is None:
        return DistanceResult(
            available=False, distance_miles=None, estimated_drive_minutes=None,
            message="Provider's live location is not available yet.",
        )
    destination = geocode_mobile_care_request(assignment.service_request)
    if not (destination.geocoded and destination.coordinates):
        return DistanceResult(available=False, distance_miles=None, estimated_drive_minutes=None, message=destination.message)
    origin = Coordinates(float(latest_ping.latitude), float(latest_ping.longitude))
    return get_distance_service(assignment.organization).estimate(origin=origin, destination=destination.coordinates)


def set_location_sharing(provider: Provider, enabled: bool, *, actor, django_request=None) -> Provider:
    """The provider's own explicit opt-in/out — separate from, and layered
    on top of, whatever account/employment consent already covers. This is
    the one action in this file that IS always audited, since it's a
    deliberate privacy decision, not routine operational data.

    Turning sharing off closes any currently-open location session for this
    provider immediately (end_reason=STOPPED_BY_PROVIDER) — revoking consent
    mid-trip has to actually stop sharing right away, not just block the
    *next* ping while an already-open session and its pings sit around."""
    provider.location_sharing_enabled = enabled
    provider.save(update_fields=["location_sharing_enabled", "updated_at"])
    if not enabled:
        for assignment in HomeVisitAssignment.objects.filter(provider=provider, status=HomeVisitAssignment.Status.EN_ROUTE):
            close_location_session(
                assignment, end_reason=ProviderLocationSession.EndReason.STOPPED_BY_PROVIDER,
                actor=actor, django_request=django_request,
            )
    record_audit_event(
        actor=actor,
        action="provider.location_sharing_updated",
        obj=provider,
        request=django_request,
        metadata={"enabled": enabled},
    )
    return provider


# Billing (pricing, charges, deposits, insurance/package handling for a home
# visit) lives in care/mobile_care_billing.py — see add_travel_charge(),
# create_home_visit_service_charge(), and estimate_home_visit_charges()
# there, mirroring this module's own split with mobile_care_notifications.py.
