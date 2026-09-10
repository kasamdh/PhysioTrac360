"""Clearinghouse adapter interface (CLEARINGHOUSE ARCHITECTURE).

Core billing logic (Claim, Charge, PatientInsurance) never talks to a
clearinghouse directly — every interaction goes through this adapter
interface, so a real clearinghouse integration can be swapped in later
without touching claim-lifecycle code anywhere else in the app.

No clearinghouse account or API credentials exist yet, so the only adapter
implemented today is `ManualClearinghouseAdapter`, which represents a
biller handling submission/status-checks/eligibility manually — the same
thing this app already required before this module existed — rather than
fabricating responses from a service nothing is actually connected to.
Swapping in a real adapter later (e.g. a Availity/Waystar/Change Healthcare
integration) means adding one class here and updating
`get_clearinghouse_adapter`; nothing else changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SubmitClaimResult:
    accepted: bool
    clearinghouse_claim_id: str
    message: str


@dataclass
class ClaimStatusResult:
    status: str
    message: str


@dataclass
class EraResult:
    reference: str
    available: bool
    message: str


@dataclass
class EligibilityResult:
    verified: bool
    message: str


class ClearinghouseAdapter(ABC):
    """Every clearinghouse integration implements this exact surface —
    matches the module's CLEARINGHOUSE ARCHITECTURE example interface
    (submitClaim / checkClaimStatus / fetchERA / verifyEligibility)."""

    @abstractmethod
    def submit_claim(self, claim) -> SubmitClaimResult: ...

    @abstractmethod
    def check_claim_status(self, claim) -> ClaimStatusResult: ...

    @abstractmethod
    def fetch_era(self, reference: str) -> EraResult: ...

    @abstractmethod
    def verify_eligibility(self, patient_insurance) -> EligibilityResult: ...


class ManualClearinghouseAdapter(ClearinghouseAdapter):
    """No electronic clearinghouse is connected — billing staff submit,
    check, and verify manually today, outside this application. This
    adapter formalizes that as the same interface a real integration would
    use, so nothing calling it needs to change once one is wired in."""

    NOT_CONNECTED = "No clearinghouse is connected for this organization."

    def submit_claim(self, claim) -> SubmitClaimResult:
        return SubmitClaimResult(
            accepted=True,
            clearinghouse_claim_id="",
            message="%s This claim is tracked internally only — submit it to the payer through your existing manual process." % self.NOT_CONNECTED,
        )

    def check_claim_status(self, claim) -> ClaimStatusResult:
        return ClaimStatusResult(
            status=claim.status,
            message="%s This reflects only the status last set manually in this system." % self.NOT_CONNECTED,
        )

    def fetch_era(self, reference: str) -> EraResult:
        return EraResult(
            reference=reference, available=False,
            message="%s ERA/EOB import is not available yet." % self.NOT_CONNECTED,
        )

    def verify_eligibility(self, patient_insurance) -> EligibilityResult:
        return EligibilityResult(
            verified=False,
            message="%s Verify eligibility manually with the payer before this visit." % self.NOT_CONNECTED,
        )


def get_clearinghouse_adapter(organization) -> ClearinghouseAdapter:
    """Single seam for selecting an organization's clearinghouse
    integration. Always returns the manual adapter today; a future real
    adapter would be chosen here (e.g. by an Organization field or a
    settings flag) without any caller needing to change."""
    return ManualClearinghouseAdapter()
