"""MAP/LOCATION-SERVICES ARCHITECTURE.

Mirrors care/telehealth.py (and care/clearinghouse.py / care/payment_processor.py):
core Mobile Care code never talks to a real map vendor directly —
everything routes through three narrow interfaces, GeocodingService /
DistanceService / DirectionsService, so a real integration (Google Maps,
Mapbox, HERE, ...) can be swapped in later via get_geocoding_service() /
get_distance_service() / get_directions_service() without touching a call
site or hard-coding one vendor into domain logic.

No geocoding or distance-matrix provider is connected in this codebase
today (ServiceArea's own docstring already noted this). ManualGeocodingService
and ManualDistanceService honestly report "not available" rather than
fabricating coordinates or mileage — the same never-fabricate contract
ManualTelehealthProvider already keeps for video. Directions are
different: opening a turn-by-turn map view needs no paid API, just a
deep-link URL, so GoogleMapsDirectionsService is a real, working default —
still swappable (a different Organization might prefer Apple Maps, Waze,
...), just not a stub.

Continuous provider GPS tracking is explicitly out of scope here — see
ProviderLocationSnapshot / care/mobile_care.py's record_location_snapshot()
for that separate, opt-in, 24-hour-retention concern. Distance/directions
below use a provider's declared ServiceArea (primary ZIP/city/state — a
coverage-area proxy) as the "origin," never live GPS and never a home
address, since this app stores no home address for a provider at all.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urlencode


@dataclass(frozen=True)
class Coordinates:
    latitude: float
    longitude: float


@dataclass(frozen=True)
class GeocodeResult:
    geocoded: bool
    coordinates: Coordinates | None
    formatted_address: str
    message: str


@dataclass(frozen=True)
class DistanceResult:
    available: bool
    distance_miles: float | None
    estimated_drive_minutes: int | None
    message: str


@dataclass(frozen=True)
class DirectionsResult:
    available: bool
    url: str | None
    message: str


class GeocodingService(ABC):
    """Address -> coordinates."""

    @abstractmethod
    def geocode(self, *, address_line_1: str, city: str, state: str, zip_code: str) -> GeocodeResult: ...


class DistanceService(ABC):
    """Approximate distance and drive time between two already-geocoded points."""

    @abstractmethod
    def estimate(self, *, origin: Coordinates, destination: Coordinates) -> DistanceResult: ...


class DirectionsService(ABC):
    """A URL a browser can open to get turn-by-turn directions."""

    @abstractmethod
    def build_directions_url(self, *, destination_address: str, origin_address: str | None = None) -> DirectionsResult: ...


class ManualGeocodingService(GeocodingService):
    """No geocoding provider is connected. Never fabricates coordinates."""

    NOT_CONNECTED = "Geocoding is not connected for this organization yet."

    def geocode(self, *, address_line_1: str, city: str, state: str, zip_code: str) -> GeocodeResult:
        formatted = ", ".join(part for part in (address_line_1, city, f"{state} {zip_code}".strip()) if part)
        return GeocodeResult(geocoded=False, coordinates=None, formatted_address=formatted, message=self.NOT_CONNECTED)


class ManualDistanceService(DistanceService):
    """No distance-matrix provider is connected. Never fabricates mileage
    or drive time — a coarse ZIP-membership heuristic already exists for
    ranking purposes (care/mobile_care.py's _distance_score()); this is a
    different, precise-mileage concern that genuinely needs a real API."""

    NOT_CONNECTED = "Distance/drive-time estimation is not connected for this organization yet."

    def estimate(self, *, origin: Coordinates, destination: Coordinates) -> DistanceResult:
        return DistanceResult(available=False, distance_miles=None, estimated_drive_minutes=None, message=self.NOT_CONNECTED)


class GoogleMapsDirectionsService(DirectionsService):
    """The public, keyless Google Maps "directions" URL scheme — no API
    key or paid tier required, so unlike geocoding/distance above this can
    genuinely work today. Still just one swappable implementation behind
    the interface, not hard-coded into any call site — see
    get_directions_service()."""

    def build_directions_url(self, *, destination_address: str, origin_address: str | None = None) -> DirectionsResult:
        destination_address = (destination_address or "").strip()
        if not destination_address:
            return DirectionsResult(available=False, url=None, message="No destination address on file.")
        params = {"api": "1", "destination": destination_address}
        if origin_address and origin_address.strip():
            params["origin"] = origin_address.strip()
        return DirectionsResult(available=True, url=f"https://www.google.com/maps/dir/?{urlencode(params)}", message="")


def get_geocoding_service(organization=None) -> GeocodingService:
    """Single factory seam — a real provider would be selected here later
    (e.g. by an Organization-level setting) with zero caller changes."""
    return ManualGeocodingService()


def get_distance_service(organization=None) -> DistanceService:
    return ManualDistanceService()


def get_directions_service(organization=None) -> DirectionsService:
    return GoogleMapsDirectionsService()
