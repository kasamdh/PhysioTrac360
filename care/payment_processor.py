"""PAYMENT PROCESSOR ARCHITECTURE.

Mirrors care/clearinghouse.py exactly: core billing/portal code never talks
to a real payment processor directly — everything routes through this
adapter interface so a real, PCI-compliant integration (Stripe, etc.) can be
swapped in later via `get_payment_processor()` without touching a single
call site. Raw cardholder data (card number, CVV, expiration) must NEVER
pass through this application at any point — a real integration would use
the processor's own hosted/tokenizing field so our backend only ever sees
an opaque token, never the card itself. The only concrete implementation
today, `ManualPaymentProcessor`, honestly reports that online payment isn't
connected rather than fabricating a successful charge.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ChargeResult:
    succeeded: bool
    processor_reference: str
    message: str


class PaymentProcessor(ABC):
    @abstractmethod
    def charge(self, *, patient, amount: Decimal) -> ChargeResult: ...


class ManualPaymentProcessor(PaymentProcessor):
    """No processor is connected. Never fabricates a successful charge —
    every attempt honestly fails with instructions to pay another way,
    mirroring ManualClearinghouseAdapter's contract exactly."""

    NOT_CONNECTED = (
        "Online payment is not yet connected for this organization. "
        "Please call the clinic to pay by phone or in person."
    )

    def charge(self, *, patient, amount: Decimal) -> ChargeResult:
        return ChargeResult(succeeded=False, processor_reference="", message=self.NOT_CONNECTED)


def get_payment_processor(organization) -> PaymentProcessor:
    """Single factory seam — a real processor would be selected here later
    (e.g. by an Organization-level setting) with zero caller changes."""
    return ManualPaymentProcessor()
