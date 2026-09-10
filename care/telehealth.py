"""TELEHEALTH VIDEO-SESSION ARCHITECTURE.

Mirrors care/clearinghouse.py and care/payment_processor.py: core portal
code never talks to a real video vendor directly — everything routes
through this adapter interface so a real integration (Zoom, Twilio Video,
etc.) can be swapped in later via `get_telehealth_provider()` without
touching a call site.

Deliberately no persisted meeting-link field exists anywhere in this
codebase (see Appointment) — a session is minted fresh, per request, by
calling `create_session()` at join time. That is the actual mechanism that
satisfies "no static, reusable public meeting link": there is nothing
stored to leak, reuse, or share ahead of time, only a live, authenticated,
time-windowed request (see care/api/patient_portal.py's eligibility check)
that a real provider would exchange for a short-lived signed room token.

The only concrete implementation today, `ManualTelehealthProvider`,
honestly reports that video isn't connected rather than fabricating a join
link.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class JoinSessionResult:
    joinable: bool
    join_url: str | None
    message: str


class TelehealthProvider(ABC):
    @abstractmethod
    def create_session(self, appointment) -> JoinSessionResult: ...


class ManualTelehealthProvider(TelehealthProvider):
    """No video vendor is connected. Never fabricates a join link."""

    NOT_CONNECTED = (
        "Video visits are not yet connected for this organization. "
        "Please contact the clinic for instructions to join your telehealth visit."
    )

    def create_session(self, appointment) -> JoinSessionResult:
        return JoinSessionResult(joinable=False, join_url=None, message=self.NOT_CONNECTED)


def get_telehealth_provider(organization) -> TelehealthProvider:
    """Single factory seam — a real provider would be selected here later
    (e.g. by an Organization-level setting) with zero caller changes."""
    return ManualTelehealthProvider()
