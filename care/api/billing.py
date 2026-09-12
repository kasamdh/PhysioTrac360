"""Billing/RCM: payer directory + patient insurance policies.

The payer directory is org-level configuration data — deliberately
data-driven (timely filing days, authorization requirement, free-text rules
notes) rather than hard-coding any payer's rules into the UI; billing staff
maintain it themselves. Patient insurance policies are patient-scoped
billing records kept indefinitely (terminated, never deleted) for billing
history, mirroring how Authorization/EpisodeOfCare are never hard-deleted.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import FileResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from ..access import BILLING_ROLES, PAYMENT_COLLECTION_ROLES, require_patient_access, require_role
from ..billing_services import build_cms1500_data, build_patient_statement_data, build_patient_superbill_data, validate_claim
from ..clearinghouse import get_clearinghouse_adapter
from ..entitlements import organization_has_feature
from ..models import (
    Appointment,
    CashPackage,
    Charge,
    Claim,
    ClaimDenial,
    ClaimTransaction,
    ClinicalNote,
    DiagnosisCode,
    EpisodeOfCare,
    Location,
    Patient,
    PatientInsurance,
    PatientStatement,
    Payer,
    ServicePrice,
    Superbill,
    User,
)
from ..services import coding_suggestions, record_audit_event
from .utils import InvalidJSON, api_error, api_login_required, api_validation_error, json_body, organization_or_error

MAX_CARD_UPLOAD_BYTES = 15 * 1024 * 1024


def _billing_feature_or_error(organization) -> JsonResponse | None:
    if not organization_has_feature(organization, "billing"):
        return api_error("Billing is not enabled for this organization. Contact your administrator.", status=403)
    return None


def _clean_error_dict(exc: ValidationError) -> dict[str, str]:
    return {field: " ".join(messages) for field, messages in exc.message_dict.items()}


# --- Payer directory ---------------------------------------------------

PAYER_TEXT_FIELDS = {
    "name": "name",
    "payer_id": "payerId",
    "electronic_payer_id": "electronicPayerId",
    "address_line_1": "addressLine1",
    "address_line_2": "addressLine2",
    "city": "city",
    "state": "state",
    "zip_code": "zipCode",
    "phone": "phone",
    "authorization_notes": "authorizationNotes",
    "notes": "notes",
}


def serialize_payer(payer: Payer) -> dict:
    return {
        "id": str(payer.pk),
        "name": payer.name,
        "payerId": payer.payer_id,
        "electronicPayerId": payer.electronic_payer_id,
        "addressLine1": payer.address_line_1,
        "addressLine2": payer.address_line_2,
        "city": payer.city,
        "state": payer.state,
        "zipCode": payer.zip_code,
        "phone": payer.phone,
        "isActive": payer.is_active,
        "timelyFilingDays": payer.timely_filing_days,
        "authorizationRequired": payer.authorization_required,
        "authorizationNotes": payer.authorization_notes,
        "notes": payer.notes,
        "createdAt": payer.created_at.isoformat(),
    }


def _validate_payer_payload(payload: dict, *, partial: bool = False) -> dict[str, str]:
    errors: dict[str, str] = {}
    if "name" in payload or not partial:
        if not str(payload.get("name", "")).strip():
            errors["name"] = "Payer name is required."
    if "timelyFilingDays" in payload:
        try:
            days = int(payload["timelyFilingDays"])
            if days <= 0 or days > 999:
                raise ValueError
        except (TypeError, ValueError):
            errors["timelyFilingDays"] = "Enter a timely filing window between 1 and 999 days."
    return errors


def _apply_payer_payload(payer: Payer, payload: dict) -> None:
    for field, key in PAYER_TEXT_FIELDS.items():
        if key in payload:
            setattr(payer, field, str(payload[key] or "").strip())
    if "timelyFilingDays" in payload:
        payer.timely_filing_days = int(payload["timelyFilingDays"])
    if "authorizationRequired" in payload:
        payer.authorization_required = bool(payload["authorizationRequired"])


@require_http_methods(["GET", "POST"])
@api_login_required
def payers(request):
    """Read is available to the same broad payment-collection audience as
    front-desk payment collection (they need the payer list at check-in);
    write is restricted to full billing roles, matching superbill_create."""
    organization, error = organization_or_error(request, roles=PAYMENT_COLLECTION_ROLES)
    if error:
        return error

    if request.method == "POST":
        try:
            require_role(request.user, BILLING_ROLES)
        except PermissionDenied as exc:
            return api_error(str(exc), status=403)
        feature_error = _billing_feature_or_error(organization)
        if feature_error:
            return feature_error
        try:
            payload = json_body(request)
        except InvalidJSON as exc:
            return api_error(str(exc), status=400)
        errors = _validate_payer_payload(payload)
        if errors:
            return api_validation_error(errors)
        payer = Payer(organization=organization, created_by=request.user)
        _apply_payer_payload(payer, payload)
        try:
            payer.full_clean()
            payer.save()
        except ValidationError as exc:
            return api_validation_error(_clean_error_dict(exc))
        record_audit_event(actor=request.user, action="payer.created", obj=payer, request=request)
        return JsonResponse({"payer": serialize_payer(payer)}, status=201)

    records = Payer.objects.filter(organization=organization).order_by("name")
    if request.GET.get("activeOnly") == "1":
        records = records.filter(is_active=True)
    return JsonResponse({"payers": [serialize_payer(record) for record in records]})


@require_http_methods(["GET", "PATCH", "DELETE"])
@api_login_required
def payer_detail(request, payer_id):
    organization, error = organization_or_error(request, roles=PAYMENT_COLLECTION_ROLES)
    if error:
        return error
    payer = Payer.objects.filter(pk=payer_id, organization=organization).first()
    if not payer:
        return api_error("Payer was not found.", status=404)
    if request.method == "GET":
        return JsonResponse({"payer": serialize_payer(payer)})

    try:
        require_role(request.user, BILLING_ROLES)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    feature_error = _billing_feature_or_error(organization)
    if feature_error:
        return feature_error

    if request.method == "DELETE":
        if not payer.is_active:
            return api_error("This payer is already inactive.", status=409)
        payer.is_active = False
        payer.save(update_fields=["is_active", "updated_at"])
        record_audit_event(actor=request.user, action="payer.deactivated", obj=payer, request=request)
        return JsonResponse({"payer": serialize_payer(payer)})

    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)
    errors = _validate_payer_payload(payload, partial=True)
    if errors:
        return api_validation_error(errors)
    _apply_payer_payload(payer, payload)
    if "isActive" in payload:
        payer.is_active = bool(payload["isActive"])
    try:
        payer.full_clean()
    except ValidationError as exc:
        return api_validation_error(_clean_error_dict(exc))
    payer.save()
    record_audit_event(actor=request.user, action="payer.updated", obj=payer, request=request)
    return JsonResponse({"payer": serialize_payer(payer)})


# --- Patient insurance ---------------------------------------------------

def _billing_patient_or_error(request, patient_id: str):
    """Billing/front-desk staff are not clinicians — `patients_for(clinical=True)`
    would give them zero patients (see care/access.py), so this deliberately
    checks clinical=False, matching workflow_views._operations_patient_or_error's
    reasoning for superbill/payment endpoints."""
    _, error = organization_or_error(request, roles=PAYMENT_COLLECTION_ROLES)
    if error:
        return None, error
    patient = Patient.objects.select_related("organization").filter(pk=patient_id).first()
    if patient is None:
        return None, api_error("Patient record was not found.", status=404)
    try:
        require_patient_access(request, patient, clinical=False)
    except PermissionDenied as exc:
        return None, api_error(str(exc), status=403)
    return patient, None


# A treating clinician may view — never edit — billing for visits they
# personally rendered ("Provider limited billing view" in BILLING
# PERMISSIONS). Scoped narrowly to Charges/Claims read endpoints only —
# payer directory, insurance policies, the payment ledger, statements, and
# the denial queue stay full-billing-staff-only.
CLINICIAN_SCHEDULE_ROLES = {User.Role.THERAPIST, User.Role.ASSISTANT}


def _billing_read_patient_or_error(request, patient_id: str):
    """Read access for full billing/front-desk staff OR a treating clinician
    viewing their own patient's charges/claims. The caller is responsible
    for further scoping the queryset to `provider=request.user` when
    `is_provider_limited_view(request.user)` is true."""
    _, error = organization_or_error(request, roles=PAYMENT_COLLECTION_ROLES | CLINICIAN_SCHEDULE_ROLES)
    if error:
        return None, error
    patient = Patient.objects.select_related("organization").filter(pk=patient_id).first()
    if patient is None:
        return None, api_error("Patient record was not found.", status=404)
    is_provider = request.user.role in CLINICIAN_SCHEDULE_ROLES
    try:
        require_patient_access(request, patient, clinical=is_provider)
    except PermissionDenied as exc:
        return None, api_error(str(exc), status=403)
    return patient, None


def is_provider_limited_view(user) -> bool:
    return user.role in CLINICIAN_SCHEDULE_ROLES


INSURANCE_TEXT_FIELDS = {
    "plan_name": "planName",
    "member_id": "memberId",
    "group_number": "groupNumber",
    "subscriber_name": "subscriberName",
}
INSURANCE_DECIMAL_FIELDS = {
    "copay": "copay",
    "coinsurance_percent": "coinsurancePercent",
    "deductible": "deductible",
}


def serialize_patient_insurance(policy: PatientInsurance) -> dict:
    return {
        "id": str(policy.pk),
        "payerId": str(policy.payer_id),
        "payerName": policy.payer.name,
        "rank": policy.rank,
        "rankLabel": policy.get_rank_display(),
        "planName": policy.plan_name,
        "memberId": policy.member_id,
        "groupNumber": policy.group_number,
        "subscriberName": policy.subscriber_name,
        "subscriberDateOfBirth": policy.subscriber_date_of_birth.isoformat() if policy.subscriber_date_of_birth else None,
        "relationshipToSubscriber": policy.relationship_to_subscriber,
        "relationshipToSubscriberLabel": policy.get_relationship_to_subscriber_display(),
        "effectiveDate": policy.effective_date.isoformat(),
        "terminationDate": policy.termination_date.isoformat() if policy.termination_date else None,
        "isActive": policy.is_active,
        "copay": str(policy.copay) if policy.copay is not None else None,
        "coinsurancePercent": str(policy.coinsurance_percent) if policy.coinsurance_percent is not None else None,
        "deductible": str(policy.deductible) if policy.deductible is not None else None,
        "authorizationRequired": policy.authorization_required,
        "hasCardFront": bool(policy.card_front),
        "hasCardBack": bool(policy.card_back),
        "createdAt": policy.created_at.isoformat(),
    }


def _parse_decimal(value) -> tuple[Decimal | None, bool]:
    if value in (None, ""):
        return None, True
    try:
        return Decimal(str(value)), True
    except InvalidOperation:
        return None, False


def _apply_insurance_payload(policy: PatientInsurance, payload: dict, *, partial: bool) -> dict[str, str]:
    errors: dict[str, str] = {}

    if "payerId" in payload:
        payer_id = str(payload["payerId"] or "").strip()
        if not payer_id:
            errors["payerId"] = "Choose a payer."
        else:
            payer = Payer.objects.filter(pk=payer_id, organization=policy.organization).first()
            if payer is None:
                errors["payerId"] = "Choose a valid payer."
            else:
                policy.payer = payer
    elif not partial:
        errors["payerId"] = "Choose a payer."

    if "memberId" in payload or not partial:
        member_id = str(payload.get("memberId", "")).strip()
        if not member_id:
            errors["memberId"] = "Member ID is required."
        else:
            policy.member_id = member_id

    if "effectiveDate" in payload or not partial:
        effective_date = payload.get("effectiveDate")
        if not effective_date:
            errors["effectiveDate"] = "Effective date is required."
        else:
            policy.effective_date = effective_date

    if "terminationDate" in payload:
        policy.termination_date = payload["terminationDate"] or None
    if "rank" in payload:
        if payload["rank"] not in PatientInsurance.Rank.values:
            errors["rank"] = "Choose a valid rank."
        else:
            policy.rank = payload["rank"]
    if "relationshipToSubscriber" in payload:
        if payload["relationshipToSubscriber"] not in PatientInsurance.Relationship.values:
            errors["relationshipToSubscriber"] = "Choose a valid relationship."
        else:
            policy.relationship_to_subscriber = payload["relationshipToSubscriber"]
    if "subscriberDateOfBirth" in payload:
        policy.subscriber_date_of_birth = payload["subscriberDateOfBirth"] or None
    if "authorizationRequired" in payload:
        policy.authorization_required = bool(payload["authorizationRequired"])

    for field, key in INSURANCE_TEXT_FIELDS.items():
        if key in payload:
            setattr(policy, field, str(payload[key] or "").strip())

    for field, key in INSURANCE_DECIMAL_FIELDS.items():
        if key in payload:
            value, ok = _parse_decimal(payload[key])
            if not ok:
                errors[key] = "Enter a valid number."
            else:
                setattr(policy, field, value)

    return errors


@require_http_methods(["GET", "POST"])
@api_login_required
def patient_insurance_policies(request, patient_id):
    patient, error = _billing_patient_or_error(request, patient_id)
    if error:
        return error

    if request.method == "POST":
        try:
            require_role(request.user, BILLING_ROLES)
        except PermissionDenied as exc:
            return api_error(str(exc), status=403)
        feature_error = _billing_feature_or_error(patient.organization)
        if feature_error:
            return feature_error
        try:
            payload = json_body(request)
        except InvalidJSON as exc:
            return api_error(str(exc), status=400)
        policy = PatientInsurance(organization=patient.organization, patient=patient, created_by=request.user)
        errors = _apply_insurance_payload(policy, payload, partial=False)
        if errors:
            return api_validation_error(errors)
        try:
            policy.full_clean()
            policy.save()
        except ValidationError as exc:
            return api_validation_error(_clean_error_dict(exc))
        record_audit_event(
            actor=request.user, action="patient_insurance.created", obj=policy, patient=patient, request=request,
            metadata={"payer_id": str(policy.payer_id), "rank": policy.rank},
        )
        return JsonResponse({"policy": serialize_patient_insurance(policy)}, status=201)

    policies = patient.insurance_policies.select_related("payer").all()
    return JsonResponse({"policies": [serialize_patient_insurance(policy) for policy in policies]})


@require_http_methods(["GET", "PATCH", "DELETE"])
@api_login_required
def patient_insurance_detail(request, patient_id, policy_id):
    patient, error = _billing_patient_or_error(request, patient_id)
    if error:
        return error
    policy = PatientInsurance.objects.select_related("payer").filter(pk=policy_id, patient=patient).first()
    if not policy:
        return api_error("Insurance policy was not found.", status=404)
    if request.method == "GET":
        return JsonResponse({"policy": serialize_patient_insurance(policy)})

    try:
        require_role(request.user, BILLING_ROLES)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    feature_error = _billing_feature_or_error(patient.organization)
    if feature_error:
        return feature_error

    if request.method == "DELETE":
        # "Delete" means terminate as of today — insurance history is a
        # billing record and is never hard-deleted, matching how
        # Authorization/EpisodeOfCare rows are kept indefinitely.
        if policy.termination_date and policy.termination_date <= timezone.localdate():
            return api_error("This policy is already terminated.", status=409)
        policy.termination_date = timezone.localdate()
        try:
            policy.full_clean()
        except ValidationError as exc:
            return api_validation_error(_clean_error_dict(exc))
        policy.save(update_fields=["termination_date", "updated_at"])
        record_audit_event(actor=request.user, action="patient_insurance.terminated", obj=policy, patient=patient, request=request)
        return JsonResponse({"policy": serialize_patient_insurance(policy)})

    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)
    errors = _apply_insurance_payload(policy, payload, partial=True)
    if errors:
        return api_validation_error(errors)
    try:
        policy.full_clean()
    except ValidationError as exc:
        return api_validation_error(_clean_error_dict(exc))
    policy.save()
    record_audit_event(actor=request.user, action="patient_insurance.updated", obj=policy, patient=patient, request=request)
    return JsonResponse({"policy": serialize_patient_insurance(policy)})


@require_POST
@api_login_required
def patient_insurance_card_upload(request, patient_id, policy_id, side):
    if side not in ("front", "back"):
        return api_error("Choose front or back.", status=400)
    patient, error = _billing_patient_or_error(request, patient_id)
    if error:
        return error
    try:
        require_role(request.user, BILLING_ROLES)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    feature_error = _billing_feature_or_error(patient.organization)
    if feature_error:
        return feature_error
    policy = PatientInsurance.objects.filter(pk=policy_id, patient=patient).first()
    if not policy:
        return api_error("Insurance policy was not found.", status=404)

    upload = request.FILES.get("file")
    if not upload:
        return api_validation_error({"file": "Choose a file to upload."})
    if upload.size > MAX_CARD_UPLOAD_BYTES:
        return api_validation_error({"file": "Files must be 15 MB or smaller."})
    setattr(policy, "card_%s" % side, upload)
    try:
        policy.full_clean()
    except ValidationError:
        return api_validation_error({"file": "Unsupported file type. Allowed: PNG, JPG, JPEG."})
    policy.save()
    record_audit_event(
        actor=request.user, action="patient_insurance.card_uploaded", obj=policy, patient=patient, request=request,
        metadata={"side": side},
    )
    return JsonResponse({"policy": serialize_patient_insurance(policy)}, status=201)


@require_GET
@api_login_required
def patient_insurance_card_download(request, patient_id, policy_id, side):
    if side not in ("front", "back"):
        return api_error("Choose front or back.", status=400)
    patient, error = _billing_patient_or_error(request, patient_id)
    if error:
        return error
    policy = PatientInsurance.objects.filter(pk=policy_id, patient=patient).first()
    if not policy:
        return api_error("Insurance policy was not found.", status=404)
    file_field = policy.card_front if side == "front" else policy.card_back
    if not file_field:
        return api_error("No card image has been uploaded for this side.", status=404)
    record_audit_event(
        actor=request.user, action="patient_insurance.card_downloaded", obj=policy, patient=patient, request=request,
        metadata={"side": side},
    )
    return FileResponse(
        file_field.open("rb"), as_attachment=False, filename="insurance-card-%s%s" % (side, Path(file_field.name).suffix)
    )


# --- Diagnosis codes (read-only ICD-10-CM reference catalog) ---------------

def serialize_diagnosis_code(code: DiagnosisCode) -> dict:
    return {"code": code.code, "description": code.description, "isBillable": code.is_billable}


@require_GET
@api_login_required
def diagnosis_codes(request):
    """Shared platform-wide reference data (see DiagnosisCode's docstring) —
    open to any authenticated org member, not role-restricted, same as
    looking up a code in a paper ICD-10 book."""
    _, error = organization_or_error(request)
    if error:
        return error
    query = request.GET.get("q", "").strip()
    records = DiagnosisCode.objects.all()
    if query:
        records = records.filter(Q(code__istartswith=query) | Q(description__icontains=query))
    records = records.order_by("code")[:50]
    return JsonResponse({"diagnosisCodes": [serialize_diagnosis_code(code) for code in records]})


# --- Charges -----------------------------------------------------------

CHARGE_EDITABLE_STATUSES = {Charge.Status.DRAFT, Charge.Status.READY}


def serialize_charge(charge: Charge) -> dict:
    return {
        "id": str(charge.pk),
        "serviceDate": charge.service_date.isoformat(),
        "patientId": str(charge.patient_id),
        "episodeOfCareId": str(charge.episode_of_care_id) if charge.episode_of_care_id else None,
        "noteId": str(charge.clinical_note_id) if charge.clinical_note_id else None,
        "providerId": str(charge.provider_id),
        "providerName": charge.provider.get_full_name() or charge.provider.username,
        "locationId": str(charge.location_id) if charge.location_id else None,
        "locationName": charge.location.name if charge.location_id else None,
        "cptCode": charge.cpt_code,
        "modifiers": charge.modifiers,
        "units": charge.units,
        "minutes": charge.minutes,
        "recommendedUnits": charge.recommended_units,
        "unitsDifference": charge.units_difference,
        "unitsOverrideReason": charge.units_override_reason,
        "diagnosisCodes": [serialize_diagnosis_code(code) for code in charge.diagnosis_codes.all()],
        "chargeAmount": str(charge.charge_amount),
        "status": charge.status,
        "statusLabel": charge.get_status_display(),
        "claimId": str(charge.claim_id) if charge.claim_id else None,
        "createdAt": charge.created_at.isoformat(),
    }


def _billing_write_patient_or_error(request, patient_id: str):
    """Charge creation is a full-billing-role action (unlike insurance
    reads, which front desk also needs) — mirrors superbill_create."""
    patient, error = _billing_patient_or_error(request, patient_id)
    if error:
        return None, error
    try:
        require_role(request.user, BILLING_ROLES)
    except PermissionDenied as exc:
        return None, api_error(str(exc), status=403)
    feature_error = _billing_feature_or_error(patient.organization)
    if feature_error:
        return None, feature_error
    return patient, None


def _apply_charge_payload(charge: Charge, payload: dict, *, partial: bool) -> dict[str, str]:
    errors: dict[str, str] = {}

    if "serviceDate" in payload or not partial:
        value = payload.get("serviceDate")
        if not value:
            errors["serviceDate"] = "Service date is required."
        else:
            charge.service_date = value

    if "providerId" in payload or not partial:
        provider_id = payload.get("providerId")
        provider = User.objects.filter(pk=provider_id, organization=charge.organization).first() if provider_id else None
        if provider is None:
            errors["providerId"] = "Choose a valid provider."
        else:
            charge.provider = provider

    if "locationId" in payload:
        location_id = payload.get("locationId")
        if not location_id:
            charge.location = None
        else:
            location = Location.objects.filter(pk=location_id, organization=charge.organization).first()
            if location is None:
                errors["locationId"] = "Choose a valid location."
            else:
                charge.location = location

    if "episodeOfCareId" in payload:
        episode_id = payload.get("episodeOfCareId")
        if not episode_id:
            charge.episode_of_care = None
        else:
            episode = EpisodeOfCare.objects.filter(pk=episode_id, patient=charge.patient).first()
            if episode is None:
                errors["episodeOfCareId"] = "Choose a valid episode of care."
            else:
                charge.episode_of_care = episode

    if "noteId" in payload:
        note_id = payload.get("noteId")
        if not note_id:
            charge.clinical_note = None
        else:
            note = ClinicalNote.objects.filter(pk=note_id, patient=charge.patient).first()
            if note is None:
                errors["noteId"] = "Choose a valid note for this patient."
            elif note.status != ClinicalNote.Status.SIGNED:
                errors["noteId"] = "Only signed documentation can be linked to a charge."
            else:
                charge.clinical_note = note

    if "cptCode" in payload or not partial:
        cpt_code = str(payload.get("cptCode", "")).strip().upper()
        if not cpt_code:
            errors["cptCode"] = "CPT/HCPCS code is required."
        else:
            charge.cpt_code = cpt_code

    if "modifiers" in payload:
        modifiers = payload.get("modifiers") or []
        if not isinstance(modifiers, list):
            errors["modifiers"] = "Modifiers must be a list."
        else:
            charge.modifiers = [str(modifier).strip().upper() for modifier in modifiers]

    if "units" in payload or not partial:
        try:
            units = int(payload.get("units", 1))
            if units < 1:
                raise ValueError
        except (TypeError, ValueError):
            errors["units"] = "Units must be a whole number of at least 1."
        else:
            charge.units = units

    if "minutes" in payload:
        minutes = payload.get("minutes")
        if minutes in (None, ""):
            charge.minutes = None
        else:
            try:
                charge.minutes = int(minutes)
            except (TypeError, ValueError):
                errors["minutes"] = "Minutes must be a whole number."

    if "chargeAmount" in payload or not partial:
        value, ok = _parse_decimal(payload.get("chargeAmount"))
        if not ok or value is None:
            errors["chargeAmount"] = "Enter a valid charge amount."
        else:
            charge.charge_amount = value

    if "unitsOverrideReason" in payload:
        charge.units_override_reason = str(payload.get("unitsOverrideReason") or "").strip()

    # Recommended units are always computed server-side from documented
    # timed minutes — never client-supplied — so the comparison stays
    # trustworthy. Recompute whenever the note link or CPT code changed;
    # leave an untouched recommendation alone otherwise. See Charge's
    # docstring in models.py.
    if "noteId" in payload or "cptCode" in payload:
        if charge.clinical_note_id and "cptCode" not in errors and "noteId" not in errors:
            suggestion = coding_suggestions(charge.clinical_note)
            match = next((row for row in suggestion["cptSuggestions"] if row["code"] == charge.cpt_code), None)
            charge.recommended_units = match["suggestedUnits"] if match else None
            if match and not charge.minutes:
                charge.minutes = match["minutes"]
        elif not charge.clinical_note_id:
            charge.recommended_units = None

    if "diagnosisCodeIds" in payload:
        ids = payload.get("diagnosisCodeIds") or []
        if not isinstance(ids, list):
            errors["diagnosisCodeIds"] = "Diagnosis codes must be a list."
        else:
            codes = list(DiagnosisCode.objects.filter(pk__in=ids))
            if len(codes) != len(set(str(i) for i in ids)):
                errors["diagnosisCodeIds"] = "One or more diagnosis codes were not found."
            else:
                charge._pending_diagnosis_codes = codes

    return errors


def _units_override_response(charge: Charge) -> JsonResponse | None:
    """A units/recommendation mismatch isn't a plain "field is required"
    error — spell out the actual numbers in the message itself (Recommended:
    X, entered: Y, difference: Z) so the client can show them without a
    separate preview round-trip; every successful response also carries
    `recommendedUnits`/`unitsDifference` on the charge itself."""
    if (
        charge.recommended_units is not None
        and charge.units != charge.recommended_units
        and not charge.units_override_reason.strip()
    ):
        return api_validation_error(
            {
                "unitsOverrideReason": (
                    "Recommended %s unit(s) based on documented timed minutes; you entered %s "
                    "(difference %+d). Explain why to continue."
                )
                % (charge.recommended_units, charge.units, charge.units_difference)
            }
        )
    return None


@require_http_methods(["GET", "POST"])
@api_login_required
def patient_charges(request, patient_id):
    if request.method == "POST":
        patient, error = _billing_write_patient_or_error(request, patient_id)
        if error:
            return error
        try:
            payload = json_body(request)
        except InvalidJSON as exc:
            return api_error(str(exc), status=400)
        charge = Charge(organization=patient.organization, patient=patient, created_by=request.user)
        errors = _apply_charge_payload(charge, payload, partial=False)
        if errors:
            return api_validation_error(errors)
        override_response = _units_override_response(charge)
        if override_response:
            return override_response
        duplicate_exists = (
            Charge.objects.filter(
                patient=patient, service_date=charge.service_date, cpt_code=charge.cpt_code, provider=charge.provider,
            )
            .exclude(status=Charge.Status.VOID)
            .exists()
        )
        if duplicate_exists:
            return api_error(
                "A charge already exists for this patient, date, provider, and CPT code. Void it first if this is a correction.",
                status=409,
            )
        try:
            charge.full_clean()
            charge.save()
        except ValidationError as exc:
            return api_validation_error(_clean_error_dict(exc))
        if hasattr(charge, "_pending_diagnosis_codes"):
            charge.diagnosis_codes.set(charge._pending_diagnosis_codes)
        record_audit_event(
            actor=request.user, action="charge.created", obj=charge, patient=patient, request=request,
            metadata={"cpt_code": charge.cpt_code, "units": charge.units, "status": charge.status},
        )
        return JsonResponse({"charge": serialize_charge(charge)}, status=201)

    patient, error = _billing_read_patient_or_error(request, patient_id)
    if error:
        return error
    charges = patient.charges.select_related("provider", "location").prefetch_related("diagnosis_codes").all()
    if is_provider_limited_view(request.user):
        charges = charges.filter(provider=request.user)
    status_filter = request.GET.get("status", "").strip()
    if status_filter and status_filter in Charge.Status.values:
        charges = charges.filter(status=status_filter)
    return JsonResponse({"charges": [serialize_charge(charge) for charge in charges]})


@require_http_methods(["GET", "PATCH"])
@api_login_required
def patient_charge_detail(request, patient_id, charge_id):
    patient, error = _billing_read_patient_or_error(request, patient_id)
    if error:
        return error
    charge = (
        Charge.objects.select_related("provider", "location")
        .prefetch_related("diagnosis_codes")
        .filter(pk=charge_id, patient=patient)
        .first()
    )
    if not charge:
        return api_error("Charge was not found.", status=404)
    if is_provider_limited_view(request.user) and charge.provider_id != request.user.id:
        return api_error("You can only view charges for visits you rendered.", status=403)
    if request.method == "GET":
        return JsonResponse({"charge": serialize_charge(charge)})

    try:
        require_role(request.user, BILLING_ROLES)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    feature_error = _billing_feature_or_error(patient.organization)
    if feature_error:
        return feature_error

    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)

    if charge.status not in CHARGE_EDITABLE_STATUSES:
        # A billed or voided charge is locked — the only allowed transition
        # is straight to void, matching how real billing corrections work
        # (void and re-enter a corrected charge, never silently rewrite one
        # that has already been billed).
        if list(payload.keys()) == ["status"] and payload.get("status") == Charge.Status.VOID:
            charge.status = Charge.Status.VOID
            charge.save(update_fields=["status", "updated_at"])
            record_audit_event(actor=request.user, action="charge.voided", obj=charge, patient=patient, request=request)
            return JsonResponse({"charge": serialize_charge(charge)})
        return api_error("This charge is locked and can only be voided.", status=409)

    if charge.claim_id and charge.claim.status != Claim.Status.DRAFT:
        # Once its claim has moved past Draft (validated, submitted, or
        # further along), a charge's fields are locked — corrections go
        # through the claim's own lifecycle, not a silent charge edit.
        return api_error("This charge belongs to a claim that is no longer a draft and cannot be edited directly.", status=409)

    requested_status = payload.get("status")
    errors = _apply_charge_payload(charge, payload, partial=True)
    if errors:
        return api_validation_error(errors)
    override_response = _units_override_response(charge)
    if override_response:
        return override_response
    if requested_status:
        if requested_status not in Charge.Status.values:
            return api_validation_error({"status": "Choose a valid status."})
        charge.status = requested_status
    try:
        charge.full_clean()
    except ValidationError as exc:
        return api_validation_error(_clean_error_dict(exc))
    charge.save()
    if hasattr(charge, "_pending_diagnosis_codes"):
        charge.diagnosis_codes.set(charge._pending_diagnosis_codes)
    record_audit_event(
        actor=request.user,
        action="charge.voided" if charge.status == Charge.Status.VOID else "charge.updated",
        obj=charge, patient=patient, request=request,
        metadata={"status": charge.status},
    )
    return JsonResponse({"charge": serialize_charge(charge)})


# --- Claims -----------------------------------------------------------

MAX_CLAIM_DIAGNOSES = 12

_MANUAL_STATUS_TRANSITIONS = {
    Claim.Status.ACCEPTED,
    Claim.Status.REJECTED,
    Claim.Status.PROCESSING,
    Claim.Status.DENIED,
    Claim.Status.PARTIAL_PAYMENT,
    Claim.Status.PAID,
    Claim.Status.APPEALED,
    Claim.Status.CORRECTED,
    Claim.Status.CLOSED,
}


def serialize_claim(claim: Claim) -> dict:
    return {
        "id": str(claim.pk),
        "patientId": str(claim.patient_id),
        "patientInsuranceId": str(claim.patient_insurance_id),
        "payerId": str(claim.payer_id),
        "payerName": claim.payer.name,
        "diagnosisCodeList": claim.diagnosis_code_list,
        "status": claim.status,
        "statusLabel": claim.get_status_display(),
        "clearinghouseClaimId": claim.clearinghouse_claim_id,
        "submittedAt": claim.submitted_at.isoformat() if claim.submitted_at else None,
        "closedAt": claim.closed_at.isoformat() if claim.closed_at else None,
        "totalChargeAmount": str(claim.total_charge_amount),
        "totalPaid": str(claim.total_paid),
        "totalAdjusted": str(claim.total_adjusted),
        "balance": str(claim.balance),
        "chargeIds": [str(charge.pk) for charge in claim.charges.all()],
        "createdAt": claim.created_at.isoformat(),
    }


def _billing_claims_write_patient_or_error(request, patient_id: str):
    """Claim lifecycle actions require the 'claims' entitlement (enterprise
    tier) on top of full billing-role access — reads don't, matching the
    Payer/PatientInsurance precedent of never hiding already-created data
    just because entitlement state changed later."""
    patient, error = _billing_patient_or_error(request, patient_id)
    if error:
        return None, error
    try:
        require_role(request.user, BILLING_ROLES)
    except PermissionDenied as exc:
        return None, api_error(str(exc), status=403)
    if not organization_has_feature(patient.organization, "claims"):
        return None, api_error(
            "Insurance claim submission is not enabled for this organization. Contact your administrator.",
            status=403,
        )
    return patient, None


@require_http_methods(["GET", "POST"])
@api_login_required
def patient_claims(request, patient_id):
    if request.method == "POST":
        patient, error = _billing_claims_write_patient_or_error(request, patient_id)
        if error:
            return error
        try:
            payload = json_body(request)
        except InvalidJSON as exc:
            return api_error(str(exc), status=400)

        policy_id = payload.get("patientInsuranceId")
        policy = PatientInsurance.objects.filter(pk=policy_id, patient=patient).first() if policy_id else None
        if policy is None:
            return api_validation_error({"patientInsuranceId": "Choose a valid insurance policy for this patient."})

        charge_ids = payload.get("chargeIds")
        if not isinstance(charge_ids, list) or not charge_ids:
            return api_validation_error({"chargeIds": "Select at least one charge."})
        charges = list(Charge.objects.filter(pk__in=charge_ids, patient=patient).exclude(status=Charge.Status.VOID))
        if len(charges) != len(set(str(i) for i in charge_ids)):
            return api_validation_error({"chargeIds": "One or more charges were not found."})
        if any(charge.claim_id is not None for charge in charges):
            return api_error("One or more selected charges already belong to another claim.", status=409)

        diagnosis_codes: list[str] = []
        for charge in charges:
            for code in charge.diagnosis_codes.all():
                if code.code not in diagnosis_codes:
                    diagnosis_codes.append(code.code)
        if len(diagnosis_codes) > MAX_CLAIM_DIAGNOSES:
            return api_validation_error(
                {
                    "chargeIds": (
                        "The selected charges reference more than %s distinct diagnosis codes; "
                        "a claim allows at most %s." % (MAX_CLAIM_DIAGNOSES, MAX_CLAIM_DIAGNOSES)
                    )
                }
            )

        claim = Claim(
            organization=patient.organization, patient=patient, patient_insurance=policy, payer=policy.payer,
            diagnosis_code_list=diagnosis_codes, created_by=request.user,
        )
        try:
            claim.full_clean()
            claim.save()
        except ValidationError as exc:
            return api_validation_error(_clean_error_dict(exc))
        Charge.objects.filter(pk__in=[charge.pk for charge in charges]).update(claim=claim)
        record_audit_event(
            actor=request.user, action="claim.created", obj=claim, patient=patient, request=request,
            metadata={"charge_count": len(charges), "payer": policy.payer.name},
        )
        return JsonResponse({"claim": serialize_claim(claim)}, status=201)

    patient, error = _billing_read_patient_or_error(request, patient_id)
    if error:
        return error
    claims = patient.claims.select_related("payer", "patient_insurance").prefetch_related("charges").all()
    if is_provider_limited_view(request.user):
        claims = claims.filter(charges__provider=request.user).distinct()
    status_filter = request.GET.get("status", "").strip()
    if status_filter and status_filter in Claim.Status.values:
        claims = claims.filter(status=status_filter)
    return JsonResponse({"claims": [serialize_claim(claim) for claim in claims]})


def _claim_or_error(request, patient_id: str, claim_id: str, *, write: bool = False):
    if write:
        patient, error = _billing_claims_write_patient_or_error(request, patient_id)
    else:
        patient, error = _billing_read_patient_or_error(request, patient_id)
    if error:
        return None, None, error
    claim = (
        Claim.objects.select_related("payer", "patient_insurance")
        .prefetch_related("charges")
        .filter(pk=claim_id, patient=patient)
        .first()
    )
    if not claim:
        return None, None, api_error("Claim was not found.", status=404)
    if not write and is_provider_limited_view(request.user) and not claim.charges.filter(provider=request.user).exists():
        return None, None, api_error("You can only view claims for visits you rendered.", status=403)
    return patient, claim, None


@require_GET
@api_login_required
def patient_claim_detail(request, patient_id, claim_id):
    _, claim, error = _claim_or_error(request, patient_id, claim_id)
    if error:
        return error
    return JsonResponse({"claim": serialize_claim(claim)})


@require_POST
@api_login_required
def claim_validate(request, patient_id, claim_id):
    """Runs the full CLAIM VALIDATION checklist (see billing_services.py)
    and sets status to Ready (zero errors) or Validation Error (one or
    more). Safe to call repeatedly while the claim is still in one of
    those three pre-submission states."""
    patient, claim, error = _claim_or_error(request, patient_id, claim_id, write=True)
    if error:
        return error
    if claim.status not in {Claim.Status.DRAFT, Claim.Status.READY, Claim.Status.VALIDATION_ERROR}:
        return api_error("Only a draft claim can be (re-)validated.", status=409)
    findings = validate_claim(claim)
    has_errors = any(finding["severity"] == "error" for finding in findings)
    claim.status = Claim.Status.VALIDATION_ERROR if has_errors else Claim.Status.READY
    claim.save(update_fields=["status", "updated_at"])
    record_audit_event(
        actor=request.user, action="claim.validated", obj=claim, patient=patient, request=request,
        metadata={"status": claim.status, "error_count": sum(1 for f in findings if f["severity"] == "error")},
    )
    return JsonResponse({"claim": serialize_claim(claim), "findings": findings})


@require_POST
@api_login_required
def claim_submit(request, patient_id, claim_id):
    """Requires a claim already validated clean (status=Ready). Routes
    through the clearinghouse adapter (see care/clearinghouse.py) rather
    than transmitting directly — today that's the manual adapter, so this
    records the claim as submitted for internal tracking only; a future
    real adapter would actually transmit here without this view changing."""
    patient, claim, error = _claim_or_error(request, patient_id, claim_id, write=True)
    if error:
        return error
    if claim.status != Claim.Status.READY:
        return api_error("Validate this claim with zero errors before submitting it.", status=409)
    adapter = get_clearinghouse_adapter(patient.organization)
    result = adapter.submit_claim(claim)
    if not result.accepted:
        return api_error(result.message, status=409)
    claim.status = Claim.Status.SUBMITTED
    claim.submitted_at = timezone.now()
    if result.clearinghouse_claim_id:
        claim.clearinghouse_claim_id = result.clearinghouse_claim_id
    claim.save(update_fields=["status", "submitted_at", "clearinghouse_claim_id", "updated_at"])
    claim.charges.exclude(status=Charge.Status.VOID).update(status=Charge.Status.BILLED)
    record_audit_event(
        actor=request.user, action="claim.submitted", obj=claim, patient=patient, request=request,
        metadata={"clearinghouse_message": result.message},
    )
    return JsonResponse({"claim": serialize_claim(claim), "clearinghouseMessage": result.message})


@require_POST
@api_login_required
def claim_check_status(request, patient_id, claim_id):
    """Ask the clearinghouse adapter for this claim's current status. The
    manual adapter just echoes back what's already tracked in this system —
    this endpoint exists so calling code and the UI are ready for the day a
    real adapter is wired in, without needing to change."""
    patient, claim, error = _claim_or_error(request, patient_id, claim_id, write=True)
    if error:
        return error
    if claim.status in (Claim.Status.DRAFT, Claim.Status.READY, Claim.Status.VALIDATION_ERROR):
        return api_error("Submit this claim before checking its clearinghouse status.", status=409)
    adapter = get_clearinghouse_adapter(patient.organization)
    result = adapter.check_claim_status(claim)
    record_audit_event(
        actor=request.user, action="claim.status_checked", obj=claim, patient=patient, request=request,
        metadata={"clearinghouse_status": result.status},
    )
    return JsonResponse(
        {"claim": serialize_claim(claim), "clearinghouseStatus": result.status, "clearinghouseMessage": result.message}
    )


@require_POST
@api_login_required
def claim_status_update(request, patient_id, claim_id):
    """Manual lifecycle update for the post-submission states (Accepted,
    Rejected, Processing, Denied, Partial Payment, Paid, Appealed,
    Corrected, Closed) — driven today by a biller checking a payer portal
    or phone call; a future clearinghouse adapter would call this same
    transition from an automated ERA/status feed instead."""
    patient, claim, error = _claim_or_error(request, patient_id, claim_id, write=True)
    if error:
        return error
    if claim.status in (Claim.Status.DRAFT, Claim.Status.READY, Claim.Status.VALIDATION_ERROR):
        return api_error("Submit this claim before updating its payer-facing status.", status=409)
    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)
    new_status = payload.get("status")
    if new_status not in _MANUAL_STATUS_TRANSITIONS:
        return api_validation_error({"status": "Choose a valid claim status."})
    claim.status = new_status
    if new_status in Claim.TERMINAL_STATUSES:
        claim.closed_at = timezone.now()
    claim.save(update_fields=["status", "closed_at", "updated_at"])
    record_audit_event(
        actor=request.user,
        action="claim.corrected" if new_status == Claim.Status.CORRECTED else "claim.status_changed",
        obj=claim, patient=patient, request=request,
        metadata={"status": new_status},
    )
    return JsonResponse({"claim": serialize_claim(claim)})


@require_GET
@api_login_required
def claim_cms1500(request, patient_id, claim_id):
    _, claim, error = _claim_or_error(request, patient_id, claim_id)
    if error:
        return error
    return JsonResponse({"cms1500": build_cms1500_data(claim)})


@require_POST
@api_login_required
def patient_insurance_verify_eligibility(request, patient_id, policy_id):
    """Routes through the clearinghouse adapter (care/clearinghouse.py) —
    today's manual adapter never fabricates a real-time eligibility
    response, it tells the caller to verify with the payer directly."""
    patient, error = _billing_patient_or_error(request, patient_id)
    if error:
        return error
    try:
        require_role(request.user, BILLING_ROLES)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    feature_error = _billing_feature_or_error(patient.organization)
    if feature_error:
        return feature_error
    policy = PatientInsurance.objects.filter(pk=policy_id, patient=patient).first()
    if not policy:
        return api_error("Insurance policy was not found.", status=404)
    adapter = get_clearinghouse_adapter(patient.organization)
    result = adapter.verify_eligibility(policy)
    record_audit_event(
        actor=request.user, action="patient_insurance.eligibility_checked", obj=policy, patient=patient, request=request,
        metadata={"verified": result.verified},
    )
    return JsonResponse({"verified": result.verified, "message": result.message})


# --- Claim transactions (payment posting / ERA-EOB workflow) ---------------

def serialize_claim_transaction(transaction: ClaimTransaction) -> dict:
    return {
        "id": str(transaction.pk),
        "patientId": str(transaction.patient_id),
        "claimId": str(transaction.claim_id) if transaction.claim_id else None,
        "transferredToClaimId": str(transaction.transferred_to_claim_id) if transaction.transferred_to_claim_id else None,
        "kind": transaction.kind,
        "kindLabel": transaction.get_kind_display(),
        "method": transaction.method,
        "methodLabel": transaction.get_method_display() if transaction.method else "",
        "amount": str(transaction.amount),
        "paymentDate": transaction.payment_date.isoformat(),
        "reference": transaction.reference,
        "denialCode": transaction.denial_code,
        "denialReason": transaction.denial_reason,
        "notes": transaction.notes,
        "isMatched": transaction.is_matched,
        "recordedBy": (transaction.recorded_by.get_full_name() or transaction.recorded_by.username) if transaction.recorded_by_id else None,
        "createdAt": transaction.created_at.isoformat(),
    }


def _apply_transaction_payload(transaction: ClaimTransaction, payload: dict) -> dict[str, str]:
    errors: dict[str, str] = {}

    kind = payload.get("kind")
    if kind not in ClaimTransaction.Kind.values:
        errors["kind"] = "Choose a valid transaction type."
    else:
        transaction.kind = kind

    method = payload.get("method", "")
    if method and method not in ClaimTransaction.Method.values:
        errors["method"] = "Choose a valid payment method."
    else:
        transaction.method = method

    amount_value, ok = _parse_decimal(payload.get("amount"))
    if not ok or amount_value is None or amount_value <= 0:
        errors["amount"] = "Enter an amount greater than zero."
    else:
        transaction.amount = amount_value

    payment_date = payload.get("paymentDate")
    if payment_date:
        transaction.payment_date = payment_date

    claim_id = payload.get("claimId")
    if claim_id:
        claim = Claim.objects.filter(pk=claim_id, patient=transaction.patient).first()
        if claim is None:
            errors["claimId"] = "Choose a valid claim for this patient."
        else:
            transaction.claim = claim
    else:
        transaction.claim = None

    transferred_to_claim_id = payload.get("transferredToClaimId")
    if transferred_to_claim_id:
        destination = Claim.objects.filter(pk=transferred_to_claim_id, patient=transaction.patient).first()
        if destination is None:
            errors["transferredToClaimId"] = "Choose a valid destination claim for this patient."
        else:
            transaction.transferred_to_claim = destination
    else:
        transaction.transferred_to_claim = None

    transaction.reference = str(payload.get("reference") or "").strip()
    transaction.denial_code = str(payload.get("denialCode") or "").strip()
    transaction.denial_reason = str(payload.get("denialReason") or "").strip()
    transaction.notes = str(payload.get("notes") or "").strip()

    return errors


@require_http_methods(["GET", "POST"])
@api_login_required
def patient_transactions(request, patient_id):
    """Payment posting: insurance payment, patient payment, contractual
    adjustment, write-off, refund, or a balance transfer to another claim
    (e.g. primary -> secondary insurance). `claimId` is optional on create —
    an ERA/EOB line that can't be matched to a specific claim yet is posted
    with no claim (see `transaction_match` to match it later), matching the
    module's "unmatched payments... manual review where necessary" workflow."""
    if request.method == "POST":
        patient, error = _billing_write_patient_or_error(request, patient_id)
        if error:
            return error
        try:
            payload = json_body(request)
        except InvalidJSON as exc:
            return api_error(str(exc), status=400)
        transaction = ClaimTransaction(organization=patient.organization, patient=patient, recorded_by=request.user)
        errors = _apply_transaction_payload(transaction, payload)
        if errors:
            return api_validation_error(errors)
        try:
            transaction.full_clean()
            transaction.save()
        except ValidationError as exc:
            return api_validation_error(_clean_error_dict(exc))
        record_audit_event(
            actor=request.user, action="claim_transaction.created", obj=transaction, patient=patient, request=request,
            metadata={"kind": transaction.kind, "amount": str(transaction.amount), "matched": transaction.is_matched},
        )
        return JsonResponse({"transaction": serialize_claim_transaction(transaction)}, status=201)

    patient, error = _billing_patient_or_error(request, patient_id)
    if error:
        return error
    transactions = patient.claim_transactions.select_related("claim", "recorded_by").all()
    if request.GET.get("unmatched") == "1":
        transactions = transactions.filter(claim__isnull=True)
    claim_id = request.GET.get("claimId", "").strip()
    if claim_id:
        transactions = transactions.filter(claim_id=claim_id)
    return JsonResponse({"transactions": [serialize_claim_transaction(t) for t in transactions]})


@require_POST
@api_login_required
def transaction_match(request, patient_id, transaction_id):
    """Attach a previously-unmatched transaction (e.g. an ERA line entered
    before the corresponding claim could be identified) to a claim."""
    patient, error = _billing_write_patient_or_error(request, patient_id)
    if error:
        return error
    transaction = ClaimTransaction.objects.filter(pk=transaction_id, patient=patient).first()
    if not transaction:
        return api_error("Transaction was not found.", status=404)
    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)
    claim_id = payload.get("claimId")
    claim = Claim.objects.filter(pk=claim_id, patient=patient).first() if claim_id else None
    if claim is None:
        return api_validation_error({"claimId": "Choose a valid claim for this patient."})
    transaction.claim = claim
    try:
        transaction.full_clean()
        transaction.save(update_fields=["claim", "updated_at"])
    except ValidationError as exc:
        return api_validation_error(_clean_error_dict(exc))
    record_audit_event(
        actor=request.user, action="claim_transaction.matched", obj=transaction, patient=patient, request=request,
        metadata={"claim_id": str(claim.pk)},
    )
    return JsonResponse({"transaction": serialize_claim_transaction(transaction)})


# --- AR aging dashboard ----------------------------------------------------

AR_BUCKET_LABELS = ["0-30", "31-60", "61-90", "91-120", "120+"]


def _ar_bucket_for(age_days: int) -> str:
    if age_days <= 30:
        return "0-30"
    if age_days <= 60:
        return "31-60"
    if age_days <= 90:
        return "61-90"
    if age_days <= 120:
        return "91-120"
    return "120+"


@require_GET
@api_login_required
def ar_aging_report(request):
    """Real, currently-queryable AR aging — every bucket total is the live
    sum of Claim.balance for claims matching the filters, aged from each
    claim's earliest charge service date; nothing here is fabricated. Only
    claims that have left the pre-submission states are included — a
    draft/ready claim carries no accounts-receivable exposure yet."""
    organization, error = organization_or_error(request, roles=BILLING_ROLES)
    if error:
        return error

    claims = (
        Claim.objects.filter(organization=organization)
        .exclude(status__in={Claim.Status.DRAFT, Claim.Status.READY, Claim.Status.VALIDATION_ERROR})
        .select_related("payer", "patient")
        .prefetch_related("charges", "transactions")
    )
    payer_id = request.GET.get("payerId", "").strip()
    if payer_id:
        claims = claims.filter(payer_id=payer_id)
    status_filter = request.GET.get("status", "").strip()
    if status_filter and status_filter in Claim.Status.values:
        claims = claims.filter(status=status_filter)
    patient_id = request.GET.get("patientId", "").strip()
    if patient_id:
        claims = claims.filter(patient_id=patient_id)
    provider_id = request.GET.get("providerId", "").strip()
    if provider_id:
        claims = claims.filter(charges__provider_id=provider_id)
    location_id = request.GET.get("locationId", "").strip()
    if location_id:
        claims = claims.filter(charges__location_id=location_id)
    claims = claims.distinct()

    today = timezone.localdate()
    buckets = {label: Decimal("0.00") for label in AR_BUCKET_LABELS}
    rows = []
    for claim in claims:
        balance = claim.balance
        if balance <= 0:
            continue
        service_dates = [charge.service_date for charge in claim.charges.all()]
        if not service_dates:
            continue
        age_days = max((today - min(service_dates)).days, 0)
        bucket = _ar_bucket_for(age_days)
        buckets[bucket] += balance
        rows.append(
            {
                "claimId": str(claim.pk),
                "patientId": str(claim.patient_id),
                "patientName": claim.patient.full_name,
                "payerName": claim.payer.name,
                "status": claim.status,
                "statusLabel": claim.get_status_display(),
                "balance": str(balance),
                "ageDays": age_days,
                "bucket": bucket,
            }
        )

    return JsonResponse(
        {
            "buckets": {label: str(total) for label, total in buckets.items()},
            "totalOutstanding": str(sum(buckets.values(), Decimal("0.00"))),
            "claims": rows,
        }
    )


# --- Claim denials (denial work queue) --------------------------------

def serialize_denial(denial: ClaimDenial) -> dict:
    return {
        "id": str(denial.pk),
        "patientId": str(denial.patient_id),
        "claimId": str(denial.claim_id),
        "payerName": denial.claim.payer.name,
        "denialCode": denial.denial_code,
        "denialReason": denial.denial_reason,
        "deniedOn": denial.denied_on.isoformat(),
        "ownerId": str(denial.owner_id) if denial.owner_id else None,
        "ownerName": (denial.owner.get_full_name() or denial.owner.username) if denial.owner_id else None,
        "dueDate": denial.due_date.isoformat() if denial.due_date else None,
        "isOverdue": denial.is_overdue,
        "actionNotes": denial.action_notes,
        "appealStatus": denial.appeal_status,
        "appealStatusLabel": denial.get_appeal_status_display(),
        "resolution": denial.resolution,
        "resolutionLabel": denial.get_resolution_display(),
        "resolvedAt": denial.resolved_at.isoformat() if denial.resolved_at else None,
        "createdAt": denial.created_at.isoformat(),
    }


def _apply_denial_payload(denial: ClaimDenial, payload: dict, *, partial: bool) -> dict[str, str]:
    errors: dict[str, str] = {}
    if "denialReason" in payload or not partial:
        reason = str(payload.get("denialReason", "")).strip()
        if not reason:
            errors["denialReason"] = "Denial reason is required."
        else:
            denial.denial_reason = reason
    if "denialCode" in payload:
        denial.denial_code = str(payload.get("denialCode") or "").strip()
    if payload.get("deniedOn"):
        denial.denied_on = payload["deniedOn"]
    if "ownerId" in payload:
        owner_id = payload.get("ownerId")
        if owner_id:
            owner = User.objects.filter(pk=owner_id, organization=denial.organization).first()
            if owner is None:
                errors["ownerId"] = "Choose a valid owner."
            else:
                denial.owner = owner
        else:
            denial.owner = None
    if "dueDate" in payload:
        denial.due_date = payload.get("dueDate") or None
    if "actionNotes" in payload:
        denial.action_notes = str(payload.get("actionNotes") or "").strip()
    if "appealStatus" in payload:
        appeal_status = payload.get("appealStatus")
        if appeal_status not in ClaimDenial.AppealStatus.values:
            errors["appealStatus"] = "Choose a valid appeal status."
        else:
            denial.appeal_status = appeal_status
    if "resolution" in payload:
        resolution = payload.get("resolution")
        if resolution not in ClaimDenial.Resolution.values:
            errors["resolution"] = "Choose a valid resolution."
        else:
            was_open = denial.resolution == ClaimDenial.Resolution.OPEN
            denial.resolution = resolution
            if resolution != ClaimDenial.Resolution.OPEN and was_open:
                denial.resolved_at = timezone.now()
            elif resolution == ClaimDenial.Resolution.OPEN:
                denial.resolved_at = None
    return errors


@require_http_methods(["GET", "POST"])
@api_login_required
def claim_denials(request, patient_id, claim_id):
    patient, claim, error = _claim_or_error(request, patient_id, claim_id, write=(request.method == "POST"))
    if error:
        return error
    if request.method == "POST":
        try:
            payload = json_body(request)
        except InvalidJSON as exc:
            return api_error(str(exc), status=400)
        denial = ClaimDenial(organization=patient.organization, patient=patient, claim=claim, created_by=request.user)
        errors = _apply_denial_payload(denial, payload, partial=False)
        if errors:
            return api_validation_error(errors)
        try:
            denial.full_clean()
            denial.save()
        except ValidationError as exc:
            return api_validation_error(_clean_error_dict(exc))
        record_audit_event(
            actor=request.user, action="claim_denial.created", obj=denial, patient=patient, request=request,
            metadata={"claim_id": str(claim.pk), "denial_reason": denial.denial_reason},
        )
        return JsonResponse({"denial": serialize_denial(denial)}, status=201)

    denials = claim.denials.select_related("owner").all()
    return JsonResponse({"denials": [serialize_denial(denial) for denial in denials]})


@require_http_methods(["GET", "PATCH"])
@api_login_required
def denial_detail(request, patient_id, denial_id):
    if request.method == "PATCH":
        patient, error = _billing_claims_write_patient_or_error(request, patient_id)
    else:
        patient, error = _billing_patient_or_error(request, patient_id)
    if error:
        return error
    denial = ClaimDenial.objects.select_related("claim", "claim__payer", "owner").filter(pk=denial_id, patient=patient).first()
    if not denial:
        return api_error("Denial was not found.", status=404)
    if request.method == "GET":
        return JsonResponse({"denial": serialize_denial(denial)})

    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)
    errors = _apply_denial_payload(denial, payload, partial=True)
    if errors:
        return api_validation_error(errors)
    try:
        denial.full_clean()
        denial.save()
    except ValidationError as exc:
        return api_validation_error(_clean_error_dict(exc))
    record_audit_event(
        actor=request.user, action="claim_denial.updated", obj=denial, patient=patient, request=request,
        metadata={"resolution": denial.resolution, "appeal_status": denial.appeal_status},
    )
    return JsonResponse({"denial": serialize_denial(denial)})


@require_GET
@api_login_required
def denial_work_queue(request):
    """Org-wide denial work queue — every open (and, on request, resolved)
    denial across every patient, filterable by owner/resolution/appeal
    status/payer/overdue. This is the queue a billing team actually works
    from, as opposed to the per-claim denial list."""
    organization, error = organization_or_error(request, roles=BILLING_ROLES)
    if error:
        return error
    denials = ClaimDenial.objects.filter(organization=organization).select_related(
        "claim", "claim__payer", "owner", "patient"
    )
    owner_id = request.GET.get("ownerId", "").strip()
    if owner_id:
        denials = denials.filter(owner_id=owner_id)
    resolution = request.GET.get("resolution", "").strip()
    if resolution and resolution in ClaimDenial.Resolution.values:
        denials = denials.filter(resolution=resolution)
    appeal_status = request.GET.get("appealStatus", "").strip()
    if appeal_status and appeal_status in ClaimDenial.AppealStatus.values:
        denials = denials.filter(appeal_status=appeal_status)
    payer_id = request.GET.get("payerId", "").strip()
    if payer_id:
        denials = denials.filter(claim__payer_id=payer_id)
    rows = list(denials)
    if request.GET.get("overdue") == "1":
        rows = [denial for denial in rows if denial.is_overdue]
    return JsonResponse({"denials": [serialize_denial(denial) for denial in rows]})


# --- Patient statements -------------------------------------------------

def serialize_statement(statement: PatientStatement) -> dict:
    return {
        "id": str(statement.pk),
        "patientId": str(statement.patient_id),
        "statementDate": statement.statement_date.isoformat(),
        "dueDate": statement.due_date.isoformat(),
        "balanceAtGeneration": str(statement.balance_at_generation),
        "generatedBy": (
            statement.generated_by.get_full_name() or statement.generated_by.username
        ) if statement.generated_by_id else None,
        "createdAt": statement.created_at.isoformat(),
    }


@require_http_methods(["GET", "POST"])
@api_login_required
def patient_statements(request, patient_id):
    if request.method == "POST":
        patient, error = _billing_write_patient_or_error(request, patient_id)
        if error:
            return error
        try:
            payload = json_body(request)
        except InvalidJSON as exc:
            return api_error(str(exc), status=400)
        due_date = payload.get("dueDate")
        if not due_date:
            return api_validation_error({"dueDate": "Due date is required."})
        statement = PatientStatement(
            organization=patient.organization, patient=patient, due_date=due_date, generated_by=request.user,
            balance_at_generation=Decimal("0.00"),
        )
        if payload.get("statementDate"):
            statement.statement_date = payload["statementDate"]
        try:
            statement.full_clean()
            statement.save()
        except ValidationError as exc:
            return api_validation_error(_clean_error_dict(exc))
        # The stored balance snapshot always matches what the statement
        # itself displays — computed from the same builder, right after save.
        data = build_patient_statement_data(statement)
        statement.balance_at_generation = Decimal(data["totalBalance"])
        statement.save(update_fields=["balance_at_generation"])
        record_audit_event(
            actor=request.user, action="patient_statement.generated", obj=statement, patient=patient, request=request,
            metadata={"balance": str(statement.balance_at_generation)},
        )
        return JsonResponse({"statement": serialize_statement(statement), "data": data}, status=201)

    patient, error = _billing_patient_or_error(request, patient_id)
    if error:
        return error
    statements = patient.statements.select_related("generated_by").all()
    return JsonResponse({"statements": [serialize_statement(statement) for statement in statements]})


@require_GET
@api_login_required
def statement_detail(request, patient_id, statement_id):
    patient, error = _billing_patient_or_error(request, patient_id)
    if error:
        return error
    statement = PatientStatement.objects.filter(pk=statement_id, patient=patient).first()
    if not statement:
        return api_error("Statement was not found.", status=404)
    return JsonResponse({"statement": serialize_statement(statement), "data": build_patient_statement_data(statement)})


# --- Cash-pay service price list ----------------------------------------

def serialize_service_price(price: ServicePrice) -> dict:
    return {
        "id": str(price.pk),
        "cptCode": price.cpt_code,
        "label": price.label,
        "price": str(price.price),
        "isActive": price.is_active,
        "homeVisitKind": price.home_visit_kind or None,
        "homeVisitKindLabel": price.get_home_visit_kind_display() if price.home_visit_kind else None,
        "isHomeVisitTravelFee": price.is_home_visit_travel_fee,
        "depositAmount": str(price.deposit_amount) if price.deposit_amount is not None else None,
        "createdAt": price.created_at.isoformat(),
    }


@require_http_methods(["GET", "POST"])
@api_login_required
def service_prices(request):
    organization, error = organization_or_error(request, roles=PAYMENT_COLLECTION_ROLES)
    if error:
        return error
    if request.method == "POST":
        try:
            require_role(request.user, BILLING_ROLES)
        except PermissionDenied as exc:
            return api_error(str(exc), status=403)
        feature_error = _billing_feature_or_error(organization)
        if feature_error:
            return feature_error
        try:
            payload = json_body(request)
        except InvalidJSON as exc:
            return api_error(str(exc), status=400)
        cpt_code = str(payload.get("cptCode", "")).strip().upper()
        label = str(payload.get("label", "")).strip()
        errors: dict[str, str] = {}
        if not cpt_code:
            errors["cptCode"] = "CPT/HCPCS code is required."
        if not label:
            errors["label"] = "Label is required."
        price_value, ok = _parse_decimal(payload.get("price"))
        if not ok or price_value is None or price_value <= 0:
            errors["price"] = "Enter a price greater than zero."
        home_visit_kind = str(payload.get("homeVisitKind") or "").strip()
        if home_visit_kind and home_visit_kind not in Appointment.Kind.values:
            errors["homeVisitKind"] = "Choose a valid visit kind."
        deposit_amount, deposit_ok = _parse_decimal(payload.get("depositAmount"))
        if not deposit_ok:
            errors["depositAmount"] = "Enter a valid deposit amount."
        if errors:
            return api_validation_error(errors)
        service_price = ServicePrice(
            organization=organization, cpt_code=cpt_code, label=label, price=price_value, created_by=request.user,
            home_visit_kind=home_visit_kind, is_home_visit_travel_fee=bool(payload.get("isHomeVisitTravelFee")),
            deposit_amount=deposit_amount,
        )
        try:
            service_price.full_clean()
            service_price.save()
        except ValidationError as exc:
            return api_validation_error(_clean_error_dict(exc))
        record_audit_event(actor=request.user, action="service_price.created", obj=service_price, request=request)
        return JsonResponse({"servicePrice": serialize_service_price(service_price)}, status=201)

    records = ServicePrice.objects.filter(organization=organization).order_by("cpt_code")
    if request.GET.get("activeOnly") == "1":
        records = records.filter(is_active=True)
    return JsonResponse({"servicePrices": [serialize_service_price(record) for record in records]})


@require_http_methods(["GET", "PATCH", "DELETE"])
@api_login_required
def service_price_detail(request, price_id):
    organization, error = organization_or_error(request, roles=PAYMENT_COLLECTION_ROLES)
    if error:
        return error
    service_price = ServicePrice.objects.filter(pk=price_id, organization=organization).first()
    if not service_price:
        return api_error("Service price was not found.", status=404)
    if request.method == "GET":
        return JsonResponse({"servicePrice": serialize_service_price(service_price)})

    try:
        require_role(request.user, BILLING_ROLES)
    except PermissionDenied as exc:
        return api_error(str(exc), status=403)
    feature_error = _billing_feature_or_error(organization)
    if feature_error:
        return feature_error

    if request.method == "DELETE":
        if not service_price.is_active:
            return api_error("This service price is already inactive.", status=409)
        service_price.is_active = False
        service_price.save(update_fields=["is_active", "updated_at"])
        record_audit_event(actor=request.user, action="service_price.deactivated", obj=service_price, request=request)
        return JsonResponse({"servicePrice": serialize_service_price(service_price)})

    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)
    if "label" in payload:
        service_price.label = str(payload["label"]).strip()
    if "price" in payload:
        value, ok = _parse_decimal(payload["price"])
        if not ok or value is None or value <= 0:
            return api_validation_error({"price": "Enter a price greater than zero."})
        service_price.price = value
    if "isActive" in payload:
        service_price.is_active = bool(payload["isActive"])
    if "homeVisitKind" in payload:
        home_visit_kind = str(payload["homeVisitKind"] or "").strip()
        if home_visit_kind and home_visit_kind not in Appointment.Kind.values:
            return api_validation_error({"homeVisitKind": "Choose a valid visit kind."})
        service_price.home_visit_kind = home_visit_kind
    if "isHomeVisitTravelFee" in payload:
        service_price.is_home_visit_travel_fee = bool(payload["isHomeVisitTravelFee"])
    if "depositAmount" in payload:
        value, ok = _parse_decimal(payload["depositAmount"])
        if not ok:
            return api_validation_error({"depositAmount": "Enter a valid deposit amount."})
        service_price.deposit_amount = value
    try:
        service_price.full_clean()
    except ValidationError as exc:
        return api_validation_error(_clean_error_dict(exc))
    service_price.save()
    record_audit_event(actor=request.user, action="service_price.updated", obj=service_price, request=request)
    return JsonResponse({"servicePrice": serialize_service_price(service_price)})


# --- Cash-pay packages / memberships -------------------------------------

def serialize_cash_package(package: CashPackage) -> dict:
    return {
        "id": str(package.pk),
        "patientId": str(package.patient_id),
        "kind": package.kind,
        "kindLabel": package.get_kind_display(),
        "name": package.name,
        "visitsIncluded": package.visits_included,
        "visitsUsed": package.visits_used,
        "visitsRemaining": package.visits_remaining,
        "price": str(package.price),
        "discountPercent": str(package.discount_percent) if package.discount_percent is not None else None,
        "purchasedOn": package.purchased_on.isoformat(),
        "expiresAt": package.expires_at.isoformat() if package.expires_at else None,
        "status": package.status,
        "statusLabel": package.get_status_display(),
        "isActive": package.is_active,
        "createdAt": package.created_at.isoformat(),
    }


@require_http_methods(["GET", "POST"])
@api_login_required
def patient_cash_packages(request, patient_id):
    if request.method == "POST":
        patient, error = _billing_write_patient_or_error(request, patient_id)
        if error:
            return error
        try:
            payload = json_body(request)
        except InvalidJSON as exc:
            return api_error(str(exc), status=400)
        kind = payload.get("kind")
        if kind not in CashPackage.Kind.values:
            return api_validation_error({"kind": "Choose a valid package type."})
        name = str(payload.get("name", "")).strip()
        if not name:
            return api_validation_error({"name": "Name is required."})
        price_value, ok = _parse_decimal(payload.get("price"))
        if not ok or price_value is None or price_value <= 0:
            return api_validation_error({"price": "Enter a price greater than zero."})
        package = CashPackage(
            organization=patient.organization, patient=patient, kind=kind, name=name, price=price_value,
            created_by=request.user,
        )
        visits_included = payload.get("visitsIncluded")
        if visits_included not in (None, ""):
            try:
                package.visits_included = int(visits_included)
            except (TypeError, ValueError):
                return api_validation_error({"visitsIncluded": "Enter a whole number of visits."})
        discount_percent = payload.get("discountPercent")
        if discount_percent not in (None, ""):
            value, ok = _parse_decimal(discount_percent)
            if not ok:
                return api_validation_error({"discountPercent": "Enter a valid percentage."})
            package.discount_percent = value
        if payload.get("expiresAt"):
            package.expires_at = payload["expiresAt"]
        try:
            package.full_clean()
            package.save()
        except ValidationError as exc:
            return api_validation_error(_clean_error_dict(exc))
        record_audit_event(
            actor=request.user, action="cash_package.created", obj=package, patient=patient, request=request,
            metadata={"kind": kind, "price": str(package.price)},
        )
        return JsonResponse({"cashPackage": serialize_cash_package(package)}, status=201)

    patient, error = _billing_patient_or_error(request, patient_id)
    if error:
        return error
    packages = patient.cash_packages.all()
    return JsonResponse({"cashPackages": [serialize_cash_package(package) for package in packages]})


@require_http_methods(["GET", "PATCH"])
@api_login_required
def cash_package_detail(request, patient_id, package_id):
    if request.method == "PATCH":
        patient, error = _billing_write_patient_or_error(request, patient_id)
    else:
        patient, error = _billing_patient_or_error(request, patient_id)
    if error:
        return error
    package = CashPackage.objects.filter(pk=package_id, patient=patient).first()
    if not package:
        return api_error("Cash package was not found.", status=404)
    if request.method == "GET":
        return JsonResponse({"cashPackage": serialize_cash_package(package)})

    try:
        payload = json_body(request)
    except InvalidJSON as exc:
        return api_error(str(exc), status=400)
    action = payload.get("action")
    if action == "record_visit":
        if package.visits_included is not None and package.visits_used >= package.visits_included:
            return api_error("No visits remaining on this package.", status=409)
        package.visits_used += 1
    elif action == "cancel":
        package.status = CashPackage.Status.CANCELLED
    elif "status" in payload:
        if payload["status"] not in CashPackage.Status.values:
            return api_validation_error({"status": "Choose a valid status."})
        package.status = payload["status"]
    try:
        package.full_clean()
        package.save()
    except ValidationError as exc:
        return api_validation_error(_clean_error_dict(exc))
    record_audit_event(
        actor=request.user, action="cash_package.updated", obj=package, patient=patient, request=request,
        metadata={"action": action, "visits_used": package.visits_used, "status": package.status},
    )
    return JsonResponse({"cashPackage": serialize_cash_package(package)})


# --- Patient-facing superbill data ---------------------------------------

@require_GET
@api_login_required
def superbill_data(request, patient_id, superbill_id):
    """Normalized superbill data for patient hand-out/self-filing — see
    billing_services.build_patient_superbill_data. Read-only; superbill
    creation stays on the existing endpoint (workflow_views.superbill_create)."""
    patient, error = _billing_patient_or_error(request, patient_id)
    if error:
        return error
    superbill = Superbill.objects.filter(pk=superbill_id, patient=patient).first()
    if not superbill:
        return api_error("Superbill was not found.", status=404)
    return JsonResponse({"superbill": build_patient_superbill_data(superbill)})


# --- Billing summary reports ---------------------------------------------
# Charges, collections, payments, claim status, clean claim rate, revenue by
# provider/location/payer, and patient balances. AR aging (bucketed by age)
# and the denial work queue are separate, already-built reports — see
# ar_aging_report and denial_work_queue above. Every number here is a real,
# live aggregate — "revenue" means billed/production charge amount (the
# standard RCM meaning), reported alongside a separately-computed
# "collections" figure (actual cash received), never conflated.

MAX_PATIENT_BALANCE_ROWS = 50


@require_GET
@api_login_required
def billing_summary_report(request):
    organization, error = organization_or_error(request, roles=BILLING_ROLES)
    if error:
        return error

    today = timezone.localdate()
    try:
        window_start = date.fromisoformat(request.GET.get("start")) if request.GET.get("start") else today - timedelta(days=90)
        window_end = date.fromisoformat(request.GET.get("end")) if request.GET.get("end") else today
    except ValueError:
        return api_error("start and end must be valid dates (YYYY-MM-DD).", status=400)

    charges = (
        Charge.objects.filter(organization=organization, service_date__gte=window_start, service_date__lte=window_end)
        .exclude(status=Charge.Status.VOID)
        .select_related("provider", "location", "claim__payer")
    )
    charge_count = 0
    charge_total = Decimal("0.00")
    by_provider: dict[str, dict] = {}
    by_location: dict[str, dict] = {}
    by_payer: dict[str, dict] = {}
    for charge in charges:
        charge_count += 1
        charge_total += charge.charge_amount

        provider_key = str(charge.provider_id)
        bucket = by_provider.setdefault(provider_key, {"id": provider_key, "name": charge.provider.get_full_name() or charge.provider.username, "amount": Decimal("0.00")})
        bucket["amount"] += charge.charge_amount

        if charge.location_id:
            location_key = str(charge.location_id)
            bucket = by_location.setdefault(location_key, {"id": location_key, "name": charge.location.name, "amount": Decimal("0.00")})
            bucket["amount"] += charge.charge_amount

        if charge.claim_id and charge.claim.payer_id:
            payer_key = str(charge.claim.payer_id)
            bucket = by_payer.setdefault(payer_key, {"id": payer_key, "name": charge.claim.payer.name, "amount": Decimal("0.00")})
            bucket["amount"] += charge.charge_amount

    transactions = ClaimTransaction.objects.filter(
        organization=organization, payment_date__gte=window_start, payment_date__lte=window_end
    )
    payment_totals = {kind: Decimal("0.00") for kind in ClaimTransaction.Kind.values}
    for transaction in transactions:
        payment_totals[transaction.kind] += transaction.amount
    collections = (
        payment_totals[ClaimTransaction.Kind.INSURANCE_PAYMENT]
        + payment_totals[ClaimTransaction.Kind.PATIENT_PAYMENT]
        - payment_totals[ClaimTransaction.Kind.REFUND]
    )

    claims_by_status: dict[str, int] = {}
    for status_value in Claim.Status.values:
        claims_by_status[status_value] = Claim.objects.filter(organization=organization, status=status_value).count()

    submitted_in_window = Claim.objects.filter(
        organization=organization, submitted_at__date__gte=window_start, submitted_at__date__lte=window_end,
    )
    submitted_count = submitted_in_window.count()
    denied_count = submitted_in_window.filter(denials__isnull=False).distinct().count()
    clean_claim_rate = (
        round((submitted_count - denied_count) / submitted_count * 100, 1) if submitted_count else None
    )

    balance_claims = (
        Claim.objects.filter(organization=organization)
        .exclude(status__in={Claim.Status.DRAFT, Claim.Status.READY, Claim.Status.VALIDATION_ERROR})
        .select_related("patient")
        .prefetch_related("charges", "transactions")
    )
    balances_by_patient: dict[str, dict] = {}
    for claim in balance_claims:
        balance = claim.balance
        if balance <= 0:
            continue
        bucket = balances_by_patient.setdefault(
            str(claim.patient_id), {"patientId": str(claim.patient_id), "patientName": claim.patient.full_name, "balance": Decimal("0.00")}
        )
        bucket["balance"] += balance
    patient_balances = sorted(balances_by_patient.values(), key=lambda row: row["balance"], reverse=True)[:MAX_PATIENT_BALANCE_ROWS]

    return JsonResponse(
        {
            "windowStart": window_start.isoformat(),
            "windowEnd": window_end.isoformat(),
            "charges": {"count": charge_count, "totalAmount": str(charge_total)},
            "collections": {"totalAmount": str(collections)},
            "payments": {
                "insurancePayments": str(payment_totals[ClaimTransaction.Kind.INSURANCE_PAYMENT]),
                "patientPayments": str(payment_totals[ClaimTransaction.Kind.PATIENT_PAYMENT]),
                "adjustments": str(payment_totals[ClaimTransaction.Kind.ADJUSTMENT]),
                "writeOffs": str(payment_totals[ClaimTransaction.Kind.WRITE_OFF]),
                "refunds": str(payment_totals[ClaimTransaction.Kind.REFUND]),
            },
            "claimsByStatus": claims_by_status,
            "cleanClaimRate": str(clean_claim_rate) if clean_claim_rate is not None else None,
            "claimsSubmittedInWindow": submitted_count,
            "revenueByProvider": sorted(
                [{"id": row["id"], "name": row["name"], "amount": str(row["amount"])} for row in by_provider.values()],
                key=lambda row: row["amount"], reverse=True,
            ),
            "revenueByLocation": sorted(
                [{"id": row["id"], "name": row["name"], "amount": str(row["amount"])} for row in by_location.values()],
                key=lambda row: row["amount"], reverse=True,
            ),
            "revenueByPayer": sorted(
                [{"id": row["id"], "name": row["name"], "amount": str(row["amount"])} for row in by_payer.values()],
                key=lambda row: row["amount"], reverse=True,
            ),
            "patientBalances": [{**row, "balance": str(row["balance"])} for row in patient_balances],
        }
    )
