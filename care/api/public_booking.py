"""Public, unauthenticated booking API.

Every view here resolves the organization strictly from the URL/query slug —
never from a client-supplied ID — and every downstream lookup (location,
appointment type, provider) is filtered by that resolved organization. See
care/availability.py and care/booking.py for the actual availability and
booking logic; these views are a thin, minimize-what-we-expose translation
layer (see care/api/public_booking.py's serializers below — no internal IDs,
private contact info, or administrative data leaves this module).
"""
from __future__ import annotations

from django.core.cache import cache
from django.http import JsonResponse
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST

from ..availability import eligible_providers, get_available_slots
from ..booking import BookingError, BookingRequest, create_public_booking
from ..models import AppointmentType, BookingConfiguration, Location, Organization, Provider
from .utils import InvalidJSON, json_body


def _public_error(message: str, *, status: int = 400, code: str = "ERROR") -> JsonResponse:
    # {"detail": ...} matches the rest of the API (care/api/utils.py's json_error) so the
    # shared frontend request()/ApiError helper surfaces the real message instead of its
    # generic fallback; `code` is included alongside for callers that need to branch on it.
    return JsonResponse({"detail": message, "code": code}, status=status)


def _throttle(request, bucket: str, *, limit: int, window_seconds: int) -> bool:
    """Lightweight IP-based rate limit using Django's cache (no Redis required
    in dev; swap CACHES to a shared backend in production for multi-process
    accuracy). Returns True if the request should be rejected."""
    ip = request.META.get("REMOTE_ADDR", "unknown")
    key = f"throttle:{bucket}:{ip}"
    count = cache.get(key, 0)
    if count >= limit:
        return True
    cache.set(key, count + 1, timeout=window_seconds)
    return False


def _active_organization_or_404(slug: str) -> Organization | None:
    organization = Organization.objects.filter(slug=slug).first()
    if not organization:
        return None
    if organization.archived_at is not None or not organization.is_active or organization.status == Organization.Status.SUSPENDED:
        return None
    return organization


def _booking_enabled_or_none(organization: Organization) -> BookingConfiguration | None:
    config, _ = BookingConfiguration.objects.get_or_create(organization=organization)
    return config if config.online_booking_enabled else None


@require_GET
def public_organization_detail(request, slug: str):
    organization = _active_organization_or_404(slug)
    if not organization or not _booking_enabled_or_none(organization):
        return _public_error("This booking page is not available.", status=404, code="NOT_FOUND")
    return JsonResponse(
        {
            "name": organization.name,
            "slug": organization.slug,
            "logoUrl": organization.logo.url if organization.logo else None,
            "address": {
                "line1": organization.address_line_1,
                "line2": organization.address_line_2,
                "city": organization.city,
                "state": organization.state,
                "zipCode": organization.zip_code,
            },
            "phone": organization.support_phone,
            "timezone": organization.timezone,
        }
    )


@require_GET
def public_locations(request, slug: str):
    organization = _active_organization_or_404(slug)
    if not organization or not _booking_enabled_or_none(organization):
        return _public_error("This booking page is not available.", status=404, code="NOT_FOUND")
    locations = Location.objects.filter(organization=organization, is_active=True).order_by("name")
    return JsonResponse(
        {
            "locations": [
                {
                    "id": str(location.pk),
                    "name": location.name,
                    "city": location.city,
                    "state": location.state,
                    "timezone": location.timezone,
                }
                for location in locations
            ]
        }
    )


@require_GET
def public_appointment_types(request, slug: str):
    organization = _active_organization_or_404(slug)
    if not organization or not _booking_enabled_or_none(organization):
        return _public_error("This booking page is not available.", status=404, code="NOT_FOUND")
    location_id = request.GET.get("location_id", "").strip()
    queryset = AppointmentType.objects.filter(
        organization=organization, is_active=True, online_booking_enabled=True
    )
    if location_id:
        queryset = queryset.filter(
            provider_links__active=True,
            provider_links__provider__is_active=True,
            provider_links__provider__online_booking_enabled=True,
            provider_links__provider__locations__pk=location_id,
        ).distinct()
    return JsonResponse(
        {
            "appointmentTypes": [
                {
                    "id": str(appointment_type.pk),
                    "name": appointment_type.name,
                    "description": appointment_type.description,
                    "durationMinutes": appointment_type.default_duration_minutes,
                    "price": float(appointment_type.price) if appointment_type.price is not None else None,
                    "requiresNewPatient": appointment_type.requires_new_patient,
                }
                for appointment_type in queryset.order_by("name")
            ]
        }
    )


@require_GET
def public_providers(request, slug: str):
    organization = _active_organization_or_404(slug)
    if not organization or not _booking_enabled_or_none(organization):
        return _public_error("This booking page is not available.", status=404, code="NOT_FOUND")
    location_id = request.GET.get("location_id", "").strip()
    appointment_type_id = request.GET.get("appointment_type_id", "").strip()
    if not location_id or not appointment_type_id:
        return _public_error("location_id and appointment_type_id are required.", status=400, code="MISSING_PARAMETERS")
    location = Location.objects.filter(pk=location_id, organization=organization, is_active=True).first()
    if not location:
        return _public_error("This location is not available for booking.", status=404, code="NOT_FOUND")
    providers = eligible_providers(location=location, appointment_type_id=appointment_type_id, organization=organization)
    return JsonResponse(
        {
            "providers": [
                {
                    "id": str(provider.pk),
                    "displayName": f"{provider.first_name} {provider.last_name}".strip(),
                    "credentials": provider.credentials,
                    "specialty": provider.specialty,
                    "bio": provider.bio,
                }
                for provider in providers
            ]
        }
    )


@require_GET
def public_availability(request, slug: str):
    if _throttle(request, "availability", limit=60, window_seconds=60):
        return _public_error("Too many requests. Please try again shortly.", status=429, code="RATE_LIMITED")
    organization = _active_organization_or_404(slug)
    if not organization or not _booking_enabled_or_none(organization):
        return _public_error("This booking page is not available.", status=404, code="NOT_FOUND")

    location_id = request.GET.get("location_id", "").strip()
    appointment_type_id = request.GET.get("appointment_type_id", "").strip()
    provider_id = request.GET.get("provider_id", "").strip()
    date_str = request.GET.get("date", "").strip()

    if not location_id or not appointment_type_id or not date_str:
        return _public_error("location_id, appointment_type_id, and date are required.", status=400, code="MISSING_PARAMETERS")
    on_date = parse_date(date_str)
    if not on_date:
        return _public_error("Provide date as YYYY-MM-DD.", status=400, code="INVALID_DATE")

    location = Location.objects.filter(pk=location_id, organization=organization, is_active=True).first()
    if not location:
        return _public_error("This location is not available for booking.", status=404, code="NOT_FOUND")
    appointment_type = AppointmentType.objects.filter(
        pk=appointment_type_id, organization=organization, is_active=True, online_booking_enabled=True
    ).first()
    if not appointment_type:
        return _public_error("This appointment type is not available for booking.", status=404, code="NOT_FOUND")

    provider = None
    if provider_id:
        provider = Provider.objects.filter(
            pk=provider_id, organization=organization, is_active=True, online_booking_enabled=True
        ).first()
        if not provider:
            return _public_error("This provider is not available for booking.", status=404, code="NOT_FOUND")

    results = get_available_slots(
        organization=organization, location=location, appointment_type=appointment_type, on_date=on_date, provider=provider
    )
    return JsonResponse(
        {
            "date": on_date.isoformat(),
            "timezone": location.timezone,
            "providers": [
                {
                    "provider": {
                        "id": str(entry.provider.pk),
                        "displayName": f"{entry.provider.first_name} {entry.provider.last_name}".strip(),
                    },
                    "slots": [
                        {"start": slot.start.isoformat(), "end": slot.end.isoformat()} for slot in entry.slots
                    ],
                }
                for entry in results
            ],
        }
    )


@require_POST
def public_create_booking(request):
    if _throttle(request, "booking", limit=10, window_seconds=60):
        return _public_error("Too many requests. Please try again shortly.", status=429, code="RATE_LIMITED")
    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return _public_error(str(exc), status=400, code="INVALID_REQUEST")

    required = ["organizationSlug", "locationId", "appointmentTypeId", "providerId", "startDatetime", "patient"]
    missing = [key for key in required if not payload.get(key)]
    if missing:
        return _public_error(f"Missing required fields: {', '.join(missing)}.", status=400, code="MISSING_PARAMETERS")

    booking_request = BookingRequest(
        organization_slug=str(payload["organizationSlug"]),
        location_id=str(payload["locationId"]),
        appointment_type_id=str(payload["appointmentTypeId"]),
        provider_id=str(payload["providerId"]),
        start_datetime=str(payload["startDatetime"]),
        is_new_patient=bool(payload.get("isNewPatient", True)),
        patient=payload.get("patient") or {},
        reason_for_visit=str(payload.get("reasonForVisit", "")),
    )
    try:
        appointment = create_public_booking(booking_request, django_request=request)
    except BookingError as exc:
        return _public_error(exc.message, status=exc.status, code=exc.code)

    return JsonResponse(
        {
            "confirmationNumber": appointment.confirmation_number,
            "appointment": {
                "id": str(appointment.pk),
                "startsAt": appointment.starts_at.isoformat(),
                "endsAt": appointment.ends_at.isoformat(),
                "provider": f"{appointment.provider.first_name} {appointment.provider.last_name}".strip() if appointment.provider else None,
                "location": appointment.location_detail.name if appointment.location_detail else None,
                "appointmentType": appointment.appointment_type.name if appointment.appointment_type else None,
                "organization": appointment.patient.organization.name,
            },
        },
        status=201,
    )
