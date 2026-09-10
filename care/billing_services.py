"""Billing/RCM: claim validation and CMS-1500 normalized-data construction.

Deterministic and rule-based — no AI, no external calls. `validate_claim`
never mutates the claim; the calling view decides what status transition a
validation result implies. `build_cms1500_data` produces a normalized data
structure only, matching the module's data model, not a rendered PDF/HTML
form and not something the frontend is trusted to assemble on its own.
"""
from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from .models import Authorization, Charge, Claim, ClaimTransaction, PatientStatement, PaymentRecord, Provider, Superbill

# CMS-1500 place-of-service code for a standard outpatient clinic visit.
# Location has no configurable place-of-service field yet, so every service
# line defaults to this — flagged here rather than silently guessing
# something more specific once telehealth/home-visit POS codes are needed.
DEFAULT_PLACE_OF_SERVICE = "11"


def _provider_npi(organization, provider_user) -> str:
    profile = Provider.objects.filter(organization=organization, user=provider_user).first()
    return profile.npi_number if profile else ""


def _display_name(user) -> str:
    return user.get_full_name() or user.username


def validate_claim(claim: Claim) -> list[dict]:
    """Return a list of {code, field, severity, message} findings, covering
    every check in the module's CLAIM VALIDATION checklist: patient
    demographics, insurance, payer, provider/NPI, diagnosis, CPT, units,
    modifiers, authorization, signed documentation, date of service,
    duplicate claim, timely filing, and credential issues. `severity` is
    'error' (blocks submission) or 'warning' (informational)."""
    findings: list[dict] = []

    def add(code: str, field: str, severity: str, message: str) -> None:
        findings.append({"code": code, "field": field, "severity": severity, "message": message})

    charges = list(
        claim.charges.exclude(status=Charge.Status.VOID).select_related("provider", "clinical_note")
    )

    # --- patient demographics -------------------------------------------
    if not claim.patient.address.strip():
        add("missing_patient_address", "patient", "warning", "Patient address is not on file.")

    # --- insurance / payer -------------------------------------------------
    if not claim.patient_insurance.is_active:
        add(
            "inactive_insurance", "patientInsuranceId", "error",
            "The selected insurance policy is not currently active.",
        )
    if not claim.payer.is_active:
        add("inactive_payer", "payerId", "error", "The selected payer is marked inactive.")

    # --- diagnosis -----------------------------------------------------
    if not claim.diagnosis_code_list:
        add("missing_diagnosis", "diagnosisCodeList", "error", "At least one diagnosis code is required.")

    # --- charges present at all -----------------------------------------
    if not charges:
        add("no_charges", "charges", "error", "This claim has no charges attached.")

    # --- duplicate claim ----------------------------------------------
    charge_dates = {charge.service_date for charge in charges}
    if charge_dates:
        overlapping = (
            Claim.objects.filter(patient=claim.patient, payer=claim.payer)
            .exclude(pk=claim.pk)
            .exclude(status__in={Claim.Status.REJECTED, Claim.Status.CLOSED})
            .prefetch_related("charges")
        )
        for other in overlapping:
            other_dates = {charge.service_date for charge in other.charges.exclude(status=Charge.Status.VOID)}
            if charge_dates & other_dates:
                add(
                    "duplicate_claim", "charges", "error",
                    "Another open claim already covers this patient, payer, and date of service.",
                )
                break

    # --- per-charge checks: CPT/units/modifiers are enforced at Charge
    # save time already (see models.Charge.clean) — re-checked here only
    # where a claim-level fact (payer, authorization) is needed.
    checked_providers: set[str] = set()
    requires_authorization = claim.patient_insurance.authorization_required or claim.payer.authorization_required
    today = timezone.localdate()

    for charge in charges:
        label = "%s (%s)" % (charge.cpt_code, charge.service_date.isoformat())

        if charge.service_date > today:
            add("future_service_date", "charges", "error", "%s: date of service is in the future." % label)

        if claim.payer.timely_filing_days and (today - charge.service_date).days > claim.payer.timely_filing_days:
            add(
                "timely_filing", "charges", "error",
                "%s: timely filing window (%s days) has passed." % (label, claim.payer.timely_filing_days),
            )

        if charge.clinical_note_id:
            if charge.clinical_note.status != "signed":
                add("unsigned_documentation", "charges", "error", "%s: linked documentation is not signed." % label)
        else:
            add("no_documentation_link", "charges", "warning", "%s: no documentation is linked to this charge." % label)

        if requires_authorization:
            active_authorization = Authorization.objects.filter(
                patient=claim.patient, status=Authorization.Status.ACTIVE,
                start_date__lte=charge.service_date, expires_at__gte=charge.service_date,
            ).first()
            if not active_authorization:
                add("missing_authorization", "charges", "error", "%s: no active authorization covers this date of service." % label)
            elif active_authorization.visits_remaining <= 0:
                add("exhausted_authorization", "charges", "error", "%s: the covering authorization has no visits remaining." % label)

        if charge.provider_id not in checked_providers:
            checked_providers.add(charge.provider_id)
            provider_name = _display_name(charge.provider)
            if not _provider_npi(claim.organization, charge.provider):
                add("missing_npi", "provider", "error", "%s has no NPI on file." % provider_name)
            alert = charge.provider.license_alert_status
            if alert in {"expired", "critical"}:
                add("credential_issue", "provider", "error", "%s's license is %s." % (provider_name, alert.replace("_", " ")))
            elif alert == "expiring_soon":
                add("credential_expiring", "provider", "warning", "%s's license is expiring soon." % provider_name)

    return findings


def build_cms1500_data(claim: Claim) -> dict:
    """Normalized CMS-1500-equivalent claim data (box references noted in
    comments for traceability) — a data structure only, never a rendered
    form. The clearinghouse adapter or a future export step is responsible
    for turning this into an actual 837P/paper CMS-1500 representation."""
    patient = claim.patient
    policy = claim.patient_insurance
    payer = claim.payer
    organization = claim.organization

    service_lines = []
    for index, charge in enumerate(
        claim.charges.exclude(status=Charge.Status.VOID).select_related("provider").order_by("service_date"), start=1
    ):
        service_lines.append(
            {
                "lineNumber": index,  # box 24 row
                "serviceDate": charge.service_date.isoformat(),  # box 24A
                "placeOfService": DEFAULT_PLACE_OF_SERVICE,  # box 24B
                "cptCode": charge.cpt_code,  # box 24D
                "modifiers": charge.modifiers,  # box 24D modifiers
                "diagnosisPointers": claim.diagnosis_pointers_for(charge),  # box 24E
                "units": charge.units,  # box 24G
                "chargeAmount": str(charge.charge_amount),  # box 24F
                "renderingProviderNpi": _provider_npi(organization, charge.provider),  # box 24J
                "renderingProviderName": _display_name(charge.provider),
            }
        )

    return {
        "claimId": str(claim.pk),
        "status": claim.status,
        "patient": {  # boxes 2-5
            "fullName": patient.full_name,
            "dateOfBirth": patient.date_of_birth.isoformat(),
            "address": patient.address,
            "phone": patient.phone,
        },
        "subscriber": {  # boxes 1a, 4, 6-11
            "name": policy.subscriber_name or patient.full_name,
            "dateOfBirth": (
                policy.subscriber_date_of_birth.isoformat()
                if policy.subscriber_date_of_birth
                else patient.date_of_birth.isoformat()
            ),
            "relationshipToPatient": policy.relationship_to_subscriber,
            "memberId": policy.member_id,
            "groupNumber": policy.group_number,
        },
        "payer": {  # top-right payer block
            "name": payer.name,
            "payerId": payer.payer_id,
            "electronicPayerId": payer.electronic_payer_id,
            "address": {
                "line1": payer.address_line_1,
                "line2": payer.address_line_2,
                "city": payer.city,
                "state": payer.state,
                "zipCode": payer.zip_code,
            },
        },
        "billingProvider": {  # box 33
            "name": organization.name,
            "npi": organization.npi_number,
            "taxId": organization.tax_id,  # box 25
            "address": {
                "line1": organization.address_line_1,
                "line2": organization.address_line_2,
                "city": organization.city,
                "state": organization.state,
                "zipCode": organization.zip_code,
            },
            "phone": organization.support_phone,
        },
        "diagnoses": [  # box 21, A-L
            {"pointer": chr(65 + index), "code": code} for index, code in enumerate(claim.diagnosis_code_list)
        ],
        "serviceLines": service_lines,
        "totalChargeAmount": str(claim.total_charge_amount),  # box 28
    }


def _practice_info(organization) -> dict:
    return {
        "name": organization.name,
        "npi": organization.npi_number,
        "taxId": organization.tax_id,
        "address": {
            "line1": organization.address_line_1,
            "line2": organization.address_line_2,
            "city": organization.city,
            "state": organization.state,
            "zipCode": organization.zip_code,
        },
        "phone": organization.support_phone,
    }


def build_patient_superbill_data(superbill: Superbill) -> dict:
    """Normalized patient-facing superbill data — patient, provider, date,
    diagnosis, CPT, units, charges, and practice information. Uses linked
    Charge rows when present (rich per-line detail, the Phase 2+ path);
    falls back to the legacy flat `codes` list for superbills created
    before charge-linking existed, so nothing already in production breaks.
    Never includes anything beyond what this specific superbill covers —
    no unrelated chart history."""
    patient = superbill.patient
    linked_charges = list(
        superbill.charges.exclude(status=Charge.Status.VOID).select_related("provider").prefetch_related("diagnosis_codes")
    )

    if linked_charges:
        lines = [
            {
                "serviceDate": charge.service_date.isoformat(),
                "cptCode": charge.cpt_code,
                "modifiers": charge.modifiers,
                "units": charge.units,
                "chargeAmount": str(charge.charge_amount),
                "diagnosisCodes": [code.code for code in charge.diagnosis_codes.all()],
                "providerName": charge.provider.get_full_name() or charge.provider.username,
            }
            for charge in linked_charges
        ]
        total_amount = sum((charge.charge_amount for charge in linked_charges), Decimal("0.00"))
        diagnosis_codes = sorted({code.code for charge in linked_charges for code in charge.diagnosis_codes.all()})
    else:
        provider_name = superbill.clinician.get_full_name() or superbill.clinician.username
        lines = [
            {
                "serviceDate": superbill.service_date.isoformat(),
                "cptCode": code,
                "modifiers": [],
                "units": None,
                "chargeAmount": None,
                "diagnosisCodes": [],
                "providerName": provider_name,
            }
            for code in superbill.codes
        ]
        total_amount = superbill.amount
        diagnosis_codes = []

    return {
        "superbillId": str(superbill.pk),
        "status": superbill.status,
        "serviceDate": superbill.service_date.isoformat(),
        "patient": {"fullName": patient.full_name, "dateOfBirth": patient.date_of_birth.isoformat()},
        "provider": {"name": superbill.clinician.get_full_name() or superbill.clinician.username},
        "diagnosisCodes": diagnosis_codes,
        "diagnosisText": patient.diagnoses if not diagnosis_codes else "",
        "lines": lines,
        "totalAmount": str(total_amount),
        "practice": _practice_info(patient.organization),
    }


def build_patient_statement_data(statement: PatientStatement) -> dict:
    """Normalized patient statement — charges, insurance payments,
    adjustments, patient payments, and balance, filtered to activity on or
    before `statement.statement_date` so a previously generated statement's
    content stays reproducible even as new activity posts later. Insurance
    claims and cash-pay superbills are different ledgers (see Charge/
    Claim's docstrings) so they're reported as separate sections."""
    patient = statement.patient
    cutoff = statement.statement_date

    claims = (
        Claim.objects.filter(patient=patient, organization=patient.organization)
        .exclude(status__in={Claim.Status.DRAFT, Claim.Status.READY, Claim.Status.VALIDATION_ERROR})
        .select_related("payer")
        .prefetch_related("charges", "transactions")
    )
    claim_lines = []
    insurance_balance = Decimal("0.00")
    for claim in claims:
        charges = [c for c in claim.charges.exclude(status=Charge.Status.VOID) if c.service_date <= cutoff]
        if not charges:
            continue
        charge_total = sum((c.charge_amount for c in charges), Decimal("0.00"))
        transactions = [t for t in claim.transactions.all() if t.payment_date <= cutoff]
        paid = sum(
            (t.amount for t in transactions if t.kind in (ClaimTransaction.Kind.INSURANCE_PAYMENT, ClaimTransaction.Kind.PATIENT_PAYMENT)),
            Decimal("0.00"),
        ) - sum((t.amount for t in transactions if t.kind == ClaimTransaction.Kind.REFUND), Decimal("0.00"))
        adjusted = sum(
            (t.amount for t in transactions if t.kind in (ClaimTransaction.Kind.ADJUSTMENT, ClaimTransaction.Kind.WRITE_OFF)),
            Decimal("0.00"),
        )
        balance = charge_total - paid - adjusted
        insurance_balance += balance
        claim_lines.append(
            {
                "claimId": str(claim.pk),
                "payerName": claim.payer.name,
                "statusLabel": claim.get_status_display(),
                "chargeTotal": str(charge_total),
                "paid": str(paid),
                "adjusted": str(adjusted),
                "balance": str(balance),
            }
        )

    superbills = Superbill.objects.filter(patient=patient, service_date__lte=cutoff).exclude(status=Superbill.Status.PAID)
    cash_lines = []
    cash_balance = Decimal("0.00")
    for superbill in superbills:
        payments = sum(
            (
                payment.amount
                for payment in superbill.payments.filter(status=PaymentRecord.Status.RECEIVED, received_on__lte=cutoff)
            ),
            Decimal("0.00"),
        )
        balance = superbill.amount - payments
        cash_balance += balance
        cash_lines.append(
            {
                "superbillId": str(superbill.pk),
                "serviceDate": superbill.service_date.isoformat(),
                "amount": str(superbill.amount),
                "paid": str(payments),
                "balance": str(balance),
            }
        )

    return {
        "statementId": str(statement.pk),
        "statementDate": statement.statement_date.isoformat(),
        "dueDate": statement.due_date.isoformat(),
        "patient": {"fullName": patient.full_name, "address": patient.address},
        "practice": _practice_info(patient.organization),
        "insuranceClaims": claim_lines,
        "cashCharges": cash_lines,
        "totalBalance": str(insurance_balance + cash_balance),
        "paymentInstructions": (
            "Please remit payment by the due date above. Contact our billing office with any questions "
            "about this statement."
        ),
    }


def patient_outstanding_balance(patient) -> Decimal:
    """Total outstanding insurance-claim balance for one patient, live —
    the same per-claim computation used by the AR aging and billing summary
    reports, factored out so the patient portal dashboard doesn't duplicate
    it. Cash-pay (Superbill/PaymentRecord) balance is intentionally not
    included yet — see build_patient_statement_data's cashCharges section
    for that ledger; a portal-facing combined figure can reuse it later."""
    claims = (
        Claim.objects.filter(patient=patient)
        .exclude(status__in={Claim.Status.DRAFT, Claim.Status.READY, Claim.Status.VALIDATION_ERROR})
        .prefetch_related("charges", "transactions")
    )
    return sum((claim.balance for claim in claims if claim.balance > 0), Decimal("0.00"))


def patient_combined_balance(patient) -> dict:
    """Insurance + cash-pay balance combined, live — the "portal-facing
    combined figure" patient_outstanding_balance's docstring anticipated.
    Cash-pay math mirrors build_patient_statement_data's cashCharges
    section, but anchored to right now rather than a fixed statement
    cutoff, since this drives the portal's live balance view."""
    insurance_balance = patient_outstanding_balance(patient)

    cash_balance = Decimal("0.00")
    superbills = Superbill.objects.filter(patient=patient).exclude(status=Superbill.Status.PAID)
    for superbill in superbills:
        paid = sum(
            (payment.amount for payment in superbill.payments.filter(status=PaymentRecord.Status.RECEIVED)),
            Decimal("0.00"),
        )
        balance = superbill.amount - paid
        if balance > 0:
            cash_balance += balance

    return {
        "insuranceBalance": insurance_balance,
        "cashBalance": cash_balance,
        "totalBalance": insurance_balance + cash_balance,
    }
