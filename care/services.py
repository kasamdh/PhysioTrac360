"""Clinical-assistance services.

The helpers in this module are deterministic and local. They provide a safe
integration seam for a future HIPAA-eligible AI service, but they never send
PHI outside the application and never finalize clinical documentation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from typing import Iterable

from django.db.models import QuerySet
from django.utils import timezone

from .models import AIArtifact, AuditEvent, ClinicalNote, NoteIntervention, Organization, OutcomeScore, Patient


OUTCOME_MEASURES = {
    OutcomeScore.Measure.LEFS: {
        "label": "LEFS",
        "maximum": 80,
        "higher_is_better": True,
        "unit": "points",
    },
    OutcomeScore.Measure.ODI: {
        "label": "ODI",
        "maximum": 100,
        "higher_is_better": False,
        "unit": "percent disability",
    },
    OutcomeScore.Measure.NDI: {
        "label": "NDI",
        "maximum": 100,
        "higher_is_better": False,
        "unit": "percent disability",
    },
    OutcomeScore.Measure.QUICK_DASH: {
        "label": "QuickDASH",
        "maximum": 100,
        "higher_is_better": False,
        "unit": "points",
    },
    OutcomeScore.Measure.TUG: {
        "label": "Timed Up and Go",
        "maximum": None,
        "higher_is_better": False,
        "unit": "seconds",
    },
    OutcomeScore.Measure.BERG: {
        "label": "Berg Balance Scale",
        "maximum": 56,
        "higher_is_better": True,
        "unit": "points",
    },
    OutcomeScore.Measure.PSFS: {
        "label": "Patient-Specific Functional Scale",
        "maximum": 10,
        "higher_is_better": True,
        "unit": "points",
    },
}


@dataclass(frozen=True)
class ComplianceFinding:
    code: str
    severity: str
    title: str
    detail: str
    finalization_blocker: bool = False


def outcome_measure_defaults(measure: str) -> dict:
    """Return display and scoring defaults for a supported outcome measure."""
    return OUTCOME_MEASURES.get(measure, {})


def outcome_trends(patient: Patient) -> list[dict]:
    """Prepare chronologically ordered, deterministic outcome trends."""
    trends = []
    for measure, config in OUTCOME_MEASURES.items():
        scores = list(
            patient.outcomes.filter(measure=measure)
            .order_by("measured_on")
            .values("measured_on", "score", "maximum_score")
        )
        if not scores:
            continue
        first = scores[0]["score"]
        latest = scores[-1]["score"]
        delta = latest - first
        improved = delta > 0 if config["higher_is_better"] else delta < 0
        declined = delta < 0 if config["higher_is_better"] else delta > 0
        trend = "Improving" if improved else "Declining" if declined else "Stable"
        trends.append(
            {
                "measure": measure,
                "label": config["label"],
                "latest": latest,
                "maximum": (
                    scores[-1]["maximum_score"]
                    if scores[-1]["maximum_score"] is not None
                    else config["maximum"]
                ),
                "unit": config["unit"],
                "trend": trend,
                "delta": abs(delta),
                "points": scores,
            }
        )
    return trends


def note_compliance_findings(
    note: ClinicalNote, today: date | None = None
) -> list[ComplianceFinding]:
    """Return explainable documentation checks; only marked blockers prevent signing."""
    today = today or timezone.localdate()
    findings: list[ComplianceFinding] = []

    if not note.objective.strip():
        findings.append(
            ComplianceFinding(
                "missing_objective",
                "high",
                "Objective findings are missing",
                "Document measurable tests, observations, or treatment response.",
                True,
            )
        )
    if not note.assessment.strip():
        findings.append(
            ComplianceFinding(
                "missing_assessment",
                "medium",
                "Assessment is missing",
                "Explain clinical reasoning and the patient response to treatment.",
            )
        )
    if not note.plan.strip():
        findings.append(
            ComplianceFinding(
                "missing_plan",
                "high",
                "Plan is missing",
                "Document the next-visit plan, progression, and needed follow-up.",
                True,
            )
        )
    if note.note_type in {ClinicalNote.Type.EVALUATION, ClinicalNote.Type.PROGRESS, ClinicalNote.Type.RE_EVALUATION}:
        poc_fields = (
            note.plan_of_care_start,
            note.plan_of_care_end,
            note.frequency_per_week,
            note.duration_weeks,
        )
        if not all(poc_fields):
            findings.append(
                ComplianceFinding(
                    "missing_poc",
                    "high",
                    "Plan-of-care details are incomplete",
                    "Include start/end dates, planned frequency, and duration.",
                    True,
                )
            )
    if note.reassessment_due and note.reassessment_due < today:
        findings.append(
            ComplianceFinding(
                "reassessment_overdue",
                "high",
                "Required reassessment is overdue",
                "Review outcome measures and update the plan of care before finalizing.",
                True,
            )
        )
    if note.status == ClinicalNote.Status.REVIEW_REQUIRED and note.cosign_required:
        findings.append(
            ComplianceFinding(
                "cosign_pending",
                "medium",
                "Supervising cosignature pending",
                "A PT or clinical director must cosign this note before it is final.",
            )
        )
    elif not note.is_signed:
        findings.append(
            ComplianceFinding(
                "signature_pending",
                "medium",
                "Therapist signature pending",
                "Drafts are not final clinical documentation.",
            )
        )
    return findings


def patient_compliance_findings(patient: Patient) -> list[ComplianceFinding]:
    """Patient-level consent and reassessment checks for the dashboard."""
    findings: list[ComplianceFinding] = []
    if not patient.consents.filter(status="signed").exists():
        findings.append(
            ComplianceFinding(
                "consent_missing",
                "high",
                "Consent record is missing",
                "Confirm required treatment consents before the next encounter.",
                True,
            )
        )
    most_recent = patient.notes.order_by("-service_date", "-created_at").first()
    if most_recent and most_recent.reassessment_due:
        if most_recent.reassessment_due < timezone.localdate():
            findings.append(
                ComplianceFinding(
                    "reassessment_overdue",
                    "high",
                    "Reassessment overdue",
                    "A plan-of-care reassessment date has passed.",
                    True,
                )
            )
    poc_tier = patient.plan_of_care_alert_tier
    if poc_tier == "expired":
        findings.append(
            ComplianceFinding(
                "poc_expired",
                "high",
                "Plan of care has expired",
                "Certify a new plan of care or discharge the patient.",
                True,
            )
        )
    elif poc_tier not in ("none", "valid"):
        days = patient.plan_of_care_days_remaining
        findings.append(
            ComplianceFinding(
                "poc_expiring_soon",
                "high" if poc_tier.startswith("critical_") else "medium",
                f"Plan of care expires in {days} day{'s' if days != 1 else ''}",
                "Schedule recertification or a progress note before the plan of care lapses.",
            )
        )
    return findings


# Standard AMA CPT codes for timed PT interventions, keyed by
# NoteIntervention.Category. Deliberately excludes PATIENT_EDUCATION and
# OTHER — no single code reliably applies to either without payer-specific
# review, so those minutes are surfaced as documented-but-uncoded rather
# than mapped to a guessed code.
CPT_CODE_BY_CATEGORY = {
    NoteIntervention.Category.THERAPEUTIC_EXERCISE: ("97110", "Therapeutic Exercise"),
    NoteIntervention.Category.MANUAL_THERAPY: ("97140", "Manual Therapy"),
    NoteIntervention.Category.THERAPEUTIC_ACTIVITY: ("97530", "Therapeutic Activity"),
    NoteIntervention.Category.NEUROMUSCULAR_REEDUCATION: ("97112", "Neuromuscular Re-education"),
    NoteIntervention.Category.GAIT_TRAINING: ("97116", "Gait Training"),
    NoteIntervention.Category.SELF_CARE: ("97535", "Self-Care / Home Management Training"),
}
_UNCODED_CATEGORIES = {NoteIntervention.Category.PATIENT_EDUCATION, NoteIntervention.Category.OTHER}


def _medicare_eight_minute_units(total_timed_minutes: int) -> int:
    """Standard CMS 8-minute-rule lookup: total timed minutes -> billable
    units (8-22=1, 23-37=2, 38-52=3, 53-67=4, +1 per additional 15 minutes).
    Not every payer follows this exact table — the caller must label this a
    suggestion, never submit it directly."""
    if total_timed_minutes < 8:
        return 0
    return 1 + (total_timed_minutes - 8) // 15


def coding_suggestions(note: ClinicalNote) -> dict:
    """Deterministic, rule-based CPT-unit and documentation-gap suggestions
    from what is already documented on this note — never infers a diagnosis
    or a code from free text, matching this module's no-fabrication rule.
    Every result must be shown as 'Suggested — provider/billing review
    required' and never submitted automatically."""
    items = list(note.intervention_items.all())

    minutes_by_category: dict[str, int] = {}
    for item in items:
        if item.is_timed and item.category:
            minutes_by_category[item.category] = minutes_by_category.get(item.category, 0) + item.minutes

    cpt_suggestions = []
    for category, minutes in minutes_by_category.items():
        mapping = CPT_CODE_BY_CATEGORY.get(category)
        if not mapping or minutes <= 0:
            continue
        code, label = mapping
        cpt_suggestions.append(
            {
                "code": code,
                "label": label,
                "category": category,
                "minutes": minutes,
                "suggestedUnits": _medicare_eight_minute_units(minutes),
            }
        )
    cpt_suggestions.sort(key=lambda row: row["minutes"], reverse=True)

    total_timed_minutes = sum(row["minutes"] for row in cpt_suggestions)
    uncategorized_minutes = sum(item.minutes for item in items if item.is_timed and not item.category)
    uncoded_labels = sorted({item.get_category_display() for item in items if item.category in _UNCODED_CATEGORIES})

    gaps = []
    if not items:
        gaps.append("No treatment interventions are documented on this note.")
    if uncategorized_minutes:
        gaps.append(
            f"{uncategorized_minutes} timed minute(s) have no intervention category and were excluded from coding suggestions."
        )
    if uncoded_labels:
        gaps.append(f"Documented but not independently coded: {', '.join(uncoded_labels)}.")
    if not note.patient.diagnoses.strip():
        gaps.append("No diagnosis is on file for this patient — a treatment diagnosis supports medical necessity.")
    if not note.assessment.strip():
        gaps.append("No assessment / medical-necessity narrative is documented on this note.")

    return {
        "cptSuggestions": cpt_suggestions,
        "totalTimedMinutes": total_timed_minutes,
        "totalSuggestedUnits": _medicare_eight_minute_units(total_timed_minutes) if cpt_suggestions else 0,
        "documentationGaps": gaps,
        "disclaimer": (
            "Suggested — provider and billing review required. Based only on documented intervention "
            "minutes and the standard CMS 8-minute rule; confirm against the specific payer's billing "
            "policy before submitting a claim. Not submitted automatically."
        ),
    }


def format_coding_draft_text(note: ClinicalNote, suggestion: dict) -> str:
    """Render `coding_suggestions()` output as the artifact's stored draft_text,
    matching the narrative-report style of every other AIArtifact kind."""
    code_lines = [
        "- %s (%s): %s timed minute(s) -> %s suggested unit(s)"
        % (row["code"], row["label"], row["minutes"], row["suggestedUnits"])
        for row in suggestion["cptSuggestions"]
    ]
    gap_lines = [f"- {gap}" for gap in suggestion["documentationGaps"]]
    return (
        "Coding suggestion draft\n\n"
        "Source note: %s (%s)\n\n"
        "Suggested CPT codes (8-minute rule):\n%s\n\n"
        "Total timed minutes: %s | Total suggested units: %s\n\n"
        "Documentation gaps:\n%s\n\n"
        "%s"
    ) % (
        note.service_date.isoformat(),
        note.get_note_type_display(),
        "\n".join(code_lines) if code_lines else "- No codeable timed interventions are documented.",
        suggestion["totalTimedMinutes"],
        suggestion["totalSuggestedUnits"],
        "\n".join(gap_lines) if gap_lines else "- None identified.",
        suggestion["disclaimer"],
    )


def goal_suggestions(
    functional_limitation: str, diagnosis: str = "", measure: str = ""
) -> list[dict]:
    """Create editable SMART-goal suggestions tied to a stated limitation.

    These are templates, not clinical decisions. A licensed therapist must
    customize and approve one before it becomes an active goal.
    """
    limitation = functional_limitation.strip()
    text = (limitation + " " + diagnosis).lower()
    measure_config = outcome_measure_defaults(measure)
    goal_measure = measure_config.get("label", "functional performance measure")
    goal_unit = measure_config.get("unit", "repetitions")
    candidates: list[dict] = []

    def add(task: str, baseline: str, target: str, method: str, weeks: int = 6):
        wording = (
            "Within %s weeks, patient will %s at %s, measured by %s, "
            "to address %s."
        ) % (weeks, task, target, method, limitation)
        candidates.append(
            {
                "functional_limitation": limitation,
                "functional_task": task,
                "baseline_hint": baseline,
                "target_hint": target,
                "measurement_method": method,
                "wording": wording,
                "timeframe_weeks": weeks,
            }
        )

    if any(word in text for word in ("stair", "step", "curb")):
        add(
            "ascend and descend one flight of 12 stairs with the prescribed assistive device",
            "current safe stair tolerance",
            "supervision or less with pain at or below the clinician-set threshold",
            "stair-performance observation",
        )
    if any(word in text for word in ("walk", "gait", "ambulat", "community")):
        add(
            "walk the distance needed for a community errand",
            "current walking distance",
            "the clinician-set distance with the prescribed device and no loss of balance",
            "distance and gait observation",
        )
    if any(word in text for word in ("balance", "fall", "transfer")):
        add(
            "complete sit-to-stand and household transfers safely",
            "current assistance level or Timed Up and Go time",
            "the clinician-set assistance level or time target",
            "Timed Up and Go and transfer observation",
        )
    if any(word in text for word in ("shoulder", "arm", "reach", "dress")):
        add(
            "reach overhead to retrieve and replace a light household item",
            "current reach tolerance",
            "the clinician-set range and symptom threshold",
            "task observation and %s" % (goal_measure or "QuickDASH"),
        )
    if any(word in text for word in ("back", "lumbar", "sit", "stand")):
        add(
            "sit or stand long enough to complete a daily household task",
            "current tolerance in minutes",
            "the clinician-set duration with manageable symptoms",
            "timed functional task and %s" % (goal_measure or "ODI"),
        )
    if not candidates:
        add(
            "complete the identified daily activity under the documented conditions",
            "current baseline performance",
            "a clinician-selected measurable target",
            "direct functional observation and %s" % goal_measure,
        )

    return candidates[:3]


def _source_fingerprint(notes: Iterable[ClinicalNote]) -> str:
    source = "|".join(
        "%s:%s:%s" % (note.pk, note.service_date.isoformat(), note.updated_at.isoformat())
        for note in notes
    )
    return sha256(source.encode("utf-8")).hexdigest()


def compose_draft(patient: Patient, kind: str) -> dict:
    """Compose a provenance-preserving draft using prior signed visits only."""
    notes = list(
        patient.notes.filter(status=ClinicalNote.Status.SIGNED)
        .order_by("-service_date", "-created_at")[:6]
    )
    goals = list(patient.goals.filter(status=FunctionalGoalStatus.ACTIVE).order_by("target_date"))
    trends = outcome_trends(patient)

    source_lines = []
    for note in reversed(notes):
        source_lines.append(
            "%s — objective: %s; assessment: %s; plan: %s"
            % (
                note.service_date.isoformat(),
                _short(note.objective),
                _short(note.assessment),
                _short(note.plan),
            )
        )
    goal_lines = [
        "%s (target %s %s by %s)"
        % (goal.functional_task, goal.target_value, goal.unit, goal.target_date.isoformat())
        for goal in goals
    ]
    outcome_lines = [
        "%s: latest %s %s (%s)"
        % (trend["label"], trend["latest"], trend["unit"], trend["trend"].lower())
        for trend in trends
    ]

    if kind == AIArtifact.Kind.DISCHARGE:
        heading = "Discharge-summary draft"
        requested_sections = (
            "Reason for discharge, course of care, functional status, goals, "
            "outcomes, and self-management/follow-up."
        )
    elif kind == AIArtifact.Kind.HANDOFF:
        heading = "Clinical handoff draft"
        requested_sections = (
            "Current status, precautions, most recent response, open goals, "
            "and recommended next actions."
        )
    elif kind == AIArtifact.Kind.PATIENT_SUMMARY:
        heading = "Patient-friendly visit summary draft"
        requested_sections = (
            "What we worked on, what to do at home, precautions, and when to contact the clinic."
        )
    else:
        heading = "Progress-note draft"
        requested_sections = (
            "Progress toward goals, objective trends, response to treatment, "
            "and updated plan of care."
        )

    draft = (
        "%s\n\n"
        "Review scope: %s\n\n"
        "Prior signed visit evidence:\n%s\n\n"
        "Active goals:\n%s\n\n"
        "Outcome trends:\n%s\n\n"
        "Therapist synthesis (edit before approval):\n"
        "Document only findings supported by the source visits above. State missing information "
        "explicitly, reconcile precautions, and set an individualized plan."
    ) % (
        heading,
        requested_sections,
        "\n".join("- " + line for line in source_lines)
        if source_lines
        else "- No signed prior visits available.",
        "\n".join("- " + line for line in goal_lines) if goal_lines else "- No active goals.",
        "\n".join("- " + line for line in outcome_lines)
        if outcome_lines
        else "- No recorded outcome-measure trends.",
    )
    sections = [
        {
            "key": "priorEvidence",
            "label": "Prior Signed Visit Evidence",
            "draftText": "\n".join("- " + line for line in source_lines) if source_lines else "No signed prior visits available.",
            "status": AIArtifact.SectionStatus.PENDING,
            "reviewedText": "",
        },
        {
            "key": "activeGoals",
            "label": "Active Goals",
            "draftText": "\n".join("- " + line for line in goal_lines) if goal_lines else "No active goals.",
            "status": AIArtifact.SectionStatus.PENDING,
            "reviewedText": "",
        },
        {
            "key": "outcomeTrends",
            "label": "Outcome Trends",
            "draftText": "\n".join("- " + line for line in outcome_lines) if outcome_lines else "No recorded outcome-measure trends.",
            "status": AIArtifact.SectionStatus.PENDING,
            "reviewedText": "",
        },
        {
            "key": "synthesisGuidance",
            "label": "Therapist Synthesis (write this section yourself)",
            "draftText": (
                "Requested sections: %s\n\nDocument only findings supported by the evidence above. "
                "State missing information explicitly, reconcile precautions, and set an "
                "individualized plan. This section is guidance only — it is never auto-written."
            ) % requested_sections,
            "status": AIArtifact.SectionStatus.PENDING,
            "reviewedText": "",
        },
    ]

    return {
        "draft_text": draft,
        "source_note_ids": [str(note.pk) for note in notes],
        "source_fingerprint": _source_fingerprint(notes),
        "sections": sections,
    }


class FunctionalGoalStatus:
    """Avoid a model import cycle in type-aware draft composition."""

    ACTIVE = "active"


def _short(value: str, limit: int = 280) -> str:
    normalized = " ".join(value.split())
    return normalized[:limit] + ("…" if len(normalized) > limit else "")


def home_program_suggestions(patient: Patient) -> list[dict]:
    """Return chart-contextual HEP review cards without prescribing progression.

    The service deliberately reflects only the documented diagnosis, precautions,
    and active functional goals. It does not infer a diagnosis or autonomously
    select dosage, progression, or contraindication handling.
    """
    precautions = patient.precautions.lower()
    diagnosis_context = _short(patient.diagnoses, limit=160) if patient.diagnoses else ""
    active_goals = list(
        patient.goals.filter(status=FunctionalGoalStatus.ACTIVE).order_by("target_date")[:2]
    )
    warnings = []
    if precautions:
        warnings.append(
            "Review documented precautions before prescribing. Do not progress exercises "
            "that conflict with current restrictions."
        )
    if diagnosis_context:
        warnings.append(
            "Review this suggestion against the documented diagnosis context before prescribing."
        )
    goal_reason = (
        "Targets the active functional goal: %s." % active_goals[0].functional_task
        if active_goals
        else "Supports the patient's documented functional goals."
    )
    suggestions = [
        {
            "name": "Symptom-guided mobility",
            "dosage": "Clinician to individualize",
            "reason": (
                "Use only within the documented diagnosis context%s. %s"
                % (": " + diagnosis_context if diagnosis_context else "", goal_reason)
            ),
        },
        {
            "name": "Functional task practice",
            "dosage": "Clinician to individualize",
            "reason": (
                "Practice the documented functional task using approved safety strategies. "
                + goal_reason
            ),
        },
    ]
    return [{"warnings": warnings, "exercises": suggestions}]


def record_audit_event(
    *,
    actor,
    action: str,
    obj,
    patient: Patient | None = None,
    request=None,
    metadata: dict | None = None,
) -> AuditEvent:
    """Write an append-only, metadata-only audit event."""
    patient = patient or getattr(obj, "patient", None)
    organization = (
        getattr(patient, "organization", None)
        or getattr(obj, "organization", None)
        or (obj if isinstance(obj, Organization) else None)
        or getattr(actor, "organization", None)
    )
    if organization is None:
        raise ValueError("An organization is required for an audit event.")
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "") if request else ""
    ip_address = forwarded.split(",")[0].strip() if forwarded else None
    if not ip_address and request:
        ip_address = request.META.get("REMOTE_ADDR")
    return AuditEvent.objects.create(
        organization=organization,
        patient=patient,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        object_type=obj._meta.label_lower,
        object_id=getattr(obj, "pk", None),
        ip_address=ip_address or None,
        metadata=metadata or {},
    )
