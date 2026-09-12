"""Staff-facing in-home PT request review/matching/scheduling, and the
provider's own home-visit field queue.

Follows this package's per-file convention of small local helpers rather
than importing another view module's private (underscore) functions — see
care/api/note_views.py / workflow_views.py for the same pattern. The
matching, scheduling, and queue logic itself lives in care/mobile_care.py;
these views only handle HTTP concerns (auth, payload parsing, serialization).
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime, parse_time
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from ..access import BILLING_ROLES, CLINICAL_ROLES, SCHEDULING_ROLES, require_patient_access, require_role
from ..entitlements import organization_has_feature
from ..services import record_audit_event
from ..mobile_care import (
    CANCELLABLE_REQUEST_STATUSES,
    DEFAULT_VISIT_DURATION_MINUTES,
    EDITABLE_REQUEST_STATUSES,
    ESTIMATED_VISIT_DURATION_MINUTES,
    build_directions_url_for_address,
    cancel_request,
    create_request,
    decline_request,
    expire_stale_offers,
    generate_matches,
    home_visit_queue,
    log_travel_delay,
    mark_offer_viewed,
    match_provider,
    matching_providers,
    offer_match,
    provider_ineligibility_reason,
    record_location_snapshot,
    request_status_history,
    respond_to_match,
    schedule_appointment,
    schedule_assignment,
    service_area_ineligibility_reason,
    set_location_sharing,
    update_assignment_status,
    update_home_visit_status,
    update_request,
)
from ..mobile_care_billing import add_travel_charge, create_home_visit_service_charge, estimate_home_visit_charges
from ..mobile_care_settings import is_mobile_care_enabled
from ..models import (
    Appointment,
    EpisodeOfCare,
    HomeVisitAssignment,
    HomeVisitAvailability,
    MobileCareRequest,
    Patient,
    Provider,
    ProviderAvailability,
    ProviderMatch,
    ServiceArea,
    ServiceAreaZipCode,
    User,
)
from .billing import serialize_charge
from .serializers import serialize_appointment, serialize_episode_of_care
from .utils import InvalidJSON, api_error, api_login_required, api_validation_error, json_body, organization_or_error

OPEN_STATUSES = (MobileCareRequest.Status.PENDING, MobileCareRequest.Status.MATCHED)
# Same scope rule workflow_views.py uses for scheduling actions: a clinician
# keeps their assigned-chart scope even here, while admin/director/scheduler
# see the whole organization's patients.
CLINICIAN_SCHEDULE_ROLES = {User.Role.THERAPIST, User.Role.ASSISTANT}


def _mobile_care_feature_or_error(organization) -> JsonResponse | None:
    """Same pattern as billing.py's _billing_feature_or_error, plus this
    organization's own admin-configurable on/off switch (see
    care/mobile_care_settings.py:is_mobile_care_enabled — defaults to True,
    so an org with no subscription at all, or one that's never touched this
    switch, stays unrestricted; only an org whose subscription lacks the
    feature, or whose admin has explicitly turned it off, is blocked)."""
    if not is_mobile_care_enabled(organization):
        return api_error("In-home PT is not enabled for this organization. Contact your administrator.", status=403)
    return None


def _validation_response(error: ValidationError) -> JsonResponse:
    if hasattr(error, "message_dict"):
        errors = error.message_dict
    else:
        errors = {"nonFieldErrors": error.messages}
    return api_validation_error(errors)


def _payload_or_error(request):
    try:
        return json_body(request), None
    except InvalidJSON as error:
        return None, api_error(str(error), status=400)


def _required_text(payload: dict, key: str, label: str, *, limit: int | None = None):
    value = payload.get(key, "")
    if not isinstance(value, str) or not value.strip():
        return None, api_error(f"{label} is required.", status=400)
    value = value.strip()
    if limit is not None and len(value) > limit:
        return None, api_error(f"{label} must be {limit} characters or fewer.", status=400)
    return value, None


def _optional_text(payload: dict, key: str, default: str = "", *, limit: int | None = None):
    value = payload.get(key, default)
    if value is None:
        return default, None
    if not isinstance(value, str):
        return None, api_error(f"{key} must be text.", status=400)
    value = value.strip()
    if limit is not None and len(value) > limit:
        return None, api_error(f"{key} must be {limit} characters or fewer.", status=400)
    return value, None


def _scheduling_patient_or_error(request, patient_id: str):
    """Same scope rule as workflow_views._operations_patient_or_error: a
    clinician retains their assigned-chart scope even for a scheduling task,
    while admin/director/scheduler see the whole organization's patients."""
    organization, error = organization_or_error(request, roles=SCHEDULING_ROLES)
    if error:
        return None, error
    feature_error = _mobile_care_feature_or_error(organization)
    if feature_error:
        return None, feature_error
    patient = Patient.objects.select_related("organization").filter(pk=patient_id).first()
    if patient is None:
        return None, api_error("Patient record was not found.", status=404)
    try:
        require_patient_access(request, patient, clinical=request.user.role in CLINICIAN_SCHEDULE_ROLES)
    except PermissionDenied as error:
        return None, api_error(str(error), status=403)
    return patient, None


def _own_provider_or_error(request):
    """The calling user's own Provider profile — the sole IDOR defense for
    every provider-facing endpoint below (offers, assignments, status
    updates): a provider only ever acts as themselves, never as a provider
    id read from a URL/body, matching require_portal_patient()'s pattern for
    the patient portal."""
    organization, error = organization_or_error(request, roles=CLINICAL_ROLES)
    if error:
        return None, error
    feature_error = _mobile_care_feature_or_error(organization)
    if feature_error:
        return None, feature_error
    provider = Provider.objects.filter(organization=organization, user=request.user, is_active=True).first()
    if provider is None:
        return None, api_error("This account has no active provider profile.", status=403)
    return provider, None


def _request_or_error(request, request_id: str):
    organization, error = organization_or_error(request, roles=SCHEDULING_ROLES)
    if error:
        return None, error
    feature_error = _mobile_care_feature_or_error(organization)
    if feature_error:
        return None, feature_error
    entry = (
        MobileCareRequest.objects.select_related("patient", "matched_provider", "appointment")
        .filter(pk=request_id, organization=organization)
        .first()
    )
    if entry is None:
        return None, api_error("Request was not found.", status=404)
    return entry, None


def _serialize_mobile_care_request(entry: MobileCareRequest) -> dict:
    return {
        "id": str(entry.pk),
        "status": entry.status,
        "statusLabel": entry.get_status_display(),
        "source": entry.source,
        "sourceLabel": entry.get_source_display(),
        "addressLine1": entry.address_line_1,
        "addressLine2": entry.address_line_2,
        "city": entry.city,
        "state": entry.state,
        "zipCode": entry.zip_code,
        "reasonForVisit": entry.reason_for_visit,
        "notes": entry.notes,
        "earliestDate": entry.earliest_date.isoformat(),
        "latestDate": entry.latest_date.isoformat() if entry.latest_date else None,
        "preferredTimeWindow": entry.preferred_time_window,
        "preferredTimeWindowLabel": entry.get_preferred_time_window_display() if entry.preferred_time_window else None,
        "requestedService": entry.requested_service,
        "requestedServiceLabel": entry.get_requested_service_display() if entry.requested_service else None,
        "specialtyRequested": entry.specialty_requested,
        "primaryCondition": entry.primary_condition,
        "providerGenderPreference": entry.provider_gender_preference,
        "providerGenderPreferenceLabel": entry.get_provider_gender_preference_display(),
        "isNewPatient": entry.is_new_patient,
        "paymentMethod": entry.payment_method,
        "paymentMethodLabel": entry.get_payment_method_display(),
        "mobilityNotes": entry.mobility_notes,
        "homeAccessNotes": entry.home_access_notes,
        "canEdit": entry.status in EDITABLE_REQUEST_STATUSES,
        "canCancel": entry.status in CANCELLABLE_REQUEST_STATUSES,
        "preferredProviderId": str(entry.preferred_provider_id) if entry.preferred_provider_id else None,
        "preferredProviderName": str(entry.preferred_provider) if entry.preferred_provider_id else None,
        "matchedProviderId": str(entry.matched_provider_id) if entry.matched_provider_id else None,
        "matchedProviderName": str(entry.matched_provider) if entry.matched_provider_id else None,
        "episodeOfCareId": str(entry.episode_of_care_id) if entry.episode_of_care_id else None,
        "appointmentId": str(entry.appointment_id) if entry.appointment_id else None,
        "appointmentStatus": entry.appointment.status if entry.appointment_id else None,
        "createdAt": timezone.localtime(entry.created_at).isoformat(),
        "patient": {"id": str(entry.patient_id), "fullName": entry.patient.full_name},
    }


def _serialize_provider_match(provider: Provider, *, continuity_provider_id) -> dict:
    return {
        "id": str(provider.pk),
        "displayName": f"{provider.first_name} {provider.last_name}".strip(),
        "credentials": provider.credentials,
        "specialty": provider.specialty,
        "isContinuity": continuity_provider_id is not None and provider.pk == continuity_provider_id,
    }


def _serialize_persisted_match(match: ProviderMatch) -> dict:
    """Staff/admin and provider-self view of one ranked candidate — includes
    the match score and reasons. Never wire this into a patient-portal view:
    care/mobile_care.py's ranking algorithm and any per-candidate reasoning
    must stay internal to staff and the offered provider themselves."""
    breakdown = match.score_breakdown or {}
    return {
        "id": str(match.pk),
        "serviceRequestId": str(match.service_request_id),
        "providerId": str(match.provider_id),
        "providerName": str(match.provider),
        "rank": match.rank,
        "matchReason": match.match_reason,
        "status": match.status,
        "statusLabel": match.get_status_display(),
        "score": float(match.score) if match.score is not None else None,
        "scoreBreakdown": {
            "continuity": breakdown.get("continuity"),
            "specialty": breakdown.get("specialty"),
            "availability": breakdown.get("availability"),
            "distance": breakdown.get("distance"),
            "preference": breakdown.get("preference"),
            "caseload": breakdown.get("caseload"),
        } if breakdown else None,
        "reasons": breakdown.get("reasons", []),
        "offeredAt": match.offered_at.isoformat() if match.offered_at else None,
        "respondedAt": match.responded_at.isoformat() if match.responded_at else None,
        "declineReason": match.decline_reason,
        "patient": {"id": str(match.service_request.patient_id), "fullName": match.service_request.patient.full_name},
        "addressLine1": match.service_request.address_line_1,
        "city": match.service_request.city,
        "state": match.service_request.state,
        "zipCode": match.service_request.zip_code,
        "earliestDate": match.service_request.earliest_date.isoformat(),
    }


def _serialize_offer_preview(match: ProviderMatch) -> dict:
    """The offered provider's own pre-acceptance view — "Do not expose
    excessive patient information before acceptance": no patient name, no
    exact street address. Once the provider accepts, they see the fuller
    HomeVisitAssignment (_serialize_assignment) instead, which does carry
    the address — accepting is the authorization boundary."""
    service_request = match.service_request
    breakdown = match.score_breakdown or {}
    distance = breakdown.get("distance")
    distance_label = (
        "Within your primary coverage area"
        if isinstance(distance, (int, float)) and distance >= 1.0
        else "Within your service area"
        if isinstance(distance, (int, float)) and distance > 0
        else None
    )
    return {
        "id": str(match.pk),
        "requestedDate": service_request.earliest_date.isoformat(),
        "preferredTimeWindow": service_request.preferred_time_window,
        "preferredTimeWindowLabel": (
            service_request.get_preferred_time_window_display() if service_request.preferred_time_window else None
        ),
        "generalArea": f"{service_request.city}, {service_request.state} {service_request.zip_code}".strip(),
        "serviceType": service_request.requested_service,
        "serviceTypeLabel": (
            service_request.get_requested_service_display() if service_request.requested_service else None
        ),
        "specialtyRequested": service_request.specialty_requested,
        "estimatedDurationMinutes": ESTIMATED_VISIT_DURATION_MINUTES.get(
            service_request.requested_service, DEFAULT_VISIT_DURATION_MINUTES
        ),
        "distanceLabel": distance_label,
        "patientStatus": "New patient" if service_request.is_new_patient else "Existing patient",
        "paymentMethodLabel": service_request.get_payment_method_display(),
        "status": match.status,
        "statusLabel": match.get_status_display(),
        "offeredAt": match.offered_at.isoformat() if match.offered_at else None,
        "expiresAt": match.expires_at.isoformat() if match.expires_at else None,
    }


def _serialize_assignment(assignment: HomeVisitAssignment) -> dict:
    appointment = assignment.appointment
    return {
        "id": str(assignment.pk),
        "serviceRequestId": str(assignment.service_request_id),
        "providerId": str(assignment.provider_id),
        "providerName": str(assignment.provider),
        "status": assignment.status,
        "statusLabel": assignment.get_status_display(),
        "acceptedAt": assignment.accepted_at.isoformat() if assignment.accepted_at else None,
        "scheduledAt": assignment.scheduled_at.isoformat() if assignment.scheduled_at else None,
        "enRouteAt": assignment.en_route_at.isoformat() if assignment.en_route_at else None,
        "arrivedAt": assignment.arrived_at.isoformat() if assignment.arrived_at else None,
        "completedAt": assignment.completed_at.isoformat() if assignment.completed_at else None,
        "cancelledAt": assignment.cancelled_at.isoformat() if assignment.cancelled_at else None,
        "appointmentId": str(assignment.appointment_id) if assignment.appointment_id else None,
        # "Time" and "General Visit Type" for the provider's Today's Home
        # Visits queue — null until schedule_assignment() picks a time.
        "visitStartsAt": appointment.starts_at.isoformat() if appointment else None,
        "visitEndsAt": appointment.ends_at.isoformat() if appointment else None,
        "visitKind": appointment.kind if appointment else None,
        "visitKindLabel": appointment.get_kind_display() if appointment else None,
        "clinicalNoteId": str(appointment.clinical_note.pk) if appointment and hasattr(appointment, "clinical_note") else None,
        "patient": {
            "id": str(assignment.service_request.patient_id),
            "fullName": assignment.service_request.patient.full_name,
        },
        "addressLine1": assignment.service_request.address_line_1,
        "addressLine2": assignment.service_request.address_line_2,
        "city": assignment.service_request.city,
        "state": assignment.service_request.state,
        "zipCode": assignment.service_request.zip_code,
    }


def _match_or_error(request, match_id: str):
    """Resolve a ProviderMatch the caller may respond to — always scoped to
    their own Provider profile, same IDOR posture as _own_provider_or_error."""
    provider, error = _own_provider_or_error(request)
    if error:
        return None, error
    match = (
        ProviderMatch.objects.select_related("service_request", "service_request__patient")
        .filter(pk=match_id, provider=provider)
        .first()
    )
    if match is None:
        return None, api_error("Offer was not found.", status=404)
    return match, None


def _own_assignment_or_error(request, assignment_id: str):
    provider, error = _own_provider_or_error(request)
    if error:
        return None, error
    assignment = (
        HomeVisitAssignment.objects.select_related("service_request", "service_request__patient")
        .filter(pk=assignment_id, provider=provider)
        .first()
    )
    if assignment is None:
        return None, api_error("Assignment was not found.", status=404)
    return assignment, None


@require_GET
@api_login_required
def mobile_care_request_list(request):
    organization, error = organization_or_error(request, roles=SCHEDULING_ROLES)
    if error:
        return error
    feature_error = _mobile_care_feature_or_error(organization)
    if feature_error:
        return feature_error
    status = request.GET.get("status", "").strip()
    entries = MobileCareRequest.objects.filter(organization=organization).select_related("patient", "matched_provider", "appointment")
    if status:
        if status not in MobileCareRequest.Status.values:
            return api_error("Unknown status filter.", status=400)
        entries = entries.filter(status=status)
    else:
        entries = entries.filter(status__in=OPEN_STATUSES)
    return JsonResponse({"requests": [_serialize_mobile_care_request(entry) for entry in entries]})


def mobile_care_dashboard_data(organization, *, own_scope: bool, user=None) -> dict:
    """Card counts plus the four main section lists — factored out of
    mobile_care_dashboard() so care/api/super_admin.py's
    privileged_mobile_care_dashboard() can reuse the exact same computation
    for a Super Admin's time-boxed break-glass view rather than duplicating
    it (that endpoint always passes own_scope=False — there is no "my own"
    scope for a platform administrator). Deliberately not underscore-prefixed:
    this package's usual "no cross-module private-helper imports" convention
    (see this module's docstring) is for per-file internals; this function
    exists specifically to be a shared, public utility."""
    today = timezone.localdate()

    home_visits_qs = Appointment.objects.filter(
        patient__organization=organization, is_home_visit=True, starts_at__date=today,
    ).exclude(status=Appointment.Status.CANCELLED).select_related("patient", "therapist")
    if own_scope:
        home_visits_qs = home_visits_qs.filter(therapist=user)
    home_visits_count = home_visits_qs.count()
    home_visits = list(home_visits_qs.order_by("starts_at")[:20])

    open_requests_qs = (
        MobileCareRequest.objects.filter(organization=organization, status__in=OPEN_STATUSES)
        .select_related("patient", "matched_provider", "appointment")
    )
    open_requests_count = open_requests_qs.count()
    unassigned_count = open_requests_qs.filter(matched_provider__isnull=True).count()
    open_requests = list(open_requests_qs.order_by("earliest_date")[:20])
    unassigned_requests = [entry for entry in open_requests if entry.matched_provider_id is None]

    episodes_qs = (
        EpisodeOfCare.objects.filter(
            organization=organization, status=EpisodeOfCare.Status.ACTIVE, mobile_care_requests__isnull=False,
        )
        .select_related("primary_therapist")
        .distinct()
    )
    episodes_count = episodes_qs.count()
    episodes = list(episodes_qs.order_by("-start_date")[:20])

    if own_scope:
        offers_count = ProviderMatch.objects.filter(
            provider__user=user, provider__organization=organization, status=ProviderMatch.Status.OFFERED,
        ).count()
    else:
        offers_count = ProviderMatch.objects.filter(
            organization=organization, status=ProviderMatch.Status.OFFERED,
        ).count()

    providers = Provider.objects.filter(organization=organization, is_active=True).select_related("user")
    if own_scope:
        providers = providers.filter(user=user)
    license_issue_count = sum(1 for provider in providers if provider_ineligibility_reason(provider) is not None)

    return {
        "cardCounts": {
            "todaysHomeVisits": home_visits_count,
            "pendingRequests": open_requests_count,
            "providerOffers": offers_count,
            "activeCareEpisodes": episodes_count,
            "visitsNeedingAssignment": unassigned_count,
            "licenseProviderIssues": license_issue_count,
        },
        "pendingRequests": [_serialize_mobile_care_request(entry) for entry in open_requests],
        "todaysHomeVisits": [serialize_appointment(appointment) for appointment in home_visits],
        "unassignedRequests": [_serialize_mobile_care_request(entry) for entry in unassigned_requests],
        "activeCareEpisodes": [serialize_episode_of_care(episode) for episode in episodes],
    }


@require_GET
@api_login_required
def mobile_care_dashboard(request):
    """Mobile Care Home / Landing page — card counts plus the four main
    section lists. Same organization_or_error(roles=SCHEDULING_ROLES) gate
    every other Mobile Care endpoint uses, so it's never reachable by a
    patient-portal account or an un-elevated Super Admin (both are
    rejected there, matching the frontend nav gate — see App.tsx's
    `canManageSchedule` check; a Super Admin's only path to this data is
    the time-boxed break-glass privileged_mobile_care_dashboard() in
    care/api/super_admin.py). Today's Home Visits and Provider Offers are
    scoped to "my own" for a PT/PTA (mirrors home_visit_queue() and
    provider_my_offers(), which already scope those same two things that
    way); Pending/Unassigned Requests and Active Care Episodes stay
    organization-wide for every scheduling-capable role, matching how the
    Requests tab itself has always behaved for PT/PTA (no per-clinician
    filtering there today) — this page doesn't invent a new, inconsistent
    scoping rule for those three."""
    organization, error = organization_or_error(request, roles=SCHEDULING_ROLES)
    if error:
        return error
    feature_error = _mobile_care_feature_or_error(organization)
    if feature_error:
        return feature_error
    own_scope = request.user.role in CLINICIAN_SCHEDULE_ROLES
    return JsonResponse(mobile_care_dashboard_data(organization, own_scope=own_scope, user=request.user))


def _extract_request_detail_fields(payload: dict) -> tuple[dict, JsonResponse | None]:
    """Parse/validate the optional descriptive fields shared by create and
    edit (requested service, specialty, time window, condition, gender
    preference, new/existing, payment method, mobility/home-access notes).
    Returns a {model_field_name: value} dict — usable directly as **kwargs
    for create_request() or as the `fields` dict for update_request() — and
    only includes keys the caller actually sent, so a partial edit payload
    only ever touches the fields it names."""
    fields: dict = {}
    if "requestedService" in payload:
        value = payload.get("requestedService") or ""
        if value and value not in MobileCareRequest.RequestedService.values:
            return {}, api_error("Choose a supported requested service.", status=400)
        fields["requested_service"] = value
    if "specialtyRequested" in payload:
        fields["specialty_requested"] = str(payload.get("specialtyRequested") or "").strip()[:120]
    if "preferredTimeWindow" in payload:
        value = payload.get("preferredTimeWindow") or ""
        if value and value not in MobileCareRequest.TimeWindow.values:
            return {}, api_error("Choose a supported time window.", status=400)
        fields["preferred_time_window"] = value
    if "primaryCondition" in payload:
        fields["primary_condition"] = str(payload.get("primaryCondition") or "").strip()[:240]
    if "providerGenderPreference" in payload:
        value = payload.get("providerGenderPreference") or MobileCareRequest.GenderPreference.NO_PREFERENCE
        if value not in MobileCareRequest.GenderPreference.values:
            return {}, api_error("Choose a supported gender preference.", status=400)
        fields["provider_gender_preference"] = value
    if "isNewPatient" in payload:
        fields["is_new_patient"] = bool(payload.get("isNewPatient"))
    if "paymentMethod" in payload:
        value = payload.get("paymentMethod") or MobileCareRequest.PaymentMethod.INSURANCE
        if value not in MobileCareRequest.PaymentMethod.values:
            return {}, api_error("Choose a supported payment method.", status=400)
        fields["payment_method"] = value
    if "mobilityNotes" in payload:
        fields["mobility_notes"] = str(payload.get("mobilityNotes") or "").strip()[:500]
    if "homeAccessNotes" in payload:
        fields["home_access_notes"] = str(payload.get("homeAccessNotes") or "").strip()[:500]
    return fields, None


@require_POST
@api_login_required
def mobile_care_request_create(request, patient_id: str):
    patient, error = _scheduling_patient_or_error(request, patient_id)
    if error:
        return error
    payload, error = _payload_or_error(request)
    if error:
        return error

    address_line_1, error = _required_text(payload, "addressLine1", "Address", limit=200)
    if error:
        return error
    address_line_2, error = _optional_text(payload, "addressLine2", limit=200)
    if error:
        return error
    city, error = _required_text(payload, "city", "City", limit=120)
    if error:
        return error
    state, error = _required_text(payload, "state", "State", limit=80)
    if error:
        return error
    zip_code, error = _required_text(payload, "zipCode", "ZIP code", limit=5)
    if error:
        return error
    reason_for_visit, error = _optional_text(payload, "reasonForVisit", limit=240)
    if error:
        return error
    notes, error = _optional_text(payload, "notes", limit=500)
    if error:
        return error

    earliest_date = parse_date(str(payload.get("earliestDate", "")))
    if not earliest_date:
        return api_error("Choose a valid earliest date.", status=400)
    latest_date = None
    if payload.get("latestDate"):
        latest_date = parse_date(str(payload["latestDate"]))
        if not latest_date:
            return api_error("Choose a valid latest date.", status=400)

    detail_fields, error_response = _extract_request_detail_fields(payload)
    if error_response:
        return error_response

    preferred_provider = None
    if payload.get("preferredProviderId"):
        preferred_provider = Provider.objects.filter(pk=payload["preferredProviderId"], organization=patient.organization_id).first()
        if preferred_provider is None:
            return api_error("Choose a preferred provider in your organization.", status=400)

    try:
        entry = create_request(
            patient,
            source=MobileCareRequest.Source.FRONT_DESK,
            address_line_1=address_line_1,
            address_line_2=address_line_2,
            city=city,
            state=state,
            zip_code=zip_code,
            reason_for_visit=reason_for_visit,
            notes=notes,
            earliest_date=earliest_date,
            latest_date=latest_date,
            preferred_provider=preferred_provider,
            created_by=request.user,
            django_request=request,
            **detail_fields,
        )
    except ValidationError as exc:
        return _validation_response(exc)
    return JsonResponse({"request": _serialize_mobile_care_request(entry)}, status=201)


@require_GET
@api_login_required
def mobile_care_request_matches(request, request_id: str):
    entry, error = _request_or_error(request, request_id)
    if error:
        return error
    providers = matching_providers(entry)
    continuity_provider_id = entry.preferred_provider_id if entry.preferred_provider_id and entry.preferred_provider.is_active else None
    return JsonResponse(
        {"providers": [_serialize_provider_match(provider, continuity_provider_id=continuity_provider_id) for provider in providers]}
    )


@require_POST
@api_login_required
def mobile_care_request_match(request, request_id: str):
    entry, error = _request_or_error(request, request_id)
    if error:
        return error
    payload, error = _payload_or_error(request)
    if error:
        return error
    provider = Provider.objects.filter(pk=payload.get("providerId"), organization=entry.organization_id).first()
    if provider is None:
        return api_error("Choose a provider in your organization.", status=400)
    try:
        match_provider(entry, provider, actor=request.user, django_request=request)
    except ValidationError as exc:
        return _validation_response(exc)
    return JsonResponse({"request": _serialize_mobile_care_request(entry)})


@require_POST
@api_login_required
def mobile_care_request_schedule(request, request_id: str):
    entry, error = _request_or_error(request, request_id)
    if error:
        return error
    payload, error = _payload_or_error(request)
    if error:
        return error
    starts_at = parse_datetime(str(payload.get("startsAt", "")))
    ends_at = parse_datetime(str(payload.get("endsAt", "")))
    if not starts_at or not ends_at:
        return api_error("Start and end must use an ISO date/time.", status=400)
    if timezone.is_naive(starts_at):
        starts_at = timezone.make_aware(starts_at, timezone.get_current_timezone())
    if timezone.is_naive(ends_at):
        ends_at = timezone.make_aware(ends_at, timezone.get_current_timezone())
    if ends_at <= starts_at:
        return api_error("End time must be after start time.", status=400)
    kind = payload.get("kind", Appointment.Kind.FOLLOW_UP)
    if kind not in Appointment.Kind.values:
        return api_error("Choose a supported appointment type.", status=400)

    try:
        appointment = schedule_appointment(
            entry, starts_at=starts_at, ends_at=ends_at, kind=kind, actor=request.user, django_request=request
        )
    except ValidationError as exc:
        message = exc.messages[0] if exc.messages else "Unable to schedule this request."
        return api_error(message, status=409)
    # schedule_appointment() saves a separately-locked copy of this row, so
    # `entry` (still held from _request_or_error above) is stale — refresh
    # before serializing the response.
    entry.refresh_from_db()
    return JsonResponse(
        {"appointment": serialize_appointment(appointment), "request": _serialize_mobile_care_request(entry)},
        status=201,
    )


@require_POST
@api_login_required
def mobile_care_request_decline(request, request_id: str):
    entry, error = _request_or_error(request, request_id)
    if error:
        return error
    try:
        decline_request(entry, actor=request.user, django_request=request)
    except ValidationError as exc:
        message = exc.messages[0] if exc.messages else "Unable to decline this request."
        return api_error(message, status=409)
    return JsonResponse({"request": _serialize_mobile_care_request(entry)})


@require_http_methods(["GET", "PATCH"])
@api_login_required
def mobile_care_request_detail(request, request_id: str):
    """Request detail, and edit-before-assignment. Editing is only allowed
    while the request is still in EDITABLE_REQUEST_STATUSES (see
    care/mobile_care.py:update_request) — once a provider has accepted, the
    address/dates/details are locked; cancel and re-request instead."""
    entry, error = _request_or_error(request, request_id)
    if error:
        return error
    if request.method == "GET":
        return JsonResponse({"request": _serialize_mobile_care_request(entry)})

    payload, error = _payload_or_error(request)
    if error:
        return error
    fields: dict = {}
    for camel, snake, limit in (
        ("addressLine1", "address_line_1", 200),
        ("addressLine2", "address_line_2", 200),
        ("city", "city", 120),
        ("state", "state", 80),
        ("zipCode", "zip_code", 5),
        ("reasonForVisit", "reason_for_visit", 240),
        ("notes", "notes", 500),
    ):
        if camel in payload:
            fields[snake] = str(payload.get(camel) or "").strip()[:limit]
    if "earliestDate" in payload:
        parsed = parse_date(str(payload.get("earliestDate", "")))
        if parsed is None:
            return api_error("earliestDate must use YYYY-MM-DD format.", status=400)
        fields["earliest_date"] = parsed
    if "latestDate" in payload:
        value = payload.get("latestDate")
        if not value:
            fields["latest_date"] = None
        else:
            parsed = parse_date(str(value))
            if parsed is None:
                return api_error("latestDate must use YYYY-MM-DD format.", status=400)
            fields["latest_date"] = parsed
    if "preferredProviderId" in payload:
        value = payload.get("preferredProviderId")
        if not value:
            fields["preferred_provider"] = None
        else:
            provider = Provider.objects.filter(pk=value, organization=entry.organization_id).first()
            if provider is None:
                return api_error("Choose a preferred provider in your organization.", status=400)
            fields["preferred_provider"] = provider

    detail_fields, error_response = _extract_request_detail_fields(payload)
    if error_response:
        return error_response
    fields.update(detail_fields)

    try:
        update_request(entry, fields, actor=request.user, django_request=request)
    except ValidationError as exc:
        return _validation_response(exc)
    return JsonResponse({"request": _serialize_mobile_care_request(entry)})


@require_POST
@api_login_required
def mobile_care_request_cancel(request, request_id: str):
    entry, error = _request_or_error(request, request_id)
    if error:
        return error
    # Unlike edit/create, a cancel confirmation from the UI may carry no body
    # at all (just "yes, cancel it") — the reason is optional, so an
    # unparseable/empty body isn't a client error here the way it is for
    # detail/create, which always expect a JSON object.
    try:
        payload = json_body(request)
    except InvalidJSON:
        payload = {}
    reason, error = _optional_text(payload, "reason", limit=240)
    if error:
        return error
    try:
        cancel_request(entry, actor=request.user, reason=reason, django_request=request)
    except ValidationError as exc:
        message = exc.messages[0] if exc.messages else "Unable to cancel this request."
        return api_error(message, status=409)
    return JsonResponse({"request": _serialize_mobile_care_request(entry)})


def _serialize_status_history_entry(event) -> dict:
    return {
        "id": str(event.pk),
        "action": event.action,
        "actorName": (event.actor.get_full_name() or event.actor.username) if event.actor_id else None,
        "createdAt": timezone.localtime(event.created_at).isoformat(),
        "metadata": event.metadata,
    }


@require_GET
@api_login_required
def mobile_care_request_status_history(request, request_id: str):
    entry, error = _request_or_error(request, request_id)
    if error:
        return error
    events = request_status_history(entry)
    return JsonResponse({"history": [_serialize_status_history_entry(event) for event in events]})


# --- Persisted offer/accept pipeline (staff side) -----------------------------


@require_POST
@api_login_required
def mobile_care_request_generate_matches(request, request_id: str):
    entry, error = _request_or_error(request, request_id)
    if error:
        return error
    matches = generate_matches(entry, actor=request.user, django_request=request)
    return JsonResponse(
        {"matches": [_serialize_persisted_match(match) for match in entry.matches.select_related("provider")]},
        status=201 if matches else 200,
    )


@require_GET
@api_login_required
def mobile_care_request_provider_matches(request, request_id: str):
    entry, error = _request_or_error(request, request_id)
    if error:
        return error
    matches = entry.matches.select_related("provider").order_by("rank")
    return JsonResponse({"matches": [_serialize_persisted_match(match) for match in matches]})


@require_POST
@api_login_required
def provider_match_offer(request, match_id: str):
    """Staff's explicit choice to send one ranked, PENDING candidate an
    offer — see offer_match()'s docstring for why this is a separate,
    deliberate step from generate_matches()."""
    organization, error = organization_or_error(request, roles=SCHEDULING_ROLES)
    if error:
        return error
    feature_error = _mobile_care_feature_or_error(organization)
    if feature_error:
        return feature_error
    match = (
        ProviderMatch.objects.select_related("provider", "service_request", "service_request__patient")
        .filter(pk=match_id, organization=organization)
        .first()
    )
    if match is None:
        return api_error("Match was not found.", status=404)
    try:
        match = offer_match(match, actor=request.user, django_request=request)
    except ValidationError as exc:
        message = exc.messages[0] if exc.messages else "Unable to offer this candidate."
        return api_error(message, status=409)
    return JsonResponse({"match": _serialize_persisted_match(match)})


# --- Persisted offer/accept pipeline (provider side) --------------------------


@require_GET
@api_login_required
def provider_my_offers(request):
    """This provider's own pending offers ("Mobile Care -> Visit Offers"),
    across every request they've been matched to — the provider-facing
    counterpart to mobile_care_request_list. Lazily expires any stale offer
    before listing (see expire_stale_offers()) and marks each returned
    offer viewed (see mark_offer_viewed()) so opening this list is itself
    the OFFER_VIEWED trigger. Uses the limited, pre-acceptance serializer —
    see _serialize_offer_preview()'s docstring."""
    provider, error = _own_provider_or_error(request)
    if error:
        return error
    expire_stale_offers(ProviderMatch.objects.filter(provider=provider))
    matches = (
        ProviderMatch.objects.filter(provider=provider, status=ProviderMatch.Status.OFFERED)
        .select_related("service_request", "service_request__patient")
        .order_by("service_request__earliest_date")
    )
    for match in matches:
        mark_offer_viewed(match, actor=request.user, django_request=request)
    return JsonResponse({"offers": [_serialize_offer_preview(match) for match in matches]})


@require_POST
@api_login_required
def provider_match_respond(request, match_id: str):
    match, error = _match_or_error(request, match_id)
    if error:
        return error
    payload, error = _payload_or_error(request)
    if error:
        return error
    accept = payload.get("accept")
    if not isinstance(accept, bool):
        return api_error("accept must be true or false.", status=400)
    decline_reason, error = _optional_text(payload, "declineReason", limit=240)
    if error:
        return error
    try:
        match, assignment = respond_to_match(
            match, accept=accept, decline_reason=decline_reason, actor=request.user, django_request=request
        )
    except ValidationError as exc:
        message = exc.messages[0] if exc.messages else "Unable to respond to this offer."
        return api_error(message, status=409)
    return JsonResponse(
        {
            "match": _serialize_persisted_match(match),
            "assignment": _serialize_assignment(assignment) if assignment else None,
        }
    )


@require_GET
@api_login_required
def provider_my_assignments(request):
    """This provider's own non-terminal assignments — accepted but not yet
    scheduled, en route, arrived, or in progress. Complements
    home_visit_queue_list (which is Appointment/date-based and only shows
    visits that already have a scheduled time)."""
    provider, error = _own_provider_or_error(request)
    if error:
        return error
    assignments = (
        HomeVisitAssignment.objects.filter(provider=provider)
        .exclude(status__in=(HomeVisitAssignment.Status.COMPLETED, HomeVisitAssignment.Status.CANCELLED, HomeVisitAssignment.Status.DECLINED))
        .select_related("service_request", "service_request__patient", "appointment", "appointment__clinical_note")
        .order_by("-created_at")
    )
    return JsonResponse({"assignments": [_serialize_assignment(assignment) for assignment in assignments]})


@require_GET
@api_login_required
def provider_todays_home_visits(request):
    """This provider's SCHEDULED-or-later accept-first-pipeline assignments
    whose appointment falls today — "Today's Home Visits," the field-day
    queue this task's UI is built around (Patient/Time/Address/General
    Visit Type/Status, with Start Travel/Arrived/Start Visit/Complete Visit
    actions). Deliberately separate from home_visit_queue_list (the older,
    Appointment.status-only queue that also covers legacy staff-assigned
    home visits, which never get a HomeVisitAssignment row at all) —
    the two pipelines' field-day workflows stay independent, matching how
    every other accept-first-pipeline function in this module already
    coexists with its legacy counterpart rather than merging into it."""
    provider, error = _own_provider_or_error(request)
    if error:
        return error
    today = timezone.localdate()
    assignments = (
        HomeVisitAssignment.objects.filter(
            provider=provider, appointment__starts_at__date=today,
        )
        .exclude(status__in=(HomeVisitAssignment.Status.CANCELLED, HomeVisitAssignment.Status.DECLINED))
        .select_related("service_request", "service_request__patient", "appointment", "appointment__clinical_note")
        .order_by("appointment__starts_at")
    )
    return JsonResponse({"visits": [_serialize_assignment(assignment) for assignment in assignments]})


@require_POST
@api_login_required
def assignment_schedule(request, assignment_id: str):
    assignment, error = _own_assignment_or_error(request, assignment_id)
    if error:
        return error
    payload, error = _payload_or_error(request)
    if error:
        return error
    starts_at = parse_datetime(str(payload.get("startsAt", "")))
    ends_at = parse_datetime(str(payload.get("endsAt", "")))
    if not starts_at or not ends_at:
        return api_error("Start and end must use an ISO date/time.", status=400)
    if timezone.is_naive(starts_at):
        starts_at = timezone.make_aware(starts_at, timezone.get_current_timezone())
    if timezone.is_naive(ends_at):
        ends_at = timezone.make_aware(ends_at, timezone.get_current_timezone())
    if ends_at <= starts_at:
        return api_error("End time must be after start time.", status=400)
    kind = payload.get("kind", Appointment.Kind.FOLLOW_UP)
    if kind not in Appointment.Kind.values:
        return api_error("Choose a supported appointment type.", status=400)
    try:
        appointment = schedule_assignment(
            assignment, starts_at=starts_at, ends_at=ends_at, kind=kind, actor=request.user, django_request=request
        )
    except ValidationError as exc:
        message = exc.messages[0] if exc.messages else "Unable to schedule this visit."
        return api_error(message, status=409)
    assignment.refresh_from_db()
    return JsonResponse(
        {"appointment": serialize_appointment(appointment), "assignment": _serialize_assignment(assignment)}, status=201
    )


@require_POST
@api_login_required
def assignment_status_update(request, assignment_id: str):
    assignment, error = _own_assignment_or_error(request, assignment_id)
    if error:
        return error
    payload, error = _payload_or_error(request)
    if error:
        return error
    new_status = str(payload.get("status", ""))
    try:
        update_assignment_status(assignment, new_status, actor=request.user, django_request=request)
    except ValidationError as exc:
        message = exc.messages[0] if exc.messages else "Unable to update this assignment."
        return api_error(message, status=409)
    return JsonResponse({"assignment": _serialize_assignment(assignment)})


def _serialize_travel_status(entry) -> dict:
    return {
        "id": str(entry.pk),
        "status": entry.status,
        "statusLabel": entry.get_status_display(),
        "note": entry.note,
        "createdAt": timezone.localtime(entry.created_at).isoformat(),
    }


@require_GET
@api_login_required
def assignment_travel_log(request, assignment_id: str):
    assignment, error = _own_assignment_or_error(request, assignment_id)
    if error:
        return error
    entries = assignment.travel_log.all()
    return JsonResponse({"travelLog": [_serialize_travel_status(entry) for entry in entries]})


@require_POST
@api_login_required
def assignment_log_delay(request, assignment_id: str):
    assignment, error = _own_assignment_or_error(request, assignment_id)
    if error:
        return error
    payload, error = _payload_or_error(request)
    if error:
        return error
    note, error = _optional_text(payload, "note", limit=240)
    if error:
        return error
    try:
        entry = log_travel_delay(assignment, note=note, actor=request.user, django_request=request)
    except ValidationError as exc:
        message = exc.messages[0] if exc.messages else "Unable to log a delay."
        return api_error(message, status=409)
    return JsonResponse({"travelStatus": _serialize_travel_status(entry)}, status=201)


@require_POST
@api_login_required
def assignment_record_location(request, assignment_id: str):
    """A single GPS ping while en route — see
    care/mobile_care.py:record_location_snapshot for the two hard gates
    (provider opt-in, assignment must be EN_ROUTE) and why this deliberately
    isn't audited per-ping."""
    assignment, error = _own_assignment_or_error(request, assignment_id)
    if error:
        return error
    payload, error = _payload_or_error(request)
    if error:
        return error
    try:
        # Round-trip through str() first: DecimalField assigned a raw Python
        # float captures its full binary floating-point expansion (dozens of
        # digits) rather than the short decimal form, and fails the
        # decimal_places=6 validation. str() gives the short, expected form.
        latitude = Decimal(str(payload.get("latitude")))
        longitude = Decimal(str(payload.get("longitude")))
    except (TypeError, ValueError, InvalidOperation):
        return api_error("latitude and longitude are required numbers.", status=400)
    accuracy_meters = payload.get("accuracyMeters")
    try:
        accuracy_meters = int(accuracy_meters) if accuracy_meters is not None else None
    except (TypeError, ValueError):
        return api_error("accuracyMeters must be a whole number.", status=400)
    try:
        record_location_snapshot(assignment, latitude=latitude, longitude=longitude, accuracy_meters=accuracy_meters)
    except ValidationError as exc:
        message = exc.messages[0] if exc.messages else "Unable to record location."
        return api_error(message, status=409)
    return JsonResponse({"recorded": True}, status=201)


@require_POST
@api_login_required
def provider_location_sharing_update(request):
    """The provider's own explicit opt-in/out toggle — see
    care/mobile_care.py:set_location_sharing."""
    provider, error = _own_provider_or_error(request)
    if error:
        return error
    payload, error = _payload_or_error(request)
    if error:
        return error
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        return api_error("enabled must be true or false.", status=400)
    set_location_sharing(provider, enabled, actor=request.user, django_request=request)
    return JsonResponse({"locationSharingEnabled": provider.location_sharing_enabled})


# --- Provider: home-visit field queue ----------------------------------------


@require_GET
@api_login_required
def home_visit_queue_list(request):
    """This clinician's own home-visit appointments for one date (default
    today) — deliberately always scoped to `request.user` regardless of role,
    since "my field queue" has no meaningful org-wide variant."""
    organization, error = organization_or_error(request, roles=CLINICAL_ROLES)
    if error:
        return error
    feature_error = _mobile_care_feature_or_error(organization)
    if feature_error:
        return feature_error
    date_param = request.GET.get("date", "")
    on_date = parse_date(date_param) if date_param else timezone.localdate()
    if on_date is None:
        return api_error("date must use YYYY-MM-DD format.", status=400)
    appointments = home_visit_queue(request.user, on_date=on_date)
    return JsonResponse({"date": on_date.isoformat(), "visits": [serialize_appointment(item) for item in appointments]})


@require_GET
@api_login_required
def mobile_care_directions(request):
    """A directions URL for a given address — the one call site that
    knows which map vendor to use (see care/mapping.py's
    get_directions_service()); the frontend never constructs a map-vendor
    URL itself. Takes a plain address string rather than a specific
    request/appointment id since a legacy home-visit Appointment doesn't
    always have a MobileCareRequest behind it to look one up from."""
    organization, error = organization_or_error(request, roles=SCHEDULING_ROLES)
    if error:
        return error
    address = request.GET.get("address", "").strip()
    if not address:
        return api_error("An address is required.", status=400)
    result = build_directions_url_for_address(organization, address)
    return JsonResponse({"available": result.available, "url": result.url, "message": result.message})


@require_POST
@api_login_required
def home_visit_status_update(request, appointment_id: str):
    organization, error = organization_or_error(request, roles=CLINICAL_ROLES)
    if error:
        return error
    feature_error = _mobile_care_feature_or_error(organization)
    if feature_error:
        return feature_error
    appointment = Appointment.objects.select_related("patient").filter(pk=appointment_id, therapist=request.user).first()
    if appointment is None:
        return api_error("Visit was not found.", status=404)
    payload, error = _payload_or_error(request)
    if error:
        return error
    new_status = str(payload.get("status", ""))
    try:
        update_home_visit_status(appointment, new_status, actor=request.user, django_request=request)
    except ValidationError as exc:
        message = exc.messages[0] if exc.messages else "Unable to update this visit."
        return api_error(message, status=409)
    return JsonResponse({"appointment": serialize_appointment(appointment)})


@require_GET
@api_login_required
def provider_options(request):
    """Every active provider in the org, for the service-area admin form's
    provider picker — deliberately not filtered by ZIP (that's
    matching_providers(), for a specific request)."""
    organization, error = organization_or_error(request, roles=SCHEDULING_ROLES)
    if error:
        return error
    feature_error = _mobile_care_feature_or_error(organization)
    if feature_error:
        return feature_error
    providers = Provider.objects.filter(organization=organization, is_active=True).order_by("last_name", "first_name")
    return JsonResponse({"providers": [_serialize_provider_match(provider, continuity_provider_id=None) for provider in providers]})


# --- Billing: home-visit pricing, service charge, and travel fee -----------


def _billing_gate_or_error(request, entry_id: str):
    """Shared setup for the three billing views below: BILLING_ROLES +
    the "billing" feature + the request itself, tenant-scoped."""
    organization, error = organization_or_error(request, roles=BILLING_ROLES)
    if error:
        return None, None, error
    if not organization_has_feature(organization, "billing"):
        return None, None, api_error("Billing is not enabled for this organization. Contact your administrator.", status=403)
    feature_error = _mobile_care_feature_or_error(organization)
    if feature_error:
        return None, None, feature_error
    entry = (
        MobileCareRequest.objects.filter(pk=entry_id, organization=organization)
        .select_related("appointment", "appointment__patient", "patient")
        .first()
    )
    if entry is None:
        return None, None, api_error("Request was not found.", status=404)
    return organization, entry, None


def serialize_home_visit_billing_estimate(estimate) -> dict:
    return {
        "paymentMethod": estimate.payment_method,
        "pricingConfigured": estimate.pricing_configured,
        "servicePriceLabel": estimate.service_price_label,
        "servicePriceAmount": str(estimate.service_price_amount) if estimate.service_price_amount is not None else None,
        "travelFeeLabel": estimate.travel_fee_label,
        "travelFeeAmount": str(estimate.travel_fee_amount) if estimate.travel_fee_amount is not None else None,
        "depositAmount": str(estimate.deposit_amount) if estimate.deposit_amount is not None else None,
        "copayAmount": str(estimate.copay_amount) if estimate.copay_amount is not None else None,
        "packageApplied": estimate.package_applied,
        "packageName": estimate.package_name,
        "totalChargeAmount": str(estimate.total_charge_amount),
        "patientResponsibility": str(estimate.patient_responsibility) if estimate.patient_responsibility is not None else None,
    }


@require_GET
@api_login_required
def mobile_care_request_billing_estimate(request, request_id: str):
    """The Home PT Initial Evaluation/Follow-Up + optional travel fee
    breakdown for one request, using this organization's configured
    ServicePrice rows — see care/mobile_care_billing.py:estimate_home_visit_charges.
    Read-only; never creates a Charge."""
    _organization, entry, error = _billing_gate_or_error(request, request_id)
    if error:
        return error
    estimate = estimate_home_visit_charges(entry)
    return JsonResponse({"estimate": serialize_home_visit_billing_estimate(estimate)})


@require_POST
@api_login_required
def mobile_care_request_add_service_charge(request, request_id: str):
    """Bills the visit itself (the "Service Price" line) once it's
    completed — see care/mobile_care_billing.py:create_home_visit_service_charge.
    Uses the organization's configured price for this visit's kind; there is
    no override here (unlike the travel fee below) since the service price
    is the visit, not an optional add-on staff might reasonably adjust."""
    _organization, entry, error = _billing_gate_or_error(request, request_id)
    if error:
        return error
    if not entry.appointment_id:
        return api_error("This request has not been scheduled yet.", status=409)
    try:
        charge = create_home_visit_service_charge(entry.appointment, actor=request.user, django_request=request)
    except ValidationError as exc:
        return _validation_response(exc)
    return JsonResponse({"charge": serialize_charge(charge)}, status=201)


@require_POST
@api_login_required
def mobile_care_request_add_travel_charge(request, request_id: str):
    """Explicit, staff-triggered billing line item for a completed home
    visit's travel cost — see care/mobile_care_billing.py:add_travel_charge
    for why this is a new, narrow entry point onto the existing Charge model
    rather than a change to care/api/billing.py. cptCode/chargeAmount are
    both optional — omit either to use the organization's configured travel
    fee ("Travel Fee if configured"); supply them to override for this one
    visit."""
    _organization, entry, error = _billing_gate_or_error(request, request_id)
    if error:
        return error
    if not entry.appointment_id:
        return api_error("This request has not been scheduled yet.", status=409)
    payload, error = _payload_or_error(request)
    if error:
        return error
    cpt_code = payload.get("cptCode")
    if cpt_code is not None:
        if not isinstance(cpt_code, str) or not cpt_code.strip():
            return api_validation_error({"cptCode": "CPT/HCPCS code cannot be blank when provided."})
        cpt_code = cpt_code.strip().upper()
    try:
        charge = add_travel_charge(
            entry.appointment,
            cpt_code=cpt_code,
            charge_amount=payload.get("chargeAmount"),
            created_by=request.user,
            django_request=request,
        )
    except ValidationError as exc:
        return _validation_response(exc)
    return JsonResponse({"charge": serialize_charge(charge)}, status=201)


# --- Admin: provider service areas -------------------------------------------
#
# Read is open to any SCHEDULING_ROLES member (matching_providers() already
# implicitly reveals coverage to them); writes are ADMIN/DIRECTOR-only — an
# organization admin manages their own org's providers, never another
# tenant's (organization_or_error()/tenant scoping), and a platform super
# admin has no standing access here either, same as everywhere else in this
# codebase — they'd need the existing PrivilegedAccessGrant break-glass flow.

_ZIP_RE = re.compile(r"^\d{5}$")
SERVICE_AREA_ADMIN_ROLES = {User.Role.ADMIN, User.Role.DIRECTOR}


def _serialize_service_area(area: ServiceArea) -> dict:
    ineligibility_reason = service_area_ineligibility_reason(area)
    return {
        "id": str(area.pk),
        "name": area.name,
        "isActive": area.is_active,
        "providerId": str(area.provider_id),
        "providerName": str(area.provider),
        "zipCodes": sorted(zip_code.zip_code for zip_code in area.zip_codes.all()),
        "primaryZipCode": area.primary_zip_code,
        "city": area.city,
        "state": area.state,
        "radiusMiles": area.radius_miles,
        "maxTravelDistanceMiles": area.max_travel_distance_miles,
        "isEligible": ineligibility_reason is None,
        "ineligibilityReason": ineligibility_reason,
    }


def _replace_zip_codes(area: ServiceArea, zip_codes) -> str | None:
    """Validate and replace this area's covered ZIP codes wholesale (the UI
    edits the full list at once, not one ZIP at a time). Returns an error
    message on failure, or None on success."""
    cleaned: list[str] = []
    for raw in zip_codes:
        value = str(raw).strip()
        if not _ZIP_RE.match(value):
            return f"'{value}' is not a valid 5-digit ZIP code."
        if value not in cleaned:
            cleaned.append(value)
    area.zip_codes.all().delete()
    ServiceAreaZipCode.objects.bulk_create([ServiceAreaZipCode(service_area=area, zip_code=z) for z in cleaned])
    return None


def _apply_service_area_payload(area: ServiceArea, payload: dict) -> JsonResponse | None:
    if "primaryZipCode" in payload:
        value = str(payload.get("primaryZipCode") or "").strip()
        if value and not _ZIP_RE.match(value):
            return api_error("primaryZipCode must be a valid 5-digit ZIP code.", status=400)
        area.primary_zip_code = value
    if "city" in payload:
        area.city = str(payload.get("city") or "").strip()[:120]
    if "state" in payload:
        area.state = str(payload.get("state") or "").strip()[:80]
    if "radiusMiles" in payload:
        value = payload.get("radiusMiles")
        if value in (None, ""):
            area.radius_miles = None
        else:
            try:
                area.radius_miles = int(value)
            except (TypeError, ValueError):
                return api_error("radiusMiles must be a whole number.", status=400)
    if "maxTravelDistanceMiles" in payload:
        value = payload.get("maxTravelDistanceMiles")
        if value in (None, ""):
            area.max_travel_distance_miles = None
        else:
            try:
                area.max_travel_distance_miles = int(value)
            except (TypeError, ValueError):
                return api_error("maxTravelDistanceMiles must be a whole number.", status=400)
    return None


@require_http_methods(["GET", "POST"])
@api_login_required
def service_areas(request):
    organization, error = organization_or_error(request, roles=SCHEDULING_ROLES)
    if error:
        return error
    feature_error = _mobile_care_feature_or_error(organization)
    if feature_error:
        return feature_error

    if request.method == "GET":
        areas = (
            ServiceArea.objects.filter(organization=organization)
            .select_related("provider", "provider__user")
            .prefetch_related("zip_codes", "provider__user__licenses")
            .order_by("provider__last_name", "name")
        )
        state_param = request.GET.get("state", "").strip()
        if state_param:
            areas = areas.filter(state__iexact=state_param)
        if request.GET.get("includeInactive") != "true":
            areas = areas.filter(is_active=True)
        serialized = [_serialize_service_area(area) for area in areas]
        if request.GET.get("eligibleOnly") == "true":
            serialized = [row for row in serialized if row["isEligible"]]
        return JsonResponse({"serviceAreas": serialized})

    try:
        require_role(request.user, SERVICE_AREA_ADMIN_ROLES)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    payload, error = _payload_or_error(request)
    if error:
        return error
    name, error = _required_text(payload, "name", "Name", limit=120)
    if error:
        return error
    provider = Provider.objects.filter(pk=payload.get("providerId"), organization=organization).first()
    if provider is None:
        return api_error("Choose a provider in your organization.", status=400)

    area = ServiceArea(organization=organization, provider=provider, name=name, created_by=request.user)
    payload_error = _apply_service_area_payload(area, payload)
    if payload_error:
        return payload_error
    try:
        area.full_clean()
        area.save()
    except ValidationError as exc:
        return _validation_response(exc)
    zip_codes = payload.get("zipCodes")
    if isinstance(zip_codes, list) and zip_codes:
        zip_error = _replace_zip_codes(area, zip_codes)
        if zip_error:
            area.delete()
            return api_validation_error({"zipCodes": zip_error})
    record_audit_event(
        actor=request.user,
        action="service_area.created",
        obj=area,
        request=request,
        metadata={"provider": str(provider)},
    )
    return JsonResponse({"serviceArea": _serialize_service_area(area)}, status=201)


@require_http_methods(["GET", "PATCH", "DELETE"])
@api_login_required
def service_area_detail(request, service_area_id):
    organization, error = organization_or_error(request, roles=SCHEDULING_ROLES)
    if error:
        return error
    feature_error = _mobile_care_feature_or_error(organization)
    if feature_error:
        return feature_error
    area = (
        ServiceArea.objects.filter(pk=service_area_id, organization=organization)
        .select_related("provider", "provider__user")
        .prefetch_related("zip_codes", "provider__user__licenses")
        .first()
    )
    if area is None:
        return api_error("Service area was not found.", status=404)

    if request.method == "GET":
        return JsonResponse({"serviceArea": _serialize_service_area(area)})

    try:
        require_role(request.user, SERVICE_AREA_ADMIN_ROLES)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)

    if request.method == "DELETE":
        if not area.is_active:
            return api_error("This service area is already inactive.", status=409)
        area.is_active = False
        area.updated_by = request.user
        area.save(update_fields=["is_active", "updated_by", "updated_at"])
        record_audit_event(actor=request.user, action="service_area.deactivated", obj=area, request=request)
        return JsonResponse({"serviceArea": _serialize_service_area(area)})

    payload, error = _payload_or_error(request)
    if error:
        return error
    if "name" in payload:
        name, error = _required_text(payload, "name", "Name", limit=120)
        if error:
            return error
        area.name = name
    if "isActive" in payload:
        area.is_active = bool(payload["isActive"])
    payload_error = _apply_service_area_payload(area, payload)
    if payload_error:
        return payload_error
    area.updated_by = request.user
    try:
        area.full_clean()
        area.save()
    except ValidationError as exc:
        return _validation_response(exc)
    if "zipCodes" in payload:
        zip_codes = payload["zipCodes"]
        if not isinstance(zip_codes, list) or not zip_codes:
            return api_validation_error({"zipCodes": "Add at least one ZIP code."})
        zip_error = _replace_zip_codes(area, zip_codes)
        if zip_error:
            return api_validation_error({"zipCodes": zip_error})
    record_audit_event(actor=request.user, action="service_area.updated", obj=area, request=request)
    return JsonResponse({"serviceArea": _serialize_service_area(area)})


# --- Provider home-visit availability -----------------------------------------
#
# Authorization: a PT/PTA may only manage their own availability; ADMIN/
# DIRECTOR may manage any provider's within their organization (the "admin
# permission" the product brief calls for). SCHEDULER/BILLER/COMPLIANCE have
# no access at all — this is the clinician's own schedule, not a front-desk
# or billing concern. Tenant isolation and the "no platform super admin"
# rule both come from organization_or_error()/organization_required(), the
# same as every other endpoint in this codebase — a super admin must use the
# existing PrivilegedAccessGrant break-glass flow (care/privileged_access.py)
# like any other tenant data, not a special case added here.

AVAILABILITY_ROLES = {User.Role.ADMIN, User.Role.DIRECTOR, User.Role.THERAPIST, User.Role.ASSISTANT}
AVAILABILITY_ADMIN_ROLES = {User.Role.ADMIN, User.Role.DIRECTOR}


def _own_provider_for_user(organization, user):
    return Provider.objects.filter(organization=organization, user=user).first()


def _can_manage_availability(user, provider) -> bool:
    if user.role in AVAILABILITY_ADMIN_ROLES:
        return True
    return provider.user_id == user.id


def _serialize_availability(row: HomeVisitAvailability) -> dict:
    return {
        "id": str(row.pk),
        "providerId": str(row.provider_id),
        "providerName": str(row.provider),
        "availabilityType": row.availability_type,
        "availabilityTypeLabel": row.get_availability_type_display(),
        "isRecurring": row.is_recurring,
        "dayOfWeek": row.day_of_week,
        "dayOfWeekLabel": row.get_day_of_week_display() if row.day_of_week is not None else None,
        "specificDate": row.specific_date.isoformat() if row.specific_date else None,
        "startTime": row.start_time.strftime("%H:%M"),
        "endTime": row.end_time.strftime("%H:%M"),
        "serviceAreaId": str(row.service_area_id) if row.service_area_id else None,
        "serviceAreaName": row.service_area.name if row.service_area_id else None,
        "effectiveFrom": row.effective_from.isoformat() if row.effective_from else None,
        "effectiveUntil": row.effective_until.isoformat() if row.effective_until else None,
        "notes": row.notes,
        "isActive": row.is_active,
        "createdAt": timezone.localtime(row.created_at).isoformat(),
    }


def _apply_availability_payload(row: HomeVisitAvailability, payload: dict) -> JsonResponse | None:
    if "availabilityType" in payload:
        value = payload["availabilityType"]
        if value not in HomeVisitAvailability.AvailabilityType.values:
            return api_error("Choose a supported availability type.", status=400)
        row.availability_type = value
    if "isRecurring" in payload:
        row.is_recurring = bool(payload["isRecurring"])
    if "dayOfWeek" in payload:
        value = payload["dayOfWeek"]
        if value is None or value == "":
            row.day_of_week = None
        else:
            try:
                day = int(value)
            except (TypeError, ValueError):
                return api_error("dayOfWeek must be a whole number 0-6.", status=400)
            if day not in ProviderAvailability.Weekday.values:
                return api_error("Choose a valid day of week.", status=400)
            row.day_of_week = day
    if "specificDate" in payload:
        value = payload["specificDate"]
        if not value:
            row.specific_date = None
        else:
            parsed = parse_date(str(value))
            if parsed is None:
                return api_error("specificDate must use YYYY-MM-DD format.", status=400)
            row.specific_date = parsed
    if "startTime" in payload:
        parsed = parse_time(str(payload.get("startTime", "")))
        if parsed is None:
            return api_error("startTime must use HH:MM format.", status=400)
        row.start_time = parsed
    if "endTime" in payload:
        parsed = parse_time(str(payload.get("endTime", "")))
        if parsed is None:
            return api_error("endTime must use HH:MM format.", status=400)
        row.end_time = parsed
    if "serviceAreaId" in payload:
        value = payload["serviceAreaId"]
        if not value:
            row.service_area = None
        else:
            area = ServiceArea.objects.filter(pk=value, organization=row.organization_id, provider=row.provider_id).first()
            if area is None:
                return api_error("Choose a service area belonging to this provider.", status=400)
            row.service_area = area
    if "effectiveFrom" in payload:
        value = payload["effectiveFrom"]
        if not value:
            row.effective_from = None
        else:
            parsed = parse_date(str(value))
            if parsed is None:
                return api_error("effectiveFrom must use YYYY-MM-DD format.", status=400)
            row.effective_from = parsed
    if "effectiveUntil" in payload:
        value = payload["effectiveUntil"]
        if not value:
            row.effective_until = None
        else:
            parsed = parse_date(str(value))
            if parsed is None:
                return api_error("effectiveUntil must use YYYY-MM-DD format.", status=400)
            row.effective_until = parsed
    if "notes" in payload:
        row.notes = str(payload.get("notes") or "")[:500]
    if "isActive" in payload:
        row.is_active = bool(payload["isActive"])
    return None


@require_http_methods(["GET", "POST"])
@api_login_required
def home_visit_availability_list(request):
    organization, error = organization_or_error(request, roles=AVAILABILITY_ROLES)
    if error:
        return error
    feature_error = _mobile_care_feature_or_error(organization)
    if feature_error:
        return feature_error
    is_admin = request.user.role in AVAILABILITY_ADMIN_ROLES

    if request.method == "GET":
        rows = HomeVisitAvailability.objects.filter(organization=organization).select_related("provider", "service_area")
        if is_admin:
            provider_id_param = request.GET.get("providerId", "").strip()
            if provider_id_param:
                rows = rows.filter(provider_id=provider_id_param)
        else:
            own_provider = _own_provider_for_user(organization, request.user)
            if own_provider is None:
                return JsonResponse({"availability": []})
            rows = rows.filter(provider=own_provider)
        if request.GET.get("includeInactive") != "true":
            rows = rows.filter(is_active=True)
        return JsonResponse({"availability": [_serialize_availability(row) for row in rows]})

    payload, error = _payload_or_error(request)
    if error:
        return error

    if is_admin and payload.get("providerId"):
        provider = Provider.objects.filter(pk=payload.get("providerId"), organization=organization).first()
        if provider is None:
            return api_error("Choose a provider in your organization.", status=400)
    else:
        provider = _own_provider_for_user(organization, request.user)
        if provider is None:
            return api_error("This account has no active provider profile.", status=403)
    if not _can_manage_availability(request.user, provider):
        return api_error("You may only manage your own availability.", status=403)

    row = HomeVisitAvailability(organization=organization, provider=provider, created_by=request.user)
    error_response = _apply_availability_payload(row, payload)
    if error_response:
        return error_response
    try:
        row.full_clean()
        row.save()
    except ValidationError as exc:
        return _validation_response(exc)
    record_audit_event(
        actor=request.user,
        action="home_visit_availability.created",
        obj=row,
        request=request,
        metadata={"provider": str(provider), "availabilityType": row.availability_type},
    )
    return JsonResponse({"availability": _serialize_availability(row)}, status=201)


@require_http_methods(["GET", "PATCH", "DELETE"])
@api_login_required
def home_visit_availability_detail(request, availability_id):
    organization, error = organization_or_error(request, roles=AVAILABILITY_ROLES)
    if error:
        return error
    feature_error = _mobile_care_feature_or_error(organization)
    if feature_error:
        return feature_error
    row = (
        HomeVisitAvailability.objects.filter(pk=availability_id, organization=organization)
        .select_related("provider", "service_area")
        .first()
    )
    if row is None:
        return api_error("Availability window was not found.", status=404)
    if not _can_manage_availability(request.user, row.provider):
        return api_error("You may only manage your own availability.", status=403)

    if request.method == "GET":
        return JsonResponse({"availability": _serialize_availability(row)})

    if request.method == "DELETE":
        if not row.is_active:
            return api_error("This availability window is already inactive.", status=409)
        row.is_active = False
        row.updated_by = request.user
        row.save(update_fields=["is_active", "updated_by", "updated_at"])
        record_audit_event(actor=request.user, action="home_visit_availability.deactivated", obj=row, request=request)
        return JsonResponse({"availability": _serialize_availability(row)})

    payload, error = _payload_or_error(request)
    if error:
        return error
    error_response = _apply_availability_payload(row, payload)
    if error_response:
        return error_response
    row.updated_by = request.user
    try:
        row.full_clean()
        row.save()
    except ValidationError as exc:
        return _validation_response(exc)
    record_audit_event(actor=request.user, action="home_visit_availability.updated", obj=row, request=request)
    return JsonResponse({"availability": _serialize_availability(row)})
