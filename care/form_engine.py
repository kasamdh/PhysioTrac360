"""The reusable form engine: schema-driven templates + insert-only
submissions, shared by digital intake, consent/privacy acknowledgements, and
any future assignable form — one engine, not one model per form type.

Two other modules touch forms for a specific purpose and are NOT this
module: `care/forms.py` (unrelated — legacy Django ModelForm classes for the
server-rendered admin pages) and the `Consent` model in care/models.py
(staff-witnessed consent, unchanged). `record_consent_if_applicable` below
is the one deliberate bridge between the two: a portal e-signature that
answers a required checkbox also creates a `Consent` row, so staff keep
seeing patient consent in the one place (IntakeConsentPanel) they already
look, without this module owning that model.
"""
from __future__ import annotations

from django.utils import timezone

from .models import Consent, FormSubmission, FormTemplate, Organization, Patient

DIGITAL_INTAKE_SCHEMA = [
    {
        "key": "demographics",
        "label": "Demographics",
        "fields": [
            {"key": "preferredName", "label": "Preferred name", "type": "text", "required": False},
            {"key": "pronouns", "label": "Pronouns", "type": "text", "required": False},
            {"key": "occupation", "label": "Occupation", "type": "text", "required": False},
        ],
    },
    {
        "key": "contact",
        "label": "Contact Information",
        "fields": [
            {"key": "address", "label": "Home address", "type": "textarea", "required": True},
            {"key": "phone", "label": "Phone number", "type": "text", "required": True},
            {"key": "email", "label": "Email address", "type": "text", "required": True},
        ],
    },
    {
        "key": "emergencyContact",
        "label": "Emergency Contact",
        "fields": [
            {"key": "emergencyName", "label": "Full name", "type": "text", "required": True},
            {"key": "emergencyRelationship", "label": "Relationship", "type": "text", "required": True},
            {"key": "emergencyPhone", "label": "Phone number", "type": "text", "required": True},
        ],
    },
    {
        "key": "medicalHistory",
        "label": "Medical History",
        "fields": [
            {"key": "conditions", "label": "Current or past medical conditions", "type": "textarea", "required": False},
            {"key": "medications", "label": "Current medications", "type": "textarea", "required": False},
            {"key": "allergies", "label": "Allergies", "type": "textarea", "required": False},
            {"key": "surgicalHistory", "label": "Surgical history", "type": "textarea", "required": False},
        ],
    },
    {
        "key": "painFunction",
        "label": "Pain & Function",
        "fields": [
            {"key": "painLocation", "label": "Where is your pain or limitation?", "type": "textarea", "required": True},
            {"key": "painLevel", "label": "Current pain level (0–10)", "type": "number", "required": False},
            {"key": "functionalLimitations", "label": "What activities are difficult right now?", "type": "textarea", "required": False},
            {"key": "goals", "label": "What are your goals for therapy?", "type": "textarea", "required": False},
        ],
    },
    {
        "key": "consent",
        "label": "Consent & Signature",
        "fields": [
            {"key": "agreeToTreatment", "label": "I consent to evaluation and treatment by this clinic.", "type": "checkbox", "required": True},
            {"key": "signatureName", "label": "Type your full legal name as your signature", "type": "text", "required": True},
        ],
    },
]

HIPAA_PRIVACY_SCHEMA = [
    {
        "key": "acknowledgment",
        "label": "Notice of Privacy Practices",
        "fields": [
            {
                "key": "acknowledged",
                "label": "I acknowledge that I have received and reviewed this clinic's Notice of Privacy Practices.",
                "type": "checkbox",
                "required": True,
            },
            {"key": "signatureName", "label": "Type your full legal name as your signature", "type": "text", "required": True},
        ],
    },
]

# Every organization gets these templates lazily provisioned (mirrors the
# BookingConfiguration get_or_create pattern) — no per-org admin authoring
# UI exists yet, but the engine (FormTemplate.schema) supports it without a
# migration once one is built.
SEEDED_TEMPLATES = [
    {
        "slug": "digital-intake",
        "name": "New Patient Intake",
        "category": FormTemplate.Category.INTAKE,
        "schema": DIGITAL_INTAKE_SCHEMA,
        "validity_days": None,
    },
    {
        "slug": "hipaa-privacy-acknowledgment",
        "name": "HIPAA & Privacy Acknowledgment",
        "category": FormTemplate.Category.CONSENT,
        "schema": HIPAA_PRIVACY_SCHEMA,
        "validity_days": 365,
    },
]

# A form's `slug` maps to a Consent.Kind only where a real Consent record
# should be mirrored for staff visibility. Templates outside this map (a
# future custom-authored form, say) simply never touch Consent.
CONSENT_KIND_BY_TEMPLATE_SLUG = {
    "digital-intake": Consent.Kind.TREATMENT,
    "hipaa-privacy-acknowledgment": Consent.Kind.PRIVACY,
}


def ensure_form_templates(organization: Organization) -> None:
    for entry in SEEDED_TEMPLATES:
        FormTemplate.objects.get_or_create(
            organization=organization,
            slug=entry["slug"],
            defaults={
                "name": entry["name"],
                "category": entry["category"],
                "schema": entry["schema"],
                "validity_days": entry["validity_days"],
            },
        )


def active_templates(organization: Organization):
    ensure_form_templates(organization)
    return FormTemplate.objects.filter(organization=organization, is_active=True).order_by("name")


def get_working_submission(patient: Patient, template: FormTemplate) -> FormSubmission:
    """The submission a patient should currently be editing or reviewing for
    this template: the latest row, unless it's a completed-and-expired one —
    in which case a fresh NOT_STARTED row is created rather than reusing (or
    mutating) the expired one, so the expired submission stays intact as a
    historical record."""
    latest = FormSubmission.objects.filter(patient=patient, template=template).order_by("-created_at").first()
    if latest is None or (latest.status == FormSubmission.Status.COMPLETED and latest.is_expired):
        return FormSubmission.objects.create(patient=patient, template=template)
    return latest


def display_status(submission: FormSubmission | None) -> str:
    if submission is None:
        return FormSubmission.Status.NOT_STARTED
    if submission.status == FormSubmission.Status.COMPLETED and submission.is_expired:
        return "expired"
    return submission.status


def forms_overview(patient: Patient) -> list[dict]:
    """One row per active template: the patient's latest submission for it
    (if any) plus a display status that folds in the live-computed
    "expired" state. This is what both the dashboard's formsDue tile and the
    portal's full forms list are built from."""
    overview = []
    latest_by_template = {}
    submissions = (
        FormSubmission.objects.filter(patient=patient)
        .select_related("template")
        .order_by("template_id", "-created_at")
    )
    for submission in submissions:
        latest_by_template.setdefault(submission.template_id, submission)

    for template in active_templates(patient.organization):
        latest = latest_by_template.get(template.pk)
        overview.append(
            {
                "templateSlug": template.slug,
                "name": template.name,
                "category": template.category,
                "status": display_status(latest),
                "submissionId": str(latest.pk) if latest else None,
                "submittedAt": latest.submitted_at.isoformat() if latest and latest.submitted_at else None,
            }
        )
    return overview


def validate_submission_data(template: FormTemplate, data: dict) -> dict[str, str]:
    """Generic required-field check driven entirely by the template's own
    schema — adding a new form type never requires new validation code."""
    errors: dict[str, str] = {}
    for section in template.schema:
        for field in section.get("fields", []):
            if not field.get("required"):
                continue
            value = data.get(field["key"])
            if field.get("type") == "checkbox":
                if not value:
                    errors[field["key"]] = f"{field['label']} is required."
            elif value in (None, ""):
                errors[field["key"]] = f"{field['label']} is required."
    return errors


def record_consent_if_applicable(template: FormTemplate, submission: FormSubmission, patient: Patient) -> None:
    kind = CONSENT_KIND_BY_TEMPLATE_SLUG.get(template.slug)
    if not kind or not patient.portal_user_id:
        return
    signature_name = str(submission.data.get("signatureName", "")).strip()
    agreed = any(
        field.get("type") == "checkbox" and field.get("required") and submission.data.get(field["key"])
        for section in template.schema
        for field in section.get("fields", [])
    )
    if not (signature_name and agreed):
        return
    Consent.objects.create(
        patient=patient,
        kind=kind,
        document_version=f"{template.slug}-v1",
        status=Consent.Status.SIGNED,
        signature_name=signature_name,
        signed_at=timezone.now(),
        recorded_by=patient.portal_user,
    )
