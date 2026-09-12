"""Mobile Care <-> existing billing integration.

No new payment or billing system: everything here is a second, narrower
entry point onto tables that already exist and are already used by the
clinic-visit billing flow (care/api/billing.py) — Charge, ServicePrice,
CashPackage, PatientInsurance, PatientPayment — mirroring how
add_travel_charge() already reused Charge before this module existed, and
how care/mapping.py/care/payment_processor.py already keep one adapter
seam per external concern rather than growing a parallel implementation.

Pricing is entirely organization-configured, never hard-coded: an org tags
up to one ServicePrice row per Appointment.Kind (its "Home PT Initial
Evaluation" price, its "Home PT Follow-Up" price, ...) via
`home_visit_kind`, and at most one row as its optional travel fee via
`is_home_visit_travel_fee` (see ServicePrice's docstring in models.py).
home_visit_price_quote() is the one place that reads those tags;
estimate_home_visit_charges() and the two charge-creation functions below
are the only other things that call it — nothing else in this codebase
should hard-code a CPT code or dollar amount for a home visit.

Self-pay/insurance/package are three different outcomes of the same quote,
not three different code paths bolted on separately:
  - self-pay -> a Charge is created for the patient to pay directly (same
    Charge table clinic visits already use — staff can still put it on a
    Superbill through the existing flow);
  - insurance -> the same Charge, left available for staff to attach to a
    Claim through the existing claims flow — this module never creates a
    Claim itself, same "billing staff decide when to actually bill" posture
    the rest of this app already has;
  - package/membership -> no Charge at all. The visit is already paid for;
    staff record its use against the CashPackage through the existing
    "record_visit" action in care/api/billing.py, exactly as they would for
    any other package-covered visit — this module does not duplicate that.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError

from .models import Appointment, CashPackage, Charge, MobileCareRequest, PatientInsurance, ServicePrice
from .services import record_audit_event


@dataclass(frozen=True)
class HomeVisitPriceQuote:
    """The organization's configured home-visit pricing for one visit kind,
    read fresh every time rather than cached — a price change should take
    effect on the next lookup, not require a restart. `configured=False`
    when the org hasn't tagged a ServicePrice for this kind yet; callers
    must treat that honestly (no fabricated price), not fall back to a
    guessed number."""

    configured: bool
    service_price: ServicePrice | None
    travel_fee_price: ServicePrice | None


def home_visit_price_quote(organization, kind: str) -> HomeVisitPriceQuote:
    service_price = ServicePrice.objects.filter(
        organization=organization, home_visit_kind=kind, is_active=True
    ).first()
    travel_fee_price = ServicePrice.objects.filter(
        organization=organization, is_home_visit_travel_fee=True, is_active=True
    ).first()
    return HomeVisitPriceQuote(configured=service_price is not None, service_price=service_price, travel_fee_price=travel_fee_price)


@dataclass(frozen=True)
class HomeVisitBillingEstimate:
    """A pre-visit, patient/staff-facing cost breakdown — never itself a
    Charge/Invoice, just what one would look like if created today. See
    estimate_home_visit_charges()."""

    payment_method: str
    pricing_configured: bool
    service_price_label: str | None
    service_price_amount: Decimal | None
    travel_fee_label: str | None
    travel_fee_amount: Decimal | None
    deposit_amount: Decimal | None
    copay_amount: Decimal | None
    package_applied: bool
    package_name: str | None
    total_charge_amount: Decimal
    patient_responsibility: Decimal | None


def _active_package_for(mobile_care_request: MobileCareRequest) -> CashPackage | None:
    candidates = CashPackage.objects.filter(
        organization=mobile_care_request.organization, patient=mobile_care_request.patient, status=CashPackage.Status.ACTIVE,
    ).order_by("-purchased_on")
    return next((entry for entry in candidates if entry.is_active), None)


def _active_primary_copay(mobile_care_request: MobileCareRequest) -> Decimal | None:
    primary = (
        PatientInsurance.objects.filter(patient=mobile_care_request.patient, rank=PatientInsurance.Rank.PRIMARY)
        .order_by("-effective_date")
        .first()
    )
    if primary is None or not primary.is_active:
        return None
    return primary.copay


def estimate_home_visit_charges(mobile_care_request: MobileCareRequest, *, include_travel_fee: bool = True) -> HomeVisitBillingEstimate:
    """The Home PT Initial Evaluation / Follow-Up / travel-fee breakdown for
    one request, using this organization's configured ServicePrice rows —
    never a hard-coded dollar figure. Honest by construction:
    `pricing_configured=False` and `patient_responsibility=None` when the
    organization hasn't set up home-visit pricing yet, rather than guessing.

    package/membership coverage always wins (patient_responsibility=0 —
    already paid for); otherwise insurance responsibility is the known
    copay if one is on file, or the full charge if not (no fabricated
    coinsurance/deductible estimate — this app doesn't adjudicate claims,
    it bills them, same as everywhere else in this codebase); self-pay
    responsibility is the full charge."""
    kind = mobile_care_request.requested_service or Appointment.Kind.FOLLOW_UP
    quote = home_visit_price_quote(mobile_care_request.organization, kind)

    service_price_amount = quote.service_price.price if quote.service_price else None
    travel_fee_price = quote.travel_fee_price if include_travel_fee else None
    travel_fee_amount = travel_fee_price.price if travel_fee_price else None
    deposit_amount = quote.service_price.deposit_amount if quote.service_price else None
    total_charge_amount = (service_price_amount or Decimal("0.00")) + (travel_fee_amount or Decimal("0.00"))

    package = _active_package_for(mobile_care_request)
    package_applied = mobile_care_request.payment_method == MobileCareRequest.PaymentMethod.PACKAGE and package is not None

    copay_amount = None
    if mobile_care_request.payment_method == MobileCareRequest.PaymentMethod.INSURANCE:
        copay_amount = _active_primary_copay(mobile_care_request)

    if package_applied:
        patient_responsibility = Decimal("0.00")
    elif not quote.configured:
        patient_responsibility = None
    elif mobile_care_request.payment_method == MobileCareRequest.PaymentMethod.INSURANCE:
        patient_responsibility = copay_amount if copay_amount is not None else total_charge_amount
    else:
        patient_responsibility = total_charge_amount

    return HomeVisitBillingEstimate(
        payment_method=mobile_care_request.payment_method,
        pricing_configured=quote.configured,
        service_price_label=quote.service_price.label if quote.service_price else None,
        service_price_amount=service_price_amount,
        travel_fee_label=travel_fee_price.label if travel_fee_price else None,
        travel_fee_amount=travel_fee_amount,
        deposit_amount=deposit_amount,
        copay_amount=copay_amount,
        package_applied=package_applied,
        package_name=package.name if package_applied else None,
        total_charge_amount=total_charge_amount,
        patient_responsibility=patient_responsibility,
    )


def _duplicate_charge_exists(appointment: Appointment, cpt_code: str) -> bool:
    return (
        Charge.objects.filter(
            patient=appointment.patient, service_date=appointment.starts_at.date(), cpt_code=cpt_code, provider=appointment.therapist,
        )
        .exclude(status=Charge.Status.VOID)
        .exists()
    )


def create_home_visit_service_charge(appointment: Appointment, *, actor, django_request=None) -> Charge:
    """The home visit's base service-price charge (evaluation/follow-up/...)
    — same manual-after-completion, same-table, same duplicate-guard pattern
    add_travel_charge() below already uses, just for the visit itself.
    Looks up the org's ServicePrice tagged for this appointment's kind
    (home_visit_kind) rather than requiring a caller-supplied amount — "use
    organization-specific pricing." Raises if the org hasn't configured one
    yet, same honest-refusal posture as every other unconfigured-provider
    check in this codebase (never fabricates a price)."""
    if not appointment.is_home_visit:
        raise ValidationError("Only home-visit appointments use this workflow.")
    if appointment.status != Appointment.Status.COMPLETED:
        raise ValidationError("Add a service charge only after the visit is marked completed.")
    quote = home_visit_price_quote(appointment.patient.organization, appointment.kind)
    if quote.service_price is None:
        raise ValidationError("This organization has not configured a home-visit price for this visit type yet.")
    if _duplicate_charge_exists(appointment, quote.service_price.cpt_code):
        raise ValidationError(
            "A charge already exists for this patient, date, provider, and CPT code. Void it first if this is a correction."
        )
    charge = Charge(
        organization=appointment.patient.organization,
        patient=appointment.patient,
        episode_of_care=appointment.episode_of_care,
        provider=appointment.therapist,
        service_date=appointment.starts_at.date(),
        cpt_code=quote.service_price.cpt_code,
        units=1,
        charge_amount=quote.service_price.price,
        created_by=actor,
    )
    charge.full_clean()
    charge.save()
    record_audit_event(
        actor=actor,
        action="charge.created",
        obj=charge,
        patient=appointment.patient,
        request=django_request,
        metadata={"cpt_code": charge.cpt_code, "units": charge.units, "status": charge.status, "source": "mobile_care_service_price"},
    )
    return charge


def add_travel_charge(
    appointment: Appointment,
    *,
    cpt_code: str | None = None,
    charge_amount=None,
    created_by,
    django_request=None,
) -> Charge:
    """A billing line item for the travel/mileage cost of a completed home
    visit. Staff-entered and explicit (never automatic) — billing always
    reflects a deliberate decision, never a side effect of marking a visit
    complete. Writes directly to the existing Charge model, the same one
    care/api/billing.py's charge-creation endpoint writes to, so it appears
    in the ordinary billing views (charge list, superbills, reports) with no
    changes to any existing billing code — this module only adds a second,
    narrower entry point onto the same table.

    `cpt_code`/`charge_amount` are optional — omit either (or both) to use
    the organization's configured travel-fee ServicePrice ("Travel Fee if
    configured"); passing them explicitly still overrides, for the one-off
    case a configured default doesn't fit. Raises if neither an override
    nor a configured travel fee exists.

    Reuses Charge's own duplicate-prevention rule (same patient/date/CPT/
    provider, excluding void) so behavior matches what billing staff already
    see elsewhere in the app."""
    if not appointment.is_home_visit:
        raise ValidationError("Only home-visit appointments use this workflow.")
    if appointment.status != Appointment.Status.COMPLETED:
        raise ValidationError("Add a travel charge only after the visit is marked completed.")
    if cpt_code is None or charge_amount is None:
        quote = home_visit_price_quote(appointment.patient.organization, appointment.kind)
        if quote.travel_fee_price is None:
            raise ValidationError("This organization has not configured a home-visit travel fee.")
        cpt_code = cpt_code or quote.travel_fee_price.cpt_code
        charge_amount = charge_amount if charge_amount is not None else quote.travel_fee_price.price
    if _duplicate_charge_exists(appointment, cpt_code):
        raise ValidationError(
            "A charge already exists for this patient, date, provider, and CPT code. Void it first if this is a correction."
        )
    charge = Charge(
        organization=appointment.patient.organization,
        patient=appointment.patient,
        episode_of_care=appointment.episode_of_care,
        provider=appointment.therapist,
        service_date=appointment.starts_at.date(),
        cpt_code=cpt_code,
        units=1,
        charge_amount=charge_amount,
        created_by=created_by,
    )
    charge.full_clean()
    charge.save()
    record_audit_event(
        actor=created_by,
        action="charge.created",
        obj=charge,
        patient=appointment.patient,
        request=django_request,
        metadata={"cpt_code": cpt_code, "units": charge.units, "status": charge.status, "source": "mobile_care_travel_fee"},
    )
    return charge
